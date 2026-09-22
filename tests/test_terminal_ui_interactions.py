#!/usr/bin/env python3
"""
Tests for TerminalUI's sort/filter/tag state transitions.

These exercise the plain state-mutation methods directly (no curses.wrapper,
no stdscr) since TerminalUI.__init__ does no curses I/O itself.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ros2top.node_monitor import NodeInfo
from ros2top.ui.terminal_ui import TerminalUI
from ros2top.ui.table_view import SORT_COLUMNS


def _node(name, pid):
    return NodeInfo(
        name=name, pid=pid, cpu_percent=0.0, ram_mb=0.0,
        gpu_memory_mb=0, gpu_utilization=0.0, gpu_device_id=-1,
        start_time=0.0, shared_count=1, auto_discovered=False,
    )


def _ui():
    return TerminalUI(MagicMock())


class TestSortState(unittest.TestCase):
    def test_cycle_sort_column_wraps_through_all_columns(self):
        ui = _ui()
        self.assertEqual(ui.sort_column, SORT_COLUMNS[0])
        seen = [ui.sort_column]
        for _ in range(len(SORT_COLUMNS)):
            ui._cycle_sort_column()
            seen.append(ui.sort_column)
        # After a full cycle we're back to the start
        self.assertEqual(seen[-1], SORT_COLUMNS[0])
        # Every column was visited along the way
        self.assertEqual(set(seen), set(SORT_COLUMNS))

    def test_toggle_sort_direction_flips_ascending(self):
        ui = _ui()
        self.assertTrue(ui.sort_ascending)
        ui._toggle_sort_direction()
        self.assertFalse(ui.sort_ascending)
        ui._toggle_sort_direction()
        self.assertTrue(ui.sort_ascending)


class TestFilterState(unittest.TestCase):
    def test_typing_appends_and_enables_filter_mode(self):
        ui = _ui()
        ui._filter_start()
        ui._filter_append_char('n')
        ui._filter_append_char('a')
        ui._filter_append_char('v')
        self.assertEqual(ui.filter_query, 'nav')
        self.assertTrue(ui.filter_mode)

    def test_backspace_removes_last_char(self):
        ui = _ui()
        ui._filter_start()
        ui._filter_append_char('a')
        ui._filter_append_char('b')
        ui._filter_backspace()
        self.assertEqual(ui.filter_query, 'a')

    def test_backspace_on_empty_query_is_a_noop(self):
        ui = _ui()
        ui._filter_start()
        ui._filter_backspace()
        self.assertEqual(ui.filter_query, '')

    def test_clear_empties_query_and_exits_filter_mode(self):
        ui = _ui()
        ui._filter_start()
        ui._filter_append_char('x')
        ui._filter_clear()
        self.assertEqual(ui.filter_query, '')
        self.assertFalse(ui.filter_mode)

    def test_confirm_exits_typing_mode_but_keeps_query(self):
        ui = _ui()
        ui._filter_start()
        ui._filter_append_char('x')
        ui._filter_confirm()
        self.assertEqual(ui.filter_query, 'x')
        self.assertFalse(ui.filter_mode)


class TestTagging(unittest.TestCase):
    def test_toggle_tag_selected_adds_then_removes_pid(self):
        ui = _ui()
        ui._last_view = [_node('/a', 1), _node('/b', 2)]
        ui.selected_row = 1
        ui._toggle_tag_selected()
        self.assertEqual(ui.tagged, {2})
        ui._toggle_tag_selected()
        self.assertEqual(ui.tagged, set())

    def test_toggle_tag_selected_out_of_range_is_a_noop(self):
        ui = _ui()
        ui._last_view = []
        ui.selected_row = 0
        ui._toggle_tag_selected()
        self.assertEqual(ui.tagged, set())


class TestKillTargets(unittest.TestCase):
    def test_single_target_when_nothing_tagged(self):
        ui = _ui()
        ui._last_view = [_node('/a', 1), _node('/b', 2)]
        ui.selected_row = 1
        self.assertEqual(ui._kill_targets(), [('/b', 2)])

    def test_batch_targets_when_pids_tagged(self):
        ui = _ui()
        ui._last_view = [_node('/a', 1), _node('/b', 2), _node('/c', 3)]
        ui.selected_row = 0
        ui.tagged = {2, 3}
        self.assertEqual(sorted(ui._kill_targets()), [('/b', 2), ('/c', 3)])

    def test_no_targets_when_view_empty(self):
        ui = _ui()
        ui._last_view = []
        ui.selected_row = 0
        self.assertEqual(ui._kill_targets(), [])


if __name__ == '__main__':
    unittest.main()
