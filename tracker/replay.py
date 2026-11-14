"""CSV sensor-log replay and ASCII trace-printing CLI for Gate B tuning and Bronze fallback.

Usage:
    python3 -m tracker.replay path/to/walk.csv
    python3 -m tracker.replay data/logs
    python3 -m tracker.replay path/to/walk.csv --step-length 0.72 --turn-rate 28 --min-turn 40
    python3 -m tracker.replay --demo-synthetic

Every output begins with an explicit REPLAY or SYNTHETIC WALK banner so a logged
or generated trace is never mistaken for live band sensing.
"""
import argparse
from dataclasses import dataclass
import math
import os
import sys
from typing import Iterable, List, Optional, Sequence

import config
from interfaces import PoseSample
from tracker.events import Event, read_log, synthetic_walk
from tracker.pdr import PathTracker


@dataclass
class PoseRow:
    """One row of the replay pose table."""
    step: int
    t_rel: float
    x_m: float
    y_m: float
    heading_deg: float
    uncertainty_deg: float
    red_led: bool


@dataclass
class ReplayReport:
    """Computed replay trace, step rows, and summary metrics."""
    label: str
    is_synthetic: bool
    duration_s: float
    total_steps: int
    path_length_m: float
    net_displacement_m: float
    final_pose: PoseSample
    calibrated: bool
    bias_dps: float
    peak_uncertainty_deg: float
    red_led_triggered: bool
    step_length_m: float
    snap_turns: bool
    turn_rate_dps: float
    turn_settle_s: float
    min_turn_deg: float
    uncertainty_threshold_deg: float
    rows: List[PoseRow]
    points: List[PoseSample]


def replay_events(
    events: Sequence[Event],
    label: str = "<events>",
    is_synthetic: bool = False,
    step_length_m: Optional[float] = None,
    snap_turns: Optional[bool] = None,
    turn_rate_dps: Optional[float] = None,
    turn_settle_s: Optional[float] = None,
    min_turn_deg: Optional[float] = None,
    uncertainty_threshold_deg: Optional[float] = None,
) -> ReplayReport:
    """Feed recorded or synthetic events into a fresh PathTracker and collect metrics."""
    tracker = PathTracker(
        step_length_m=step_length_m,
        snap_turns=snap_turns,
        turn_rate_dps=turn_rate_dps,
        turn_settle_s=turn_settle_s,
        min_turn_deg=min_turn_deg,
        uncertainty_threshold_deg=uncertainty_threshold_deg,
    )
    t0 = events[0][1] if events else 0.0
    first = tracker.start(t0)

    rows: List[PoseRow] = [
        PoseRow(
            step=first.steps,
            t_rel=0.0,
            x_m=first.x_m,
            y_m=first.y_m,
            heading_deg=first.heading_deg,
            uncertainty_deg=tracker.uncertainty_deg,
            red_led=tracker.heading_uncertain,
        )
    ]
    red_triggered = [False]
    peak_unc = [0.0]

    def on_uncertain(flag: bool):
        if flag:
            red_triggered[0] = True

    def on_sample(sample: PoseSample):
        if tracker.uncertainty_deg > peak_unc[0]:
            peak_unc[0] = tracker.uncertainty_deg
        if tracker.heading_uncertain:
            red_triggered[0] = True
        rows.append(
            PoseRow(
                step=sample.steps,
                t_rel=max(0.0, sample.t - t0),
                x_m=sample.x_m,
                y_m=sample.y_m,
                heading_deg=sample.heading_deg,
                uncertainty_deg=tracker.uncertainty_deg,
                red_led=tracker.heading_uncertain,
            )
        )

    tracker.on_uncertainty(on_uncertain)
    tracker.on_sample(on_sample)

    for kind, t, fields in events:
        if kind == "motion":
            tracker.on_motion(
                t,
                fields["ax"],
                fields["ay"],
                fields["az"],
                fields["gx"],
                fields["gy"],
                fields["gz"],
            )
        elif kind == "activity":
            tracker.on_activity(t, fields["steps"], fields["state"])
        if tracker.uncertainty_deg > peak_unc[0]:
            peak_unc[0] = tracker.uncertainty_deg
        if tracker.heading_uncertain:
            red_triggered[0] = True

    tracker.stop()
    duration_s = max(0.0, events[-1][1] - t0) if events else 0.0
    pts = list(tracker.points)
    path_len = 0.0
    for i in range(1, len(pts)):
        path_len += math.hypot(pts[i].x_m - pts[i - 1].x_m, pts[i].y_m - pts[i - 1].y_m)
    end_pose = tracker.pose
    net_disp = math.hypot(end_pose.x_m, end_pose.y_m)

    return ReplayReport(
        label=label,
        is_synthetic=is_synthetic,
        duration_s=duration_s,
        total_steps=end_pose.steps,
        path_length_m=path_len,
        net_displacement_m=net_disp,
        final_pose=end_pose,
        calibrated=tracker.calibrated,
        bias_dps=tracker.bias,
        peak_uncertainty_deg=peak_unc[0],
        red_led_triggered=red_triggered[0],
        step_length_m=tracker.step_length_m,
        snap_turns=tracker.snap_turns,
        turn_rate_dps=tracker.turn_rate_dps,
        turn_settle_s=tracker.turn_settle_s,
        min_turn_deg=tracker.min_turn_deg,
        uncertainty_threshold_deg=tracker.uncertainty_threshold_deg,
        rows=rows,
        points=pts,
    )


