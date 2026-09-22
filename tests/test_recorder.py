#!/usr/bin/env python3
"""Tests for the CSV recorder."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ros2top.node_monitor import NodeInfo
from ros2top.recording.recorder import (
    Recorder, node_names_by_pid, select_pids, wait_for_nodes,
)


def _node(name, pid, cpu=0.0, ram=0.0, start_time=0.0, shared_count=1,
          gpu_id=-1, gpu_util=0.0, gpu_mem=0):
    return NodeInfo(
        name=name, pid=pid, cpu_percent=cpu, ram_mb=ram,
        gpu_memory_mb=gpu_mem, gpu_utilization=gpu_util, gpu_device_id=gpu_id,
        start_time=start_time, shared_count=shared_count, auto_discovered=False,
    )


class RecorderTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'run.csv')

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        with open(self.path) as f:
            return f.read()

    def data_rows(self):
        return [line for line in self.read().splitlines()
                if line and not line.startswith('#') and not line.startswith('timestamp')]


class TestMetadataHeader(RecorderTestCase):
    def test_header_names_the_format_and_core_count(self):
        rec = Recorder(self.path, pids=[1], cores=16, node_names={1: ['/a']})
        rec.close()
        text = self.read()
        self.assertIn('# ros2top-recording v1', text)
        self.assertIn('# cpu_cores=16', text)

    def test_header_records_node_names_per_pid(self):
        rec = Recorder(self.path, pids=[7], cores=4,
                       node_names={7: ['/container', '/talker', '/listener']})
        rec.close()
        self.assertIn('# pid=7 node_count=3 node_names=/container;/talker;/listener',
                      self.read())

    def test_column_header_row_is_present(self):
        rec = Recorder(self.path, pids=[1], cores=2, node_names={})
        rec.close()
        self.assertIn(
            'timestamp,elapsed_s,pid,node_name,node_count,uptime_s,'
            'cpu_percent,ram_mb,gpu_index,gpu_percent,gpu_mem_mb',
            self.read())


class TestSampling(RecorderTestCase):
    def test_one_row_per_tracked_pid_per_tick(self):
        rec = Recorder(self.path, pids=[1, 2], cores=8, node_names={})
        rec.sample([_node('/a', 1), _node('/b', 2)], now=1000.0)
        rec.sample([_node('/a', 1), _node('/b', 2)], now=1001.0)
        rec.close()
        self.assertEqual(len(self.data_rows()), 4)

    def test_every_row_in_a_tick_shares_one_timestamp(self):
        rec = Recorder(self.path, pids=[1, 2], cores=8, node_names={})
        rec.sample([_node('/a', 1), _node('/b', 2)], now=1234.5)
        rec.close()
        stamps = {row.split(',')[0] for row in self.data_rows()}
        self.assertEqual(stamps, {'1234.500'})

    def test_pids_outside_the_tracked_set_are_ignored(self):
        rec = Recorder(self.path, pids=[1], cores=8, node_names={})
        rec.sample([_node('/a', 1), _node('/stranger', 99)], now=1000.0)
        rec.close()
        rows = self.data_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].split(',')[2], '1')

    def test_elapsed_is_measured_from_the_first_sample(self):
        rec = Recorder(self.path, pids=[1], cores=8, node_names={})
        rec.sample([_node('/a', 1)], now=500.0)
        rec.sample([_node('/a', 1)], now=502.5)
        rec.close()
        elapsed = [row.split(',')[1] for row in self.data_rows()]
        self.assertEqual(elapsed, ['0.000', '2.500'])

    def test_sample_returns_rows_written(self):
        rec = Recorder(self.path, pids=[1, 2], cores=8, node_names={})
        written = rec.sample([_node('/a', 1), _node('/b', 2)], now=1.0)
        rec.close()
        self.assertEqual(written, 2)

    def test_row_count_accumulates(self):
        rec = Recorder(self.path, pids=[1], cores=8, node_names={})
        rec.sample([_node('/a', 1)], now=1.0)
        rec.sample([_node('/a', 1)], now=2.0)
        self.assertEqual(rec.row_count, 2)
        rec.close()


class TestComposableNodes(RecorderTestCase):
    def test_one_row_per_pid_headed_by_the_container(self):
        # Three nodes in one container process: NodeMonitor lists the
        # container first. Usage is process-wide, so only one row is right.
        rec = Recorder(self.path, pids=[5], cores=8, node_names={})
        rec.sample([
            _node('/container', 5, cpu=3.0, shared_count=3),
            _node('/talker', 5, cpu=3.0, shared_count=3),
            _node('/listener', 5, cpu=3.0, shared_count=3),
        ], now=1000.0)
        rec.close()
        rows = self.data_rows()
        self.assertEqual(len(rows), 1)
        fields = rows[0].split(',')
        self.assertEqual(fields[3], '/container')
        self.assertEqual(fields[4], '3')  # node_count


class TestGpuColumns(RecorderTestCase):
    def test_gpu_columns_empty_when_no_gpu(self):
        rec = Recorder(self.path, pids=[1], cores=8, node_names={})
        rec.sample([_node('/a', 1, gpu_id=-1)], now=1.0)
        rec.close()
        fields = self.data_rows()[0].split(',')
        self.assertEqual(fields[8], '-1')  # gpu_index
        self.assertEqual(fields[9], '')    # gpu_percent
        self.assertEqual(fields[10], '')   # gpu_mem_mb

    def test_gpu_columns_populated_when_gpu_present(self):
        rec = Recorder(self.path, pids=[1], cores=8, node_names={})
        rec.sample([_node('/a', 1, gpu_id=0, gpu_util=42.0, gpu_mem=1536)], now=1.0)
        rec.close()
        fields = self.data_rows()[0].split(',')
        self.assertEqual(fields[8], '0')
        self.assertEqual(fields[9], '42.0')
        self.assertEqual(fields[10], '1536')


class TestDurability(RecorderTestCase):
    def test_rows_are_readable_before_close(self):
        # A recording killed mid-run must still have its samples on disk.
        rec = Recorder(self.path, pids=[1], cores=8, node_names={})
        rec.sample([_node('/a', 1)], now=1.0)
        self.assertEqual(len(self.data_rows()), 1)
        rec.close()

    def test_works_as_a_context_manager(self):
        with Recorder(self.path, pids=[1], cores=8, node_names={}) as rec:
            rec.sample([_node('/a', 1)], now=1.0)
        self.assertEqual(len(self.data_rows()), 1)

    def test_unwritable_path_raises_on_open(self):
        with self.assertRaises(OSError):
            Recorder(os.path.join(self.tmp.name, 'nope', 'run.csv'),
                     pids=[1], cores=8, node_names={})


class TestSelectPids(unittest.TestCase):
    def setUp(self):
        self.nodes = [_node('/container', 5, shared_count=2),
                      _node('/composed', 5, shared_count=2),
                      _node('/solo', 9)]

    def test_no_request_selects_every_discovered_pid(self):
        self.assertEqual(select_pids(self.nodes), [5, 9])

    def test_request_narrows_to_those_pids(self):
        self.assertEqual(select_pids(self.nodes, [9]), [9])

    def test_requested_pid_that_is_not_running_is_dropped(self):
        self.assertEqual(select_pids(self.nodes, [9, 4242]), [9])

    def test_empty_node_list_selects_nothing(self):
        self.assertEqual(select_pids([], [9]), [])


class _FakeClock:
    """Time only moves when something sleeps."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, dt):
        self.t += dt


