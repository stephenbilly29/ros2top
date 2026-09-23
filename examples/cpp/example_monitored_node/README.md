# example_monitored_node

A minimal ROS 2 C++ package that registers itself with ros2top. It publishes a
counter on `/example_topic` and does a little arithmetic each cycle, so it shows
measurable CPU in the monitor.

## Requirements

- ROS 2 (Humble, Jazzy, Kilted or Rolling)
- `ros2top` installed — `pip install ros2top`
- `nlohmann_json` — `sudo apt install nlohmann-json3-dev`

## Build

```bash
mkdir -p ~/ros2_ws/src
cp -r example_monitored_node ~/ros2_ws/src/
cd ~/ros2_ws
colcon build --packages-select example_monitored_node
source install/setup.bash
```

## Run

```bash
ros2 run example_monitored_node example_monitored_node
```

With it running, in another terminal:

```bash
ros2top                         # the node appears, no `~` prefix
ros2 topic echo /example_topic  # see what it publishes
```

A `~` before a name would mean the PID was inferred from the DDS GUID; this node
reports its own, because it registers.

## What the code does

```cpp
#include <ros2top/ros2top.hpp>

// at startup
ros2top::register_node("/example_monitored_node");

// in the timer callback
ros2top::heartbeat("/example_monitored_node");

// on shutdown
ros2top::unregister_node("/example_monitored_node");
```

`register_node()` writes this process's PID to `~/.ros2top/registry/` so ros2top
can attribute usage to the node by name. `heartbeat()` keeps the entry fresh and
is optional; `unregister_node()` is optional too, since entries are cleaned up
when the process exits.

## Watching it work

```bash
# record this node for 30 seconds, then read the figures back
ros2top --record example.csv --pid $(pgrep -f example_monitored_node) &
sleep 30 && kill %1
```

## Troubleshooting

**`ros2top/ros2top.hpp` not found.** The header ships with the Python package.
Confirm `pip show ros2top`, and that `find_package(ros2top)` resolves in
`CMakeLists.txt`.

**`nlohmann_json` not found.** `sudo apt install nlohmann-json3-dev`.

**The node builds but does not appear in ros2top.** Check ros2top's status bar:
`Auto✗ register` means registration is the only route in, so confirm
`register_node()` is reached. Otherwise verify the node is running with
`ros2 node list`.
