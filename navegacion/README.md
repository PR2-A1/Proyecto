# `robodk_bridge` — how it works

This is the ROS 2 node that glues everything together. It talks to three
things at once:

- **MQTT (ESP32) → Nav2**: the ESP32 sends `goto <STATION>` orders, the
  node queues them and fires them one by one at `navigate_to_pose`.
- **Cobot (MQTT) → AMR**: when the cobot is done with whatever it's
  doing it publishes `COMPLETED` and the AMR is allowed to move again.
- **TF → RoboDK**: it reads the robot pose from TF (`map → base_link`)
  and pushes it onto the RoboDK item so the digital twin moves with the
  real robot.


---

## 1. The communication flow

```
   ESP32                    MQTT broker part                   ROS 2
+--------+   action {goto}   +-------------+   subscribe   +------------------+
| ESP32  | ────────────────► | giirob/.../ | ────────────► | robodk_bridge    |
+--------+                   |  amr/action |               |  ┌────────────┐  |
                             +-------------+               |  │   queue    │  |
                                                           |  └─────┬──────┘  |
   Cobot                     +-------------+               |        ▼         |
+--------+   COMPLETED       | giirob/.../ | ────────────► | navigate_to_pose |
| Cobot  | ────────────────► |cobot/status |               | (Nav2 action)    |
+--------+                   +-------------+               |        ▲         |
                                                           |        │         |
                             +-------------+   publish     |  ┌─────┴──────┐  |
                             | giirob/.../ | ◄──────────── |  │ AMR status │  |
                             | amr/status  |               |  └────────────┘  |
                             +-------------+               +────────┬─────────+
                                                                    │ TF (30 Hz)
                                                                    ▼
                                                           +──────────────────+
                                                           | RoboDK station   |
                                                           |  · MiR (twin)    |
                                                           +──────────────────+
```

---

## 2. AMR state machine

The node keeps a single state (`AMRState`) protected by a lock, since
the MQTT callbacks run in a different thread than the ROS executor and
we don't want them stepping on each other.

| State            | What it means                                                |
|------------------|--------------------------------------------------------------|
| `IDLE`           | Nothing going on. If the queue isn't empty, dispatch next.   |
| `NAVIGATING`     | Nav2 accepted the goal, robot is on its way.                 |
| `WAITING_COBOT`  | Robot got there. Now we wait for the cobot to say it's done. |

Transitions:

```
   IDLE ── new order in queue ──► NAVIGATING
   NAVIGATING ── Nav2 status=4 (succeeded) ──► WAITING_COBOT
   NAVIGATING ── anything else / rejected / no server ──► IDLE
   WAITING_COBOT ── cobot status=COMPLETED ──► IDLE
```

While the state is anything other than `IDLE`, new orders just pile up
in the queue. They don't get dispatched until we're back to `IDLE`.
That's the whole point: the AMR and the cobot stay in lockstep, no
order can start until the previous station is finished.

---

## 3. Inputs

### 3.1 AMR action MQTT topic (`mqtt_topic_amr_action`)

Default: `giirob/pr2-A1/devices/amr/action`.

Expected JSON payload:

```json
{ "cmd": "goto", "location": "TOLVA_X" }
```

- `cmd` has to be `"goto"`. Anything else is dropped with a warning.
- `location` has to be a key that exists in `STATION_TARGETS` (see
  section 4). If it isn't, the order will go through, fail at dispatch
  time and a `failed` will be published on the AMR status topic.

Valid orders go into a FIFO **queue** and get dispatched whenever the
state goes back to `IDLE`.

### 3.2 Cobot status MQTT topic (`mqtt_topic_cobot_status`)

Default: `giirob/pr2/devices/cobot/status`.

This one only matters when we're in `WAITING_COBOT`. The bridge expects
JSON with a `status` field:

```json
{ "status": "COMPLETED" }
```

Anything else is just ignored. `COMPLETED` releases the AMR (back to
`IDLE`) and the next order in the queue starts on the next dispatch
tick (200 ms).

### 3.3 ROS topic `goal_pose` (RViz, debug)

Still works. RViz goals get forwarded straight to Nav2, skipping the
queue and the state machine entirely. Useful for poking at localization
without touching MQTT.

```
+ goal_pose (RViz)  ──►  navigate_to_pose  (doesn't touch _state, no MQTT)
```

> Don't fire RViz goals while there's an MQTT order running, both will
> fight for Nav2. Debug only.

---

## 4. Stations dictionary (`STATION_TARGETS`)

Hardcoded at the top of [scripts/robodk_bridge.py](scripts/robodk_bridge.py).
It maps the symbolic name we get over MQTT to `(x, y)` coordinates in
metres on the `map` frame.

> These numbers are basically random for now, just placeholders until
> the actual workshop layout is settled. The yaw is also hardcoded to
> `FIXED_YAW_RAD = 0.0` until the ESP32 starts sending orientations.
> If you want to change them, edit the dict at the top of the file and
> restart the node.

---

## 5. Outputs

### 5.1 AMR status MQTT topic (`mqtt_topic_amr_status`)

Default: `giirob/pr2-A1/devices/amr/status`.

JSON payload:

