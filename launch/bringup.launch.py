"""
Full bringup launch file for the MiR robot with Nav2.

Launches:
  - Robot state publisher (URDF)
  - Joint state publisher
  - Nav2 navigation stack (AMCL + planners + controllers)
  - RViz2 (optional)

Usage:
  # With a pre-built map (localization mode):
  ros2 launch mir_nav2_robodk bringup.launch.py map:=/path/to/map.yaml

  # With SLAM (mapping mode):
  ros2 launch mir_nav2_robodk bringup.launch.py slam:=true

  # With RoboDK bridge:
  ros2 launch mir_nav2_robodk bringup.launch.py
  # Then in another terminal:
  ros2 run mir_nav2_robodk robodk_bridge.py --ros-args -p robodk_host:=<IP>
"""

import os
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    GroupAction,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (
    LaunchConfiguration,
    PathJoinSubstitution,
    Command,
)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    pkg_share = FindPackageShare('mir_nav2_robodk')
    nav2_bringup_share = FindPackageShare('nav2_bringup')

    # Launch arguments
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time', default_value='false',
        description='Use simulation clock')

    mir_type_arg = DeclareLaunchArgument(
        'mir_type', default_value='mir_100',
        description='MiR variant: mir_100 or mir_250')

    slam_arg = DeclareLaunchArgument(
        'slam', default_value='False',
        description='Run SLAM instead of localization with a known map')

    map_arg = DeclareLaunchArgument(
        'map', default_value='',
        description='Path to map yaml file (required unless slam:=true)')

    rviz_arg = DeclareLaunchArgument(
        'rviz', default_value='true',
        description='Launch RViz2')

    nav2_params_arg = DeclareLaunchArgument(
        'nav2_params_file',
        default_value=PathJoinSubstitution([pkg_share, 'config', 'nav2_params.yaml']),
        description='Path to Nav2 parameters file')

    slam_params_arg = DeclareLaunchArgument(
        'slam_params_file',
        default_value=PathJoinSubstitution([pkg_share, 'config', 'slam_toolbox_params.yaml']),
        description='Path to SLAM Toolbox parameters file')

    # Robot description
    xacro_file = PathJoinSubstitution([pkg_share, 'urdf', 'mir.urdf.xacro'])
    robot_description = Command([
        'xacro ', xacro_file,
        ' mir_type:=', LaunchConfiguration('mir_type'),
    ])

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        parameters=[{
            'robot_description': ParameterValue(robot_description, value_type=str),
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }],
        output='screen',
    )

    joint_state_publisher = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }],
    )

    # Nav2 bringup (localization mode with map)
    nav2_localization = GroupAction(
        condition=UnlessCondition(LaunchConfiguration('slam')),
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution([nav2_bringup_share, 'launch', 'bringup_launch.py'])
                ),
                launch_arguments={
                    'use_sim_time': LaunchConfiguration('use_sim_time'),
                    'map': LaunchConfiguration('map'),
                    'params_file': LaunchConfiguration('nav2_params_file'),
                    'autostart': 'true',
                }.items(),
            ),
        ],
    )

    # Nav2 bringup (SLAM mode)
    # nav2_bringup already launches slam_toolbox when slam:=True.
    nav2_slam = GroupAction(
        condition=IfCondition(LaunchConfiguration('slam')),
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution([nav2_bringup_share, 'launch', 'bringup_launch.py'])
                ),
                launch_arguments={
                    'use_sim_time': LaunchConfiguration('use_sim_time'),
                    'slam': 'True',
                    'params_file': LaunchConfiguration('nav2_params_file'),
                    'autostart': 'true',
                }.items(),
            ),
        ],
    )

    # RViz
    rviz_config = PathJoinSubstitution([pkg_share, 'rviz', 'nav2_view.rviz'])
    rviz_node = Node(
        condition=IfCondition(LaunchConfiguration('rviz')),
        package='rviz2',
        executable='rviz2',
        arguments=['-d', rviz_config],
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }],
        output='screen',
    )

    return LaunchDescription([
        use_sim_time_arg,
        mir_type_arg,
        slam_arg,
        map_arg,
        rviz_arg,
        nav2_params_arg,
        slam_params_arg,
        robot_state_publisher,
        joint_state_publisher,
        nav2_localization,
        nav2_slam,
        rviz_node,
    ])
