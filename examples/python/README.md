# Python example

`example_node.py` is a ROS 2 node that registers itself with ros2top, so it
appears in the monitor with its real PID and its own start time.

Registration is only *required* on middleware whose DDS GUID does not carry the
process id — `rmw_zenoh_cpp` and Cyclone DDS. Under Fast DDS (the ROS 2 default)
ros2top finds nodes on its own; registering is still more precise, and lets a node
attach metadata.

## Run it

```bash
source /opt/ros/<distro>/setup.bash
python3 example_node.py
```

Then, in another terminal:

```bash
ros2top          # the node appears without the `~` prefix, because it registered
```

A `~` before a name means the PID was *inferred* from the DDS GUID rather than
reported by the node itself.

## What it does

```python
import ros2top

ros2top.register_node('/example_node', {
    'description': 'What this node is for',
    'type': 'demo',
})

ros2top.heartbeat('/example_node')      # optional, in your main loop

ros2top.unregister_node('/example_node')  # optional - automatic on exit
```

- **`register_node(name, metadata=None)`** — states this process's PID for the
  given node name. Call once at startup.
- **`heartbeat(name)`** — marks the registration as fresh. Optional; stale
  registrations are cleaned up on their own.
- **`unregister_node(name)`** — removes it. Optional: registrations are cleaned
  up when the process exits.

Registrations live in `~/.ros2top/registry/`.

## Several nodes in one process

Register each by name. They share the process, so ros2top groups them under it
and reports the CPU, RAM and GPU once — those are whole-process figures and
cannot be split per node.

```python
ros2top.register_node('/camera_driver')
ros2top.register_node('/camera_processor')
```

## Troubleshooting

**The node does not appear.** Check the status bar. `Auto✗ register` means your
middleware does not expose PIDs, so registration is the only way in — confirm
`register_node()` is actually being called. With `Auto✓` the node should appear
either way; verify it is running with `ros2 node list`.

**`ModuleNotFoundError: ros2top`.** Install it into the same interpreter that runs
your node: `pip install ros2top`.
