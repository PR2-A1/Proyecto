# mir_nav2_robodk

Nav2 navigation package for the MiR 100/250 robot with a RoboDK API bridge.
Self-contained ROS 2 Jazzy package -- does not depend on the original `mir_description` catkin package.

---

## Prerequisites

- ROS 2 Jazzy
- Nav2 (`sudo apt install ros-jazzy-navigation2 ros-jazzy-nav2-bringup`)
- SLAM Toolbox (`sudo apt install ros-jazzy-slam-toolbox`)
- joint-state-publisher-gui (for display only: `sudo apt install ros-jazzy-joint-state-publisher-gui`)
- Gazebo Harmonic + ros_gz (`sudo apt install ros-jazzy-ros-gz`)
- RoboDK Python API (only for the bridge node): `pip install robodk`

## Build

```bash
cd ~/mir_robodk_ws
colcon build --packages-select mir_nav2_robodk
source install/setup.bash
```

---

## 1. Verify the URDF

Launch the robot model in RViz to check that the MiR description loads correctly:

```bash
ros2 launch mir_nav2_robodk display.launch.py
```

Use `mir_type` to switch between variants:

```bash
ros2 launch mir_nav2_robodk display.launch.py mir_type:=mir_250
```

## 2. Simulation (Gazebo)

Launch the full simulation with the warehouse world. This starts Gazebo, spawns the
MiR, bridges all topics to ROS 2, and launches Nav2 in SLAM mode by default.

```bash
ros2 launch mir_nav2_robodk simulation.launch.py
```

This opens:
- **Gazebo** with a warehouse environment (20x15 m, walls, shelves, crates, pillars).
- **RViz** showing the robot, laser scans, map, and costmaps.
- **Nav2** in SLAM mode -- drive around to build the map.

Drive with teleop in a second terminal:

```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel
```

Save the map when done:

```bash
ros2 run nav2_map_server map_saver_cli -f ~/mir_robodk_ws/src/mir_nav2_robodk/maps/warehouse
```

Then re-launch in localization mode with the saved map:

```bash
ros2 launch mir_nav2_robodk simulation.launch.py slam:=false \
  map:=$HOME/mir_robodk_ws/src/mir_nav2_robodk/maps/warehouse.yaml
```

Set the initial pose in RViz (**2D Pose Estimate**), then send goals (**2D Goal Pose**).

### Simulation launch arguments

| Argument | Default | Description |
|---|---|---|
| `mir_type` | `mir_100` | Robot variant |
| `slam` | `true` | SLAM mode (set `false` for localization) |
| `map` | `""` | Map yaml path (when `slam:=false`) |
| `world` | `worlds/warehouse.sdf` | Gazebo world file |
| `rviz` | `true` | Launch RViz |
| `spawn_x` | `0.0` | Robot spawn X position |
| `spawn_y` | `0.0` | Robot spawn Y position |
| `spawn_yaw` | `0.0` | Robot spawn yaw |

### Custom world

You can point to any SDF world:

```bash
ros2 launch mir_nav2_robodk simulation.launch.py world:=/path/to/custom.sdf
```

---

## 3. Create a map (SLAM) -- real robot

Start the full stack in SLAM mode.
Drive the robot around (via teleop or RoboDK) to build the map:

```bash
# Terminal 1 -- bringup with SLAM
ros2 launch mir_nav2_robodk bringup.launch.py slam:=true

# Terminal 2 -- teleop (optional, for manual driving)
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel
```

When the map is complete, save it:

```bash
ros2 run nav2_map_server map_saver_cli -f ~/mir_robodk_ws/src/mir_nav2_robodk/maps/my_map
```

This creates `my_map.yaml` and `my_map.pgm` inside the `maps/` folder.

## 4. Navigate with an existing map -- real robot

Launch the stack in localization mode, pointing to the saved map:

```bash
ros2 launch mir_nav2_robodk bringup.launch.py \
  map:=$HOME/mir_robodk_ws/src/mir_nav2_robodk/maps/my_map.yaml
```

In RViz:

1. Set the initial pose with **2D Pose Estimate**.
2. Send goals with **2D Goal Pose**.

