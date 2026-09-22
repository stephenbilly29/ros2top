#!/usr/bin/env python3
"""
Write a selected set of PIDs' resource usage to CSV over time.

Takes NodeInfo batches in and writes rows out - no psutil, no ROS, no curses -
so the TUI, the CLI and the GUI can all drive the same recorder, and so this
is testable with synthetic input.
"""

import datetime
import os
import socket
import time
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from ..node_monitor import NodeInfo

FORMAT_VERSION = 1

COLUMNS = (
    'timestamp', 'elapsed_s', 'pid', 'node_name', 'node_count', 'uptime_s',
    'cpu_percent', 'ram_mb', 'gpu_index', 'gpu_percent', 'gpu_mem_mb',
)


def select_pids(nodes: Sequence[NodeInfo],
                requested: Optional[Iterable[int]] = None) -> List[int]:
    """
    Which PIDs to record: everything discovered, or the requested subset.

    A requested PID that isn't running is dropped rather than recorded as an
    empty column, so the file only ever describes processes that existed.
    """
    live = []
    for node in nodes:
        if node.pid not in live:
            live.append(node.pid)
    if requested is None:
        return live
    wanted = set(requested)
    return [pid for pid in live if pid in wanted]


def wait_for_nodes(poll, settle_polls: int = 3, timeout_s: float = 10.0,
                   interval: float = 0.25, min_wait_s: float = 3.0,
                   sleep=time.sleep, clock=time.monotonic) -> List[NodeInfo]:
    """
    Poll until the discovered node count settles, then return the nodes.

    Nodes arrive from the graph over a second or two, so taking the first
    non-empty result would freeze the recording's PID set around whichever
    handful arrived first and silently miss the rest of the system.

    Stability alone is not enough either: discovery is observed to report a
    partial set, hold it steady for more than a second, and only then deliver
    the remainder (measured on a Nav2 graph: 9 nodes at 1.1s, still 9 at 1.6s,
    then 39 at 2.3s). A settle window short enough to be responsive will sit
    entirely inside that plateau. `min_wait_s` therefore sets a floor on how
    early any answer is accepted, and `timeout_s` a ceiling for a graph that
    never settles because nodes are still starting.

    There is no completion signal from the graph, so this is a heuristic by
    nature; `--pid` is the escape hatch when the exact set matters.
    """
    started = clock()
    previous = poll()
    stable = 0
    while clock() - started < timeout_s:
        sleep(interval)
        current = poll()
        if current and len(current) == len(previous):
            stable += 1
            if stable >= settle_polls and clock() - started >= min_wait_s:
                return current
        else:
            stable = 0
        previous = current
    return previous


def node_names_by_pid(nodes: Sequence[NodeInfo]) -> Dict[int, List[str]]:
    """
    Every node name grouped under the PID hosting it, order preserved.

    NodeMonitor lists a container ahead of the nodes composed into it, so the
    first name in each group is the group head - which is what rows record.
    """
    grouped: Dict[int, List[str]] = {}
    for node in nodes:
        grouped.setdefault(node.pid, []).append(node.name)
    return grouped


class Recorder:
    """
    Append one row per (tick, tracked PID) to a CSV.

    Every row written in one `sample()` call carries the same timestamp. Cross-PID
    combination downstream is then plain addition at each timestamp rather than a
    resampling problem, so do not move the clock read inside the per-row loop.
    """

    def __init__(self, path: str, pids: Iterable[int], cores: int,
                 node_names: Mapping[int, Sequence[str]]):
        self.path = path
        self.pids = set(pids)
        self.cores = cores
        self._row_count = 0
        self._t0: Optional[float] = None
        self._last: Optional[float] = None

        # Opened eagerly so an unwritable path fails now, at the point the user
        # asked to record, rather than silently at the first sample.
        self._fh = open(path, 'w')
        self._write_header(node_names)

    def _write_header(self, node_names: Mapping[int, Sequence[str]]):
        started = datetime.datetime.now(datetime.timezone.utc)
        self._fh.write(f"# ros2top-recording v{FORMAT_VERSION}\n")
        self._fh.write(f"# started_utc={started.isoformat(timespec='seconds')}\n")
        self._fh.write(f"# host={socket.gethostname()}\n")
        # cpu_percent is machine-relative, not core-relative, so a reader cannot
        # turn it into core-seconds without this.
        self._fh.write(f"# cpu_cores={self.cores}\n")
        for pid in sorted(self.pids):
            names = list(node_names.get(pid, ()))
            if not names:
                continue
            self._fh.write(f"# pid={pid} node_count={len(names)} "
                           f"node_names={';'.join(names)}\n")
        self._fh.write(','.join(COLUMNS) + '\n')
        self._fh.flush()

    def sample(self, nodes: Sequence[NodeInfo], now: Optional[float] = None) -> int:
        """
        Write one row for each tracked PID present in `nodes`.

        Returns the number of rows written. Nodes sharing a PID (composable nodes
        in a container) produce a single row headed by the first of them, which is
        the container itself: the CPU/RAM/GPU figures are process-wide and would be
        counted N times over if every node got its own row.
        """
        if now is None:
            now = time.time()
        if self._t0 is None:
            self._t0 = now
        self._last = now
        elapsed = now - self._t0

        written = 0
        seen = set()
        for node in nodes:
            if node.pid not in self.pids or node.pid in seen:
                continue
            seen.add(node.pid)
            self._fh.write(self._format_row(node, now, elapsed))
            written += 1

        self._row_count += written
        # Flushed every tick: a recording killed mid-run should still be readable.
        self._fh.flush()
        return written

    def _format_row(self, node: NodeInfo, now: float, elapsed: float) -> str:
        if node.gpu_device_id >= 0:
            gpu_pct = f"{node.gpu_utilization:.1f}"
            gpu_mem = f"{node.gpu_memory_mb:.0f}"
        else:
            # Blank rather than 0: no GPU is not the same as an idle GPU.
            gpu_pct = ''
            gpu_mem = ''
        return (
            f"{now:.3f},{elapsed:.3f},{node.pid},{node.name},{node.shared_count},"
            f"{max(0.0, now - node.start_time):.3f},"
            f"{node.cpu_percent:.1f},{node.ram_mb:.1f},"
            f"{node.gpu_device_id},{gpu_pct},{gpu_mem}\n"
        )

    @property
    def row_count(self) -> int:
        return self._row_count

    @property
    def elapsed(self) -> float:
        if self._t0 is None or self._last is None:
            return 0.0
        return self._last - self._t0

    def close(self):
        if not self._fh.closed:
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
