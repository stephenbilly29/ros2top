#!/usr/bin/env python3
"""
Read a ros2top recording back into per-PID series.

The counterpart to recorder.py. Kept free of numpy and Qt so the stats layer
and the tests can use it without the GUI extra installed.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .recorder import COLUMNS


@dataclass
class Series:
    """One PID's samples over the run. All lists share an index."""
    pid: int
    node_name: str = ''
    node_count: int = 1
    t: List[float] = field(default_factory=list)          # seconds since start
    cpu: List[float] = field(default_factory=list)        # percent of machine
    ram: List[float] = field(default_factory=list)        # MB
    gpu: List[Optional[float]] = field(default_factory=list)      # None when no GPU
    gpu_mem: List[Optional[float]] = field(default_factory=list)  # None when no GPU
    uptime: List[float] = field(default_factory=list)

    @property
    def has_gpu(self) -> bool:
        return any(v is not None for v in self.gpu)


@dataclass
class Recording:
    cores: int
    started_utc: str = ''
    host: str = ''
    duration_s: float = 0.0
    series: Dict[int, Series] = field(default_factory=dict)
    # Full node list per PID, from the header - rows only carry the head node.
    node_names: Dict[int, List[str]] = field(default_factory=dict)


def _parse_metadata(line: str, cores_box: List[Optional[int]],
                    meta: Dict[str, str], node_names: Dict[int, List[str]]):
    body = line[1:].strip()
    if body.startswith('pid='):
        parts = dict(p.split('=', 1) for p in body.split(' ') if '=' in p)
        pid = int(parts['pid'])
        names = parts.get('node_names', '')
        node_names[pid] = [n for n in names.split(';') if n]
        return
    if '=' not in body:
        return
    key, value = body.split('=', 1)
    if key == 'cpu_cores':
        cores_box[0] = int(value)
    else:
        meta[key] = value


def _optional_float(text: str) -> Optional[float]:
    # Blank means "there was no GPU", which is not the same as 0.0.
    return float(text) if text else None


def read_recording(path: str) -> Recording:
    """
    Parse a recording file.

    Raises ValueError if the core count is missing: cpu_percent is machine-
    relative, so without it any core-seconds figure derived from this file
    would be wrong, and wrong silently.
    """
    cores_box: List[Optional[int]] = [None]
    meta: Dict[str, str] = {}
    node_names: Dict[int, List[str]] = {}
    series: Dict[int, Series] = {}
    duration = 0.0
    expected = len(COLUMNS)

    with open(path) as fh:
        for line in fh:
            if line.startswith('#'):
                _parse_metadata(line, cores_box, meta, node_names)
                continue
            line = line.rstrip('\n')
            if not line or line.startswith(COLUMNS[0]):
                continue
            fields = line.split(',')
            # A recorder killed mid-write leaves a torn final row. Everything
            # before it is still good, so drop the fragment rather than failing.
            if len(fields) != expected:
                continue

            pid = int(fields[2])
            s = series.get(pid)
            if s is None:
                s = Series(pid=pid, node_name=fields[3], node_count=int(fields[4]))
                series[pid] = s
            elapsed = float(fields[1])
            s.t.append(elapsed)
            s.uptime.append(float(fields[5]))
            s.cpu.append(float(fields[6]))
            s.ram.append(float(fields[7]))
            s.gpu.append(_optional_float(fields[9]))
            s.gpu_mem.append(_optional_float(fields[10]))
            duration = max(duration, elapsed)

    if cores_box[0] is None:
        raise ValueError(
            f"{path}: missing 'cpu_cores' in the header. ros2top records CPU as "
            "a percentage of the whole machine, so the core count is required "
            "to interpret it.")

    return Recording(
        cores=cores_box[0],
        started_utc=meta.get('started_utc', ''),
        host=meta.get('host', ''),
        duration_s=duration,
        series=series,
        node_names=node_names,
    )
