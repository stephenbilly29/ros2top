#!/usr/bin/env python3
"""
One place for the visualiser's colours.

A dark palette, because this sits next to a terminal and beside RViz, and a
light grey Qt default would be the odd one out. Series colours are picked to
stay distinguishable against the dark panels and from each other.
"""

BG = '#14161a'          # window
PANEL = '#1b1e24'       # plot and card backgrounds
BORDER = '#2b3038'
FG = '#e6e9ef'          # primary text
MUTED = '#8b93a3'       # captions, axes
ACCENT = '#4c9be8'
DANGER = '#e0574a'      # recording

# Ordered so the first few are maximally distinct - most selections are small.
SERIES_COLOURS = (
    '#4c9be8',  # blue
    '#f5a65b',  # amber
    '#5ec9a0',  # green
    '#e06c9f',  # pink
    '#b48ee8',  # violet
    '#e0d267',  # yellow
    '#6fd0e0',  # cyan
    '#e0574a',  # red
)

AXIS = '#3a404a'


def pen_for(index: int) -> str:
    """A stable colour for the Nth selected process."""
    return SERIES_COLOURS[index % len(SERIES_COLOURS)]


STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {FG};
    font-family: "Ubuntu", "DejaVu Sans", sans-serif;
    font-size: 12px;
}}
QLineEdit {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px 8px;
    color: {FG};
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
QListWidget {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 2px;
    outline: none;
}}
QListWidget::item {{ padding: 5px 4px; border-radius: 3px; }}
QListWidget::item:hover {{ background: #232830; }}
QPushButton {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 10px;
    color: {FG};
}}
QPushButton:hover {{ background: #232830; border: 1px solid #3c4250; }}
QPushButton:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: #0d1117; }}
QPushButton:disabled {{ color: {MUTED}; background: #191c21; }}
QPushButton#recordButton {{ font-weight: 600; }}
QPushButton#recordButton:checked {{ background: {DANGER}; border: 1px solid {DANGER}; color: #fff; }}
QFrame#statBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 5px;
}}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 4px; top: -1px; }}
QTabBar::tab {{
    background: {BG};
    color: {MUTED};
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    padding: 6px 14px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {PANEL}; color: {FG}; }}
QCheckBox {{ spacing: 7px; }}
QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QStatusBar {{ color: {MUTED}; border-top: 1px solid {BORDER}; }}
QToolTip {{
    background: {PANEL}; color: {FG};
    border: 1px solid {BORDER}; padding: 4px;
}}
"""
