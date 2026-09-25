# ros2top

Resource monitoring for ROS 2 processes — a terminal monitor, a CSV recorder, and
a Qt visualiser, sharing one sampling core.

- **`ros2top`** — `htop` for the ROS graph: per-node CPU, RAM and GPU in the terminal
- **`ros2top --record`** — sample a chosen set of processes to CSV, headless
- **`ros2top-viz`** — Qt app: live charts, recording playback, combined-CPU figures

## Why

`ros2 node list` tells you what is running. It does not tell you that your planner
is eating a core, which container the costmap actually lives in, or what the whole
navigation stack cost over a ten-minute mission. ros2top answers those.

It understands **component containers**: nodes composed into one process share that
process's CPU, RAM and GPU, so they are grouped under their container and the usage
is reported once rather than counted N times over.

## Install

```bash
pip install ros2top             # terminal UI + recorder
pip install "ros2top[viz]"      # adds the Qt visualiser
```

On Ubuntu 24.04 and newer the system interpreter is externally managed (PEP 668):

```bash
pip install --break-system-packages ros2top
# or a venv that can still see the ROS 2 packages:
python3 -m venv --system-site-packages ~/.venvs/ros2top
source ~/.venvs/ros2top/bin/activate && pip install ros2top
```

### From source

```bash
git clone <this repo> && cd ros2top
pip install --user -e .
```

It is a plain pip project, not an ament package — keep it outside a colcon
workspace's `src/`, and no `colcon build` is involved. On Ubuntu 22.04 (pip 22,
setuptools too old for PEP 660) an editable install needs a nudge:

```bash
pip install --user "setuptools>=64,<80"    # <80 keeps colcon-core happy
pip install --user --no-build-isolation -e .
```

**Requirements:** Python 3.8+, `psutil`, `pynvml`. GPU figures need NVIDIA drivers.
The Qt extra adds `PyQt5`, `pyqtgraph`, `numpy`. Tested on Humble, Jazzy, Kilted
and Rolling.

## Terminal UI

```bash
ros2top          # standalone
ros2 top         # same program, via the ros2 CLI
```

| Key | Action |
| --- | --- |
| `↑` `↓`, `Home`/`End` | Move the selection |
| `s` / `S` | Cycle sort column (PID/CPU/RAM/GPU/name) / reverse it |
| `/` | Filter by node name or namespace as you type; `Enter` applies, `Esc` clears |
| `Space` | Tag a process for batch actions |
| `k` | Kill the selection — or every tagged process at once |
| `y` / `n`, `Esc` | Confirm / cancel |
| `p`, `r`, `+`/`-` | Pause, force refresh, sample faster/slower |
| `h`, `q` | Help, quit |

Filtering keeps whole container groups together, so a match on a composed node
still shows you the process it lives in.

Tagging several processes and pressing `k` confirms them as one batch. Killing any
node in a container ends the whole process, and the dialog says so.

### Options

```bash
ros2top --refresh 2           # node-list refresh interval
ros2top --no-auto-discovery   # only nodes that registered themselves
```

## Recording

Capture what a set of processes costs over a run, then analyse it afterwards.
Headless — no curses — so it works over ssh, in a container and under `timeout`.

```bash
ros2top --record run.csv                        # everything discovered
ros2top --record run.csv --pid 1234 --pid 5678  # just these
ros2top --record run.csv --interval 0.5         # twice a second
timeout 60 ros2top --record run.csv             # fixed-length run
```

Ctrl-C or SIGTERM closes the file cleanly; rows are flushed every tick, so even a
recording that is killed outright stays readable. ros2top waits a few seconds for
node discovery to settle before fixing the PID set — the graph arrives in batches,
and sampling too early captures a fraction of the system. Use `--pid` when you want
an exact set regardless.

### The file

Plain CSV with `#` metadata, so `pandas.read_csv(path, comment='#')` just works:

```
# ros2top-recording v1
# started_utc=2026-09-22T11:27:42+00:00
# cpu_cores=16
# pid=3496 node_count=2 node_names=/smoother_server;/transform_listener_impl_59e07
timestamp,elapsed_s,pid,node_name,node_count,uptime_s,cpu_percent,ram_mb,gpu_index,gpu_percent,gpu_mem_mb
1790076462.890,0.000,3496,/smoother_server,2,7929.170,0.3,38.4,-1,,
```

One row per (tick, process), every process in a tick sharing one timestamp — which
is what makes combining series across processes exact rather than a resampling
problem. `cpu_percent` is a share of the **whole machine**, not of one core, which
is why the core count is in the header; a reader that ignores it will produce wrong
totals, so ros2top's own reader refuses to guess.

### Reading it back

```python
from ros2top.recording.reader import read_recording
from ros2top.recording.stats import combined_cpu_stats

rec = read_recording('run.csv')
s = combined_cpu_stats(rec)              # or pids=[3496, 3500]

s.peak_combined_pct     # most the set ever drew at one instant
s.sum_of_peaks_pct      # worst case, if every process peaked together
s.total_cpu_seconds     # total work done, in core-seconds
s.mean_combined_pct     # time-weighted mean
```

