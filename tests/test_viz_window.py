#!/usr/bin/env python3
"""
Headless smoke tests for the Qt window.

Run under an offscreen Qt platform so they work in CI and over ssh. Skipped
entirely when the `viz` extra is not installed, since the terminal UI does not
need it.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

try:
    from PyQt5 import QtWidgets
    import pyqtgraph  # noqa: F401
    HAVE_QT = True
except ImportError:                                  # pragma: no cover
    HAVE_QT = False

from ros2top.node_monitor import NodeInfo
from ros2top.recording.reader import Recording, Series

if HAVE_QT:
    from ros2top.viz.main_window import MainWindow
    from ros2top.viz.source import LiveSource, ReplaySource


def _recording(pids=(1, 2), cores=8):
    series = {}
    for i, pid in enumerate(pids):
        series[pid] = Series(
            pid=pid, node_name=f'/node{pid}', node_count=1,
            t=[0.0, 1.0, 2.0],
            cpu=[10.0 * (i + 1), 20.0 * (i + 1), 15.0 * (i + 1)],
            ram=[100.0, 110.0, 105.0],
            gpu=[None, None, None], gpu_mem=[None, None, None],
            uptime=[0.0, 1.0, 2.0])
    return Recording(cores=cores, duration_s=2.0, series=series)


@unittest.skipUnless(HAVE_QT, "PyQt5/pyqtgraph not installed (viz extra)")
class TestMainWindow(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _window(self, recording=None):
        window = MainWindow(ReplaySource(recording or _recording(), path='demo.csv'))
        self.addCleanup(window.close)
        return window

    def test_opens_with_the_recorded_processes_listed(self):
        window = self._window()
        self.assertEqual(window.sidebar.list.count(), 2)

    def test_starts_on_a_getting_started_tab_with_nothing_selected(self):
        window = self._window()
        self.assertEqual(window.tabs.count(), 1)
        self.assertEqual(window.tabs.tabText(0), "Getting started")

    def test_selecting_a_process_opens_its_tab(self):
        window = self._window()
        window._on_selection_changed([1])
        titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        self.assertIn('node1', titles)
        self.assertNotIn("Getting started", titles)

    def test_combined_tab_appears_alongside_per_process_tabs(self):
        window = self._window()
        window._on_selection_changed([1, 2])
        titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        self.assertIn('Combined', titles)
        self.assertEqual(len(titles), 3)          # two processes + combined

    def test_unticking_combined_removes_only_that_tab(self):
        window = self._window()
        window._on_selection_changed([1, 2])
        window._on_combined_toggled(False)
        titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        self.assertNotIn('Combined', titles)
        self.assertEqual(len(titles), 2)

    def test_deselecting_everything_restores_the_placeholder(self):
        window = self._window()
        window._on_selection_changed([1])
        window._on_selection_changed([])
        self.assertEqual(window.tabs.tabText(0), "Getting started")

    def test_summary_fills_in_for_a_selection(self):
        window = self._window()
        window._on_selection_changed([1, 2])
        # peak combined = 20 + 40 at t=1
        self.assertEqual(window.summary._values['peak_combined_pct'].text(), '60.0')

    def test_summary_blanks_when_nothing_is_selected(self):
        window = self._window()
        window._on_selection_changed([1])
        window._on_selection_changed([])
        self.assertEqual(window.summary._values['peak_combined_pct'].text(), '—')

    def test_replay_mode_disables_recording(self):
        window = self._window()
        self.assertFalse(window.sidebar.record_button.isEnabled())

    def test_gpu_chart_stays_hidden_without_gpu_data(self):
        window = self._window()
        window._on_selection_changed([1])
        tab = window._tabs_by_pid[1]
        self.assertFalse(tab.gpu_plot.isVisible())

    def test_sidebar_filter_narrows_the_list(self):
        window = self._window()
        window.sidebar.filter_box.setText('node2')
        self.assertEqual(window.sidebar.list.count(), 1)

    def test_curves_share_one_time_base(self):
        # A process discovered later starts at a later timestamp. Re-basing each
        # curve on its own first sample would slide it left and align it against
        # the wrong moments of the others.
        late = _recording(pids=(1,))
        late.series[2] = Series(pid=2, node_name='/late', node_count=1,
                                t=[5.0, 6.0], cpu=[50.0, 50.0], ram=[10.0, 10.0],
                                gpu=[None, None], gpu_mem=[None, None],
                                uptime=[0.0, 1.0])
        window = self._window(late)
        window._on_selection_changed([1, 2])

        tab = window._combined_tab
        xs_early = tab._curves['cpu'][1].getData()[0]
        xs_late = tab._curves['cpu'][2].getData()[0]
        self.assertAlmostEqual(xs_early[0], 0.0)
        self.assertAlmostEqual(xs_late[0], 5.0)     # not re-zeroed

    def test_combined_tab_overlays_a_total_curve(self):
        window = self._window()
        window._on_selection_changed([1, 2])
        self.assertIn('__total__', window._combined_tab._curves['cpu'])

    def test_no_total_curve_for_a_single_process(self):
        window = self._window()
        window._on_selection_changed([1])
        self.assertNotIn('__total__', window._combined_tab._curves['cpu'])

    def test_summary_states_the_period_it_covers(self):
        # Identical labels meaning "last 60s" live and "whole file" in replay is
        # how someone quotes the wrong number. The period is on screen.
        window = self._window()
        window._on_selection_changed([1, 2])
        self.assertIn('2.0 s', window.summary.period_label.text())
        self.assertIn('recording', window.summary.period_label.text().lower())

    def test_summary_period_is_blank_with_no_selection(self):
        window = self._window()
        self.assertEqual(window.summary.period_label.text(), '')

    def test_refresh_is_safe_to_call_repeatedly(self):
        window = self._window()
        window._on_selection_changed([1, 2])
        for _ in range(5):
            window._refresh()
        self.assertEqual(window.tabs.count(), 3)

    def test_replay_mode_disables_clearing(self):
        # A file is its own history; there is nothing on screen to reset.
        window = self._window()
        self.assertFalse(window.sidebar.clear_button.isEnabled())


class _FakeMonitor:
    """Stands in for NodeMonitor with a fixed pair of processes."""

    cores = 8

    def __init__(self, cpu=10.0):
        self.cpu = cpu

    def update_nodes(self):
        pass

    def cleanup_dead_processes(self):
        pass

    def get_node_info_list(self):
        return [NodeInfo(name=f'/node{pid}', pid=pid, cpu_percent=self.cpu,
                         ram_mb=100.0, gpu_memory_mb=0, gpu_utilization=0.0,
                         gpu_device_id=-1, start_time=0.0, shared_count=1,
                         auto_discovered=False)
                for pid in (1, 2)]


@unittest.skipUnless(HAVE_QT, "PyQt5/pyqtgraph not installed (viz extra)")
class TestClearHistory(unittest.TestCase):
    """The Clear history button, which re-bases the figures on the moment it
    is pressed rather than on when the app was opened."""

    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _window(self, cpu=10.0):
        self.monitor = _FakeMonitor(cpu=cpu)
        window = MainWindow(LiveSource(self.monitor))
        window._timer.stop()             # drive the polling from the test
        self.addCleanup(window.close)
        return window

    def test_the_button_clears_the_retained_history(self):
        window = self._window()
        window.source.poll(now=0.0)
        window.source.poll(now=10.0)
        window.sidebar.clear_button.click()
        self.assertEqual(window.source.snapshot().series, {})

    def test_clearing_empties_the_open_charts(self):
        # An emptied series leaves the previous curve painted unless the tab is
        # told to drop it, which would show stale data under a cleared summary.
        window = self._window()
        window.source.poll(now=0.0)
        window._refresh()
        window._on_selection_changed([1])
        self.assertTrue(window._tabs_by_pid[1]._curves['cpu'])

        window.sidebar.clear_button.click()
        self.assertEqual(window._tabs_by_pid[1]._curves['cpu'], {})

    def test_clearing_keeps_the_selection_and_its_tabs(self):
        window = self._window()
        window.source.poll(now=0.0)
        window._refresh()
        window._on_selection_changed([1, 2])
        titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]

        window.sidebar.clear_button.click()
        self.assertEqual(window._selected, [1, 2])
        self.assertEqual([window.tabs.tabText(i)
                          for i in range(window.tabs.count())], titles)

    def test_a_cleared_chart_stops_advertising_the_discarded_span(self):
        # The axis keeps whatever range the old data auto-ranged it to, so an
        # emptied chart was still labelled with the seconds just thrown away.
        window = self._window()
        for t in range(0, 40, 2):
            window.source.poll(now=float(t))
        window._refresh()
        window._on_selection_changed([1])
        tab = window._tabs_by_pid[1]
        self.app.processEvents()          # auto-range runs on the event loop
        self.assertGreater(tab.cpu_plot.viewRange()[0][1], 20.0)

        window.sidebar.clear_button.click()
        self.app.processEvents()
        self.assertLess(tab.cpu_plot.viewRange()[0][1], 20.0)

    def test_charts_refill_after_a_clear(self):
        window = self._window()
        window.source.poll(now=0.0)
        window._refresh()
        window._on_selection_changed([1])
        window.sidebar.clear_button.click()

        window.source.poll(now=1.0)
        window._refresh()
        self.assertTrue(window._tabs_by_pid[1]._curves['cpu'])

    def test_clearing_forgets_an_earlier_spike_in_the_summary(self):
        window = self._window(cpu=90.0)
        window.source.poll(now=0.0)
        window._refresh()
        window._on_selection_changed([1])
        self.assertEqual(window.summary._values['peak_combined_pct'].text(), '90.0')

        window.sidebar.clear_button.click()
        self.monitor.cpu = 5.0
        window.source.poll(now=1.0)
        window._refresh()
        self.assertEqual(window.summary._values['peak_combined_pct'].text(), '5.0')

    def test_clearing_says_what_it_did(self):
        window = self._window()
        window.source.poll(now=0.0)
        window.sidebar.clear_button.click()
        self.assertIn('cleared', window.sidebar.status_label.text().lower())

    def test_clearing_mid_recording_says_the_file_is_untouched(self):
        # "Clear" sitting next to "Stop recording" reasonably reads as throwing
        # the recording away. It does not, and the status line has to say so.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        window = self._window()
        window.source.poll(now=0.0)
        window._on_selection_changed([1])
        window.source.start_recording(os.path.join(tmp.name, 'r.csv'), pids=[1])
        self.addCleanup(window.source.stop_recording)

        window.sidebar.clear_button.click()
        text = window.sidebar.status_label.text().lower()
        self.assertIn('recording', text)
        self.assertTrue(window.source.is_recording)


if __name__ == '__main__':
    unittest.main()
