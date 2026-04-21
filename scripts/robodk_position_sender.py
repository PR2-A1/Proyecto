#!/usr/bin/env python3
"""
RoboDK position sender node. This is for testing proposes, for full Nav2-RoboDK 
integration, see ``robodk_bridge.py``.

Reads the robot's pose from TF (``global_frame`` -> ``robot_frame``) and
pushes (x, y, yaw) to a RoboDK station so the digital twin tracks the
platform smoothly.

Reading from TF (instead of ``/amcl_pose``) gives a high-rate, smoothly
interpolated pose and works with both AMCL and SLAM localization.

Usage:
  ros2 run mir_nav2_robodk robodk_position_sender.py
  ros2 run mir_nav2_robodk robodk_position_sender.py --ros-args \
      -p robodk_host:=192.168.1.10 -p robot_item_name:='MiR100 Base'

Parameters:
  - robodk_host (str):           RoboDK API host            (default: 'localhost')
  - robodk_port (int):           RoboDK API port             (default: 20500)
  - robot_item_name (str):       Name of the RoboDK item     (default: 'MiR')
  - global_frame (str):          TF global frame             (default: 'map')
  - robot_frame (str):           TF robot frame              (default: 'base_link')
  - send_rate (float):           Update rate in Hz           (default: 30.0)
  - only_while_navigating (bool): Stream only during Nav2    (default: False)
  - log_position (bool):         Print position logs         (default: True)
  - position_log_period (float): Log period in sec           (default: 1.0)
"""

import math

import rclpy
from rclpy.node import Node
from rclpy.duration import Duration
from rclpy.time import Time
from action_msgs.msg import GoalStatusArray, GoalStatus
from tf2_ros import (
    Buffer,
    TransformListener,
    LookupException,
    ExtrapolationException,
    ConnectivityException,
)

try:
    from robodk.robolink import Robolink, ITEM_TYPE_FRAME, ITEM_TYPE_ROBOT
    from robodk.robomath import TxyzRxyz_2_Pose
    ROBODK_AVAILABLE = True
except ImportError:
    ROBODK_AVAILABLE = False


