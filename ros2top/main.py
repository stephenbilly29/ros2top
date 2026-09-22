#!/usr/bin/env python3
"""
Main entry point for ros2top
"""

import sys
import argparse
from . import __version__
from .node_monitor import NodeMonitor
from .ui.terminal_ui import run_ui, show_error_message


DESCRIPTION = 'Real-time monitor for ROS2 nodes showing CPU, RAM, and GPU usage'

EPILOG = """
Examples:
    ros2top                      # Run with default settings
    ros2top --refresh 2          # Refresh every 2 seconds
    ros2top --no-auto-discovery  # Only registered nodes

    Also available as a ros2 CLI sub-command:
    ros2 top                     # identical to `ros2top`

    Recording (headless, no UI; Ctrl-C or SIGTERM stops it):
    ros2top --record run.csv                    # every node found
    ros2top --record run.csv --pid 123 --pid 456
    ros2top --record run.csv --interval 0.5     # sample twice a second
    timeout 60 ros2top --record run.csv         # fixed-length run

    Controls:
    q/Q - Quit
    r/R - Force refresh node list
    h/H - Show help
    s/S - Sort column / reverse
    /   - Filter by node name
"""


def add_arguments(parser):
    """
    Add ros2top's arguments to a parser.

    Shared with the ros2cli plugin, which is handed a subparser rather than
    creating its own, so `ros2top` and `ros2 top` cannot drift apart.
    """
    parser.add_argument(
        '--refresh', '-r',
        type=float,
        default=0.1,
        help='Node refresh interval in seconds (default: 0.1)'
    )
    
    parser.add_argument(
        '--no-auto-discovery',
        action='store_true',
        help='Only show nodes that registered with ros2top, never those found '
             'on the ROS graph'
    )

    parser.add_argument(
        '--record',
        metavar='FILE',
        help='Record resource usage to a CSV instead of showing the UI. '
             'Runs headless until interrupted'
    )

    parser.add_argument(
        '--pid',
        type=int,
        action='append',
        dest='pids',
        metavar='PID',
        help='PID to record; repeat for several. Default: every node found'
    )

    parser.add_argument(
        '--interval',
        type=float,
        default=1.0,
        help='Seconds between recorded samples (default: 1.0)'
    )

    parser.add_argument(
        '--version', '-v',
        action='version',
        version=f'%(prog)s {__version__}'
    )

    return parser


def create_argument_parser():
    """Create command line argument parser for the standalone `ros2top`"""
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    return add_arguments(parser)


def check_requirements():
    """Check if required dependencies are available"""
    try:
        import psutil
    except ImportError:
        show_error_message("psutil is required but not installed. Run: pip install psutil")
        return False
    
    try:
        import curses
    except ImportError:
        show_error_message("curses is required but not available on this system")
        return False
    
    return True


def run_record(args) -> int:
    """
    Record to CSV headlessly until interrupted, for scripted and CI runs.

    No curses: this path must work over ssh, in a container and under `timeout`,
    so it only ever writes plain lines to stdout.
    """
    import signal
    import time

    from .recording.recorder import (
        Recorder, node_names_by_pid, select_pids, wait_for_nodes,
    )

    stop = {'requested': False}

    def _stop(_signum, _frame):
        stop['requested'] = True

    monitor = NodeMonitor(refresh_interval=0.0,
                          auto_discovery=not args.no_auto_discovery)

    # Nodes arrive from the graph over a second or two. Waiting for the count
    # to settle keeps the recording from freezing its PID set around whichever
    # few were discovered first.
    def _poll():
        monitor.update_nodes()
        return monitor.get_node_info_list()

    print("Waiting for node discovery to settle...", flush=True)
    nodes = wait_for_nodes(_poll)

    pids = select_pids(nodes, args.pids)
    if not pids:
        monitor.shutdown()
        print("Nothing to record: no nodes found.", file=sys.stderr)
        return 1

    missing = sorted(set(args.pids or []) - set(pids))
    if missing:
        print(f"Skipping PIDs that are not running: "
              f"{', '.join(str(p) for p in missing)}", file=sys.stderr)

    # Installed only now, and deliberately not before NodeMonitor: graph
    # discovery calls rclpy.init() on a daemon thread, so it lands at some
    # point after the constructor returns and installs rclpy's own SIGINT/
    # SIGTERM handlers over any set earlier. With ours lost, Ctrl-C and
    # `timeout` kill the process outright and the recording is never closed.
    # By the time discovery has settled, rclpy is up and will not do it again.
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        recorder = Recorder(args.record, pids=pids, cores=monitor.cores,
                            node_names=node_names_by_pid(nodes))
    except OSError as exc:
        monitor.shutdown()
        print(f"Cannot record to {args.record}: {exc}", file=sys.stderr)
        return 1

    print(f"Recording {len(pids)} process(es) to {args.record} "
          f"every {args.interval}s. Ctrl-C to stop.", flush=True)
    try:
        while not stop['requested']:
            monitor.update_nodes()
            monitor.cleanup_dead_processes()
            recorder.sample(monitor.get_node_info_list())
            time.sleep(args.interval)
    finally:
        recorder.close()
        monitor.shutdown()

    print(f"Wrote {recorder.row_count} rows over {recorder.elapsed:.1f}s "
          f"to {args.record}", flush=True)
    return 0


def run(args) -> int:
    """
    Run the monitor with already-parsed arguments, returning an exit code.

    Returns rather than exits so the ros2cli plugin can hand the code back to
    ros2cli instead of tearing the process down from underneath it.
    """
    # Check requirements
    if not check_requirements():
        return 1

    # Validate arguments
    if args.refresh <= 0:
        show_error_message("Refresh interval must be positive")
        return 1

    if getattr(args, 'record', None):
        if args.interval <= 0:
            show_error_message("Sample interval must be positive")
            return 1
        return run_record(args)

    # Create node monitor
    try:
        monitor = NodeMonitor(refresh_interval=args.refresh,
                              auto_discovery=not args.no_auto_discovery)
    except Exception as e:
        show_error_message(f"Failed to initialize node monitor: {e}")
        return 1

    # Run UI
    try:
        return 0 if run_ui(monitor) else 1
    except KeyboardInterrupt:
        print("\nGoodbye!")
        return 0
    except Exception as e:
        show_error_message(f"Unexpected error: {e}")
        return 1
    finally:
        # Cleanup background threads
        if hasattr(monitor, 'cleanup'):
            monitor.cleanup()


def main():
    """Entry point for the standalone `ros2top` command"""
    sys.exit(run(create_argument_parser().parse_args()))


if __name__ == '__main__':
    main()
