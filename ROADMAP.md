# ros2top interactive TUI — roadmap

This is a local fork of [`AhmedARadwan/ros2top`](https://github.com/AhmedARadwan/ros2top)
(vendored from its `dev` branch, commit `9bec731`) with a more interactive
terminal UI added on top. This file is the running plan: what's shipped,
what's next, in the order it's being built.

Each phase builds on the last. Table UX came first because sorting/filtering
is the foundation the later drill-down and history views assume (a stable,
identity-tracked selection).

**Current build order:** Phase 1 shipped; Phases 5 and 6 (recording and the GUI
visualiser) are being built next. Phases 2–4 are deferred behind them — recording
turned out to be the more useful thing to have first, and Phase 3's history
graphs largely fall out of Phase 6 once the data is being recorded anyway.

## Phase 1 — Table UX (done)

Foundation: sortable, filterable, multi-selectable process table, without
breaking the existing component-container grouping or kill-by-identity safety.

- [x] Sort by column (PID / %CPU / RAM / GPU / Name), `s` cycles, `S` reverses,
      header shows a `^`/`v` marker
- [x] Selection stable across sort/refresh/filter, tracked by (PID, name)
      identity rather than row index
- [x] Filter-as-you-type (`/`), matches node name or namespace, whole
      component-container groups kept together
- [x] Multi-select (`Space` tags a process) + batch kill dialog
- [x] GPU columns auto-hide when no GPU is present, width budget recalculated

Implementation: `ros2top/ui/table_view.py` (pure, curses-free grouping/sort/
filter logic) + `ros2top/ui/terminal_ui.py` wiring. Tests:
`tests/test_table_view.py`, `tests/test_terminal_ui_interactions.py`.

## Phase 2 — ROS introspection depth (next)

Turns the monitor into a debugging tool, not just a resource gauge.

- [ ] Per-node detail pane (`Enter`/`→` on a row): topics published/
      subscribed with type, services, actions, parameters
- [ ] Live Hz/bandwidth for a selected topic (like `ros2 topic hz`/`bw`, inline)
- [ ] QoS profile display per topic, with mismatch warning
- [ ] Mini TF-tree view scoped to frames the selected node touches

## Phase 3 — History & alerting

- [ ] Per-node CPU/RAM sparkline (last N samples), shown in an expanded row
      or the detail pane
- [ ] Configurable thresholds with visual flag + optional log line on breach
- [ ] Node death/respawn detection with a small event log (last 20 events)

## Phase 4 — Infra/config (threaded through, not a separate release)

- [ ] `~/.config/ros2top/config.toml` for default refresh rate, thresholds,
      visible columns, sort
- [ ] Tests for the introspection/history logic, same pure-module pattern as
      Phase 1's `table_view.py`

## Phase 5 — Recording

Sample a selected set of PIDs over time to a CSV, so a run can be analysed
after the fact instead of only watched live.

- [x] `Recorder` in `ros2top/recording/` — takes `NodeInfo` batches, writes one
      row per (timestamp, pid); every PID in a tick shares one timestamp
- [x] CSV format with `#` metadata header (cpu core count, node names per PID)
- [x] `RecordingReader` — CSV back into per-PID series, tolerant of a
      truncated final line
- [x] `stats.py` — peak combined CPU, sum of per-PID peaks, total CPU-seconds,
      time-weighted mean combined
- [x] `ros2top --record run.csv --pid N` for headless/scripted runs
- [ ] `R` in the TUI records the `Space`-tagged set

Two things only running it revealed, both now handled and regression-tested:

- **Discovery plateaus.** The graph reports a partial set, holds it steady for
  over a second, then delivers the rest (measured: 9 nodes at 1.1s, still 9 at
  1.6s, 39 at 2.3s). Any settle heuristic short enough to feel responsive sits
  entirely inside that plateau and records a third of the system. `wait_for_nodes()`
  therefore has a minimum wait as well as a stability window.
- **rclpy steals the signal handlers.** `GraphDiscovery` calls `rclpy.init()` on
  a daemon thread, so it lands *after* `NodeMonitor.__init__` returns and replaces
  any handler installed before it. Ctrl-C then killed the process outright and the
  recording was never closed. Handlers are now installed after discovery settles.

## Phase 6 — GUI visualiser (`ros2top-viz`)

A PyQt5 + pyqtgraph desktop app: live rolling charts, replay of recordings,
and combined-CPU numbers for a selected set.

- [ ] Sidebar listing live ROS 2 nodes with checkboxes, plus Load-recording
- [ ] One tab per selected PID: rolling CPU / RAM / GPU charts
- [ ] `source.py` abstraction so plots don't know live from replay
- [ ] Combined tab: all selected PIDs overlaid, with the four CPU numbers
- [ ] Optional install extra: `pip install "ros2top[viz]"` — the TUI never
      imports Qt, so a missing PyQt5 can't break `ros2top`

Full design: [`docs/specs/2026-09-22-recorder-and-visualiser-design.md`](docs/specs/2026-09-22-recorder-and-visualiser-design.md)

## Notes for whoever picks this up next

- Sorting/filtering operate on **groups** (nodes sharing one PID), never on
  flat rows — `NodeMonitor.get_node_info_list()` groups composable nodes
  under their container in an order the kill path depends on. Any new
  view-transform should follow `table_view.build_view()`'s pattern: group,
  filter, sort, flatten.
- Selection is identity-based (`resolve_selection()` in `table_view.py`), not
  index-based. Any new stateful UI feature (tagging, detail pane) should key
  off `(pid, name)`, not a row number, for the same reason.