class RoboDKPositionSender(Node):
    def __init__(self):
        super().__init__('robodk_position_sender')

        self.declare_parameter('robodk_host', 'localhost') # IP of the RoboDK API server
        self.declare_parameter('robodk_port', 20500) # Port of the RoboDK API server
        self.declare_parameter('robot_item_name', 'MiR') # Name of the robot that will be updated in RoboDK
        self.declare_parameter('global_frame', 'map') # TF frame used as the global reference (ros2)
        self.declare_parameter('robot_frame', 'base_link') # TF frame used as the robot reference (ros2)
        self.declare_parameter('send_rate', 30.0) # Update rate in Hz
        self.declare_parameter('only_while_navigating', False) # Shoud just activate streaming while it is moving?
        self.declare_parameter('log_position', True) # Print position logs, set to False on prod
        self.declare_parameter('position_log_period', 1.0) # Log period in sec
        self.declare_parameter('freeze_yaw', False) # If we do not want to update the orientation in RoboDK

        # Set by parameters:
        self.host = self.get_parameter('robodk_host').value 
        self.port = self.get_parameter('robodk_port').value
        self.robot_item_name = self.get_parameter('robot_item_name').value
        self.global_frame = self.get_parameter('global_frame').value
        self.robot_frame = self.get_parameter('robot_frame').value
        send_rate = self.get_parameter('send_rate').value
        self.log_position = self.get_parameter('log_position').value
        self.position_log_period = self.get_parameter('position_log_period').value

        # Internal state:
        self.rdk = None
        self.robot_item = None
        self.navigating = False
        self._last_position_log_ns = 0
        self._tf_warn_count = 0

        # TF setup:
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        # Create the subscription to Nav2
        self.create_subscription(
            GoalStatusArray, 'navigate_to_pose/_action/status',
            self._nav_status_cb, 10)

        # Timer for sending to RoboDK
        self.send_timer = self.create_timer(1.0 / send_rate, self._send_position)

        # Checks if RoboDK API is avaiable in the connected host
        if ROBODK_AVAILABLE:
            self._connect_robodk()
        else:
            self.get_logger().warn(
                'robodk package not installed. Install with: pip install robodk')

        # Info logs for startup
        self.get_logger().info('RoboDK position sender started')
        self.get_logger().info(f'  RoboDK: {self.host}:{self.port}')
        self.get_logger().info(f'  Robot item: {self.robot_item_name}')
        self.get_logger().info(
            f'  TF: {self.global_frame} -> {self.robot_frame}')
        self.get_logger().info(f'  Send rate: {send_rate} Hz')

    # RoboDK connection
    # This will try to connect, if it fails, it will retry on the next timer callback
    def _connect_robodk(self):
        try:
            self.rdk = Robolink(self.host, port=self.port)
            station = self.rdk.ActiveStation()
            self.get_logger().info(f'Connected to RoboDK station: {station.Name()}')
            self._resolve_robot_item()
        except Exception as e:
            self.get_logger().warn(
                f'Cannot connect to RoboDK at {self.host}:{self.port}: {e}')
            self.rdk = None
    # Gets the RoboDK item based on the object given in the parameters
    def _resolve_robot_item(self):
        if self.rdk is None:
            return
        try:
            # Checks if it is a robot
            item = self.rdk.Item(self.robot_item_name, ITEM_TYPE_ROBOT)
            # Checks if it is a frame
            if not item.Valid():
                item = self.rdk.Item(self.robot_item_name, ITEM_TYPE_FRAME)
            # CHecks if it is an item
            if not item.Valid():
                item = self.rdk.Item(self.robot_item_name)
            # If any of the checks went fine, we log the info of the item, if not, we log a warning and set the item to None
            if item.Valid():
                self.robot_item = item
                self.get_logger().info(
                    f'Resolved robot item: {self.robot_item_name} '
                    f'(type={item.Type()})')
                try:
                    parent = item.Parent()
                    self.get_logger().info(
                        f'  Parent: {parent.Name()} (type={parent.Type()})')
                    self.get_logger().info(f'  Pose():    {list(item.Pose().Pos())}')
                    self.get_logger().info(f'  PoseAbs(): {list(item.PoseAbs().Pos())}')
                except Exception:
                    pass
            else:
                self.get_logger().warn(
                    f'Robot item "{self.robot_item_name}" not found in station')
                self.robot_item = None
        except Exception as e:
            self.get_logger().warn(f'Error resolving robot item: {e}')
            self.robot_item = None

    # Callbacks

    # Nav2 statusthat checks if we are navigating
    def _nav_status_cb(self, msg: GoalStatusArray):
        was_navigating = self.navigating
        self.navigating = any(
            s.status in (GoalStatus.STATUS_ACCEPTED, GoalStatus.STATUS_EXECUTING)
            for s in msg.status_list
        )
        if self.navigating != was_navigating:
            self.get_logger().info(
                f'Navigation state changed: navigating={self.navigating}')

    # TF lookup, returns the pose of the robot in the global frame, or None if TF is not available
    def _lookup_pose_from_tf(self):
        """Return (x_m, y_m, yaw_rad, quat_tuple) from TF, or None."""
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
            return None

        t = tf.transform.translation
        q = tf.transform.rotation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny, cosy)
        return t.x, t.y, yaw, (q.x, q.y, q.z, q.w)

    def _maybe_log_position(self, x, y, yaw_rad, quat=None):
        if not self.log_position:
            return
        now_ns = self.get_clock().now().nanoseconds
        min_period_ns = int(max(0.0, float(self.position_log_period)) * 1e9)
        if min_period_ns > 0 and (now_ns - self._last_position_log_ns) < min_period_ns:
            return
        base = (f'Position: x={x:.3f}m  y={y:.3f}m  '
                f'yaw={math.degrees(yaw_rad):.1f}deg')
        if quat is not None:
            qx, qy, qz, qw = quat
            base += (f'  q=[{qx:+.4f}, {qy:+.4f}, {qz:+.4f}, {qw:+.4f}]')
        self.get_logger().info(base)
        self._last_position_log_ns = now_ns

    # Periodic sender
    def _send_position(self):
        if self.get_parameter('only_while_navigating').value and not self.navigating:
            return

        pose = self._lookup_pose_from_tf()
        if pose is None:
            return
        x, y, yaw, quat = pose
        self._maybe_log_position(x, y, yaw, quat)

        if self.rdk is None:
            if ROBODK_AVAILABLE:
                self._connect_robodk()
            return

        if self.robot_item is None:
            self._resolve_robot_item()
            return

        x_mm = x * 1000.0
        y_mm = y * 1000.0
        yaw_deg = 0.0 if self.get_parameter('freeze_yaw').value else math.degrees(yaw)

        try:
            if self.robot_item.Type() == ITEM_TYPE_ROBOT:
                # Mobile-robot mechanism: joints are [x_mm, y_mm, z_mm, yaw_deg].
                # setPose / setPoseAbs on such a robot does IK and either
                # fights the mobile mechanism or doesn't move at all.
                self.robot_item.setJoints([x_mm, y_mm, 0.0, yaw_deg])
            else:
                # For a plain FRAME, set its absolute (station-root) pose.
                robodk_pose = TxyzRxyz_2_Pose([x_mm, y_mm, 0, 0, 0, yaw_deg])
                self.robot_item.setPoseAbs(robodk_pose)
            self.get_logger().debug(
                f'Sent to RoboDK: x={x_mm:.1f}mm  y={y_mm:.1f}mm  yaw={yaw_deg:.1f}deg')
        except Exception as e:
            self.get_logger().warn(f'Failed to update RoboDK: {e}')
            self.rdk = None
            self.robot_item = None


def main(args=None):
    rclpy.init(args=args)
    node = RoboDKPositionSender()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