## 5. RoboDK bridge

The bridge node connects the RoboDK API to the Nav2 stack.
It reads target poses from RoboDK and sends them as Nav2 goals.

```bash
# RoboDK running on the same machine
ros2 run mir_nav2_robodk robodk_bridge.py

# RoboDK on a remote machine
ros2 run mir_nav2_robodk robodk_bridge.py --ros-args \
  -p robodk_host:=192.168.1.100 \
  -p robodk_port:=20500
```

### How it works

1. In RoboDK, create **Targets** (frames) that represent navigation goals for the MiR.
   The X/Y translation (in mm) maps to the map frame, and the Z-rotation maps to the goal yaw.
2. **Select a target** in RoboDK -- the bridge detects it and sends a `NavigateToPose` goal to Nav2.
3. Nav2 plans the path, executes it, and publishes `cmd_vel`.
4. The AMCL pose is sent back to RoboDK to keep the digital twin in sync.

### Alternative: send targets via ROS topic

Instead of polling RoboDK, you can publish a target name directly:

```bash
ros2 topic pub --once /robodk/target_name std_msgs/msg/String "data: 'TargetStation1'"
```

The bridge resolves the name in the RoboDK station and navigates to it.

### Monitor bridge status

```bash
ros2 topic echo /robodk/status
```

Possible values: `connected`, `disconnected`, `navigating`, `goal_reached`, `goal_rejected`, `nav2_unavailable`.

---

## 6. Send goal by x, y, yaw from terminal

Use the manual goal sender script to type target poses directly.

```bash
# Single goal (x y yaw_deg)
ros2 run mir_nav2_robodk manual_goal_sender.py -- 1.5 -0.8 90

# Interactive mode (type many goals)
ros2 run mir_nav2_robodk manual_goal_sender.py
```

In interactive mode, enter values as:

```text
x y yaw_deg
```

Example:

```text
2.0 1.2 180
```

Type `q` to exit interactive mode.

---

## Launch arguments reference

| Argument | Default | Description |
|---|---|---|
| `use_sim_time` | `false` | Use simulation clock |
| `mir_type` | `mir_100` | Robot variant (`mir_100` or `mir_250`) |
| `slam` | `false` | Run SLAM instead of localization |
| `map` | `""` | Path to map `.yaml` (required unless `slam:=true`) |
| `rviz` | `true` | Launch RViz2 |
| `nav2_params_file` | `config/nav2_params.yaml` | Nav2 parameters file |
| `slam_params_file` | `config/slam_toolbox_params.yaml` | SLAM Toolbox parameters file |

## RoboDK bridge parameters

| Parameter | Default | Description |
|---|---|---|
| `robodk_host` | `localhost` | RoboDK API host address |
| `robodk_port` | `20500` | RoboDK API port |
| `poll_rate` | `2.0` | Hz to poll RoboDK for selected targets |
| `station_name` | `""` | RoboDK station name filter |

## Key topics

| Topic | Type | Description |
|---|---|---|
| `/f_scan` | `sensor_msgs/LaserScan` | Front SICK S300 laser |
| `/b_scan` | `sensor_msgs/LaserScan` | Back SICK S300 laser |
| `/cmd_vel` | `geometry_msgs/Twist` | Velocity commands from Nav2 |
| `/odom` | `nav_msgs/Odometry` | Wheel odometry input |
| `/map` | `nav_msgs/OccupancyGrid` | Map (from map_server or SLAM) |
| `/amcl_pose` | `geometry_msgs/PoseWithCovarianceStamped` | Localized robot pose |
| `/robodk/target_name` | `std_msgs/String` | Send a RoboDK target by name |
| `/robodk/status` | `std_msgs/String` | Bridge status updates |

## TF frames

```
map
 └── odom
      └── base_footprint
           └── base_link
                ├── front_laser_link
                ├── back_laser_link
                ├── imu_link -> imu_frame
                ├── left_wheel_link
                ├── right_wheel_link
                ├── fl/fr/bl/br_caster_rotation_link -> *_caster_wheel_link
                ├── us_1_frame / us_2_frame
                └── surface
```
