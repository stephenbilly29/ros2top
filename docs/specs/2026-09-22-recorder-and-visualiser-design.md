# ros2top recorder + live visualiser — design

Date: 2026-09-22
Status: implemented, except the terminal UI's `R` key — see [ROADMAP](../../ROADMAP.md)
Covers: the CSV recorder and the Qt visualiser

Kept as the record of *why* these are shaped the way they are. Where the
implementation departed from the plan, this document says so rather than being
quietly rewritten to match.

## Problem

ros2top shows resource usage *now*. There is no way to answer "what did
`/controller_server` and `/planner_server` actually cost me over that 10-minute
mission?", to compare two runs, or to watch a node's CPU trend as a curve rather
than a number that jumps every second.

This adds two things:

1. **Recording** — sample a chosen set of PIDs over time to a CSV.
2. **A GUI visualiser** — live rolling charts for selected nodes, replay of
   recorded runs, and a combined-CPU summary for a selected set.

## Goals

- Record uptime, CPU, RAM, GPU and node name for one or more selected PIDs.
- Visualise those series live, and replay them from file, in a desktop GUI.
- Report, for a selected set of PIDs over a run: peak combined CPU, sum of
  per-PID peaks, total CPU time, and mean combined CPU.
- Ship as one installable open-source project; the GUI must be optional so
  terminal-only users are not forced to install Qt.

## Non-goals

- Distributed/multi-machine recording. PIDs are local by definition.
- Alerting or thresholds (see the roadmap).
- Replacing `rosbag2`. This records *process resource usage*, not ROS messages.

## Architecture

One recorder in the core; three front-ends drive it. The plotting layer never
learns whether its data is live or from a file.

```
NodeMonitor (existing)  ──List[NodeInfo]──▶  Recorder  ──▶  run_*.csv
                                                              │
        ┌── TUI  (R key)  ──┐                                 ▼
  drives├── CLI  (--record) ┤                         RecordingReader
        └── GUI  (sidebar)  ┘                                 │
                                                              ▼
                                                      stats.combined_cpu_stats()
```

### Central invariant

**One recorder tick writes every tracked PID with the same timestamp.**

Combining series across PIDs is therefore exact — no resampling, no
interpolation, no nearest-neighbour matching. Every cross-PID statistic in this
design depends on this property, so `Recorder.sample()` takes one timestamp for
the whole batch rather than reading the clock per row.

### Sample spacing is never assumed uniform

The TUI redraws on its own interval, the GUI has a configurable one, and both
can stall. Every time-integrated statistic uses the recorded timestamps with
trapezoidal integration. No code may assume a fixed `dt`.

## Data format

CSV with `#` comment metadata, one row per (timestamp, pid).

```
# ros2top-recording v1
# started_utc=2026-09-22T14:33:01Z
# host=mglocadmin-ThinkStation-P350
# cpu_cores=16
# pid=2939270 node_count=3 node_names=/rviz;/rviz_navigation_dialog;/transform_listener_impl_5d89
# pid=2939264 node_count=1 node_names=/static_tf_microgenesis
timestamp,elapsed_s,pid,node_name,node_count,uptime_s,cpu_percent,ram_mb,gpu_index,gpu_percent,gpu_mem_mb
1790000581.412,0.000,2939270,/rviz,3,1802.4,6.4,454.2,-1,,
1790000582.415,1.003,2939270,/rviz,3,1803.4,6.1,454.9,-1,,
```

| Column | Type | Meaning |
|---|---|---|
| `timestamp` | float | Unix epoch seconds, same for every row in a tick |
| `elapsed_s` | float | Seconds since recording start |
| `pid` | int | Process id |
| `node_name` | str | The group's head node (the container, for composable nodes) |
| `node_count` | int | Nodes sharing this PID; >1 means a component container |
| `uptime_s` | float | Node uptime at this sample |
| `cpu_percent` | float | **Percent of the whole machine**, not of one core (see below) |
| `ram_mb` | float | RSS in MB |
| `gpu_index` | int | GPU device, `-1` if none |
| `gpu_percent` | float | Device utilisation, empty when no GPU |
| `gpu_mem_mb` | float | Process GPU memory, empty when no GPU |

Rationale for CSV: matches the existing `telemetry_visualizer` lineage in this
workspace, is readable without tooling, opens in Excel, and `pandas.read_csv(p,
comment='#')` just works. That matters for an artifact meant to be published.

### Why `cpu_cores` is in the metadata

`NodeMonitor` normalises CPU by core count (`cpu_pct = raw_cpu / cores`), so a
`cpu_percent` of 100 means *every core saturated*, not one core busy. Core-seconds
cannot be reconstructed without knowing the core count, so it is recorded. A
reader that ignores it will silently produce wrong totals.

### Composable nodes