def replay_file(
    path: str,
    step_length_m: Optional[float] = None,
    snap_turns: Optional[bool] = None,
    turn_rate_dps: Optional[float] = None,
    turn_settle_s: Optional[float] = None,
    min_turn_deg: Optional[float] = None,
    uncertainty_threshold_deg: Optional[float] = None,
) -> ReplayReport:
    """Read a CSV sensor log from disk and replay it through PathTracker."""
    events = read_log(path)
    return replay_events(
        events,
        label=path,
        is_synthetic=False,
        step_length_m=step_length_m,
        snap_turns=snap_turns,
        turn_rate_dps=turn_rate_dps,
        turn_settle_s=turn_settle_s,
        min_turn_deg=min_turn_deg,
        uncertainty_threshold_deg=uncertainty_threshold_deg,
    )


def format_trace(points: Sequence[PoseSample], width: int = 50, height: int = 20) -> str:
    """Render a 2D top-down ASCII trace (+x right, +y up, S=start, E=end, *=sample)."""
    inner_w = max(12, width - 2)
    inner_h = max(8, height - 2)
    grid = [[" " for _ in range(inner_w)] for _ in range(inner_h)]

    if not points:
        points = [PoseSample(0.0, 0.0, 0.0, 0.0, 0)]

    xs = [p.x_m for p in points] + [0.0]
    ys = [p.y_m for p in points] + [0.0]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    plot_w = max(4, inner_w - 2)
    plot_h = max(4, inner_h - 2)
    char_aspect = 2.0  # terminal cells are roughly twice as tall as wide
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    m_per_col = max(span_x / (plot_w - 1), (span_y / (plot_h - 1)) / char_aspect)
    m_per_row = m_per_col * char_aspect
    mid_x = 0.5 * (min_x + max_x)
    mid_y = 0.5 * (min_y + max_y)

    def to_cell(x: float, y: float):
        c = 1 + int(round((plot_w - 1) * 0.5 + (x - mid_x) / m_per_col))
        r = 1 + int(round((plot_h - 1) * 0.5 - (y - mid_y) / m_per_row))
        c = max(1, min(inner_w - 2, c))
        r = max(1, min(inner_h - 2, r))
        return c, r

    coords = [to_cell(p.x_m, p.y_m) for p in points]

    # Interpolate connecting segments with '.'
    for i in range(1, len(coords)):
        c0, r0 = coords[i - 1]
        c1, r1 = coords[i]
        steps = max(abs(c1 - c0), abs(r1 - r0))
        if steps > 1:
            for k in range(1, steps):
                ci = int(round(c0 + (c1 - c0) * (k / float(steps))))
                ri = int(round(r0 + (r1 - r0) * (k / float(steps))))
                if grid[ri][ci] == " ":
                    grid[ri][ci] = "."

    # Mark sampled pose breadcrumbs with '*'
    for c, r in coords[1:-1]:
        grid[r][c] = "*"

    sc, sr = coords[0]
    ec, er = coords[-1]
    grid[sr][sc] = "S"
    if len(coords) > 1 and (ec, er) != (sc, sr):
        grid[er][ec] = "E"

    border = "+" + ("-" * inner_w) + "+"
    lines = [
        "Top-down 2D trace (+y up, +x right; x=[%.1f, %.1f] m, y=[%.1f, %.1f] m):"
        % (min_x, max_x, min_y, max_y),
        border,
    ]
    for row in grid:
        lines.append("|" + "".join(row) + "|")
    lines.append(border)
    overlap_note = " (E overlaps S)" if (len(coords) == 1 or (ec, er) == (sc, sr)) else ""
    lines.append("Legend: S=start (0,0)  E=end%s  *=step sample  .=segment" % overlap_note)
    return "\n".join(lines)


