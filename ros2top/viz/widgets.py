#!/usr/bin/env python3
"""Sidebar, plot tabs and summary panel for the visualiser."""

from typing import Dict, List, Optional, Sequence

import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

from ..recording.reader import Series
from ..recording.stats import CombinedStats
from .source import NodeEntry
from .theme import AXIS, BORDER, FG, MUTED, PANEL, pen_for

# Identifies the summed overlay curve, which has no PID of its own.
TOTAL_KEY = '__total__'


class Sidebar(QtWidgets.QWidget):
    """
    Process picker and mode switch.

    Emits `selection_changed` with the checked PIDs. The list is rebuilt as the
    graph changes, so it keeps check state keyed by PID rather than by row.
    """

    selection_changed = QtCore.pyqtSignal(list)
    record_toggled = QtCore.pyqtSignal(bool)
    load_requested = QtCore.pyqtSignal()
    live_requested = QtCore.pyqtSignal()
    combined_toggled = QtCore.pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(290)
        self._checked: set = set()
        self._building = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QtWidgets.QLabel("ros2top")
        title.setStyleSheet(
            f"color:{FG}; font-size:19px; font-weight:600; letter-spacing:0.5px;")
        layout.addWidget(title)

        self.source_label = QtWidgets.QLabel("Live graph")
        self.source_label.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        layout.addWidget(self.source_label)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.setSpacing(6)
        self.live_button = QtWidgets.QPushButton("Live")
        self.live_button.setCheckable(True)
        self.live_button.setChecked(True)
        self.live_button.clicked.connect(lambda: self.live_requested.emit())
        self.load_button = QtWidgets.QPushButton("Open recording…")
        self.load_button.clicked.connect(lambda: self.load_requested.emit())
        mode_row.addWidget(self.live_button)
        mode_row.addWidget(self.load_button, 1)
        layout.addLayout(mode_row)

        layout.addWidget(self._separator())

        header = QtWidgets.QHBoxLayout()
        nodes_label = QtWidgets.QLabel("PROCESSES")
        nodes_label.setStyleSheet(
            f"color:{MUTED}; font-size:10px; font-weight:600; letter-spacing:1px;")
        header.addWidget(nodes_label)
        header.addStretch(1)
        self.count_label = QtWidgets.QLabel("0")
        self.count_label.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        header.addWidget(self.count_label)
        layout.addLayout(header)

        self.filter_box = QtWidgets.QLineEdit()
        self.filter_box.setPlaceholderText("Filter by name…")
        self.filter_box.setClearButtonEnabled(True)
        self.filter_box.textChanged.connect(self._rebuild)
        layout.addWidget(self.filter_box)

        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.list, 1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(6)
        self.all_button = QtWidgets.QPushButton("All")
        self.none_button = QtWidgets.QPushButton("None")
        for b in (self.all_button, self.none_button):
            b.setFixedHeight(26)
            buttons.addWidget(b)
        self.all_button.clicked.connect(lambda: self._set_all(True))
        self.none_button.clicked.connect(lambda: self._set_all(False))
        layout.addLayout(buttons)

        layout.addWidget(self._separator())

        self.combined_check = QtWidgets.QCheckBox("Combined CPU of selection")
        self.combined_check.setChecked(True)
        self.combined_check.toggled.connect(self.combined_toggled)
        layout.addWidget(self.combined_check)

        self.record_button = QtWidgets.QPushButton("  Record")
        self.record_button.setCheckable(True)
        self.record_button.setFixedHeight(34)
        self.record_button.setObjectName("recordButton")
        self.record_button.toggled.connect(self._on_record_toggled)
        layout.addWidget(self.record_button)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        layout.addWidget(self.status_label)

        self._entries: List[NodeEntry] = []

    def _separator(self) -> QtWidgets.QFrame:
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setStyleSheet(f"color:{BORDER};")
        line.setFixedHeight(1)
        return line

    # -- population --------------------------------------------------------

    def set_entries(self, entries: Sequence[NodeEntry]):
        """Refresh the process list, preserving which PIDs were ticked."""
        self._entries = list(entries)
        live_pids = {e.pid for e in entries}
        # Drop ticks for processes that have gone away, or a dead PID would
        # keep contributing an empty tab and skew the combined figures.
        if self._checked - live_pids:
            self._checked &= live_pids
            self.selection_changed.emit(sorted(self._checked))
        self._rebuild()

    def _rebuild(self):
        needle = self.filter_box.text().strip().lower()
        self._building = True
        self.list.clear()
        shown = 0
        for entry in self._entries:
            if needle and needle not in entry.name.lower():
                continue
            shown += 1
            label = entry.name
            if entry.node_count > 1:
                label += f"  (+{entry.node_count - 1})"
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, entry.pid)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if entry.pid in self._checked
                               else QtCore.Qt.Unchecked)
            item.setToolTip(f"PID {entry.pid}\n{entry.name}"
                            + (f"\n{entry.node_count} nodes in this process"
                               if entry.node_count > 1 else ""))
            if entry.pid in self._checked:
                item.setForeground(QtGui.QColor(pen_for(
                    sorted(self._checked).index(entry.pid))))
            self.list.addItem(item)
        self.count_label.setText(f"{shown}/{len(self._entries)}"
                                  if needle else str(len(self._entries)))
        self._building = False

    def _on_item_changed(self, item: QtWidgets.QListWidgetItem):
        if self._building:
            return
        pid = item.data(QtCore.Qt.UserRole)
        if item.checkState() == QtCore.Qt.Checked:
            self._checked.add(pid)
        else:
            self._checked.discard(pid)
        self._rebuild()
        self.selection_changed.emit(sorted(self._checked))

    def _set_all(self, checked: bool):
        visible = []
        for i in range(self.list.count()):
            visible.append(self.list.item(i).data(QtCore.Qt.UserRole))
        if checked:
            self._checked.update(visible)
        else:
            self._checked.difference_update(visible)
        self._rebuild()
        self.selection_changed.emit(sorted(self._checked))

    def selected_pids(self) -> List[int]:
        return sorted(self._checked)

    def _on_record_toggled(self, on: bool):
        self.record_button.setText("  Stop recording" if on else "  Record")
        self.record_toggled.emit(on)

    def set_recording_state(self, on: bool):
        """Reflect state set elsewhere without re-emitting."""
        self.record_button.blockSignals(True)
        self.record_button.setChecked(on)
        self.record_button.setText("  Stop recording" if on else "  Record")
        self.record_button.blockSignals(False)

    def set_status(self, text: str):
        self.status_label.setText(text)

    def set_mode(self, live: bool, detail: str):
        self.live_button.setChecked(live)
        self.source_label.setText(detail)
        self.record_button.setEnabled(live)


