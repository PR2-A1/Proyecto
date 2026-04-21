# Connecting the MiR to RoboDK

Step-by-step guide to establish communication between the ROS 2 Nav2 stack
and RoboDK so the digital twin mirrors the real (or simulated) platform.

---

## 1. Prerequisites

| Requirement | How to get it |
|---|---|
| ROS 2 Jazzy with Nav2 | `sudo apt install ros-jazzy-navigation2 ros-jazzy-nav2-bringup` |
| RoboDK Python API | `pip install robodk` |
| This package built | `cd ~/mir_robodk_ws && colcon build --packages-select mir_nav2_robodk && source install/setup.bash` |

## 2. Prepare the RoboDK station

1. Open RoboDK and create a new station (or open an existing one).
2. Add a **robot item** that represents the MiR platform.
   - The item **must** be named `MiR` (this is the default the nodes look for).
   - If you use a different name, pass it with the `robot_item_name` parameter.
3. Create **Target** frames for every navigation destination.
   - The **X / Y translation** (in millimetres) maps to the ROS `map` frame coordinates.
   - The **Z rotation** maps to the goal yaw.
   - Leave all other translation/rotation values at zero (the MiR moves on a 2D plane).

## 3. Enable the RoboDK API

RoboDK exposes a TCP socket API on port **20500** by default.

1. In RoboDK go to **Tools > Options > Other**.
2. Make sure **Start the API server automatically** is checked.
3. Note the port number (default `20500`). If you change it, pass it as
   the `robodk_port` parameter when launching the nodes.
4. If RoboDK runs on a **different machine** than the ROS 2 nodes, make sure:
   - The firewall allows inbound TCP on the API port.
   - Both machines can reach each other over the network.

### Verify the API is reachable

From the machine running ROS 2:

```bash
# Quick check — should connect without error
python3 -c "from robodk.robolink import Robolink; rdk = Robolink('ROBODK_IP', port=20500); print(rdk.ActiveStation().Name())"
```

Replace `ROBODK_IP` with the IP of the machine running RoboDK (use `localhost`
if both run on the same machine).

## 4. Launch the Nav2 stack

Start navigation on the real robot or in simulation. The RoboDK nodes
need the AMCL pose and the Nav2 action servers to be running.

```bash
# Simulation (SLAM mode)
ros2 launch mir_nav2_robodk simulation.launch.py

# Real robot with an existing map
ros2 launch mir_nav2_robodk bringup.launch.py \
  map:=$HOME/mir_robodk_ws/src/mir_nav2_robodk/maps/my_map.yaml
```

## 5. Choose which node to run

This package provides two nodes that talk to RoboDK. Pick the one that
fits your workflow (or run both)

### Option A — Full bridge (`robodk_bridge.py`)

Bidirectional: reads targets **from** RoboDK and sends the AMCL pose
**back to** RoboDK at every pose update.

```bash
# RoboDK on the same machine
ros2 run mir_nav2_robodk robodk_bridge.py

# RoboDK on a remote machine
ros2 run mir_nav2_robodk robodk_bridge.py --ros-args \
  -p robodk_host:=192.168.1.100 \
  -p robodk_port:=20500
```

| Parameter | Default | Description |
|---|---|---|
| `robodk_host` | `localhost` | RoboDK API host |
| `robodk_port` | `20500` | RoboDK API port |
| `poll_rate` | `2.0` | Hz to poll RoboDK for selected targets |
| `station_name` | `""` | Station name filter |

**Workflow:**
1. Select a Target in the RoboDK station.
2. The bridge detects the selection and sends a `NavigateToPose` goal to Nav2.
3. While Nav2 navigates, the AMCL pose is pushed back to update the digital twin.

### Option B — Position sender only (`robodk_position_sender.py`)

Unidirectional: streams the platform (x, y, yaw) to RoboDK **only while
the robot is actively navigating**. Does not read targets from RoboDK.

```bash
ros2 run mir_nav2_robodk robodk_position_sender.py

# With custom parameters
ros2 run mir_nav2_robodk robodk_position_sender.py --ros-args \
  -p robodk_host:=192.168.1.100 \
  -p robot_item_name:=MiR \
  -p send_rate:=5.0
```

| Parameter | Default | Description |
|---|---|---|
| `robodk_host` | `localhost` | RoboDK API host |
| `robodk_port` | `20500` | RoboDK API port |
| `robot_item_name` | `MiR` | Name of the robot item in the station |
| `send_rate` | `10.0` | Update rate in Hz |

This node detects active navigation by subscribing to
`navigate_to_pose/_action/status`. When no goal is active it stops
sending updates to avoid unnecessary API traffic.

## 6. Verify the connection

Once a node is running you should see a log line confirming the
connection:

```
[INFO] Connected to RoboDK station: <your station name>
```

If it fails, common issues are:

| Symptom | Cause | Fix |
|---|---|---|
| `Cannot connect to RoboDK` | RoboDK is not running or the API server is off | Open RoboDK and enable the API (see step 3) |
| `Cannot connect to RoboDK` | Wrong host/port | Double-check the IP and port with the `python3 -c` test above |
| `Robot item "MiR" not found` | The item name doesn't match | Rename the item in RoboDK to `MiR`, or pass `-p robot_item_name:=YourName` |
| Connection drops periodically | Network instability or RoboDK restart | The nodes auto-reconnect on the next timer tick |
| No position updates in RoboDK | Robot is not navigating (position sender) or AMCL pose not published | Send a Nav2 goal and make sure `ros2 topic echo /amcl_pose` shows data |

## 7. Unit conventions

ROS 2 and RoboDK use different units. The nodes handle the conversion
automatically, but keep this in mind when creating targets in RoboDK:

| Quantity | ROS 2 | RoboDK |
|---|---|---|
| Distance | metres (m) | millimetres (mm) |
| Angle | radians | degrees |

A target at **(3.5, 2.0)** metres in the ROS map frame should be placed at
**(3500, 2000)** mm in RoboDK.

## 8. Network diagram

```
+-----------------+          TCP :20500          +------------------+
|  ROS 2 machine  | ◄─────────────────────────► |  RoboDK machine  |
|                 |    robodk Python API          |                  |
|  Nav2 stack     |                               |  Station         |
|  robodk_bridge  |  ── target selection ──►      |    MiR (item)    |
|  or             |  ◄── setPose(x,y,yaw) ──      |    Targets       |
|  position_sender|                               |                  |
+-----------------+                               +------------------+
```

Both machines can be the same host (use `localhost`).