render_ascii_trace = format_trace


def format_report(report: ReplayReport, width: int = 50, height: int = 20) -> str:
    """Format banner, pose table, summary block, and ASCII trace."""
    out: List[str] = []
    if report.is_synthetic:
        out.append("SYNTHETIC WALK (not real sensing): %s" % report.label)
    else:
        out.append("REPLAY: %s (recorded sensor log, NOT live sensing)" % report.label)
    out.append("")

    out.append("Pose samples:")
    out.append(
        "  %5s  %7s  %8s  %8s  %8s  %9s  %s"
        % ("step", "t_rel", "x_m", "y_m", "hdg_deg", "unc_deg", "RED_LED")
    )
    out.append("  " + ("-" * 60))
    for row in report.rows:
        flag = "RED_LED" if row.red_led else "-"
        out.append(
            "  %5d  %6.2fs  %8.2f  %8.2f  %8.1f  %9.1f  %s"
            % (row.step, row.t_rel, row.x_m, row.y_m, row.heading_deg, row.uncertainty_deg, flag)
        )
    out.append("")

    calib_text = "%.3f dps" % report.bias_dps if report.calibrated else "uncalibrated (%.3f dps)" % report.bias_dps
    out.append("Summary:")
    out.append("  Duration              : %.2f s" % report.duration_s)
    out.append("  Total steps           : %d" % report.total_steps)
    out.append("  Path length           : %.2f m" % report.path_length_m)
    out.append(
        "  Net displacement (0,0): %.2f m  (end x=%.2f m, y=%.2f m, heading=%.1f deg)"
        % (
            report.net_displacement_m,
            report.final_pose.x_m,
            report.final_pose.y_m,
            report.final_pose.heading_deg,
        )
    )
    out.append("  Calibrated gyro bias  : %s" % calib_text)
    out.append(
        "  Peak uncertainty      : %.1f deg (threshold %.1f deg)"
        % (report.peak_uncertainty_deg, report.uncertainty_threshold_deg)
    )
    out.append("  Red LED 'uncertain'   : %s" % ("YES" if report.red_led_triggered else "NO"))
    out.append(
        "  Tuning                : step_length=%.2f m, snap_turns=%s, turn_rate=%.1f dps, "
        "turn_settle=%.2f s, min_turn=%.1f deg"
        % (
            report.step_length_m,
            report.snap_turns,
            report.turn_rate_dps,
            report.turn_settle_s,
            report.min_turn_deg,
        )
    )
    out.append("")
    out.append(format_trace(report.points, width=width, height=height))
    return "\n".join(out)