class PlotTab(QtWidgets.QWidget):
    """CPU / RAM / GPU charts for one process, or for the whole selection."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.heading = QtWidgets.QLabel(title)
        self.heading.setStyleSheet(
            f"color:{FG}; font-size:14px; font-weight:600;")
        layout.addWidget(self.heading)

        self.cpu_plot = self._make_plot("CPU  %  of machine")
        self.ram_plot = self._make_plot("Memory  MB")
        self.gpu_plot = self._make_plot("GPU  %")
        for plot in (self.cpu_plot, self.ram_plot, self.gpu_plot):
            layout.addWidget(plot, 1)

        self._curves: Dict[str, Dict[int, pg.PlotDataItem]] = {
            'cpu': {}, 'ram': {}, 'gpu': {}}
        self.gpu_plot.hide()          # shown only if a GPU series appears

    def _make_plot(self, label: str) -> pg.PlotWidget:
        plot = pg.PlotWidget()
        plot.setBackground(PANEL)
        plot.showGrid(x=True, y=True, alpha=0.15)
        plot.setMenuEnabled(False)
        plot.setMouseEnabled(x=True, y=False)
        plot.setLabel('left', label)
        plot.getAxis('left').setPen(AXIS)
        plot.getAxis('bottom').setPen(AXIS)
        plot.getAxis('left').setTextPen(MUTED)
        plot.getAxis('bottom').setTextPen(MUTED)
        plot.setLabel('bottom', 'seconds')
        plot.setYRange(0, 1, padding=0.05)
        # Without a legend the only way to tell the lines apart is to count
        # colours against the sidebar, which is not a reasonable ask.
        legend = plot.addLegend(offset=(-8, 8), labelTextColor=FG,
                                brush=pg.mkBrush(PANEL), pen=pg.mkPen(BORDER))
        legend.setColumnCount(2)
        return plot

    def update_series(self, named: Sequence[tuple], total: Optional[Series] = None):
        """
        Draw `(identifier, colour_index, label, Series)` tuples.

        Curves are created once and given new data afterwards; recreating them
        every tick makes the view flicker and leaks plot items. `total`, when
        given, is overlaid as a thicker line - on the combined view the sum is
        the number people actually want, and adding lines up by eye is not it.
        """
        entries = list(named)
        if total is not None:
            entries.append((TOTAL_KEY, None, 'Total', total))

        # One time base for every curve in the tab. Re-basing each series on its
        # own first sample would slide processes discovered later leftwards and
        # line them up against the wrong moments of the others.
        starts = [s.t[0] for _, _, _, s in entries if s.t]
        base = min(starts) if starts else 0.0

        wanted = {ident for ident, _, _, _ in entries}
        for key, plot in (('cpu', self.cpu_plot), ('ram', self.ram_plot),
                          ('gpu', self.gpu_plot)):
            for stale in [k for k in self._curves[key] if k not in wanted]:
                plot.removeItem(self._curves[key].pop(stale))

        any_gpu = False
        for key, plot, getter in (
                ('cpu', self.cpu_plot, lambda s: s.cpu),
                ('ram', self.ram_plot, lambda s: s.ram),
                ('gpu', self.gpu_plot, lambda s: list(s.gpu))):
            peak = 0.0
            for ident, colour_index, label, series in entries:
                values = getter(series)
                if key == 'gpu':
                    if not series.has_gpu:
                        continue
                    any_gpu = True
                    values = [v if v is not None else 0.0 for v in values]
                if not series.t:
                    continue
                xs = [t - base for t in series.t]
                curve = self._curves[key].get(ident)
                if curve is None:
                    if ident == TOTAL_KEY:
                        pen = pg.mkPen(FG, width=3)
                    else:
                        pen = pg.mkPen(pen_for(colour_index), width=2)
                    curve = plot.plot(pen=pen, name=label)
                    self._curves[key][ident] = curve
                curve.setData(xs, values[:len(xs)])
                if values:
                    peak = max(peak, max(values))
                    # Put the live value in the legend, so a line hugging the
                    # axis is still readable as a number.
                    self._relabel(plot, curve, f"{label}   {values[-1]:.1f}")
            # A little headroom, and never a zero-height axis
            plot.setYRange(0, max(peak * 1.25, 1.0), padding=0)

        self.gpu_plot.setVisible(any_gpu)

    @staticmethod
    def _relabel(plot: pg.PlotWidget, curve: pg.PlotDataItem, text: str):
        legend = plot.plotItem.legend
        if legend is None:
            return
        for sample, label in legend.items:
            if sample.item is curve:
                label.setText(text)
                return


class SummaryPanel(QtWidgets.QWidget):
    """The four combined-CPU figures, with what each one means."""

    FIELDS = (
        ('Peak combined', 'peak_combined_pct', '%',
         'Most the selection ever drew at one instant. This happened.'),
        ('Sum of peaks', 'sum_of_peaks_pct', '%',
         'If every process peaked together. May never have occurred.'),
        ('Total CPU time', 'total_cpu_seconds', 'core-s',
         'Total work done over the run.'),
        ('Mean combined', 'mean_combined_pct', '%',
         'Time-weighted average of the combined series.'),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(66)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        self._values: Dict[str, QtWidgets.QLabel] = {}
        for label, attr, unit, tip in self.FIELDS:
            box = QtWidgets.QFrame()
            box.setObjectName("statBox")
            box.setToolTip(tip)
            inner = QtWidgets.QVBoxLayout(box)
            inner.setContentsMargins(10, 5, 10, 5)
            inner.setSpacing(1)

            caption = QtWidgets.QLabel(label.upper())
            caption.setStyleSheet(
                f"color:{MUTED}; font-size:9px; font-weight:600; letter-spacing:1px;")
            value = QtWidgets.QLabel("—")
            value.setStyleSheet(f"color:{FG}; font-size:17px; font-weight:600;")
            units = QtWidgets.QLabel(unit)
            units.setStyleSheet(f"color:{MUTED}; font-size:9px;")

            row = QtWidgets.QHBoxLayout()
            row.setSpacing(4)
            row.addWidget(value)
            row.addWidget(units)
            row.addStretch(1)

            inner.addWidget(caption)
            inner.addLayout(row)
            self._values[attr] = value
            layout.addWidget(box, 1)

    def show_stats(self, stats: Optional[CombinedStats]):
        if stats is None:
            for label in self._values.values():
                label.setText("—")
            return
        for _, attr, _, _ in self.FIELDS:
            self._values[attr].setText(f"{getattr(stats, attr):.1f}")