`peak_combined` and `sum_of_peaks` differ whenever processes peak at different
moments: the first actually happened, the second is an upper bound that may
describe a moment that never occurred. Both are useful; neither alone is "the"
answer. Combined figures are CPU-only — GPU utilisation is per-device and does not
add across processes, and summed RSS double-counts shared pages.

## Qt visualiser

```bash
ros2top-viz                  # live graph
ros2top-viz run.csv          # open a recording
ros2top-viz --window 120     # show two minutes on the charts
ros2top-viz --history 7200   # keep two hours behind the figures
```

Tick processes in the sidebar; each opens as a tab with rolling CPU, memory and GPU
charts. **Combined CPU of selection** adds an overlay of all of them plus a summed
`Total` line, and fills in the four figures along the bottom.

The charts and the figures cover different spans on purpose: the charts roll over
`--window`, while the figures describe the session so far (`--history`, capped so a
window left open all day cannot grow without bound). The summary says which period
it is reporting, so a live figure is never mistaken for a whole-run one.

`Record` writes the ticked processes to CSV; `Open recording…` replays one, with the
same charts and the same summary.

`Clear history` discards the samples collected so far and starts the charts and the
figures again from that moment. The figures only ever ratchet upwards — one spike
during startup owns `peak combined` for the rest of the session — so this is how you
measure a run without restarting the app. The selection and its tabs stay put, and a
recording in progress keeps running with its file untouched.

## How nodes are found

Showing a node's usage needs its **PID**, which the ROS graph does not publish.
Two mechanisms fill the gap:

**Automatically.** On middleware whose DDS GUID encodes the process id — Fast DDS,
the ROS 2 default — ros2top recovers the mapping from the graph alone. These nodes
are shown with a `~` prefix, because the PID is *inferred* rather than reported.

**By registration.** A node that calls `register_node()` states its PID directly.
This is required on middleware that does not carry it (`rmw_zenoh_cpp`, Cyclone DDS)
and is more precise everywhere — registered nodes report their own start time and
can attach metadata.

```python
import ros2top
ros2top.register_node('/my_node', {'description': 'optional metadata'})
ros2top.heartbeat('/my_node')        # optional
ros2top.unregister_node('/my_node')  # optional, automatic on exit
```

```cpp
#include <ros2top/ros2top.hpp>
ros2top::register_node("/my_node");
```

Working examples: [Python](examples/python/README.md), [C++](examples/cpp/README.md).
Registrations live in `~/.ros2top/registry/` and are cleaned up automatically.

The status bar says which applies, so an empty table is never a mystery:

```text
ROS2✓ | RMW:fastrtps | Auto✓ | Nodes:39      # discovered automatically
ROS2✓ | RMW:zenoh | Auto✗ register | Nodes:0 # registration required
```

## Troubleshooting

**Nodes missing.** Check the status bar first. `Auto✗ register` means your
middleware does not expose PIDs — nodes must register. With `Auto✓`, confirm the
node is running; nodes on other machines are skipped deliberately (their PID is
meaningless locally), as is any node whose PID cannot be pinned down unambiguously,
since showing the wrong process is worse than showing none.

**No GPU columns.** They hide themselves when no GPU is present. Otherwise check
the NVIDIA drivers and `pynvml`.

**`ros2top-viz` says the GUI extra is missing.** `pip install "ros2top[viz]"`.

**`pip install` succeeded but `ros2top` is missing.** `pip show ros2top` reporting
`UNKNOWN 0.0.0` means pip was too old to read `pyproject.toml`: upgrade pip and
reinstall.

## Development

```bash
pip install --user -e ".[viz]"
python3 -m unittest discover -s tests     # GUI tests run offscreen, and skip
                                          # themselves without the viz extra
```

Layout:

```text
ros2top/
├── node_monitor.py      # sampling core - PIDs, CPU, RAM, GPU, grouping
├── graph_discovery.py   # finding nodes on the ROS graph
├── node_registry.py     # the registration API
├── command/top.py       # the `ros2 top` ros2cli plugin
├── recording/           # recorder, reader, combined statistics
└── ui/ and viz/         # the curses TUI and the Qt app
```

Logic worth testing is kept out of the drawing code: `ui/table_view.py`
(sort/filter/selection), `recording/stats.py` (the combined figures) and
`viz/source.py` (live vs replay) are all plain functions over plain data, and the
widgets only wire them up.

[CONTRIBUTING.md](CONTRIBUTING.md) covers the invariants worth knowing before
changing things; [CHANGELOG.md](CHANGELOG.md) records what has changed, and
[ROADMAP.md](ROADMAP.md) what is planned.

## License

MIT — see [LICENSE](LICENSE).
