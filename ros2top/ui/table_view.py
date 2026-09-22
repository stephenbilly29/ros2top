#!/usr/bin/env python3
"""
Pure sort/filter/select logic for the nodes table.

Kept free of curses so it can be unit tested directly. Operates on groups
(nodes sharing one PID) rather than flat rows: NodeMonitor.get_node_info_list()
groups composable nodes under their container in a fixed internal order that
the kill path and the CPU/RAM/GPU-shown-once-per-group convention both depend
on, so sorting/filtering must reorder or drop whole groups, never split one.
"""

from typing import List, Optional, Sequence

from ..node_monitor import NodeInfo

# Column name -> key function reading the group's head node (index 0), which
# carries the whole-process CPU/RAM/GPU figures shared by every node in it.
_SORT_KEYS = {
    'pid': lambda n: n.pid,
    'cpu': lambda n: n.cpu_percent,
    'ram': lambda n: n.ram_mb,
    'gpu': lambda n: n.gpu_utilization,
    'name': lambda n: (n.name or '').lower(),
}

# Column name -> the header text that names it, for the sort-direction marker.
# Matched by prefix (not a fixed index) so it still finds the right header
# after GPU columns are dropped by visible_headers().
_COLUMN_HEADER_PREFIX = {
    'pid': 'PID',
    'cpu': '%CPU',
    'ram': 'RAM',
    'gpu': '%GPU',
    'name': 'Node Name',
}

SORT_COLUMNS = ('pid', 'cpu', 'ram', 'gpu', 'name')

# Headers (and their matching row cells) hidden when no GPU is present, since
# "--" in every row for a device that doesn't exist tells the user nothing.
_GPU_COLUMNS = ('GPU#', '%GPU', 'GMEM(MB)')


def group_by_pid(nodes: Sequence[NodeInfo]) -> List[List[NodeInfo]]:
    """Split a NodeMonitor-ordered list into contiguous same-PID groups."""
    groups: List[List[NodeInfo]] = []
    for node in nodes:
        if groups and groups[-1][0].pid == node.pid:
            groups[-1].append(node)
        else:
            groups.append([node])
    return groups


def sort_groups(groups: List[List[NodeInfo]], column: str, ascending: bool
                 ) -> List[List[NodeInfo]]:
    """Sort groups by a column read from each group's head node. Stable."""
    key_fn = _SORT_KEYS.get(column)
    if key_fn is None:
        return groups
    return sorted(groups, key=lambda g: key_fn(g[0]), reverse=not ascending)


def filter_groups(groups: List[List[NodeInfo]], query: str) -> List[List[NodeInfo]]:
    """Keep groups where any node's name contains query (case-insensitive)."""
    if not query:
        return groups
    needle = query.lower()
    return [g for g in groups if any(needle in (n.name or '').lower() for n in g)]


def flatten(groups: List[List[NodeInfo]]) -> List[NodeInfo]:
    """Rejoin groups into the flat row list the table draws."""
    return [node for group in groups for node in group]


def build_view(nodes: Sequence[NodeInfo], column: str, ascending: bool, query: str
               ) -> List[NodeInfo]:
    """Filter then sort, whole groups at a time, and flatten to display rows."""
    groups = group_by_pid(nodes)
    groups = filter_groups(groups, query)
    groups = sort_groups(groups, column, ascending)
    return flatten(groups)


def resolve_selection(view: List[NodeInfo], prev_pid: Optional[int],
                       prev_name: Optional[str], prev_index: int) -> int:
    """
    Find the row a prior selection should land on after sort/filter/refresh.

    Matches by (pid, name) identity rather than trusting the old index, since
    sorting and filtering both reorder or remove rows. Falls back to the old
    index clamped into range when that identity is no longer present (e.g.
    the node died, or a filter now hides it).
    """
    if not view:
        return 0
    for i, node in enumerate(view):
        if node.pid == prev_pid and node.name == prev_name:
            return i
    return max(0, min(prev_index, len(view) - 1))


def decorate_headers(headers: List[str], column: str, ascending: bool) -> List[str]:
    """Append a sort-direction marker to the header of the active column."""
    prefix = _COLUMN_HEADER_PREFIX.get(column)
    if prefix is None:
        return list(headers)
    marker = '^' if ascending else 'v'
    for i, header in enumerate(headers):
        if header.startswith(prefix):
            result = list(headers)
            result[i] = f"{result[i]}{marker}"
            return result
    return list(headers)


def visible_headers(headers: List[str], show_gpu: bool) -> List[str]:
    """Drop the GPU columns from a header list when no GPU is available."""
    if show_gpu:
        return list(headers)
    return [h for h in headers if h not in _GPU_COLUMNS]


def visible_row(row: List, headers: List[str], show_gpu: bool) -> List:
    """Drop a row's GPU cells to match visible_headers(headers, show_gpu)."""
    if show_gpu:
        return row
    return [cell for header, cell in zip(headers, row) if header not in _GPU_COLUMNS]


def toggle_tag(tagged: set, pid: int) -> set:
    """Return a new tagged-PID set with `pid` toggled in or out."""
    result = set(tagged)
    if pid in result:
        result.discard(pid)
    else:
        result.add(pid)
    return result
