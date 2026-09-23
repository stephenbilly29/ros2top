#!/usr/bin/env python3
"""
Entry point for `ros2top-viz`.

Qt is imported inside main(), never at module scope, so a core install without
the `viz` extra gets a one-line instruction instead of an import traceback.
"""

import argparse
import sys

DESCRIPTION = 'Live charts and recording playback for ROS 2 process usage'

MISSING_DEPS = """\
ros2top-viz needs the GUI extra, which is not installed.

    pip install "ros2top[viz]"

(that pulls in PyQt5 and pyqtgraph; the `ros2top` terminal UI needs neither)
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    ros2top-viz                     # live view of the ROS 2 graph
    ros2top-viz run.csv             # open a recording made by `ros2top --record`
    ros2top-viz --interval 0.5      # sample twice a second
    ros2top-viz --window 120        # keep two minutes of history on screen
""")
    parser.add_argument('recording', nargs='?',
                        help='A CSV from `ros2top --record` to open instead of '
                             'the live graph')
    parser.add_argument('--interval', type=float, default=1.0,
                        help='Seconds between live samples (default: 1.0)')
    parser.add_argument('--window', type=float, default=60.0,
                        help='Seconds of history shown on the charts (default: 60)')
    parser.add_argument('--history', type=float, default=3600.0,
                        help='Seconds of samples kept for the combined figures '
                             '(default: 3600)')
    parser.add_argument('--no-auto-discovery', action='store_true',
                        help='Only show nodes that registered with ros2top')
    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        from PyQt5 import QtWidgets
    except ImportError:
        print(MISSING_DEPS, file=sys.stderr)
        return 1
    try:
        import pyqtgraph  # noqa: F401
    except ImportError:
        print(MISSING_DEPS, file=sys.stderr)
        return 1

    from ..node_monitor import NodeMonitor
    from .main_window import MainWindow
    from .source import LiveSource, ReplaySource
    from ..recording.reader import read_recording

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName('ros2top-viz')

    monitor = None
    if args.recording:
        try:
            source = ReplaySource(read_recording(args.recording),
                                  path=args.recording)
        except (OSError, ValueError) as exc:
            print(f"Cannot open {args.recording}: {exc}", file=sys.stderr)
            return 1
    else:
        monitor = NodeMonitor(refresh_interval=0.0,
                              auto_discovery=not args.no_auto_discovery)
        source = LiveSource(monitor, window_s=args.window,
                            history_s=args.history)

    window = MainWindow(source, interval_ms=int(args.interval * 1000))
    window.show()
    try:
        return app.exec_()
    finally:
        if monitor is not None:
            monitor.shutdown()


if __name__ == '__main__':
    sys.exit(main())
