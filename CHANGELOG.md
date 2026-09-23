# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Qt visualiser (`ros2top-viz`)** — sidebar of live processes, a tab of rolling
  CPU/memory/GPU charts per selected process, and a Combined tab overlaying the
  selection with a summed `Total` line. Records the selection to CSV and replays a
  recording through the same views. Ships as the optional `viz` extra; the terminal
  UI never imports Qt.
- **Recording** — `ros2top --record run.csv [--pid N] [--interval S]` samples
  headlessly to CSV until interrupted. One row per (tick, process), every process
  in a tick sharing one timestamp.
- **Combined CPU statistics** — peak combined, sum of per-process peaks, total
  CPU-seconds and a time-weighted mean, over a recording or a live session.
- **Sortable, filterable table** in the terminal UI — `s`/`S` to sort by
  PID/CPU/RAM/GPU/name, `/` to filter by name or namespace, `Space` to tag
  processes and `k` to kill the tagged set in one confirmation.
- GPU columns hide themselves when no GPU is present.

### Fixed

- The combined figures now state the period they describe. Live and replay carried
  identical labels over different spans — the live summary covered only the chart
  window while replay covered the whole file.
- Chart curves share one time base. Each was previously re-based on its own first
  sample, sliding processes discovered later against the wrong moments of the others.
- The kill dialog paints an opaque panel. It filled its background with a
  foreground-on-default colour pair, which draws nothing, leaving the table legible
  through the dialog text.
- Node discovery is allowed to settle before a recording fixes its PID set. The
  graph reports a partial set and holds it steady for over a second before
  delivering the rest, so a stability check alone captured a fraction of the system.
- `SIGINT`/`SIGTERM` close a recording cleanly. `GraphDiscovery` initialises rclpy
  on a daemon thread, which replaced handlers installed before it, so Ctrl-C killed
  the process with the file still open.
- Table selection survives sorting and filtering — it is tracked by (PID, name)
  identity rather than by row position.

### Removed

- `requirements.txt`, which only repeated the dependencies declared in
  `pyproject.toml`.

## [0.1.3]

- Removed the hard dependency on ROS 2 being present to start ros2top.

## [0.1.2]

- README improvements.

## [0.1.1]

- Added usage examples.

## [0.1.0]

- Initial release: node monitoring with CPU, RAM and GPU usage, a curses
  interface, command line options, and the node registration API.
