#!/usr/bin/env python3
"""Tests for the GUI's data sources - the layer that makes plots ignorant of
whether they are showing a live graph or a replayed file."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ros2top.node_monitor import NodeInfo
from ros2top.recording.reader import Recording, Series
from ros2top.recording.stats import combined_cpu_stats
from ros2top.viz.source import LiveSource, ReplaySource, combined_series


def _node(name, pid, cpu=0.0, ram=0.0, shared_count=1, gpu_id=-1, gpu_util=0.0):
    return NodeInfo(
        name=name, pid=pid, cpu_percent=cpu, ram_mb=ram,
        gpu_memory_mb=0, gpu_utilization=gpu_util, gpu_device_id=gpu_id,
        start_time=0.0, shared_count=shared_count, auto_discovered=False,
    )


class _FakeMonitor:
    """Stands in for NodeMonitor: returns whatever batch was queued."""

    def __init__(self, batches, cores=8):
        self.batches = list(batches)
        self.cores = cores
        self.updated = 0

    def update_nodes(self):
        self.updated += 1

    def cleanup_dead_processes(self):
        pass

    def get_node_info_list(self):
        return self.batches.pop(0) if len(self.batches) > 1 else self.batches[0]


class TestLiveSource(unittest.TestCase):
    def test_poll_accumulates_samples_per_pid(self):
        src = LiveSource(_FakeMonitor([[_node('/a', 1, cpu=10.0)]]))
        src.poll(now=0.0)
        src.poll(now=1.0)
        self.assertEqual(src.series(1).cpu, [10.0, 10.0])
        self.assertEqual(src.series(1).t, [0.0, 1.0])

    def test_rolling_window_drops_samples_older_than_the_window(self):
        src = LiveSource(_FakeMonitor([[_node('/a', 1, cpu=5.0)]]), window_s=10.0)
        for t in range(0, 26, 5):        # 0,5,10,15,20,25
            src.poll(now=float(t))
        # Only the last 10 seconds are kept
        self.assertEqual(src.series(1).t, [15.0, 20.0, 25.0])

    def test_available_lists_one_entry_per_pid_headed_by_the_container(self):
        monitor = _FakeMonitor([[_node('/container', 5, shared_count=2),
                                 _node('/composed', 5, shared_count=2),
                                 _node('/solo', 9)]])
        src = LiveSource(monitor)
        src.poll(now=0.0)
        entries = src.available()
        self.assertEqual([(e.pid, e.name, e.node_count) for e in entries],
                          [(5, '/container', 2), (9, '/solo', 1)])

    def test_series_for_an_unknown_pid_is_empty_not_an_error(self):
        src = LiveSource(_FakeMonitor([[_node('/a', 1)]]))
        src.poll(now=0.0)
        self.assertEqual(src.series(4242).cpu, [])

    def test_a_pid_that_disappears_keeps_the_samples_it_had(self):
        monitor = _FakeMonitor([[_node('/a', 1, cpu=5.0), _node('/b', 2, cpu=7.0)],
                                [_node('/a', 1, cpu=6.0)]])
        src = LiveSource(monitor)
        src.poll(now=0.0)
        src.poll(now=1.0)
        self.assertEqual(src.series(2).cpu, [7.0])
        self.assertEqual(src.series(1).cpu, [5.0, 6.0])


class TestLiveSourceSnapshot(unittest.TestCase):
    def test_snapshot_feeds_the_stats_module_directly(self):
        monitor = _FakeMonitor([[_node('/a', 1, cpu=30.0), _node('/b', 2, cpu=50.0)]],
                               cores=16)
        src = LiveSource(monitor)
        src.poll(now=0.0)
        src.poll(now=10.0)

        stats = combined_cpu_stats(src.snapshot())
        self.assertAlmostEqual(stats.peak_combined_pct, 80.0)
        self.assertAlmostEqual(stats.duration_s, 10.0)

    def test_snapshot_carries_the_core_count(self):
        src = LiveSource(_FakeMonitor([[_node('/a', 1)]], cores=12))
        src.poll(now=0.0)
        self.assertEqual(src.snapshot().cores, 12)


class TestLiveSourceRecording(unittest.TestCase):
    def test_recording_writes_the_selected_pids_while_polling(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, 'run.csv')

        monitor = _FakeMonitor([[_node('/a', 1, cpu=5.0), _node('/b', 2, cpu=6.0)]])
        src = LiveSource(monitor)
        src.poll(now=0.0)
        src.start_recording(path, pids=[1])
        src.poll(now=1.0)
        src.poll(now=2.0)
        src.stop_recording()

        self.assertFalse(src.is_recording)
        with open(path) as fh:
            text = fh.read()
        rows = [l for l in text.splitlines()
                if l and not l.startswith('#') and not l.startswith('timestamp')]
        self.assertEqual(len(rows), 2)              # only PID 1, two polls
        self.assertTrue(all(r.split(',')[2] == '1' for r in rows))

    def test_is_recording_reports_state(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src = LiveSource(_FakeMonitor([[_node('/a', 1)]]))
        src.poll(now=0.0)
        self.assertFalse(src.is_recording)
        src.start_recording(os.path.join(tmp.name, 'r.csv'), pids=[1])
        self.assertTrue(src.is_recording)
        src.stop_recording()
        self.assertFalse(src.is_recording)


class TestCombinedSeries(unittest.TestCase):
    """The summed curve drawn on the Combined tab - what the selection cost
    together at each instant, rather than several lines to add up by eye."""

    def _series(self, pid, t, cpu, ram=None):
        return Series(pid=pid, node_name=f'/n{pid}', t=list(t), cpu=list(cpu),
                      ram=list(ram or [0.0] * len(t)),
                      gpu=[None] * len(t), gpu_mem=[None] * len(t),
                      uptime=list(t))

    def test_adds_cpu_at_each_shared_timestamp(self):
        a = self._series(1, [0.0, 1.0], [10.0, 20.0])
        b = self._series(2, [0.0, 1.0], [5.0, 7.0])
        total = combined_series([a, b])
        self.assertEqual(total.t, [0.0, 1.0])
        self.assertEqual(total.cpu, [15.0, 27.0])

    def test_adds_ram_too(self):
        a = self._series(1, [0.0], [0.0], ram=[100.0])
        b = self._series(2, [0.0], [0.0], ram=[50.0])
        self.assertEqual(combined_series([a, b]).ram, [150.0])

    def test_a_process_missing_at_a_timestamp_contributes_zero(self):
        a = self._series(1, [0.0, 1.0, 2.0], [10.0, 10.0, 10.0])
        b = self._series(2, [0.0, 1.0], [5.0, 5.0])      # died before t=2
        self.assertEqual(combined_series([a, b]).cpu, [15.0, 15.0, 10.0])

    def test_single_series_is_itself(self):
        a = self._series(1, [0.0, 1.0], [3.0, 4.0])
        self.assertEqual(combined_series([a]).cpu, [3.0, 4.0])

    def test_no_series_is_empty(self):
        total = combined_series([])
        self.assertEqual(total.t, [])
        self.assertEqual(total.cpu, [])


class TestReplaySource(unittest.TestCase):
    def setUp(self):
        s = Series(pid=7, node_name='/replayed', node_count=2,
                   t=[0.0, 1.0], cpu=[10.0, 20.0], ram=[100.0, 110.0],
                   gpu=[None, None], gpu_mem=[None, None], uptime=[0.0, 1.0])
        self.recording = Recording(cores=4, duration_s=1.0, series={7: s})

    def test_available_lists_the_recorded_pids(self):
        entries = ReplaySource(self.recording).available()
        self.assertEqual([(e.pid, e.name, e.node_count) for e in entries],
                          [(7, '/replayed', 2)])

    def test_series_returns_the_recorded_samples(self):
        self.assertEqual(ReplaySource(self.recording).series(7).cpu, [10.0, 20.0])

    def test_snapshot_is_the_recording_itself(self):
        self.assertIs(ReplaySource(self.recording).snapshot(), self.recording)

    def test_replay_never_records(self):
        self.assertFalse(ReplaySource(self.recording).is_recording)


if __name__ == '__main__':
    unittest.main()
