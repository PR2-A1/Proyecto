"""
Master bringup: full simulation + RoboDK-MQTT bridge + SCADA.

Includes simulation.launch.py (Gazebo + MiR + Nav2 + RViz) and adds the
RoboDK-MQTT-ROS2 bridge node and the SCADA Qt app. Each extra piece can be
toggled with its own argument.

Usage:
  ros2 launch mir_nav2_robodk bringup.launch.py
  ros2 launch mir_nav2_robodk bringup.launch.py bridge:=false scada:=false
  ros2 launch mir_nav2_robodk bringup.launch.py mqtt_host:=localhost robodk_host:=192.168.1.50
"""

import sys

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    ExecuteProcess,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    pkg_share = FindPackageShare('mir_nav2_robodk')

    # --- arguments ---
    slam_arg = DeclareLaunchArgument(
        'slam', default_value='True',
        description='Run SLAM (True) or localization with a map (False)')
    world_arg = DeclareLaunchArgument(
        'world',
        default_value=PathJoinSubstitution([pkg_share, 'worlds', 'station.sdf']),
        description='Path to Gazebo world SDF file')
    map_arg = DeclareLaunchArgument(
        'map',
        default_value=PathJoinSubstitution([pkg_share, 'maps', 'warehouse.yaml']),
        description='Map yaml for localization (used when slam:=False)')
    rviz_arg = DeclareLaunchArgument(
        'rviz', default_value='true', description='Launch RViz2')
    bridge_arg = DeclareLaunchArgument(
        'bridge', default_value='true', description='Launch the RoboDK-MQTT bridge')
    scada_arg = DeclareLaunchArgument(
        'scada', default_value='true', description='Launch the SCADA Qt app')
    mqtt_host_arg = DeclareLaunchArgument(
        'mqtt_host', default_value='broker.hivemq.com',
        description='MQTT broker host for the bridge')
    robodk_host_arg = DeclareLaunchArgument(
        'robodk_host', default_value='localhost',
        description='RoboDK API host for the bridge')

    # --- simulation (reuse the existing launch) ---
    simulation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([pkg_share, 'launch', 'simulation.launch.py'])
        ),
        launch_arguments={
            'slam': LaunchConfiguration('slam'),
            'world': LaunchConfiguration('world'),
            'map': LaunchConfiguration('map'),
            'rviz': LaunchConfiguration('rviz'),
        }.items(),
    )

    # --- RoboDK-MQTT-ROS2 bridge ---
    bridge_node = Node(
        condition=IfCondition(LaunchConfiguration('bridge')),
        package='mir_nav2_robodk',
        executable='robodk_bridge.py',
        name='robodk_bridge',
        output='screen',
        parameters=[{
            'use_sim_time': True,
            'mqtt_host': LaunchConfiguration('mqtt_host'),
            'robodk_host': LaunchConfiguration('robodk_host'),
        }],
    )

    # --- SCADA Qt app (installed under share/<pkg>/scada) ---
    scada_proc = ExecuteProcess(
        condition=IfCondition(LaunchConfiguration('scada')),
        cmd=[sys.executable, PathJoinSubstitution([pkg_share, 'scada', 'main.py'])],
        output='screen',
    )

    return LaunchDescription([
        slam_arg, world_arg, map_arg, rviz_arg,
        bridge_arg, scada_arg, mqtt_host_arg, robodk_host_arg,
        simulation,
        bridge_node,
        scada_proc,
    ])
