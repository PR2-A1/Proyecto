#!/usr/bin/env python3
"""
RoboDK <-> Nav2 <-> MQTT bridge node.

Receives navigation orders from the ESP32 controller via MQTT, queues
them, and dispatches them as Nav2 NavigateToPose goals one at a time.
A new order is only started after the cobot publishes ``COMPLETED`` on
its status topic, so the AMR and the cobot stay in lockstep.

Parameters:
  - robodk_host RoboDK API host (default 'localhost')
  - robodk_port RoboDK API port (default 20500)
  - robot_item_name RoboDK robot/frame (default 'MiR')
  - global_frame TF global frame (default 'map')
  - robot_frame TF robot frame (default 'base_link')
  - twin_update_rate Twin update Hz (default 30.0)
  - freeze_yaw (bool) Don't update yaw (default False)
  - mqtt_host MQTT broker host (default 'broker.hivemq.com')
  - mqtt_port MQTT broker port (default 1883)
  - mqtt_topic_amr_action Incoming order topic (default 'giirob/pr2-A1/devices/amr/action')
  - mqtt_topic_amr_status Outgoing status topic (default 'giirob/pr2-A1/devices/amr/status')
  - mqtt_topic_cobot_status (str) Cobot status topic (default 'giirob/pr2/devices/cobot/status')
  - amr_device_name Device ID (default 'AMR_1')
"""

import json
import math
import threading
from collections import deque
from enum import Enum

# ROS2 imports
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.time import Time
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from std_msgs.msg import String
from tf2_ros import (
    Buffer,
    TransformListener,
    LookupException,
    ExtrapolationException,
    ConnectivityException,
)

# MQTT client
import paho.mqtt.client as mqtt

# RoboDK API (optional)
try:
    from robodk.robolink import Robolink, ITEM_TYPE_ROBOT, ITEM_TYPE_FRAME
    ROBODK_AVAILABLE = True
except ImportError:
    ROBODK_AVAILABLE = False

# States for the ARM
class AMRState(Enum):
    IDLE = 'IDLE'
    NAVIGATING = 'NAVIGATING'
    WAITING_COBOT = 'WAITING_COBOT'
    WAITING_TOLVA = 'WAITING_TOLVA'


# AMR's memory for the locations of the different stations (dictionary).
# Locations sent by the ESP32: TOLVA_# and COBOT_PICK. They are random for now
STATION_TARGETS = {
    'TOLVA_1': (-5.3875, -0.5251),
    'TOLVA_2': (-3.7087, 0.581),
    'TOLVA_3': (-5.3875, -0.5251),
    'TOLVA_4': (-5.3875, 0.581),
    'TOLVA_5': (-4.4581, 0.581),
    'TOLVA_6': (-3.782, -0.5251),
    'COBOT_PICK': (-0.116087, -0.0583, -90.0),
}

# Fixed yaw (radians) applied to every dispatched goal until the ESP32
# starts sending an orientation (final iteration)(will be deleted).
FIXED_YAW_RAD = 0.0

