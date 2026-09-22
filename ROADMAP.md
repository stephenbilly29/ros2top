# ros2top interactive TUI — roadmap

This is a local fork of [`AhmedARadwan/ros2top`](https://github.com/AhmedARadwan/ros2top)
(vendored from its `dev` branch, commit `9bec731`) with a more interactive
terminal UI added on top. This file is the running plan: what's shipped,
what's next, in the order it's being built.

Each phase builds on the last. Table UX comes first because sorting/filtering
is the foundation the later drill-down and history views assume (a stable,
identity-tracked selection).

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

## Notes for whoever picks this up next

- Sorting/filtering operate on **groups** (nodes sharing one PID), never on
  flat rows — `NodeMonitor.get_node_info_list()` groups composable nodes
  under their container in an order the kill path depends on. Any new
  view-transform should follow `table_view.build_view()`'s pattern: group,
  filter, sort, flatten.
- Selection is identity-based (`resolve_selection()` in `table_view.py`), not
  index-based. Any new stateful UI feature (tagging, detail pane) should key
  off `(pid, name)`, not a row number, for the same reason.
