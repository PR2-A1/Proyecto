cmake_minimum_required(VERSION 3.8)
project(mir_nav2_robodk)

find_package(ament_cmake REQUIRED)

install(DIRECTORY
  config
  launch
  maps
  meshes
  rviz
  urdf
  worlds
  DESTINATION share/${PROJECT_NAME}
)

install(PROGRAMS
  scripts/robodk_bridge.py
  scripts/robodk_position_sender.py
  scripts/manual_goal_sender.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