```json
{ "status": "<status>", "location": "<STATION>", "caja_id": "" }
```

| `status`    | When it gets published                                       |
|-------------|--------------------------------------------------------------|
| `arrived`   | Nav2 finished with status=4, robot reached the destination.  |
| `failed`    | Goal rejected, no Nav2 server, unknown target, or Nav2       |
|             | finished with anything other than 4.                         |

`caja_id` is empty for now (placeholder, we'll fill it once the box
identification logic is in).


### 5.2 Digital twin in RoboDK

At `twin_update_rate` Hz (30 Hz by default) the bridge looks up
`global_frame → robot_frame` on TF, converts to mm/degrees and writes
onto the `robot_item_name` in RoboDK:

- If the item is `ITEM_TYPE_ROBOT` (mobile robot mechanism):
  `setJoints([x_mm, y_mm, 0, yaw_deg])`.
  > For now this is unused, the frame of the robot is used instead of the robot type.

- Anything else (a frame, etc.): `setPoseAbs(...)`.

If `freeze_yaw=true` the yaw is forced to `0°`. 

If RoboDK drops, the twin just stops updating, the navigation + MQTT
side keeps working. *RoboDK is optional*.

---

## 6. Parameters

| Parameter                  | Type  | Default                                       | What it does                                       |
|----------------------------|-------|-----------------------------------------------|----------------------------------------------------|
| `robodk_host`              | str   | `localhost`                                   | RoboDK API host                                    |
| `robodk_port`              | int   | `20500`                                       | RoboDK API port                                    |
| `robot_item_name`          | str   | `MiR`                                         | Name of the item to update in the station          |
| `global_frame`             | str   | `map`                                         | Global TF frame                                    |
| `robot_frame`              | str   | `base_link`                                   | Robot TF frame                                     |
| `twin_update_rate`         | float | `30.0`                                        | Twin update rate in Hz                             |
| `freeze_yaw`               | bool  | `false`                                       | If `true`, don't update yaw on the twin            |
| `mqtt_host`                | str   | `broker.hivemq.com`                           | MQTT broker                                        |
| `mqtt_port`                | int   | `1883`                                        | MQTT port                                          |
| `mqtt_topic_amr_action`    | str   | `giirob/pr2-A1/devices/amr/action`            | Where the ESP32 sends orders                       |
| `mqtt_topic_amr_status`    | str   | `giirob/pr2-A1/devices/amr/status`            | Where the AMR posts its status                     |
| `mqtt_topic_cobot_status`  | str   | `giirob/pr2-A1/devices/cobot/status`          | Cobot status topic the AMR listens to              |
| `amr_device_name`          | str   | `AMR`                                         | Device id (used for the MQTT client_id)            |

---

## 7. Running it

You'll need:

- Nav2 running (the `navigate_to_pose` action server has to be up).
- TF `map → base_link` being published (AMCL or SLAM).
- The MQTT broker reachable from wherever the bridge runs.
- (Optional) RoboDK open with the API enabled if you want the twin.
  Without RoboDK the node still starts, it just leaves a warning.
- Python: `pip install robodk paho-mqtt`.

```bash
# RoboDK and broker on localhost
ros2 run mir_nav2_robodk robodk_bridge.py

# Typical setup with remote RoboDK and our own broker
ros2 run mir_nav2_robodk robodk_bridge.py --ros-args \
  -p robodk_host:=192.168.1.100 \
  -p robot_item_name:=MiR \
  -p mqtt_host:=192.168.1.50 \
  -p mqtt_port:=1883 \
  -p amr_device_name:=AMR_1
```

---

## 8. End-to-end example

Terminal A — navigation:

```bash
ros2 launch mir_nav2_robodk bringup.launch.py \
  map:=$HOME/mir_robodk_ws/src/mir_nav2_robodk/maps/my_map.yaml
```

Terminal B — bridge:

```bash
ros2 run mir_nav2_robodk robodk_bridge.py
```

Terminal C — fake the ESP32 by publishing an order:

```bash
mosquitto_pub -h broker.hivemq.com -p 1883 \
  -t giirob/pr2-A1/devices/amr/action \
  -m '{"cmd":"goto","location":"TOLVA_3"}'
```

Terminal D — watch the AMR status:

```bash
mosquitto_sub -h broker.hivemq.com -p 1883 \
  -t giirob/pr2-A1/devices/amr/status -v
```

Once the AMR gets there, fake the cobot's `COMPLETED` to continue with the next
order:

```bash
mosquitto_pub -h broker.hivemq.com -p 1883 \
  -t giirob/pr2/devices/cobot/status \
  -m '{"status":"COMPLETED"}'
```


---

## 9. Stuff to know about the current state of the code

- `STATION_TARGETS` and `FIXED_YAW_RAD` are **placeholders**. They'll
  go away once the ESP32 starts sending real coordinates / orientations
  and/or once we lock down the final layout.
- `caja_id` in the AMR status payload is reserved but not filled in
  yet.
- `robodk_position_sender.py` isn't part of this repo anymore. The
  twin functionality is inside `robodk_bridge.py` now.
- The bridge is fine without RoboDK. Navigation + MQTT keep working, you just lose
  the twin updates
