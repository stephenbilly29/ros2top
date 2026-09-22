#!/usr/bin/env python3
"""Tests for reading a recording back into per-PID series."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ros2top.node_monitor import NodeInfo
from ros2top.recording.recorder import Recorder
from ros2top.recording.reader import read_recording


def _node(name, pid, cpu=0.0, ram=0.0, start_time=0.0, shared_count=1,
          gpu_id=-1, gpu_util=0.0, gpu_mem=0):
    return NodeInfo(
        name=name, pid=pid, cpu_percent=cpu, ram_mb=ram,
        gpu_memory_mb=gpu_mem, gpu_utilization=gpu_util, gpu_device_id=gpu_id,
        start_time=start_time, shared_count=shared_count, auto_discovered=False,
    )


class ReaderTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'run.csv')

    def tearDown(self):
        self.tmp.cleanup()


class TestRoundTrip(ReaderTestCase):
    def test_samples_survive_a_write_then_read(self):
        with Recorder(self.path, pids=[1, 2], cores=8, node_names={}) as rec:
            rec.sample([_node('/a', 1, cpu=10.0, ram=100.0),
                        _node('/b', 2, cpu=20.0, ram=200.0)], now=1000.0)
            rec.sample([_node('/a', 1, cpu=30.0, ram=110.0),
                        _node('/b', 2, cpu=40.0, ram=210.0)], now=1001.0)

        rec_read = read_recording(self.path)
        self.assertEqual(set(rec_read.series), {1, 2})
        self.assertEqual(rec_read.series[1].cpu, [10.0, 30.0])
        self.assertEqual(rec_read.series[2].cpu, [20.0, 40.0])
        self.assertEqual(rec_read.series[1].ram, [100.0, 110.0])
        self.assertEqual(rec_read.series[1].t, [0.0, 1.0])

    def test_node_name_and_count_come_back(self):
        with Recorder(self.path, pids=[5], cores=8, node_names={}) as rec:
            rec.sample([_node('/container', 5, shared_count=3)], now=1.0)
        series = read_recording(self.path).series[5]
        self.assertEqual(series.node_name, '/container')
        self.assertEqual(series.node_count, 3)


class TestMetadata(ReaderTestCase):
    def test_reads_core_count(self):
        with Recorder(self.path, pids=[1], cores=16, node_names={}) as rec:
            rec.sample([_node('/a', 1)], now=1.0)
        self.assertEqual(read_recording(self.path).cores, 16)

    def test_reads_started_utc(self):
        with Recorder(self.path, pids=[1], cores=8, node_names={}) as rec:
            rec.sample([_node('/a', 1)], now=1.0)
        self.assertTrue(read_recording(self.path).started_utc)

    def test_reads_full_node_name_list_per_pid(self):
        with Recorder(self.path, pids=[5], cores=8,
                      node_names={5: ['/container', '/talker', '/listener']}) as rec:
            rec.sample([_node('/container', 5, shared_count=3)], now=1.0)
        names = read_recording(self.path).node_names
        self.assertEqual(names[5], ['/container', '/talker', '/listener'])

    def test_missing_core_count_raises(self):
        # Guessing a core count would silently corrupt every core-seconds total.
        with open(self.path, 'w') as f:
            f.write('# ros2top-recording v1\n')
            f.write('timestamp,elapsed_s,pid,node_name,node_count,uptime_s,'
                    'cpu_percent,ram_mb,gpu_index,gpu_percent,gpu_mem_mb\n')
            f.write('1000.000,0.000,1,/a,1,0.000,5.0,10.0,-1,,\n')
        with self.assertRaises(ValueError) as ctx:
            read_recording(self.path)
        self.assertIn('cpu_cores', str(ctx.exception))


class TestDuration(ReaderTestCase):
    def test_duration_is_the_last_elapsed_time(self):
        with Recorder(self.path, pids=[1], cores=8, node_names={}) as rec:
            rec.sample([_node('/a', 1)], now=100.0)
            rec.sample([_node('/a', 1)], now=107.5)
        self.assertAlmostEqual(read_recording(self.path).duration_s, 7.5)

    def test_empty_recording_has_no_series_and_zero_duration(self):
        Recorder(self.path, pids=[1], cores=8, node_names={}).close()
        rec = read_recording(self.path)
        self.assertEqual(rec.series, {})
        self.assertEqual(rec.duration_s, 0.0)


class TestGpuColumns(ReaderTestCase):
    def test_absent_gpu_reads_as_none_not_zero(self):
        # 0.0 would claim an idle GPU; there isn't one.
        with Recorder(self.path, pids=[1], cores=8, node_names={}) as rec:
            rec.sample([_node('/a', 1, gpu_id=-1)], now=1.0)
        series = read_recording(self.path).series[1]
        self.assertEqual(series.gpu, [None])
        self.assertEqual(series.gpu_mem, [None])
        self.assertFalse(series.has_gpu)

    def test_present_gpu_is_parsed(self):
        with Recorder(self.path, pids=[1], cores=8, node_names={}) as rec:
            rec.sample([_node('/a', 1, gpu_id=0, gpu_util=42.0, gpu_mem=1536)], now=1.0)
        series = read_recording(self.path).series[1]
        self.assertEqual(series.gpu, [42.0])
        self.assertEqual(series.gpu_mem, [1536.0])
        self.assertTrue(series.has_gpu)


class TestTruncatedFile(ReaderTestCase):
    def test_partial_final_line_is_discarded(self):
        # A recorder killed mid-write leaves a half row; the rest is still good.
        with Recorder(self.path, pids=[1], cores=8, node_names={}) as rec:
            rec.sample([_node('/a', 1, cpu=5.0)], now=1.0)
            rec.sample([_node('/a', 1, cpu=6.0)], now=2.0)
        with open(self.path) as f:
            text = f.read()
        with open(self.path, 'w') as f:
            f.write(text + '3.000,2.000,1,/a,1,')  # torn row, no newline

        series = read_recording(self.path).series[1]
        self.assertEqual(series.cpu, [5.0, 6.0])


if __name__ == '__main__':
    unittest.main()