Nodes loaded into one container share a PID, and CPU/RAM/GPU are process-wide —
they cannot be split per node. Rows therefore key on PID and carry the head
node's name plus `node_count`; the full node list goes in the header once rather
than being repeated in every sample.

## Components

### `ros2top/recording/recorder.py`

```python
class Recorder:
    def __init__(self, path, pids, cores, node_names): ...
    def sample(self, nodes: Sequence[NodeInfo], now: float | None = None) -> int
    def close(self) -> None
    row_count: int
    elapsed: float
```

Takes `NodeInfo` objects in, writes CSV out. No psutil, no ROS, no curses —
so it is testable with synthetic input. Supports the context-manager protocol.
Writes and flushes per tick so a killed process still leaves a usable file.

### `ros2top/recording/reader.py`

```python
@dataclass
class Series:
    pid: int; node_name: str; node_count: int
    t: list[float]; cpu: list[float]; ram: list[float]
    gpu: list[float]; gpu_mem: list[float]

@dataclass
class Recording:
    cores: int; started_utc: str; duration_s: float
    series: dict[int, Series]

def read_recording(path) -> Recording
```

Tolerates a truncated final line (recorder killed mid-write) by discarding it.

### `ros2top/recording/stats.py`

Pure functions over a `Recording`. Same pattern as `ui/table_view.py`: all logic
that deserves a test lives where a test can reach it without a GUI.

```python
@dataclass
class CombinedStats:
    peak_combined_pct: float
    sum_of_peaks_pct: float
    total_cpu_seconds: float
    mean_combined_pct: float
    duration_s: float

def combined_cpu_stats(recording, pids=None) -> CombinedStats
```

Definitions, over the union of all timestamps in the selected PIDs:

- `combined(t) = Σ_pid cpu_percent(pid, t)`, where a PID with no sample at `t`
  contributes **0** (it had died, so it was using nothing).
- `peak_combined_pct = max_t combined(t)` — the most the set ever drew at one
  moment. This actually happened.
- `sum_of_peaks_pct = Σ_pid max_t cpu_percent(pid, t)` — worst case if every
  node peaked together. May never have occurred; useful as a budget ceiling.
- `total_cpu_seconds = ∫ (combined(t)/100 × cores) dt`, trapezoidal.
- `mean_combined_pct = ∫ combined(t) dt / duration_s`, trapezoidal — time-weighted,
  not the arithmetic mean of samples, because spacing is not uniform.

Worked example used as a test fixture — two nodes over 60s, A peaking at t=10,
B at t=40:

| | A | B | combined |
|---|---|---|---|
| t=10s | 80% | 5% | **85%** |
| t=40s | 5% | 70% | 75% |

`peak_combined = 85`, `sum_of_peaks = 150`. The 150 never occurred.

### Combined statistics are CPU-only

Deliberately. GPU *utilisation* is a per-device figure and is not additive
across processes sharing that device — summing it would produce a number that
means nothing. Summed RSS double-counts shared pages. CPU percent is the only
one of the three that sums honestly, and it is what was asked for.

### `ros2top/viz/` — the GUI (`ros2top-viz`)

| Module | Responsibility |
|---|---|
| `app.py` | QApplication bootstrap, arg parsing, dependency-missing message |
| `main_window.py` | Wires sidebar ↔ tabs ↔ summary; owns the QTimer |
| `sidebar.py` | Live/Recording mode switch, node list with checkboxes, Record button, Load-recording, combined checkbox |
| `source.py` | `LiveSource` (NodeMonitor + QTimer) and `ReplaySource` (Recording) behind one interface |
| `plot_tab.py` | One tab per selected PID: CPU, RAM, GPU rolling charts |
| `summary_panel.py` | The four combined numbers |

`source.py` is what keeps the plots ignorant of origin: both sources expose the
same "give me each PID's series so far" call, so `plot_tab.py` has no live/replay
branching in it.

```
┌──────────────┬───────────────────────────────────┐
│ SIDEBAR      │ [/rviz] [/gazebo] [Combined]      │
│ ◉ Live       │ ┌───────────────────────────────┐ │
│ ○ Recording  │ │ CPU %    rolling 60s window   │ │
│              │ └───────────────────────────────┘ │
│ ☑ /rviz      │ ┌───────────────────────────────┐ │
│ ☑ /gazebo    │ │ RAM MB                        │ │
│ ☐ /ekf_node  │ └───────────────────────────────┘ │
│              │ ┌───────────────────────────────┐ │
│ [ Record ● ] │ │ GPU %                         │ │
│ [ Load CSV ] │ └───────────────────────────────┘ │
│              │ Peak 85% │ Sum 150% │ 42.3 core-s │
│ ☑ Combined   │ Mean 31.2%                        │
└──────────────┴───────────────────────────────────┘
```

