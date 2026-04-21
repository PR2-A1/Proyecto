# Nav2 1.3.11 Migration Changes (ROS 2 Jazzy)

**Date:** 2026-04-15
**Nav2 version:** 1.3.11 (built 2026-04-12)

---

## 1. `behavior_server` - Parameter renames

The behavior server parameters were renamed to distinguish between local and global costmaps.

| Old parameter      | New parameter            | Value                                    |
|--------------------|--------------------------|------------------------------------------|
| `costmap_topic`    | `local_costmap_topic`    | `local_costmap/costmap_raw`              |
| *(none)*           | `global_costmap_topic`   | `global_costmap/costmap_raw` **(new)**   |
| `footprint_topic`  | `local_footprint_topic`  | `local_costmap/published_footprint`      |
| *(none)*           | `global_footprint_topic` | `global_costmap/published_footprint` **(new)** |
| `global_frame`     | `local_frame`            | `odom`                                   |
| *(none)*           | `global_frame`           | `map` **(new)**                          |

New parameters also added:

| Parameter              | Value | Description                          |
|------------------------|-------|--------------------------------------|
| `simulate_ahead_time`  | 2.0   | Time to simulate ahead for behaviors |
| `max_rotational_vel`   | 1.0   | Maximum rotational velocity          |
| `min_rotational_vel`   | 0.4   | Minimum rotational velocity          |
| `rotational_acc_lim`   | 3.2   | Rotational acceleration limit        |

## 2. `controller_server` - Deprecated parameters removed

| Removed parameter            | Notes                                            |
|------------------------------|--------------------------------------------------|
| `current_progress_checker`   | Redundant; `progress_checker_plugins` list is used instead |
| `current_goal_checker`       | Redundant; `goal_checker_plugins` list is used instead     |

New parameters added:

| Parameter                | Value | Description                              |
|--------------------------|-------|------------------------------------------|
| `costmap_update_timeout` | 0.30  | Timeout for costmap updates (seconds)    |
| `use_realtime_priority`  | false | Whether to use realtime thread priority  |

## 3. `collision_monitor` - cmd_vel pipeline change

The velocity command pipeline was restructured. The `velocity_smoother` now sits **between** the controller and the collision monitor:

```
Old:  controller --> cmd_vel_nav --> collision_monitor --> cmd_vel
New:  controller --> cmd_vel_nav --> velocity_smoother --> cmd_vel_smoothed --> collision_monitor --> cmd_vel
```

| Parameter          | Old value      | New value          |
|--------------------|----------------|--------------------|
| `cmd_vel_in_topic` | `cmd_vel_nav`  | `cmd_vel_smoothed` |

This change is driven by the upstream `navigation_launch.py` remapping the `velocity_smoother` node's `cmd_vel` subscription to `cmd_vel_nav`, so it consumes the controller output and publishes to `cmd_vel_smoothed`.

---

## Files modified

- `config/nav2_params.yaml`