# Main node class 
class RoboDKBridge(Node):
    def __init__(self):
        super().__init__('robodk_bridge')

        # Parameters with defaults
        self.declare_parameter('robodk_host', 'localhost')
        self.declare_parameter('robodk_port', 20500)
        self.declare_parameter('robot_item_name', 'MiR')
        self.declare_parameter('global_frame', 'map')
        self.declare_parameter('robot_frame', 'base_link')
        self.declare_parameter('twin_update_rate', 10.0)
        self.declare_parameter('freeze_yaw', False)
        self.declare_parameter('mqtt_host', 'broker.hivemq.com')
        self.declare_parameter('mqtt_port', 1883)
        self.declare_parameter('mqtt_topic_amr_action', 'giirob/pr2-A1/devices/amr/action')
        self.declare_parameter('mqtt_topic_amr_status', 'giirob/pr2-A1/devices/amr/status')
        self.declare_parameter('mqtt_topic_cobot_status', 'giirob/pr2-A1/devices/cobot/status')
        self.declare_parameter('amr_device_name', 'AMR')
        # Only this destination triggers WAITING_COBOT on arrival. Any other
        # target (TOLVA_*) waits `tolva_wait_seconds` and then goes to IDLE.
        self.declare_parameter('cobot_pickup_location', 'COBOT_PICK')
        # Seconds the AMR stays at a TOLVA before the queue advances, to
        # simulate the dispense/fill operation.
        self.declare_parameter('tolva_wait_seconds', 6.0)

        self.host = self.get_parameter('robodk_host').value
        self.port = self.get_parameter('robodk_port').value
        self.robot_item_name = self.get_parameter('robot_item_name').value
        self.global_frame = self.get_parameter('global_frame').value
        self.robot_frame = self.get_parameter('robot_frame').value  
        twin_update_rate = self.get_parameter('twin_update_rate').value
        self.amr_device_name = self.get_parameter('amr_device_name').value
        self.mqtt_topic_amr_action = self.get_parameter('mqtt_topic_amr_action').value
        self.mqtt_topic_amr_status = self.get_parameter('mqtt_topic_amr_status').value
        self.mqtt_topic_cobot_status = self.get_parameter('mqtt_topic_cobot_status').value
        self.cobot_pickup_location = self.get_parameter('cobot_pickup_location').value
        self.tolva_wait_seconds = float(self.get_parameter('tolva_wait_seconds').value)

        # Order queue and AMR sates.
        self._state = AMRState.IDLE
        # Lock to protect the state and the queue, since MQTT callbacks run in a separate thread.
        self._state_lock = threading.Lock()
        self._queue = deque()
        self._current_order = None

        # Nav2 action client for navigation.
        self.nav_to_pose_client = ActionClient(
            self, NavigateToPose, 'navigate_to_pose')

        # Manual goal sender from RViz, is kept for debugging and previous mapping.
        self.goal_sub = self.create_subscription(
            PoseStamped, 'goal_pose', self._goal_pose_cb, 10)
        self.status_pub = self.create_publisher(String, 'robodk/status', 10)

        # RDK API and digital twin setup.
        self.rdk = None
        self.robot_item = None
        self._tf_warn_count = 0

        # TF Listener
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        # Checks if the RoboDK API is available before trying to connect. The twin update timer is only created if the API is available.
        if ROBODK_AVAILABLE:
            self._connect_robodk()
            self.twin_timer = self.create_timer(
                1.0 / twin_update_rate, self._update_robodk_from_tf)
        else:
            self.get_logger().warn(
                'robodk package not installed. Install with: pip install robodk')

        # MQTT setup
        self._setup_mqtt()

        # Gets from the queue when state allows it, runs on the ROS executor.
        self.dispatch_timer = self.create_timer(0.2, self._dispatch_next)

        # Logs startup info
        self.get_logger().info('RoboDK bridge node started')
        self.get_logger().info(f'  RoboDK host: {self.host}:{self.port}')
        self.get_logger().info(f'  Robot item: {self.robot_item_name}')
        self.get_logger().info(f'  TF: {self.global_frame} -> {self.robot_frame}')
        self.get_logger().info(f'  AMR device: {self.amr_device_name}')

    # MQTT
    def _setup_mqtt(self):
        host = self.get_parameter('mqtt_host').value
        port = self.get_parameter('mqtt_port').value
        client_id = f'robodk_bridge_{self.amr_device_name}'
        self.mqtt = mqtt.Client(client_id=client_id, clean_session=True)
        # MQTT callbacks
        self.mqtt.on_connect = self._mqtt_on_connect
        self.mqtt.on_message = self._mqtt_on_message
        self.mqtt.on_disconnect = self._mqtt_on_disconnect
        self.mqtt.reconnect_delay_set(min_delay=1, max_delay=30)
        # Try to connect
        try:
            self.mqtt.connect_async(host, port, keepalive=60)
            self.mqtt.loop_start()
            self.get_logger().info(f'MQTT connecting to {host}:{port}')
        except Exception as e:
            self.get_logger().error(f'MQTT connect failed: {e}')

    # Callback for MQTT connect: subscribes to the relevant topics.
    def _mqtt_on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            self.get_logger().error(f'MQTT connect failed rc={rc}')
            return
        self.get_logger().info('MQTT connected')
        client.subscribe(self.mqtt_topic_amr_action, qos=1)
        client.subscribe(self.mqtt_topic_cobot_status, qos=1)

    # Callback for MQTT disconnect: logs the event and attempts to reconnect.
    def _mqtt_on_disconnect(self, client, userdata, rc):
        self.get_logger().warn(f'MQTT disconnected rc={rc}, will reconnect')

    # Callback for MQTT messages: handles incoming orders and cobot status updates.
    def _mqtt_on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
        # CHek if the message is valid JSON
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self.get_logger().warn(f'Bad MQTT payload on {msg.topic}: {e}')
            return
        # Check if the message is for AMR actions or cobot status and handle.
        if msg.topic == self.mqtt_topic_amr_action:
            self._handle_amr_action(payload)
        elif msg.topic == self.mqtt_topic_cobot_status:
            self._handle_cobot_status(payload)

    # Handles incoming AMR action messages: validates and enqueues them.
    def _handle_amr_action(self, payload):
        cmd = payload.get('cmd')
        target = payload.get('location')
        if cmd != 'goto' or not isinstance(target, str) or not target.strip():
            self.get_logger().warn(f'Ignoring AMR action: {payload}')
            return
        # Normalise to upper case so the rest of the pipeline (STATION_TARGETS
        # keys, cobot_pickup_location default, etc.) does not depend on the
        # casing chosen by the publisher (ESP32 sends e.g. 'cobot_pick').
        target = target.strip().upper()
        with self._state_lock:
            self._queue.append(target)
            qsize = len(self._queue)
        self.get_logger().info(f'Enqueued goto {target} (queue size={qsize})')

    # Handles incoming cobot status messages: if the cobot reports COMPLETED, transitions the AMR to IDLE and clears the current order.
    def _handle_cobot_status(self, payload):
        # If it is still not completed, we ignore it and keep waiting in the current state.
        if payload.get('status') != 'COMPLETED':
            return
        with self._state_lock:
            if self._state == AMRState.WAITING_COBOT:
                self._state = AMRState.IDLE
                self._current_order = None
                self.get_logger().info(
                    'Cobot COMPLETED, AMR transitions to IDLE')

    # Publishes the AMR status to MQTT, including the current location and caja_id if available.
    def _publish_amr_status(self, status, location='', caja_id=''):
        payload = json.dumps({
            'status': status,
            'location': location,
            'caja_id': caja_id,
        })
        self.mqtt.publish(self.mqtt_topic_amr_status, payload, qos=1)
        self.get_logger().info(f'Published AMR status: {payload}')

    # Queue dispatch
    def _dispatch_next(self):
        # If we are not IDLE or the queue is empty, we cannot dispatch a new order, so we return early.
        with self._state_lock:
            if self._state != AMRState.IDLE or not self._queue:
                return
            # We pop the next target from the queue, set the state to NAVIGATING, and store the current order for status tracking.
            target = self._queue.popleft()
            self._state = AMRState.NAVIGATING
            self._current_order = target
        self.get_logger().info(f'Dispatching GOTO {target}')
        # We attempt to send the Nav2 goal for the target. If it fails, reset the state to IDLE, and publish a failed status.
        if not self._send_goal_for_target(target):
            with self._state_lock:
                self._state = AMRState.IDLE
                self._current_order = None
            self._publish_amr_status('failed', target)

    # Nav2 helpers

    # Helper that resolves a target name into coordinates and dispatches the Nav2 goal.
    def _send_goal_for_target(self, target_name):
        coords = STATION_TARGETS.get(target_name)
        if coords is None:
            self.get_logger().error(
                f'Unknown target "{target_name}". Known: {list(STATION_TARGETS)}')
            return False
        if len(coords) == 3:
            x, y, yaw_deg = coords
            yaw = math.radians(yaw_deg)
        else:
            x, y = coords
            yaw = FIXED_YAW_RAD
        self._send_nav2_goal_xy(x, y, yaw=yaw, target_name=target_name)
        return True

    # Helper that builds a PoseStamped from (x, y, yaw) and forwards it to _send_nav2_goal.
    def _send_nav2_goal_xy(self, x, y, yaw=0.0, target_name=''):
        goal_pose = PoseStamped()
        goal_pose.header.frame_id = self.global_frame
        goal_pose.header.stamp = self.get_clock().now().to_msg()
        goal_pose.pose.position.x = float(x)
        goal_pose.pose.position.y = float(y)
        goal_pose.pose.position.z = 0.0
        goal_pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_pose.pose.orientation.w = math.cos(yaw / 2.0)

        self.get_logger().info(
            f'Sending Nav2 goal "{target_name}": '
            f'x={x:.3f}, y={y:.3f}, yaw={math.degrees(yaw):.1f}°')
        self._send_nav2_goal(goal_pose)

    # RoboDK connection / digital twin
    def _connect_robodk(self):
        # Try to connect to RoboDK and resolve the robot item.
        try:
            self.rdk = Robolink(self.host, port=self.port)
            station = self.rdk.ActiveStation()
            self.get_logger().info(f'Connected to RoboDK station: {station.Name()}')
            self._resolve_robot_item()
            self._publish_status('connected')
        # Log the error and set the RoboDK references to None if connection fails.
        except Exception as e:
            self.get_logger().warn(
                f'Cannot connect to RoboDK at {self.host}:{self.port}: {e}')
            self.rdk = None
            self.robot_item = None
            self._publish_status('disconnected')

    # Resolves the robot item in RoboDK based on the provided name, trying different item types. Logs the result and sets self.robot_item.
    def _resolve_robot_item(self):
        if self.rdk is None:
            return
        try:
            item = self.rdk.Item(self.robot_item_name, ITEM_TYPE_ROBOT)
            if not item.Valid():
                item = self.rdk.Item(self.robot_item_name, ITEM_TYPE_FRAME)
            if not item.Valid():
                item = self.rdk.Item(self.robot_item_name)
            if item.Valid():
                self.robot_item = item
                self.get_logger().info(
                    f'Resolved robot item: {self.robot_item_name} '
                    f'(type={item.Type()})')
            else:
                self.get_logger().warn(
                    f'Robot item "{self.robot_item_name}" not found')
                self.robot_item = None
        except Exception as e:
            self.get_logger().warn(f'Error resolving robot item: {e}')
            self.robot_item = None

    # Callback for updating the RoboDK twin's pose based on the TF transform between the global frame and the robot frame.
    def _update_robodk_from_tf(self):
        # If RoboDK is not connected or the robot item has not been resolved, we return early.
        if self.rdk is None or self.robot_item is None:
            return
        try:
            # We get the latest transform between the global frame and the robot frame. If it fails, we log a warning and return.
            tf = self.tf_buffer.lookup_transform(
                self.global_frame, self.robot_frame, Time(),
                timeout=Duration(seconds=0.0))
        except (LookupException, ExtrapolationException, ConnectivityException) as e:
            self._tf_warn_count += 1
            if self._tf_warn_count % 50 == 1:
                self.get_logger().warn(
                    f'TF lookup {self.global_frame} -> {self.robot_frame} '
                    f'failed: {e}')
            return

        # Here we extract the translation and yaw from the transform and apply it to the RoboDK item. We also convert from meters to millimeters for RoboDK.
        t = tf.transform.translation
        q = tf.transform.rotation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        # If the yaw is frozen, we keep it at 0. Otherwise, we compute it from the quaternion.
        yaw_deg = 0.0 if self.get_parameter('freeze_yaw').value \
            else math.degrees(math.atan2(siny, cosy))
        # Apply the pose to the RoboDK item, converting from meters to millimeters.
        self._apply_pose_to_item(t.x * 1000.0, t.y * 1000.0, yaw_deg)

    # Applies the given pose (in millimeters and degrees) to the RoboDK item.
    def _apply_pose_to_item(self, x_mm, y_mm, yaw_deg):
        if self.rdk is None or self.robot_item is None:
            return
        # Unused as the roboDK item will be a frame, but left for legacy and for potential ussage in the future.
        try:
            if self.robot_item.Type() == ITEM_TYPE_ROBOT:
                # Mobile-robot mechanism: joints are [x_mm, y_mm, z_mm, yaw_deg].
                self.robot_item.setJoints([x_mm, y_mm, 0.0, yaw_deg])
            else:
                from robodk.robomath import TxyzRxyz_2_Pose
                robodk_pose = TxyzRxyz_2_Pose([x_mm, y_mm, 0, 0, 0, yaw_deg])
                self.robot_item.setPoseAbs(robodk_pose)
        except Exception as e:
            self.get_logger().warn(f'Failed to update RoboDK twin: {e}')
            self.rdk = None
            self.robot_item = None

    # Nav2 goal handling (helpers + action callbacks)

    # Callback for manual goals coming from RViz: skips the MQTT queue and forwards directly to Nav2.
    def _goal_pose_cb(self, msg: PoseStamped):
        self.get_logger().info('Received goal from RViz, forwarding to Nav2')
        self._send_nav2_goal(msg)

    # Sends a PoseStamped to the Nav2 navigate_to_pose action server and wires the response/result callbacks.
    def _send_nav2_goal(self, goal_pose: PoseStamped):
        # If the Nav2 action server is not up, we cannot navigate. Reset the state machine and report the failure via MQTT.
        if not self.nav_to_pose_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('Nav2 navigate_to_pose action server not available')
            self._publish_status('nav2_unavailable')
            with self._state_lock:
                target = self._current_order
                self._state = AMRState.IDLE
                self._current_order = None
            if target:
                self._publish_amr_status('failed', target)
            return

        # Build the action goal and ship it asynchronously, wiring feedback and response callbacks.
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = goal_pose
        self._publish_status('navigating')

        future = self.nav_to_pose_client.send_goal_async(
            goal_msg, feedback_callback=self._nav_feedback_cb)
        future.add_done_callback(self._nav_goal_response_cb)

    # Callback for the Nav2 goal response: checks if the goal was accepted and wires the result callback if so.
    def _nav_goal_response_cb(self, future):
        goal_handle = future.result()
        # If Nav2 rejects the goal we abort the order, reset the state and notify via MQTT.
        if not goal_handle.accepted:
            self.get_logger().warn('Nav2 goal was rejected')
            with self._state_lock:
                target = self._current_order
                self._state = AMRState.IDLE
                self._current_order = None
            self._publish_status('goal_rejected')
            if target:
                self._publish_amr_status('failed', target)
            return
        # Goal accepted: wait for the final result asynchronously.
        self.get_logger().info('Nav2 goal accepted, navigating...')
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._nav_result_cb)

    # Callback for periodic Nav2 feedback: throttled log of the remaining distance to goal.
    def _nav_feedback_cb(self, feedback_msg):
        remaining = feedback_msg.feedback.distance_remaining
        if remaining > 0:
            self.get_logger().info(
                f'Distance remaining: {remaining:.2f}m',
                throttle_duration_sec=2.0)

    # Callback for the final Nav2 result: drives the state transition once navigation ends.
    def _nav_result_cb(self, future):
        result = future.result()
        # On success the AMR has arrived. If the target was the cobot pickup
        # we hold in WAITING_COBOT until the cobot publishes COMPLETED; for
        # any other destination (TOLVA_*) we hold in WAITING_TOLVA for a
        # fixed time (tolva_wait_seconds) and then transition to IDLE.
        # On any other Nav2 status we treat the order as failed and return to IDLE.
        with self._state_lock:
            target = self._current_order
            if result.status == 4:  # STATUS_SUCCEEDED
                if target == self.cobot_pickup_location:
                    self._state = AMRState.WAITING_COBOT
                else:
                    self._state = AMRState.WAITING_TOLVA
            else:
                self._state = AMRState.IDLE
                self._current_order = None
        # Notify the controller via MQTT and the local ROS status topic.
        if result.status == 4:
            if target == self.cobot_pickup_location:
                self.get_logger().info(f'Arrived at {target}, waiting for cobot')
            else:
                self.get_logger().info(
                    f'Arrived at {target}, waiting {self.tolva_wait_seconds:.1f}s')
                self._start_tolva_wait(target)
            self._publish_status('goal_reached')
            self._publish_amr_status('arrived', target or '')
        else:
            self.get_logger().warn(f'Navigation ended with status: {result.status}')
            self._publish_status(f'nav_status_{result.status}')
            self._publish_amr_status('failed', target or '')

    # One-shot timer that releases the AMR from WAITING_TOLVA after the configured delay.
    # For simulating the time it takes for a complete unload.
    def _start_tolva_wait(self, target):
        timer_holder = {'timer': None}

        def _on_timeout():
            with self._state_lock:
                # Guard: only act if we are still waiting at this same tolva.
                if self._state == AMRState.WAITING_TOLVA:
                    self._state = AMRState.IDLE
                    self._current_order = None
                    self.get_logger().info(
                        f'Tolva wait done at {target}, AMR transitions to IDLE')
            t = timer_holder['timer']
            if t is not None:
                t.cancel()
                self.destroy_timer(t)

        timer_holder['timer'] = self.create_timer(
            self.tolva_wait_seconds, _on_timeout)

    # Publishes a short status string on the local ROS topic (separate from the MQTT AMR status).
    def _publish_status(self, status: str):
        msg = String()
        msg.data = status
        self.status_pub.publish(msg)

    # Cleanly stops the MQTT loop on node shutdown so the broker connection is released.
    def destroy_node(self):
        try:
            self.mqtt.loop_stop()
            self.mqtt.disconnect()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = RoboDKBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()