#!/usr/bin/env python3
"""
Where the visualiser gets its data.

Two sources - one polling a live graph, one replaying a file - behind the same
small interface, so the plotting widgets never branch on which they are showing.
Deliberately free of Qt so this layer is testable on its own.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from ..node_monitor import NodeInfo
from ..recording.reader import Recording, Series
from ..recording.recorder import Recorder, node_names_by_pid


def combined_series(series_list: Sequence[Series]) -> Series:
    """
    Sum several processes into one series: what the selection cost together.

    Summed over the union of their timestamps, with a process contributing 0
    wherever it has no sample - it had died or not yet started, so it was using
    nothing. Carrying its last value forward would invent usage.

    GPU is left out: utilisation is a per-device figure and does not add up
    across processes sharing that device.
    """
    total = Series(pid=-1, node_name='Total', node_count=len(series_list))
    if not series_list:
        return total

    cpu_at = [dict(zip(s.t, s.cpu)) for s in series_list]
    ram_at = [dict(zip(s.t, s.ram)) for s in series_list]
    for t in sorted({t for s in series_list for t in s.t}):
        total.t.append(t)
        total.cpu.append(sum(at.get(t, 0.0) for at in cpu_at))
        total.ram.append(sum(at.get(t, 0.0) for at in ram_at))
        total.gpu.append(None)
        total.gpu_mem.append(None)
        total.uptime.append(0.0)
    return total


@dataclass
class NodeEntry:
    """One selectable row in the sidebar: a process, not a node."""
    pid: int
    name: str           # the group head - the container, for composable nodes
    node_count: int


class LiveSource:
    """
    Samples a NodeMonitor on demand, keeping two spans of the same data.

    The charts show a moving `window_s`; the combined figures describe the
    session. Those are different questions, and serving both from one trimmed
    buffer made the live summary silently mean "over the last minute" while the
    identical labels in replay meant "over the whole file".

    So samples are kept for `history_s` and the plot slices the tail off that.
    History is bounded rather than unlimited because the app is meant to be left
    open; `covered_s` reports the span the figures actually describe, so a
    truncated history is stated rather than misrepresented.

    Recording, when enabled, gets every sample regardless of either span.
    """

    name = 'Live'

    def __init__(self, monitor, window_s: float = 60.0,
                 history_s: float = 3600.0):
        self.monitor = monitor
        self.window_s = window_s
        self.history_s = max(history_s, window_s)
        self._series: Dict[int, Series] = {}
        self._entries: List[NodeEntry] = []
        self._recorder: Optional[Recorder] = None

    def poll(self, now: Optional[float] = None) -> None:
        """Take one sample of every process currently on the graph."""
        import time
        if now is None:
            now = time.time()

        self.monitor.update_nodes()
        self.monitor.cleanup_dead_processes()
        nodes: Sequence[NodeInfo] = self.monitor.get_node_info_list()

        seen = set()
        entries = []
        for node in nodes:
            if node.pid in seen:
                continue
            seen.add(node.pid)
            entries.append(NodeEntry(node.pid, node.name, node.shared_count))

            series = self._series.get(node.pid)
            if series is None:
                series = Series(pid=node.pid, node_name=node.name,
                                node_count=node.shared_count)
                self._series[node.pid] = series
            series.t.append(now)
            series.cpu.append(node.cpu_percent)
            series.ram.append(node.ram_mb)
            series.gpu.append(node.gpu_utilization if node.gpu_device_id >= 0 else None)
            series.gpu_mem.append(float(node.gpu_memory_mb)
                                  if node.gpu_device_id >= 0 else None)
            series.uptime.append(max(0.0, now - node.start_time))

        self._entries = entries
        self._trim(now)

        if self._recorder is not None:
            self._recorder.sample(nodes, now=now)

    def _trim(self, now: float) -> None:
        """Drop samples older than the retained history."""
        cutoff = now - self.history_s
        for series in self._series.values():
            keep = 0
            while keep < len(series.t) and series.t[keep] < cutoff:
                keep += 1
            if keep:
                del series.t[:keep]
                del series.cpu[:keep]
                del series.ram[:keep]
                del series.gpu[:keep]
                del series.gpu_mem[:keep]
                del series.uptime[:keep]

    def available(self) -> List[NodeEntry]:
        return list(self._entries)

    def series(self, pid: int) -> Series:
        """The plot window: the tail of the retained history."""
        full = self._series.get(pid)
        if full is None or not full.t:
            return Series(pid=pid)
        cutoff = full.t[-1] - self.window_s
        start = 0
        while start < len(full.t) and full.t[start] < cutoff:
            start += 1
        return Series(pid=full.pid, node_name=full.node_name,
                      node_count=full.node_count,
                      t=full.t[start:], cpu=full.cpu[start:],
                      ram=full.ram[start:], gpu=full.gpu[start:],
                      gpu_mem=full.gpu_mem[start:], uptime=full.uptime[start:])

    @property
    def covered_s(self) -> float:
        """The span the combined figures describe - the retained history."""
        spans = [s.t[-1] - s.t[0] for s in self._series.values() if s.t]
        return max(spans) if spans else 0.0

    def snapshot(self) -> Recording:
        """The whole retained session, shaped for the stats module."""
        return Recording(cores=self.monitor.cores, duration_s=self.covered_s,
                         series=dict(self._series))

    # -- recording ---------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        return self._recorder is not None

    def start_recording(self, path: str, pids: Sequence[int]) -> None:
        nodes = self.monitor.get_node_info_list()
        self._recorder = Recorder(path, pids=pids, cores=self.monitor.cores,
                                  node_names=node_names_by_pid(nodes))

    def stop_recording(self) -> None:
        if self._recorder is not None:
            self._recorder.close()
            self._recorder = None

    @property
    def recorded_rows(self) -> int:
        return self._recorder.row_count if self._recorder else 0


class ReplaySource:
    """Serves an already-loaded recording. Nothing to poll, nothing to record."""

    name = 'Recording'
    is_recording = False

    def __init__(self, recording: Recording, path: str = ''):
        self.recording = recording
        self.path = path

    def poll(self, now: Optional[float] = None) -> None:
        """A file does not change under us."""

    def available(self) -> List[NodeEntry]:
        return [NodeEntry(pid, s.node_name, s.node_count)
                for pid, s in sorted(self.recording.series.items())]

    def series(self, pid: int) -> Series:
        return self.recording.series.get(pid) or Series(pid=pid)

    def snapshot(self) -> Recording:
        return self.recording
