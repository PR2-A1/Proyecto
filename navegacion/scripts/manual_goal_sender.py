#!/usr/bin/env python3
"""
Manual Nav2 goal sender.

Send a single NavigateToPose goal from terminal input (x, y, yaw).
You can pass coordinates as arguments or use interactive mode.

Usage:
  ros2 run mir_nav2_robodk manual_goal_sender.py -- 1.25 -0.40 90

  ros2 run mir_nav2_robodk manual_goal_sender.py
  # then type: x y yaw_deg

Arguments:
  x          Goal X position in meters (map frame)
  y          Goal Y position in meters (map frame)
  yaw_deg    Goal yaw in degrees

Options:
  --frame-id map_frame_name   (default: map)
"""

import argparse
import math
import sys

import rclpy
from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node


def parse_args(argv):
    parser = argparse.ArgumentParser(description='Send manual x/y/yaw goals to Nav2')
    parser.add_argument('x', nargs='?', type=float, help='goal x in meters')
    parser.add_argument('y', nargs='?', type=float, help='goal y in meters')
    parser.add_argument('yaw_deg', nargs='?', type=float, help='goal yaw in degrees')
    parser.add_argument('--frame-id', default='map', help='target frame id (default: map)')
    return parser.parse_args(argv)


class ManualGoalSender(Node):
    def __init__(self, frame_id='map'):
        super().__init__('manual_goal_sender')
        self.frame_id = frame_id
        self.nav_to_pose_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self._last_feedback_distance = None

    def _feedback_cb(self, feedback_msg):
        feedback = feedback_msg.feedback
        remaining = feedback.distance_remaining
        if remaining <= 0:
            return

        # Log only when distance changes enough to avoid terminal spam.
        if self._last_feedback_distance is None or abs(remaining - self._last_feedback_distance) >= 0.2:
            self.get_logger().info(f'Distance remaining: {remaining:.2f} m')
            self._last_feedback_distance = remaining

    def _build_goal(self, x, y, yaw_deg):
        yaw = math.radians(yaw_deg)
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = self.frame_id
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = x
        goal_msg.pose.pose.position.y = y
        goal_msg.pose.pose.position.z = 0.0 # In robodk the robot will allways be on the ground
        goal_msg.pose.pose.orientation.x = 0.0 # No rotation on x or y axis in robodk, never
        goal_msg.pose.pose.orientation.y = 0.0
        goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0) # This comes from quaternion conversion
        goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        return goal_msg

    def send_goal_and_wait(self, x, y, yaw_deg):
        if not self.nav_to_pose_client.wait_for_server(timeout_sec=10.0): # We wait for Nav2 server to be ready, if not, we send an error and terminate
            self.get_logger().error('navigate_to_pose action server is not available')
            return False

        self._last_feedback_distance = None # We reset the feedback for a new goal
        self.get_logger().info(
            f'Sending goal: x={x:.3f} m, y={y:.3f} m, yaw={yaw_deg:.1f} deg (frame: {self.frame_id})') # Print info 

        goal_msg = self._build_goal(x, y, yaw_deg)
        send_future = self.nav_to_pose_client.send_goal_async(
            goal_msg, feedback_callback=self._feedback_cb)
        rclpy.spin_until_future_complete(self, send_future)

        goal_handle = send_future.result()
        if goal_handle is None:
            self.get_logger().error('Failed to send goal (no goal handle returned)')
            return False

        if not goal_handle.accepted:
            self.get_logger().warn('Goal was rejected by Nav2')
            return False

        self.get_logger().info('Goal accepted. Waiting for result...')
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)

        result = result_future.result()
        if result is None:
            self.get_logger().error('No result received from Nav2')
            return False

        if result.status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info('Goal reached successfully')
            return True

        self.get_logger().warn(f'Navigation finished with status: {result.status}')
        return False


def run_interactive(sender):
    print('Interactive mode: enter goals as: x y yaw_deg')
    print('Type q to quit')

    while rclpy.ok():
        try:
            line = input('goal> ').strip()
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            break

        if not line:
            continue

        if line.lower() in ('q', 'quit', 'exit'):
            break

        parts = line.split()
        if len(parts) != 3:
            print('Expected 3 values: x y yaw_deg')
            continue

        try:
            x = float(parts[0])
            y = float(parts[1])
            yaw_deg = float(parts[2])
        except ValueError:
            print('Invalid numeric values. Example: 1.2 -0.3 90')
            continue

        sender.send_goal_and_wait(x, y, yaw_deg)


def main(args=None):
    ros_args = rclpy.utilities.remove_ros_args(args=sys.argv)[1:]
    cli_args = parse_args(ros_args)

    rclpy.init(args=args)
    node = ManualGoalSender(frame_id=cli_args.frame_id)

    try:
        if cli_args.x is not None and cli_args.y is not None and cli_args.yaw_deg is not None:
            node.send_goal_and_wait(cli_args.x, cli_args.y, cli_args.yaw_deg)
        elif cli_args.x is None and cli_args.y is None and cli_args.yaw_deg is None:
            run_interactive(node)
        else:
            node.get_logger().error('Provide either all 3 values (x y yaw_deg) or no values for interactive mode')
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
