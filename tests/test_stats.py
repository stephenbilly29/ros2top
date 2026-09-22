#!/usr/bin/env python3
"""Tests for the combined-CPU statistics over a recording."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ros2top.recording.reader import Recording, Series
from ros2top.recording.stats import combined_cpu_stats


def _rec(cores, **pid_to_samples):
    """Build a Recording from {name: (pid, [(t, cpu), ...])} style kwargs."""
    series = {}
    for _, (pid, samples) in pid_to_samples.items():
        s = Series(pid=pid, node_name=f'/n{pid}')
        for t, cpu in samples:
            s.t.append(t)
            s.cpu.append(cpu)
            s.ram.append(0.0)
            s.gpu.append(None)
            s.gpu_mem.append(None)
            s.uptime.append(t)
        series[pid] = s
    duration = max((max(s.t) for s in series.values()), default=0.0)
    return Recording(cores=cores, duration_s=duration, series=series)


class TestWorkedExample(unittest.TestCase):
    """Two nodes that peak at different moments - the case that makes
    peak-combined and sum-of-peaks disagree."""

    def setUp(self):
        # A peaks at t=10, B at t=40. They never peak together.
        self.recording = _rec(16,
                              a=(1, [(10.0, 80.0), (40.0, 5.0)]),
                              b=(2, [(10.0, 5.0), (40.0, 70.0)]))

    def test_peak_combined_is_the_max_of_the_summed_series(self):
        # t=10 -> 80+5 = 85; t=40 -> 5+70 = 75
        self.assertAlmostEqual(combined_cpu_stats(self.recording).peak_combined_pct, 85.0)

    def test_sum_of_peaks_adds_each_pid_own_maximum(self):
        # 80 + 70, a moment that never actually occurred
        self.assertAlmostEqual(combined_cpu_stats(self.recording).sum_of_peaks_pct, 150.0)

    def test_total_cpu_seconds_scales_by_core_count(self):
        # trapezoid of combined: (85+75)/2 * 30s = 2400 %-seconds
        # -> 2400/100 * 16 cores = 384 core-seconds
        self.assertAlmostEqual(combined_cpu_stats(self.recording).total_cpu_seconds, 384.0)

    def test_mean_combined_is_the_time_weighted_average(self):
        # 2400 %-seconds over 30s
        self.assertAlmostEqual(combined_cpu_stats(self.recording).mean_combined_pct, 80.0)

    def test_duration_spans_the_selected_samples(self):
        self.assertAlmostEqual(combined_cpu_stats(self.recording).duration_s, 30.0)


class TestTimeWeighting(unittest.TestCase):
    def test_mean_is_time_weighted_not_a_sample_average(self):
        # 0% briefly, then 100% for a long stretch. A plain mean of the three
        # samples would say 66.7%; the honest answer is dominated by the long
        # stretch at 100%.
        recording = _rec(8, a=(1, [(0.0, 0.0), (1.0, 100.0), (11.0, 100.0)]))
        stats = combined_cpu_stats(recording)
        # trapezoid: (0+100)/2*1 + (100+100)/2*10 = 50 + 1000 = 1050 over 11s
        self.assertAlmostEqual(stats.mean_combined_pct, 1050.0 / 11.0)
        self.assertNotAlmostEqual(stats.mean_combined_pct, 200.0 / 3.0)


class TestDeadProcess(unittest.TestCase):
    def test_a_pid_that_stops_contributes_zero_afterwards(self):
        # B dies after t=1, so it draws nothing at t=2 - not "its last value".
        recording = _rec(8,
                         a=(1, [(0.0, 10.0), (1.0, 10.0), (2.0, 10.0)]),
                         b=(2, [(0.0, 20.0), (1.0, 20.0)]))
        stats = combined_cpu_stats(recording)
        self.assertAlmostEqual(stats.peak_combined_pct, 30.0)
        self.assertAlmostEqual(stats.sum_of_peaks_pct, 30.0)
        # trapezoid: (30+30)/2*1 + (30+10)/2*1 = 30 + 20 = 50 over 2s
        self.assertAlmostEqual(stats.mean_combined_pct, 25.0)


class TestSelection(unittest.TestCase):
    def setUp(self):
        self.recording = _rec(8,
                              a=(1, [(0.0, 10.0), (1.0, 10.0)]),
                              b=(2, [(0.0, 50.0), (1.0, 50.0)]))

    def test_all_pids_used_when_none_given(self):
        self.assertAlmostEqual(combined_cpu_stats(self.recording).peak_combined_pct, 60.0)

    def test_only_the_selected_pids_are_counted(self):
        stats = combined_cpu_stats(self.recording, pids=[1])
        self.assertAlmostEqual(stats.peak_combined_pct, 10.0)

    def test_unknown_pids_are_ignored(self):
        stats = combined_cpu_stats(self.recording, pids=[1, 9999])
        self.assertAlmostEqual(stats.peak_combined_pct, 10.0)


class TestDegenerateCases(unittest.TestCase):
    def test_empty_selection_is_all_zeros(self):
        recording = _rec(8, a=(1, [(0.0, 10.0)]))
        stats = combined_cpu_stats(recording, pids=[])
        self.assertEqual(stats.peak_combined_pct, 0.0)
        self.assertEqual(stats.sum_of_peaks_pct, 0.0)
        self.assertEqual(stats.total_cpu_seconds, 0.0)
        self.assertEqual(stats.mean_combined_pct, 0.0)
        self.assertEqual(stats.duration_s, 0.0)

    def test_recording_with_no_samples_is_all_zeros(self):
        stats = combined_cpu_stats(Recording(cores=8))
        self.assertEqual(stats.peak_combined_pct, 0.0)
        self.assertEqual(stats.total_cpu_seconds, 0.0)

    def test_single_sample_has_no_elapsed_time_so_no_cpu_seconds(self):
        recording = _rec(8, a=(1, [(5.0, 40.0)]))
        stats = combined_cpu_stats(recording)
        self.assertAlmostEqual(stats.peak_combined_pct, 40.0)
        self.assertAlmostEqual(stats.duration_s, 0.0)
        self.assertAlmostEqual(stats.total_cpu_seconds, 0.0)
        # With one observation the mean is simply that observation.
        self.assertAlmostEqual(stats.mean_combined_pct, 40.0)


if __name__ == '__main__':
    unittest.main()
