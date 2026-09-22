#!/usr/bin/env python3
"""
Combined-CPU statistics over a recording.

Pure functions over a Recording, deliberately free of numpy, Qt and I/O, so the
numbers that get quoted at people are directly testable.

CPU only, on purpose. GPU *utilisation* is a per-device figure that does not add
up across processes sharing that device, and summed RSS double-counts shared
pages; CPU percent is the only one of the three that sums honestly.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from .reader import Recording


@dataclass
class CombinedStats:
    """
    What a selected set of PIDs cost over a run.

    peak_combined_pct and sum_of_peaks_pct answer different questions and will
    differ whenever the nodes peak at different moments:

    - peak_combined_pct is the most the set ever drew at one instant. It happened.
    - sum_of_peaks_pct assumes every node peaks together. It is an upper bound
      for sizing headroom, and may describe a moment that never occurred.
    """
    peak_combined_pct: float = 0.0
    sum_of_peaks_pct: float = 0.0
    total_cpu_seconds: float = 0.0
    mean_combined_pct: float = 0.0
    duration_s: float = 0.0


def _combined_timeline(recording: Recording, pids: Iterable[int]):
    """
    (times, combined_cpu) over the union of the selected PIDs' sample times.

    A PID with no sample at a given time contributes 0: it had died or had not
    started, so it was drawing nothing. Carrying its last value forward would
    invent usage that never happened.

    The recorder writes every PID in a tick under one timestamp, so in practice
    these timelines line up exactly and no interpolation is involved.
    """
    by_pid: Dict[int, Dict[float, float]] = {}
    for pid in pids:
        series = recording.series.get(pid)
        if series is None:
            continue
        by_pid[pid] = dict(zip(series.t, series.cpu))

    times: List[float] = sorted({t for samples in by_pid.values() for t in samples})
    combined = [sum(samples.get(t, 0.0) for samples in by_pid.values()) for t in times]
    return times, combined, by_pid


def _trapezoid(times: List[float], values: List[float]) -> float:
    """Integrate values over times. Sample spacing is never assumed uniform."""
    total = 0.0
    for i in range(1, len(times)):
        dt = times[i] - times[i - 1]
        total += (values[i] + values[i - 1]) / 2.0 * dt
    return total


def combined_cpu_stats(recording: Recording,
                       pids: Optional[Iterable[int]] = None) -> CombinedStats:
    """
    Summarise what `pids` (default: every PID in the recording) cost.

    CPU percentages are machine-relative, as ros2top records them, so core-seconds
    need the recording's core count - which is why the reader insists on having it.
    """
    selected = list(recording.series) if pids is None else list(pids)
    times, combined, by_pid = _combined_timeline(recording, selected)

    if not times:
        return CombinedStats()

    duration = times[-1] - times[0]
    peak = max(combined)
    sum_of_peaks = sum(max(samples.values()) for samples in by_pid.values() if samples)

    if duration > 0:
        area_pct_seconds = _trapezoid(times, combined)
        mean = area_pct_seconds / duration
        total_cpu_seconds = area_pct_seconds / 100.0 * recording.cores
    else:
        # One observation: no time has elapsed, so no CPU-time has accrued, and
        # the mean is just that observation.
        mean = combined[0]
        total_cpu_seconds = 0.0

    return CombinedStats(
        peak_combined_pct=peak,
        sum_of_peaks_pct=sum_of_peaks,
        total_cpu_seconds=total_cpu_seconds,
        mean_combined_pct=mean,
        duration_s=duration,
    )
