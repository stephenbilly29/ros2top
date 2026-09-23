# C++ example

`example_monitored_node/` is a complete ROS 2 package that registers itself with
ros2top from C++, so it appears in the monitor with its real PID and its own
start time.

Registration is only *required* on middleware whose DDS GUID does not carry the
process id — `rmw_zenoh_cpp` and Cyclone DDS. Under Fast DDS (the ROS 2 default)
ros2top finds nodes on its own; registering is still more precise, and lets a node
attach metadata.

## Requirements

- ROS 2 (Humble, Jazzy, Kilted or Rolling)
- `ros2top` installed — `pip install ros2top`
- `nlohmann_json` — `sudo apt install nlohmann-json3-dev`

## Build and run

Copy the package into a colcon workspace and build it:

```bash
cp -r example_monitored_node ~/ros2_ws/src/
cd ~/ros2_ws
colcon build --packages-select example_monitored_node
source install/setup.bash
ros2 run example_monitored_node example_monitored_node
```

Then, in another terminal:

```bash
ros2top          # the node appears without the `~` prefix, because it registered
```

A `~` before a name means the PID was *inferred* from the DDS GUID rather than
reported by the node itself.

## The API

The header is installed with ros2top; `ros2topConfig.cmake` locates it.

```cpp
#include <ros2top/ros2top.hpp>

ros2top::register_node("/my_node");                 // once, at startup
ros2top::heartbeat("/my_node");                     // optional, in your loop
ros2top::unregister_node("/my_node");               // optional, automatic on exit
```

In `CMakeLists.txt`:

```cmake
find_package(ros2top REQUIRED)
find_package(nlohmann_json REQUIRED)

target_link_libraries(your_node nlohmann_json::nlohmann_json)
target_include_directories(your_node PRIVATE ${ros2top_INCLUDE_DIRS})
```

Registrations are written to `~/.ros2top/registry/` — the same place the Python
API uses, so a mixed C++/Python system shows up in one table.

## Troubleshooting

**`ros2top/ros2top.hpp` not found.** The header ships with the Python package;
confirm `pip show ros2top` reports an install, and that `find_package(ros2top)`
resolves. Failing that, point `target_include_directories` at the `include/`
directory of this repository.

**The node does not appear.** Check ros2top's status bar. `Auto✗ register` means
registration is the only way in, so confirm `register_node()` runs. With `Auto✓`
the node should appear either way; verify it with `ros2 node list`.
