#!/usr/bin/env python3
"""
RoboDK <-> Nav2 bridge node.

Connects to a RoboDK station and listens for navigation targets.
When RoboDK sends a target pose, this node forwards it as a Nav2
NavigateToPose goal. It also pushes the robot's current TF pose back
to RoboDK so the digital twin stays in sync.

Workflow:
  1. RoboDK defines targets (frames) in its station for the MiR.
  2. This bridge polls RoboDK for the active target or listens on
     a ROS 2 topic for target names.
  3. Targets are converted to Nav2 goals (x, y, yaw on the ground plane).
  4. Nav2 plans and executes the path, sending cmd_vel to the robot.
  5. The robot's TF pose is pushed back to update RoboDK.

Target string format (for the ``NAV_TARGET`` station parameter):
  ``X:<metres>,Y:<metres>[,YAW:<degrees>]``

  Example: ``X:3.5,Y:2.0,YAW:90``

  The legacy ``Z:<degrees>`` field is still accepted as yaw for
  backward compatibility, but ``YAW:`` is preferred.

Do **not** run this node at the same time as ``robodk_position_sender``
— both write the twin pose and the calls will collide.

Requirements:
  pip install robodk

Parameters:
  - robodk_host (str):        RoboDK API host                  (default: 'localhost')
  - robodk_port (int):        RoboDK API port                  (default: 20500)
  - poll_rate (float):        Hz to poll RoboDK for targets    (default: 2.0)
  - station_name (str):       RoboDK station name filter       (default: '')
  - robot_item_name (str):    Robot/frame item in RoboDK       (default: 'MiR')
  - target_var_name (str):    Station param to poll            (default: 'NAV_TARGET')
  - global_frame (str):       TF global frame                  (default: 'map')
  - robot_frame (str):        TF robot frame                   (default: 'base_link')
  - twin_update_rate (float): Digital-twin update rate in Hz   (default: 30.0)
  - freeze_yaw (bool):        Do not update yaw in RoboDK      (default: False)
"""

import math
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

try:
    from robodk.robolink import (
        Robolink, ITEM_TYPE_TARGET, ITEM_TYPE_ROBOT, ITEM_TYPE_FRAME,
    )
    ROBODK_AVAILABLE = True
except ImportError:
    ROBODK_AVAILABLE = False


