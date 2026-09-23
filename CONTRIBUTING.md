# Contributing

## Getting set up

```bash
pip install --user -e ".[viz]"
python3 -m unittest discover -s tests
```

ros2top is a plain pip project, not an ament package — keep it outside a colcon
workspace's `src/`. On Ubuntu 22.04 an editable install needs a newer setuptools
than the system one, pinned below 80 so `colcon-core` keeps working:

```bash
pip install --user "setuptools>=64,<80"
pip install --user --no-build-isolation -e .
```

## Tests

```bash
python3 -m unittest discover -s tests
```

The Qt tests run under `QT_QPA_PLATFORM=offscreen` and skip themselves when the
`viz` extra is not installed, so the suite passes on a headless machine and in a
terminal-only install.

Write the test first. The two bugs that cost the most here — a recording that
captured a third of the graph, and chart curves silently aligned to the wrong
moments — were both found by running the thing, not by reading it, so a change
that cannot be exercised somehow is a change worth being suspicious of.

## How the code is arranged

```text
ros2top/
├── node_monitor.py      # sampling core - PIDs, CPU, RAM, GPU, grouping
├── graph_discovery.py   # finding nodes on the ROS graph
├── node_registry.py     # the registration API
├── command/top.py       # the `ros2 top` ros2cli plugin
├── recording/           # recorder, reader, combined statistics
├── ui/                  # curses terminal UI
└── viz/                 # Qt visualiser (optional extra)
```

One sampling core, three front-ends. `NodeMonitor` is the only thing that talks to
psutil and the ROS graph; the terminal UI, the `--record` path and the Qt app are
all consumers of it. Don't add a second sampler.

**Keep logic out of the drawing code.** Anything worth testing lives where a test
can reach it without a screen: `ui/table_view.py` (sort, filter, selection),
`recording/stats.py` (the combined figures), `viz/source.py` (live versus replay).
The widgets wire those up and little else. This is why the suite runs in about a
second with no display.

## Invariants worth knowing before you change things

- **Sorting and filtering act on process groups, never on individual rows.**
  Composable nodes share a process, and `NodeMonitor.get_node_info_list()` returns
  them grouped under their container in an order the kill path depends on. Follow
  `table_view.build_view()`: group, filter, sort, flatten.
- **Selection is identity-based, not positional.** `resolve_selection()` tracks
  `(pid, name)`. Anything keyed to a row index breaks the moment the table reorders
  under it — which, with live CPU sorting, is constantly.
- **One recorder tick writes every process under a single timestamp.** That is what
  makes combining series across processes plain addition instead of a resampling
  problem. Every combined figure depends on it.
- **CPU is a share of the whole machine, not of one core.** `NodeMonitor` divides by
  the core count, which is why recordings carry `cpu_cores` and the reader refuses
  to guess when it is absent.
- **Combined figures are CPU-only.** GPU utilisation is per-device and does not add
  across processes sharing it; summed RSS double-counts shared pages.
- **Whole-process figures are reported once per group.** Repeating a container's CPU
  on each composed node invites reading three nodes as three times the load.

## Style

Follow what is there. Comments explain *why* — a constraint, a measurement, a
surprise — not what the line already says. Several comments in this codebase record
measurements (discovery timings, for instance); if you change the behaviour they
describe, re-measure rather than delete.
