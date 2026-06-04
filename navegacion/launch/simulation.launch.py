"""
Simulation launch file: Gazebo Harmonic + MiR robot + Nav2.

Starts Gazebo with the station world, spawns the MiR, bridges
Gazebo topics to ROS 2, and launches the Nav2 stack.

Usage:
  # SLAM mode (build a map in the default station world)
  ros2 launch mir_nav2_robodk simulation.launch.py

  # Localization in the warehouse with its shipped map
  ros2 launch mir_nav2_robodk simulation.launch.py slam:=false \\
      world:=$(ros2 pkg prefix mir_nav2_robodk)/share/mir_nav2_robodk/worlds/warehouse.sdf \\
      map:=$(ros2 pkg prefix mir_nav2_robodk)/share/mir_nav2_robodk/maps/warehouse.yaml

  # Localization in the station world (requires a map you saved with
  # nav2_map_server map_saver_cli, e.g. maps/station.yaml)
  ros2 launch mir_nav2_robodk simulation.launch.py slam:=false map:=/path/to/station.yaml
"""

import os

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    SetEnvironmentVariable,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (
    LaunchConfiguration,
    PathJoinSubstitution,
    Command,
    EnvironmentVariable,
)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare
from nav2_common.launch import RewrittenYaml


def generate_launch_description():
    pkg_share = FindPackageShare('mir_nav2_robodk')
    nav2_bringup_share = FindPackageShare('nav2_bringup')
    ros_gz_sim_share = FindPackageShare('ros_gz_sim')

    # Both paths are needed:
    #   - share/mir_nav2_robodk/models  -> resolves model://Station
    #   - share/                        -> resolves model://mir_nav2_robodk/meshes/...
    # Append (do not overwrite) so Gazebo's default model paths still work.
    gz_resource_path = SetEnvironmentVariable(
        'GZ_SIM_RESOURCE_PATH',
        [
            PathJoinSubstitution([pkg_share, 'models']),
            ':',
            PathJoinSubstitution([pkg_share, os.pardir]),
            ':',
            EnvironmentVariable('GZ_SIM_RESOURCE_PATH', default_value=''),
        ],
    )

    # Launch arguments
    mir_type_arg = DeclareLaunchArgument(
        'mir_type', default_value='mir_100',
        description='MiR variant: mir_100 or mir_250')

    slam_arg = DeclareLaunchArgument(
        'slam', default_value='True',
        description='Run SLAM (True) or localization with a map (False)')

    rviz_arg = DeclareLaunchArgument(
        'rviz', default_value='true',
        description='Launch RViz2')

    world_arg = DeclareLaunchArgument(
        'world', default_value=PathJoinSubstitution([pkg_share, 'worlds', 'station.sdf']),
        description='Path to Gazebo world SDF file')

    # Map yaml used only when slam:=False (localization mode). Must match the
    # `world`. Defaults to warehouse.yaml since that is the only map shipped;
    # if you want station.sdf with localization, generate maps/station.yaml
    # first by running SLAM and saving with nav2_map_server map_saver_cli.
    map_arg = DeclareLaunchArgument(
        'map',
        default_value=PathJoinSubstitution([pkg_share, 'maps', 'warehouse.yaml']),
        description='Map yaml file for localization (used when slam:=False)')

    nav2_params_arg = DeclareLaunchArgument(
        'nav2_params_file',
        default_value=PathJoinSubstitution([pkg_share, 'config', 'nav2_params.yaml']),
        description='Nav2 parameters file')

    spawn_x_arg = DeclareLaunchArgument('spawn_x', default_value='-0.5')
    spawn_y_arg = DeclareLaunchArgument('spawn_y', default_value='0.0')
    spawn_yaw_arg = DeclareLaunchArgument('spawn_yaw', default_value='0.0')

    # Robot description
    xacro_file = PathJoinSubstitution([pkg_share, 'urdf', 'mir_sim.urdf.xacro'])
    robot_description = Command([
        'xacro ', xacro_file,
        ' mir_type:=', LaunchConfiguration('mir_type'),
    ])

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        parameters=[{
            'robot_description': ParameterValue(robot_description, value_type=str),
            'use_sim_time': True,
        }],
        output='screen',
    )

    # Gazebo Harmonic
    gz_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([ros_gz_sim_share, 'launch', 'gz_sim.launch.py'])
        ),
        launch_arguments={
            'gz_args': ['-r ', LaunchConfiguration('world')],
        }.items(),
    )

    gz_spawn = Node(
        package='ros_gz_sim',
        executable='create',
        arguments=[
            '-name', 'mir',
            '-topic', '/robot_description',
            '-x', LaunchConfiguration('spawn_x'),
            '-y', LaunchConfiguration('spawn_y'),
            '-z', '0.0',
            '-Y', LaunchConfiguration('spawn_yaw'),
        ],
        output='screen',
    )

    # ros_gz_bridge
    gz_bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        parameters=[{
            'config_file': PathJoinSubstitution(
                [pkg_share, 'config', 'gz_bridge.yaml']),
            'expand_gz_topic_names': True,
            'use_sim_time': True,
        }],
        output='screen',
    )

    # Shared Nav2 launch arguments
    nav2_params_sim = RewrittenYaml(
        source_file=LaunchConfiguration('nav2_params_file'),
        root_key='',
        param_rewrites={'use_sim_time': 'true'},
        convert_types=True,
    )

    nav2_common = {
        'use_sim_time': 'true',
        'params_file': nav2_params_sim,
        'autostart': 'true',
        'use_composition': 'False',
    }

    # Nav2: SLAM mode
    nav2_slam = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([nav2_bringup_share, 'launch', 'slam_launch.py'])
        ),
        condition=IfCondition(LaunchConfiguration('slam')),
        launch_arguments=nav2_common.items(),
    )

    nav2_slam_nav = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([nav2_bringup_share, 'launch', 'navigation_launch.py'])
        ),
        condition=IfCondition(LaunchConfiguration('slam')),
        launch_arguments=nav2_common.items(),
    )

    # Nav2: localization mode (uses `map` to pick which yaml is loaded).
    nav2_loc_args = {**nav2_common, 'map': LaunchConfiguration('map')}
    nav2_loc = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([nav2_bringup_share, 'launch', 'localization_launch.py'])
        ),
        condition=UnlessCondition(LaunchConfiguration('slam')),
        launch_arguments=nav2_loc_args.items(),
    )

    nav2_loc_nav = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([nav2_bringup_share, 'launch', 'navigation_launch.py'])
        ),
        condition=UnlessCondition(LaunchConfiguration('slam')),
        launch_arguments=nav2_common.items(),
    )

    # RViz
    rviz_node = Node(
        condition=IfCondition(LaunchConfiguration('rviz')),
        package='rviz2',
        executable='rviz2',
        arguments=['-d', PathJoinSubstitution([pkg_share, 'rviz', 'nav2_view.rviz'])],
        parameters=[{'use_sim_time': True}],
        output='screen',
    )

    return LaunchDescription([
        gz_resource_path,
        mir_type_arg,
        slam_arg,
        rviz_arg,
        world_arg,
        map_arg,
        nav2_params_arg,
        spawn_x_arg,
        spawn_y_arg,
        spawn_yaw_arg,
        robot_state_publisher,
        gz_sim,
        gz_spawn,
        gz_bridge,
        nav2_slam,
        nav2_slam_nav,
        nav2_loc,
        nav2_loc_nav,
        rviz_node,
    ])