class TestWaitForNodes(unittest.TestCase):
    """Discovery trickles in. Freezing the PID set on the first node found
    would record a handful of processes and miss the rest of the graph."""

    def _wait(self, polls, **kw):
        clock = _FakeClock()
        calls = iter(polls)
        last = polls[-1]

        def poll():
            return next(calls, last)

        return wait_for_nodes(poll, sleep=clock.sleep, clock=clock, **kw)

    def test_waits_for_the_count_to_stop_growing(self):
        growing = [[_node('/a', 1)],
                   [_node('/a', 1), _node('/b', 2)],
                   [_node('/a', 1), _node('/b', 2), _node('/c', 3)]]
        stable = [growing[-1]] * 5
        result = self._wait(growing + stable, settle_polls=2, min_wait_s=0.0)
        self.assertEqual(len(result), 3)

    def test_returns_once_the_count_holds_steady(self):
        steady = [[_node('/a', 1), _node('/b', 2)]] * 6
        result = self._wait(steady, settle_polls=2, min_wait_s=0.0)
        self.assertEqual(len(result), 2)

    def test_an_early_plateau_does_not_end_the_wait(self):
        # Real behaviour on a Nav2 graph: discovery reports a partial set,
        # holds it for over a second, then delivers the rest. Returning during
        # that plateau silently records a fraction of the system.
        plateau = [[_node('/a', 1)]] * 7
        full = [[_node(f'/n{i}', i) for i in range(5)]] * 10
        result = self._wait(plateau + full, settle_polls=2,
                            min_wait_s=2.0, interval=0.25, timeout_s=10.0)
        self.assertEqual(len(result), 5)

    def test_gives_up_at_the_timeout_if_nodes_keep_appearing(self):
        forever_growing = [[_node(f'/n{i}', i) for i in range(n)]
                           for n in range(1, 100)]
        result = self._wait(forever_growing, settle_polls=3,
                            timeout_s=1.0, interval=0.25)
        # Bounded by the timeout rather than running until discovery settles
        self.assertLessEqual(len(result), 6)

    def test_empty_graph_returns_empty_without_hanging(self):
        result = self._wait([[]] * 50, settle_polls=3, timeout_s=1.0, interval=0.25)
        self.assertEqual(result, [])


class TestNodeNamesByPid(unittest.TestCase):
    def test_groups_names_under_their_shared_pid(self):
        nodes = [_node('/container', 5, shared_count=2),
                 _node('/composed', 5, shared_count=2),
                 _node('/solo', 9)]
        self.assertEqual(node_names_by_pid(nodes),
                          {5: ['/container', '/composed'], 9: ['/solo']})

    def test_keeps_the_container_first(self):
        # NodeMonitor lists the container ahead of the nodes composed into it,
        # and the header's first name is taken to be the group head.
        nodes = [_node('/container', 5, shared_count=3),
                 _node('/talker', 5, shared_count=3),
                 _node('/listener', 5, shared_count=3)]
        self.assertEqual(node_names_by_pid(nodes)[5][0], '/container')


class TestUptime(RecorderTestCase):
    def test_uptime_is_now_minus_node_start_time(self):
        rec = Recorder(self.path, pids=[1], cores=8, node_names={})
        rec.sample([_node('/a', 1, start_time=900.0)], now=1000.0)
        rec.close()
        self.assertEqual(self.data_rows()[0].split(',')[5], '100.000')


if __name__ == '__main__':
    unittest.main()
