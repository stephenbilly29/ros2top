#!/usr/bin/env python3
"""The visualiser's main window: sidebar, per-process tabs, summary bar."""

import os
import time
from typing import Dict, List, Optional

from PyQt5 import QtCore, QtWidgets

from ..recording.reader import read_recording
from ..recording.stats import combined_cpu_stats
from .source import LiveSource, ReplaySource, combined_series
from .theme import STYLESHEET
from .widgets import PlotTab, Sidebar, SummaryPanel

COMBINED_TAB = 'combined'


class MainWindow(QtWidgets.QMainWindow):
    """
    Wires a source to the views.

    Everything on screen is driven by `_refresh()`, which is called on a timer
    in live mode and once per change in replay mode, so there is a single path
    that updates the tabs and the summary regardless of where data came from.
    """

    def __init__(self, source, interval_ms: int = 1000, parent=None):
        super().__init__(parent)
        self.source = source
        self.setWindowTitle("ros2top — live process monitor")
        self.resize(1320, 820)
        self.setStyleSheet(STYLESHEET)

        self.sidebar = Sidebar()
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.summary = SummaryPanel()

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(self.tabs, 1)
        right_layout.addWidget(self.summary)

        central = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        layout.addWidget(self.sidebar)
        layout.addWidget(right, 1)
        self.setCentralWidget(central)

        self.setStatusBar(QtWidgets.QStatusBar())
        self._placeholder = self._make_placeholder()
        self.tabs.addTab(self._placeholder, "Getting started")

        self._tabs_by_pid: Dict[int, PlotTab] = {}
        self._combined_tab: Optional[PlotTab] = None
        self._selected: List[int] = []
        self._show_combined = True
        self._record_path: Optional[str] = None

        self.sidebar.selection_changed.connect(self._on_selection_changed)
        self.sidebar.combined_toggled.connect(self._on_combined_toggled)
        self.sidebar.record_toggled.connect(self._on_record_toggled)
        self.sidebar.load_requested.connect(self._on_load_recording)
        self.sidebar.live_requested.connect(self._on_go_live)

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._interval_ms = interval_ms
        self._apply_mode()

    def _make_placeholder(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(page)
        box.addStretch(1)
        for text, size, colour in (
                ("Tick a process on the left to chart it", 16, "#e6e9ef"),
                ("Several at once open as separate tabs, and 'Combined CPU' "
                 "adds an overlay of the whole selection.", 12, "#8b93a3"),
                ("Record writes the selection to CSV; Open recording replays one.",
                 12, "#8b93a3")):
            label = QtWidgets.QLabel(text)
            label.setAlignment(QtCore.Qt.AlignCenter)
            label.setWordWrap(True)
            label.setStyleSheet(f"color:{colour}; font-size:{size}px;")
            box.addWidget(label)
        box.addStretch(1)
        return page

    # -- modes -------------------------------------------------------------

    def _apply_mode(self):
        live = isinstance(self.source, LiveSource)
        if live:
            self.sidebar.set_mode(True, "Live graph")
            self._timer.start(self._interval_ms)
            self.statusBar().showMessage("Waiting for nodes…")
        else:
            self._timer.stop()
            name = os.path.basename(getattr(self.source, 'path', '')) or 'recording'
            self.sidebar.set_mode(False, f"Replaying {name}")
            # Whatever the live session was saying no longer applies
            self.sidebar.set_status("")
            self._record_path = None
            rec = self.source.snapshot()
            self.statusBar().showMessage(
                f"{name} — {len(rec.series)} processes, {rec.duration_s:.1f}s, "
                f"{rec.cores} cores")
        self._refresh()

    def _on_go_live(self):
        if isinstance(self.source, LiveSource):
            self.sidebar.set_mode(True, "Live graph")
            return
        if self._live_source is None:
            self.sidebar.set_mode(False, "No live source available")
            return
        self.source = self._live_source
        self._reset_tabs()
        self._apply_mode()

    _live_source = None

    def _on_load_recording(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open ros2top recording", os.getcwd(), "CSV recordings (*.csv)")
        if not path:
            return
        self.load_recording(path)

    def load_recording(self, path: str):
        try:
            recording = read_recording(path)
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "Could not open recording", str(exc))
            return
        if isinstance(self.source, LiveSource):
            if self.source.is_recording:
                self.source.stop_recording()
                self.sidebar.set_recording_state(False)
            type(self)._live_source = self.source
        self.source = ReplaySource(recording, path=path)
        self._reset_tabs()
        self._apply_mode()

    def _reset_tabs(self):
        self.tabs.clear()
        self._tabs_by_pid.clear()
        self._combined_tab = None
        self._selected = []
        self.tabs.addTab(self._placeholder, "Getting started")

    # -- events ------------------------------------------------------------

    def _tick(self):
        self.source.poll()
        self._refresh()

    def _on_selection_changed(self, pids: List[int]):
        self._selected = list(pids)
        self._sync_tabs()
        self._refresh()

    def _on_combined_toggled(self, on: bool):
        self._show_combined = on
        self._sync_tabs()
        self._refresh()

    def _on_record_toggled(self, on: bool):
        if not isinstance(self.source, LiveSource):
            return
        if on:
            if not self._selected:
                QtWidgets.QMessageBox.information(
                    self, "Nothing selected",
                    "Tick the processes you want to record first.")
                self.sidebar.set_recording_state(False)
                return
            default = os.path.join(
                os.getcwd(), time.strftime("ros2top-%Y%m%d-%H%M%S.csv"))
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Record to", default, "CSV recordings (*.csv)")
            if not path:
                self.sidebar.set_recording_state(False)
                return
            try:
                self.source.start_recording(path, self._selected)
            except OSError as exc:
                QtWidgets.QMessageBox.warning(self, "Cannot record", str(exc))
                self.sidebar.set_recording_state(False)
                return
            self._record_path = path
            self.sidebar.set_status(
                f"Recording {len(self._selected)} process(es) → "
                f"{os.path.basename(path)}")
        else:
            self.source.stop_recording()
            if self._record_path:
                self.sidebar.set_status(
                    f"Saved {os.path.basename(self._record_path)}")
            self._record_path = None

    # -- rendering ---------------------------------------------------------

    def _sync_tabs(self):
        """Add/remove tabs so they match the selection, keeping existing ones."""
        entries = {e.pid: e for e in self.source.available()}

        for pid in list(self._tabs_by_pid):
            if pid not in self._selected:
                tab = self._tabs_by_pid.pop(pid)
                index = self.tabs.indexOf(tab)
                if index >= 0:
                    self.tabs.removeTab(index)
                tab.deleteLater()

        for pid in self._selected:
            if pid in self._tabs_by_pid:
                continue
            entry = entries.get(pid)
            name = entry.name if entry else f"pid {pid}"
            tab = PlotTab(f"{name}    ·    pid {pid}")
            self._tabs_by_pid[pid] = tab
            self.tabs.addTab(tab, self._labels().get(pid, self._short(name)))

        want_combined = self._show_combined and len(self._selected) >= 1
        if want_combined and self._combined_tab is None:
            self._combined_tab = PlotTab("Combined — all selected processes")
            self.tabs.addTab(self._combined_tab, "Combined")
        elif not want_combined and self._combined_tab is not None:
            index = self.tabs.indexOf(self._combined_tab)
            if index >= 0:
                self.tabs.removeTab(index)
            self._combined_tab.deleteLater()
            self._combined_tab = None

        placeholder_index = self.tabs.indexOf(self._placeholder)
        if self._selected and placeholder_index >= 0:
            self.tabs.removeTab(placeholder_index)
        elif not self._selected and placeholder_index < 0:
            self.tabs.insertTab(0, self._placeholder, "Getting started")

    @staticmethod
    def _short(name: str) -> str:
        leaf = name.rstrip('/').split('/')[-1] or name
        return leaf[:22]

    def _labels(self) -> Dict[int, str]:
        """
        Display name per PID, disambiguated when names repeat.

        Two processes can genuinely run the same node name, and identical
        legend entries would be unreadable, so those get their PID appended.
        """
        entries = self.source.available()
        seen: Dict[str, int] = {}
        for entry in entries:
            seen[entry.name] = seen.get(entry.name, 0) + 1
        return {e.pid: (f"{self._short(e.name)} ({e.pid})" if seen[e.name] > 1
                        else self._short(e.name))
                for e in entries}

    def _refresh(self):
        self.sidebar.set_entries(self.source.available())

        labels = self._labels()
        for pid, tab in self._tabs_by_pid.items():
            index = self._selected.index(pid) if pid in self._selected else 0
            tab.update_series(
                [(pid, index, labels.get(pid, str(pid)), self.source.series(pid))])

        if self._combined_tab is not None:
            series = [self.source.series(pid) for pid in self._selected]
            tab_data = [(pid, i, labels.get(pid, str(pid)), s)
                        for i, (pid, s) in enumerate(zip(self._selected, series))]
            # Only worth overlaying a sum when there is more than one line to add
            total = combined_series(series) if len(series) > 1 else None
            self._combined_tab.update_series(tab_data, total=total)

        if self._selected:
            stats = combined_cpu_stats(self.source.snapshot(), pids=self._selected)
            self.summary.show_stats(stats)
        else:
            self.summary.show_stats(None)

        if isinstance(self.source, LiveSource):
            count = len(self.source.available())
            state = (f"  ·  recording → {os.path.basename(self._record_path)} "
                     f"({self.source.recorded_rows} rows)"
                     if self.source.is_recording and self._record_path else "")
            self.statusBar().showMessage(
                f"{count} processes on the graph  ·  "
                f"{len(self._selected)} selected{state}")

    def closeEvent(self, event):
        self._timer.stop()
        if isinstance(self.source, LiveSource) and self.source.is_recording:
            self.source.stop_recording()
        super().closeEvent(event)