One tab per selected PID. Ticking **Combined** adds a `Combined` tab overlaying
all selected PIDs on one CPU chart, with the four numbers beneath it. In live
mode the numbers cover the session so far; in replay, the whole file.

Live plots roll over `window_s` (default 60s, configurable), but samples are
retained for `history_s` (default 1h) and the plot takes the tail off that.

This split was not in the first implementation and the omission was a real bug:
serving both from one trimmed buffer made the live summary mean "over the last
minute" while the identical labels in replay meant "over the whole file". The
summary therefore also states the period it covers, and marks it when the history
cap has truncated it. History is bounded rather than unlimited because the window
is meant to be left open.

Replay shows the full series and relies on pyqtgraph's built-in pan/zoom rather
than a custom scrubber.

### Front-end integration

- **CLI**: `ros2top --record run.csv --pid 2939270 --pid 2939264`. Headless, no
  curses, for scripted and CI runs. Omitting `--pid` records every discovered node.
- **TUI**: `R` starts/stops recording the `Space`-tagged set (tagging already
  exists as of the Phase 1 commit). Footer shows `REC ● 3 pids 00:42`.
- **GUI**: sidebar checkboxes select, Record button starts/stops.

## Error handling

| Situation | Behaviour |
|---|---|
| Node dies mid-recording | Its rows stop. Reader returns a shorter series for it; stats treat it as 0 thereafter |
| Unwritable path / disk full | Recorder raises once on open; front-end surfaces the message and keeps monitoring. Recording never takes the monitor down |
| Process killed mid-write | Partial final line discarded by the reader |
| CSV missing `cpu_cores` | Reader raises with a clear message rather than guessing — a wrong core count silently corrupts every total |
| PyQt5/pyqtgraph absent | `ros2top-viz` prints `pip install "ros2top[viz]"` and exits 1. No traceback |
| No GPU present | `gpu_*` columns written empty; GUI hides the GPU chart |

## Testing

Everything except the Qt widgets is pure and gets real unit tests.

- `test_recorder.py` — header contents, one row per tracked PID per tick, shared
  timestamp within a tick, PIDs outside the tracked set ignored, flush-per-tick.
- `test_reader.py` — round trip (record synthetic → read back → assert equal),
  truncated last line, `#` metadata parsing, missing `cpu_cores` raises.
- `test_stats.py` — the 80/5, 5/70 worked example; non-uniform spacing;
  a PID that dies part-way; single PID; empty selection.
- `test_viz_smoke.py` — under `QT_QPA_PLATFORM=offscreen`: construct the main
  window, feed it a small recording, switch tabs, tick Combined, assert no
  exception. Skipped when PyQt5 is unavailable.

Tests are `unittest.TestCase` subclasses, matching the existing suites that
actually run here (`python3 -m unittest discover -s tests`).

## Packaging

```toml
[project.optional-dependencies]
viz = ["PyQt5>=5.15", "pyqtgraph>=0.12", "numpy>=1.20"]

[project.scripts]
ros2top = "ros2top.main:main"
ros2top-viz = "ros2top.viz.app:main"
```

Core install stays dependency-light (`psutil`, `pynvml`); `pip install
"ros2top[viz]"` adds the GUI stack. `ros2top/viz/` is never imported by the TUI
path, so a missing PyQt5 cannot break `ros2top`.

## Build order

Each phase is independently useful and shippable.

| Phase | Deliverable |
|---|---|
| **A** | `recording/` — recorder, reader, stats, `--record` CLI, full tests. No GUI. Scriptable recording works |
| **B** | TUI `R` key recording the tagged set |
| **C** | GUI: sidebar, live rolling plots, one tab per PID |
| **D** | GUI: load recording (replay) + Combined tab and summary numbers |
| **E** | Packaging extra, README, screenshots, release prep |

## Built

Phases A, C, D and E are done, along with the packaging extra. Phase B (`R` in the
terminal UI) is not. Two faults that only appeared when run against a live graph
are recorded in ROADMAP.md, along with a third — the window/history confusion
described above — that only appeared when the two modes were compared side by side.

## Decisions taken

| Decision | Chosen | Why not the alternative |
|---|---|---|
| Where it lives | One repo, `[viz]` extra | A separate repo means two things to version and release, and the recorder *is* the sampling loop |
| GUI stack | PyQt5 + pyqtgraph | matplotlib degrades on continuously-updating streams; a web UI is a poor fit for a desktop process monitor; C++ Qt would reimplement the Python sampling |
| Format | CSV + `#` metadata | JSONL is bigger and not spreadsheet-friendly; SQLite is opaque without tooling |
| Selection | TUI tags + GUI sidebar + CLI flags | All three drive one `Recorder`; the GUI sidebar is required by the design anyway, and TUI tagging already exists |
| Combined metric | All four numbers | They answer different questions and are computed from the same data at no extra cost |