class RoboDKBridge(Node):
    def __init__(self):
        super().__init__('robodk_bridge')

        # Parameters
        self.declare_parameter('robodk_host', 'localhost') # RoboDK API host
        self.declare_parameter('robodk_port', 20500) # RoboDK API port
        self.declare_parameter('poll_rate', 2.0) # Hz to poll RoboDK for targets
        self.declare_parameter('station_name', '') # RoboDK station name filter
        self.declare_parameter('robot_item_name', 'MiR') # Robot/item name in RoboDK
        self.declare_parameter('target_var_name', 'NAV_TARGET') # Station parameter to poll
        self.declare_parameter('global_frame', 'map') # TF global frame
        self.declare_parameter('robot_frame', 'base_link') # TF robot frame
        self.declare_parameter('twin_update_rate', 30.0) # Digital-twin update rate in Hz
        self.declare_parameter('freeze_yaw', False) # If true, do not update yaw in RoboDK.

        # Read parameters and set values
        self.host = self.get_parameter('robodk_host').value
        self.port = self.get_parameter('robodk_port').value
        poll_rate = self.get_parameter('poll_rate').value
        self.robot_item_name = self.get_parameter('robot_item_name').value
        self.target_var_name = self.get_parameter('target_var_name').value
        self.global_frame = self.get_parameter('global_frame').value
        self.robot_frame = self.get_parameter('robot_frame').value
        twin_update_rate = self.get_parameter('twin_update_rate').value

        # Nav2 action client
        self.nav_to_pose_client = ActionClient(
            self, NavigateToPose, 'navigate_to_pose')

        # Subscribe to target commands (alternative to polling RoboDK)
        self.target_sub = self.create_subscription(
            String, 'robodk/target_name', self._target_name_cb, 10)

        # Subscribe to goal_pose from RViz (for manual goals alongside RoboDK)
        self.goal_sub = self.create_subscription(
            PoseStamped, 'goal_pose', self._goal_pose_cb, 10)

        # Publisher: current status of the bridge
        self.status_pub = self.create_publisher(String, 'robodk/status', 10)

        # RoboDK connection
        self.rdk = None
        self.robot_item = None
        self._last_target = None
        self._pending_target = None
        self._navigating = False
        self._tf_warn_count = 0

        # TF, to read the robot's current pose and update the digital twin in RoboDK
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        # Check if RoboDK API is available and connect
        if ROBODK_AVAILABLE:
            self._connect_robodk()
            self.poll_timer = self.create_timer(1.0 / poll_rate, self._poll_robodk)
            self.twin_timer = self.create_timer(
                1.0 / twin_update_rate, self._update_robodk_from_tf)
        else:
            self.get_logger().warn(
                'robodk package not installed. Install with: pip install robodk\n'
                'Running in ROS-only mode (use goal_pose topic or robodk/target_name topic).')

        # Logs for verification
        self.get_logger().info('RoboDK bridge node started')
        self.get_logger().info(f'  RoboDK host: {self.host}:{self.port}')
        self.get_logger().info(f'  Robot item: {self.robot_item_name}')
        self.get_logger().info(
            f'  TF: {self.global_frame} -> {self.robot_frame}')
        self.get_logger().info(f'  Twin update rate: {twin_update_rate} Hz')
        self.get_logger().info(f'  Nav2 action: navigate_to_pose')
        self.get_logger().info(f'  Target topic: robodk/target_name')

    # Connect to RoboDK and resolve the robot item.
    def _connect_robodk(self):
        """Attempt connection to the RoboDK API."""
        try:
            self.rdk = Robolink(self.host, port=self.port)
            station = self.rdk.ActiveStation()
            self.get_logger().info(f'Connected to RoboDK station: {station.Name()}')
            self._resolve_robot_item()
            self._publish_status('connected')
        except Exception as e:
            self.get_logger().warn(f'Cannot connect to RoboDK at {self.host}:{self.port}: {e}')
            self.rdk = None
            self.robot_item = None
            self._publish_status('disconnected')

    # Checks if the robot item exists in RoboDK and caches it.
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

    # Polls the specified station parameter for a target string and send it to Nav2.
    def _poll_robodk(self):
        """Poll the RoboDK station parameter for a target string.

        Expected format: ``X:<m>,Y:<m>[,YAW:<deg>]``. For backward
        compatibility ``Z:<deg>`` is also accepted as yaw (but only if
        ``YAW:`` is absent).
        """
        if self.rdk is None:
            self._connect_robodk()
            return
        if self._navigating:
            return

        try:
            target_str = self.rdk.getParam(self.target_var_name)
        except Exception as e:
            self.get_logger().warn(f'RoboDK poll error: {e}')
            self.rdk = None
            return

        if not target_str or not isinstance(target_str, str):
            return
        if target_str == self._last_target:
            return

        self.get_logger().info(f'RoboDK target received: {target_str}')

        parsed = self._parse_target_string(target_str)
        if parsed is None:
            # Malformed — remember it so we don't re-log every tick.
            self._last_target = target_str
            return
        x_val, y_val, yaw_rad = parsed

        # Acknowledge reception (handshake with RoboDK).
        try:
            self.rdk.setParam('ORDER_NAV_RECEIVED', 'True')
            self.rdk.setParam('GOAL_NAV_REACHED', 'False')
        except Exception as e:
            self.get_logger().warn(f'Failed to set RoboDK handshake params: {e}')
            self.rdk = None
            return

        goal_pose = PoseStamped()
        goal_pose.header.frame_id = self.global_frame
        goal_pose.header.stamp = self.get_clock().now().to_msg()
        goal_pose.pose.position.x = x_val
        goal_pose.pose.position.y = y_val
        goal_pose.pose.position.z = 0.0
        goal_pose.pose.orientation.z = math.sin(yaw_rad / 2.0)
        goal_pose.pose.orientation.w = math.cos(yaw_rad / 2.0)

        # _last_target is committed only once Nav2 accepts the goal — see
        # _nav_goal_response_cb. If Nav2 is unavailable the next poll will
        # retry automatically.
        self._pending_target = target_str
        self._send_nav2_goal(goal_pose)

    @staticmethod # staticmethod since it doesn't use self, and makes testing easier
    def _parse_target_string(target_str):
        """Return (x_m, y_m, yaw_rad) or None if malformed."""
        parts = target_str.replace(' ', '').split(',')
        x_val = y_val = 0.0
        yaw_deg = None
        z_deg = None
        try:
            for part in parts:
                if not part:
                    continue
                key, _, value = part.partition(':')
                if not _:
                    return None
                key = key.upper()
                if key == 'X':
                    x_val = float(value)
                elif key == 'Y':
                    y_val = float(value)
                elif key == 'YAW':
                    yaw_deg = float(value)
                elif key == 'Z':
                    z_deg = float(value)
        except ValueError:
            return None
        # Prefer explicit YAW; fall back to Z for legacy payloads.
        if yaw_deg is None:
            yaw_deg = z_deg if z_deg is not None else 0.0
        return x_val, y_val, math.radians(yaw_deg)

    # ROS topic callback to receive target names directly (alternative to polling RoboDK).
    def _target_name_cb(self, msg: String):
        """Handle target name sent via ROS topic."""
        target_name = msg.data
        self.get_logger().info(f'Received target name via topic: {target_name}')

        if self.rdk is not None:
            try:
                item = self.rdk.Item(target_name, ITEM_TYPE_TARGET)
                if item.Valid():
                    # PoseAbs() is relative to the station root, which is
                    # what matches the map frame — Pose() would be relative
                    # to whatever frame the target is parented to.
                    pose = item.PoseAbs()
                    self._send_nav2_goal_from_matrix(pose, target_name)
                else:
                    self.get_logger().error(f'Target "{target_name}" not found in RoboDK')
            except Exception as e:
                self.get_logger().error(f'Error fetching target from RoboDK: {e}')
        else:
            self.get_logger().warn('RoboDK not connected, cannot resolve target name')

    # ROS topic callback to receive goal poses directly (e.g. from RViz).
    def _goal_pose_cb(self, msg: PoseStamped):
        """Forward RViz goal_pose directly to Nav2."""
        self.get_logger().info('Received goal from RViz, forwarding to Nav2')
        self._send_nav2_goal(msg)

    # Read robot pose from TF and push it to the RoboDK digital twin.
    def _update_robodk_from_tf(self):
        """Read robot pose from TF and push it to the RoboDK digital twin."""
        if self.rdk is None or self.robot_item is None:
            return
        try:
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

        t = tf.transform.translation
        q = tf.transform.rotation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw_deg = 0.0 if self.get_parameter('freeze_yaw').value \
            else math.degrees(math.atan2(siny, cosy))
        self._apply_pose_to_item(t.x * 1000.0, t.y * 1000.0, yaw_deg)

    # Converts a RoboDK 4x4 homogeneous matrix to a Nav2 goal.
    def _send_nav2_goal_from_matrix(self, robodk_pose, target_name=''):
        """Convert a RoboDK 4x4 homogeneous matrix to a Nav2 goal."""
        # Extract x, y from translation (RoboDK uses mm, ROS uses m)
        x = robodk_pose[0, 3] / 1000.0
        y = robodk_pose[1, 3] / 1000.0

        # Extract yaw from rotation matrix
        yaw = math.atan2(robodk_pose[1, 0], robodk_pose[0, 0])

        goal_pose = PoseStamped()
        goal_pose.header.frame_id = 'map'
        goal_pose.header.stamp = self.get_clock().now().to_msg()
        goal_pose.pose.position.x = x
        goal_pose.pose.position.y = y
        goal_pose.pose.position.z = 0.0

        # Quaternion from yaw
        goal_pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_pose.pose.orientation.w = math.cos(yaw / 2.0)

        self.get_logger().info(
            f'Sending Nav2 goal from RoboDK target "{target_name}": '
            f'x={x:.3f}, y={y:.3f}, yaw={math.degrees(yaw):.1f}°')

        self._send_nav2_goal(goal_pose)

    # Send a NavigateToPose action goal to Nav2.
    def _send_nav2_goal(self, goal_pose: PoseStamped):
        """Send a NavigateToPose action goal to Nav2."""
        if not self.nav_to_pose_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('Nav2 navigate_to_pose action server not available')
            self._publish_status('nav2_unavailable')
            # Drop the pending marker so the next poll re-sends the order
            # once Nav2 comes up.
            self._pending_target = None
            return

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = goal_pose

        self._navigating = True
        self._publish_status('navigating')

        send_goal_future = self.nav_to_pose_client.send_goal_async(
            goal_msg, feedback_callback=self._nav_feedback_cb)
        send_goal_future.add_done_callback(self._nav_goal_response_cb)

    # Callback for Nav2 goal response: check if accepted, and if so commit the last-target marker and clear the station param so RoboDK can publish the next order.
    def _nav_goal_response_cb(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().warn('Nav2 goal was rejected')
            self._navigating = False
            self._pending_target = None
            self._publish_status('goal_rejected')
            return

        # Goal accepted: commit the last-target marker and clear the
        # station param so RoboDK can publish the next order.
        if self._pending_target is not None:
            self._last_target = self._pending_target
            self._pending_target = None
            if self.rdk is not None:
                try:
                    self.rdk.setParam(self.target_var_name, '')
                except Exception as e:
                    self.get_logger().warn(
                        f'Failed to clear {self.target_var_name}: {e}')

        self.get_logger().info('Nav2 goal accepted, navigating...')
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._nav_result_cb)

    # Callback for Nav2 feedback: log remaining distance, useful for monitoring.
    def _nav_feedback_cb(self, feedback_msg):
        feedback = feedback_msg.feedback
        remaining = feedback.distance_remaining
        if remaining > 0:
            self.get_logger().info(
                f'Distance remaining: {remaining:.2f}m', throttle_duration_sec=2.0)

    # Callback for Nav2 result: check if succeeded and log the outcome.
    def _nav_result_cb(self, future):
        self._navigating = False
        result = future.result()
        
        if result.status == 4:  # STATUS_SUCCEEDED
            self.get_logger().info('Navigation goal reached!')
            self._publish_status('goal_reached')
            if self.rdk is not None:
                try:
                    self.rdk.setParam('GOAL_NAV_REACHED', 'True')
                except Exception as e:
                    self.get_logger().warn(f'Failed to set GOAL_NAV_REACHED: {e}')
        else:
            self.get_logger().warn(f'Navigation ended with status: {result.status}')
            self._publish_status(f'nav_status_{result.status}')

    # This callback is used when receiving a target name via ROS topic, it resolves the target in RoboDK and sends the corresponding goal to Nav2.
    def _apply_pose_to_item(self, x_mm, y_mm, yaw_deg):
        """Write a planar pose (mm, deg) to the resolved RoboDK item."""
        if self.rdk is None or self.robot_item is None:
            return
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

    # Publishes the current status to a ROS topic.
    def _publish_status(self, status: str):
        msg = String()
        msg.data = status
        self.status_pub.publish(msg)


def main(args=None):
    # Initialize ROS 2 and start the RoboDK bridge node.
    rclpy.init(args=args)
    node = RoboDKBridge()
    try:
        # Keep the node running to process callbacks and timers.
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # Clean up and shut down.
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
