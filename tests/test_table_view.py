#!/usr/bin/env python3
"""Tests for the pure sort/filter/group table-view logic used by the UI."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ros2top.node_monitor import NodeInfo
from ros2top.ui.table_view import (
    group_by_pid,
    sort_groups,
    filter_groups,
    flatten,
    build_view,
    resolve_selection,
    decorate_headers,
    toggle_tag,
    visible_headers,
    visible_row,
)

BASE_HEADERS = ["PID", "Uptime", "%CPU", "RAM(MB)", "GPU#", "%GPU", "GMEM(MB)", "Node Name"]


def _node(name, pid, cpu=0.0, ram=0.0, gpu=0.0, start_time=0.0, shared_count=1):
    return NodeInfo(
        name=name, pid=pid, cpu_percent=cpu, ram_mb=ram,
        gpu_memory_mb=0, gpu_utilization=gpu, gpu_device_id=-1,
        start_time=start_time, shared_count=shared_count, auto_discovered=False,
    )


class TestGroupByPid(unittest.TestCase):
    def test_contiguous_same_pid_rows_become_one_group(self):
        nodes = [_node('/a', 1), _node('/a_helper', 1), _node('/b', 2)]
        groups = group_by_pid(nodes)
        self.assertEqual([[n.name for n in g] for g in groups],
                          [['/a', '/a_helper'], ['/b']])

    def test_empty_input(self):
        self.assertEqual(group_by_pid([]), [])


class TestSortGroups(unittest.TestCase):
    def setUp(self):
        self.groups = [
            [_node('/charlie', 3, cpu=1.0, ram=30)],
            [_node('/alpha', 1, cpu=3.0, ram=10)],
            [_node('/bravo', 2, cpu=2.0, ram=20)],
        ]

    def test_sort_by_pid_ascending(self):
        result = sort_groups(self.groups, 'pid', ascending=True)
        self.assertEqual([g[0].pid for g in result], [1, 2, 3])

    def test_sort_by_pid_descending(self):
        result = sort_groups(self.groups, 'pid', ascending=False)
        self.assertEqual([g[0].pid for g in result], [3, 2, 1])

    def test_sort_by_cpu_ascending(self):
        result = sort_groups(self.groups, 'cpu', ascending=True)
        self.assertEqual([g[0].name for g in result], ['/charlie', '/bravo', '/alpha'])

    def test_sort_by_name_ascending(self):
        result = sort_groups(self.groups, 'name', ascending=True)
        self.assertEqual([g[0].name for g in result], ['/alpha', '/bravo', '/charlie'])

    def test_sort_is_stable_for_equal_keys(self):
        groups = [
            [_node('/first', 1, cpu=5.0)],
            [_node('/second', 2, cpu=5.0)],
        ]
        result = sort_groups(groups, 'cpu', ascending=True)
        self.assertEqual([g[0].name for g in result], ['/first', '/second'])

    def test_unknown_column_returns_groups_unchanged(self):
        result = sort_groups(self.groups, 'bogus', ascending=True)
        self.assertEqual(result, self.groups)


class TestFilterGroups(unittest.TestCase):
    def setUp(self):
        self.groups = [
            [_node('/nav/controller_server', 1), _node('/nav/costmap', 1)],
            [_node('/gazebo', 2)],
        ]

    def test_empty_query_returns_all_groups(self):
        self.assertEqual(filter_groups(self.groups, ''), self.groups)

    def test_matches_any_node_name_in_group(self):
        result = filter_groups(self.groups, 'costmap')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0].name, '/nav/controller_server')

    def test_matches_namespace_prefix(self):
        result = filter_groups(self.groups, '/nav')
        self.assertEqual(len(result), 1)

    def test_case_insensitive(self):
        result = filter_groups(self.groups, 'GAZEBO')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0].name, '/gazebo')

    def test_no_match_returns_empty(self):
        self.assertEqual(filter_groups(self.groups, 'nothing-matches-this'), [])


class TestFlattenAndBuildView(unittest.TestCase):
    def test_flatten_preserves_group_internal_order(self):
        groups = [[_node('/head', 1), _node('/composed', 1)], [_node('/solo', 2)]]
        self.assertEqual([n.name for n in flatten(groups)], ['/head', '/composed', '/solo'])

    def test_build_view_filters_then_sorts(self):
        nodes = [_node('/b', 2, cpu=1.0), _node('/nav/a', 1, cpu=9.0), _node('/c', 3, cpu=5.0)]
        view = build_view(nodes, column='cpu', ascending=True, query='nav')
        self.assertEqual([n.name for n in view], ['/nav/a'])

    def test_build_view_no_filter_sorts_all(self):
        nodes = [_node('/b', 2, cpu=1.0), _node('/a', 1, cpu=9.0)]
        view = build_view(nodes, column='cpu', ascending=True, query='')
        self.assertEqual([n.name for n in view], ['/b', '/a'])


class TestResolveSelection(unittest.TestCase):
    def test_finds_previous_identity_after_reorder(self):
        view = [_node('/a', 1), _node('/b', 2), _node('/c', 3)]
        idx = resolve_selection(view, prev_pid=3, prev_name='/c', prev_index=0)
        self.assertEqual(idx, 2)

    def test_falls_back_to_clamped_index_when_identity_gone(self):
        view = [_node('/a', 1), _node('/b', 2)]
        idx = resolve_selection(view, prev_pid=99, prev_name='/gone', prev_index=5)
        self.assertEqual(idx, 1)  # clamped to last valid index

    def test_empty_view_returns_zero(self):
        idx = resolve_selection([], prev_pid=1, prev_name='/a', prev_index=3)
        self.assertEqual(idx, 0)


class TestDecorateHeaders(unittest.TestCase):
    def test_marks_active_ascending_column(self):
        headers = ["PID", "Uptime", "%CPU", "RAM(MB)", "GPU#", "%GPU", "GMEM(MB)", "Node Name"]
        result = decorate_headers(headers, column='cpu', ascending=True)
        self.assertEqual(result[2], "%CPU^")
        # Other headers are untouched
        self.assertEqual(result[0], "PID")
        self.assertEqual(result[7], "Node Name")

    def test_marks_active_descending_column(self):
        headers = ["PID", "Uptime", "%CPU", "RAM(MB)", "GPU#", "%GPU", "GMEM(MB)", "Node Name"]
        result = decorate_headers(headers, column='name', ascending=False)
        self.assertEqual(result[7], "Node Namev")


class TestVisibleColumns(unittest.TestCase):
    def test_gpu_columns_kept_when_gpu_available(self):
        self.assertEqual(visible_headers(BASE_HEADERS, show_gpu=True), BASE_HEADERS)

    def test_gpu_columns_dropped_when_no_gpu(self):
        result = visible_headers(BASE_HEADERS, show_gpu=False)
        self.assertEqual(result, ["PID", "Uptime", "%CPU", "RAM(MB)", "Node Name"])

    def test_row_kept_whole_when_gpu_available(self):
        row = ["123", "01s", "1.0", "2.0", "0", "3.0", "4", "/node"]
        self.assertEqual(visible_row(row, BASE_HEADERS, show_gpu=True), row)

    def test_row_drops_gpu_cells_when_no_gpu(self):
        row = ["123", "01s", "1.0", "2.0", "0", "3.0", "4", "/node"]
        result = visible_row(row, BASE_HEADERS, show_gpu=False)
        self.assertEqual(result, ["123", "01s", "1.0", "2.0", "/node"])


class TestDecorateHeadersAfterColumnDrop(unittest.TestCase):
    def test_marks_correct_column_when_gpu_columns_are_hidden(self):
        narrowed = visible_headers(BASE_HEADERS, show_gpu=False)
        result = decorate_headers(narrowed, column='name', ascending=True)
        self.assertEqual(result[-1], "Node Name^")


class TestToggleTag(unittest.TestCase):
    def test_toggle_adds_then_removes(self):
        tagged = set()
        tagged = toggle_tag(tagged, 42)
        self.assertEqual(tagged, {42})
        tagged = toggle_tag(tagged, 42)
        self.assertEqual(tagged, set())

    def test_toggle_does_not_disturb_other_entries(self):
        tagged = {1, 2}
        tagged = toggle_tag(tagged, 3)
        self.assertEqual(tagged, {1, 2, 3})


if __name__ == '__main__':
    unittest.main()
