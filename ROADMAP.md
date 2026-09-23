# Roadmap

What is built and what is next. Design notes for the recorder and visualiser live
in [`docs/specs/2026-09-22-recorder-and-visualiser-design.md`](docs/specs/2026-09-22-recorder-and-visualiser-design.md).

## Built

**Interactive table (terminal UI)**

- [x] Sort by PID, CPU, RAM, GPU or name — `s` cycles, `S` reverses
- [x] Filter as you type with `/`, matching node name or namespace
- [x] Tag processes with `Space`, kill the whole set with one confirmation
- [x] Selection tracked by (PID, name) identity, so it survives sorting,
      filtering and the background refresh
- [x] GPU columns hide themselves when there is no GPU

**Recording**

- [x] `Recorder` writing one row per (tick, PID), every PID in a tick sharing
      one timestamp
- [x] CSV with `#` metadata (core count, node names per PID)
- [x] Reader tolerant of a truncated final line
- [x] `peak combined`, `sum of peaks`, `total CPU-seconds`, time-weighted mean
- [x] `ros2top --record run.csv --pid N` for headless and scripted runs

**Qt visualiser (`ros2top-viz`)**

- [x] Sidebar listing live processes, with filter and select-all
- [x] A tab per selected process: rolling CPU, memory and GPU charts
- [x] Combined tab overlaying the selection plus a summed `Total` line
- [x] The four combined figures along the bottom
- [x] Record the selection to CSV, and replay a recording with the same views
- [x] Optional install extra — the terminal UI never imports Qt

## Next

- [ ] `R` in the terminal UI to record the `Space`-tagged set
- [ ] Per-node drill-down: topics published/subscribed with Hz and bandwidth,
      services, parameters, QoS
- [ ] Thresholds with a visual flag when a process crosses one
- [ ] Node death and respawn detection with a small event log
- [ ] `~/.config/ros2top/config.toml` for default refresh, columns and sort

## Notes for whoever picks this up

- Sorting and filtering act on **groups** (processes), never on individual rows.
  `NodeMonitor.get_node_info_list()` returns composable nodes grouped under their
  container in an order the kill path depends on. New view transforms should
  follow `ui/table_view.build_view()`: group, filter, sort, flatten.
- Selection is identity-based (`resolve_selection()`), not by row index. Anything
  stateful keyed to a row will break the moment the table reorders.
- Combining series across processes is exact only because one recorder tick writes
  every process under a single timestamp. Keep it that way; the alternative is
  resampling.
- Two things only showed up by running against a real graph, both now regression
  tested: node discovery reports a partial set and holds it steady for over a
  second before delivering the rest (so `wait_for_nodes()` has a minimum wait, not
  just a stability check), and `GraphDiscovery` calls `rclpy.init()` on a daemon
  thread, which replaces any signal handler installed before it.