def _format_empty_dir_message(directory: str) -> str:
    return (
        "No logged CSV walks found in '%s' yet.\n"
        "Record a real band walk with `python3 main.py --band` (SampleLogger writes "
        "timestamped CSVs to %s), or pass `--demo-synthetic` to preview a synthetic walk."
        % (directory, config.LOG_DIR)
    )


def _is_default_log_dir(path: str) -> bool:
    norm = os.path.normpath(path)
    default_norm = os.path.normpath(config.LOG_DIR)
    return norm == default_norm or norm.endswith(os.sep + default_norm)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m tracker.replay",
        description="Replay recorded CSV sensor logs (never live sensing) and print pose trace + metrics.",
    )
    p.add_argument(
        "path",
        nargs="?",
        default=config.LOG_DIR,
        help="CSV sensor log file or directory of CSV logs (default: %s)" % config.LOG_DIR,
    )
    p.add_argument(
        "--step-length",
        type=float,
        default=None,
        help="override step length in metres (default: %.2f)" % config.STEP_LENGTH_M,
    )
    p.add_argument(
        "--no-snap",
        action="store_true",
        help="disable 90-degree turn snapping",
    )
    p.add_argument(
        "--turn-rate",
        type=float,
        default=None,
        help="override turn rate threshold in deg/s (default: %.1f)" % config.TURN_RATE_DPS,
    )
    p.add_argument(
        "--turn-settle",
        type=float,
        default=None,
        help="override turn settle quiet duration in s (default: %.2f)" % config.TURN_SETTLE_S,
    )
    p.add_argument(
        "--min-turn",
        type=float,
        default=None,
        help="override minimum net turn angle in deg (default: %.1f)" % config.MIN_TURN_DEG,
    )
    p.add_argument(
        "--uncertainty-threshold",
        type=float,
        default=None,
        help="override heading uncertainty threshold in deg (default: 35.0)",
    )
    p.add_argument(
        "--demo-synthetic",
        action="store_true",
        help="run on a generated synthetic walk (explicitly labelled as not real sensing)",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    snap_turns: Optional[bool] = False if args.no_snap else None

    if args.demo_synthetic:
        events = synthetic_walk(legs=((20, "left"), (15, None)))
        report = replay_events(
            events,
            label="synthetic L-walk (20 steps, left 90 deg, 15 steps) — NOT live or recorded band data",
            is_synthetic=True,
            step_length_m=args.step_length,
            snap_turns=snap_turns,
            turn_rate_dps=args.turn_rate,
            turn_settle_s=args.turn_settle,
            min_turn_deg=args.min_turn,
            uncertainty_threshold_deg=args.uncertainty_threshold,
        )
        print(format_report(report))
        return 0

    target = args.path
    if os.path.isdir(target):
        csv_files = sorted(
            os.path.join(target, name)
            for name in os.listdir(target)
            if name.lower().endswith(".csv") and os.path.isfile(os.path.join(target, name))
        )
        if not csv_files:
            print(_format_empty_dir_message(target))
            return 0
        for idx, csv_path in enumerate(csv_files):
            if idx > 0:
                print("\n" + ("=" * 68) + "\n")
            report = replay_file(
                csv_path,
                step_length_m=args.step_length,
                snap_turns=snap_turns,
                turn_rate_dps=args.turn_rate,
                turn_settle_s=args.turn_settle,
                min_turn_deg=args.min_turn,
                uncertainty_threshold_deg=args.uncertainty_threshold,
            )
            print(format_report(report))
        return 0

    if not os.path.exists(target):
        if _is_default_log_dir(target):
            print(_format_empty_dir_message(target))
            return 0
        print("Error: CSV log or directory not found: %s" % target, file=sys.stderr)
        return 1

    report = replay_file(
        target,
        step_length_m=args.step_length,
        snap_turns=snap_turns,
        turn_rate_dps=args.turn_rate,
        turn_settle_s=args.turn_settle,
        min_turn_deg=args.min_turn,
        uncertainty_threshold_deg=args.uncertainty_threshold,
    )
    print(format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
