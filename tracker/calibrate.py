"""Gate A & Gate B live band connection check and calibration analyzer for Vexo-HACK-80.

Usage:
  1. Live link + sensor + LED check (double-tap Band #80 first so it blinks blue):
         python3 -m tracker.calibrate --check --seconds 8

  2. Record a measured Gate B calibration walk (e.g. walk a known 10 m hallway or L-shape):
         python3 -m tracker.calibrate --record --seconds 25 --label gate-b

  3. Compute tuned config.py constants from any logged walk CSV + known distance:
         python3 -m tracker.calibrate --analyze data/logs/<file>.csv --distance-m 10.0

Rules (vexo-open-kit/AGENTS.md):
  - Connects ONLY to config.BAND (never guesses or scans without the exact band number).
  - Verifies band.number == config.BAND immediately after connecting.
"""
import argparse
import math
import os
import sys
import time
from typing import List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import config  # noqa: E402
from tracker import band_source  # noqa: E402
from tracker.events import Event, SampleLogger, feed, read_log  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402
from tracker.replay import render_ascii_trace  # noqa: E402


def analyze_calibration(
    events: List[Event],
    known_distance_m: Optional[float] = None,
    calib_s: float = None,
) -> dict:
    """Compute step length, resting gyro bias, still noise, and turn profile from a log."""
    calib_window = config.CALIBRATION_S if calib_s is None else calib_s
    if not events:
        raise ValueError("No events in log.")

    t0 = events[0][1]
    t_end = events[-1][1]
    duration_s = max(0.0, t_end - t0)

    # Track projected yaw rates during still vs turning phases.
    gravity = None
    alpha = config.GRAVITY_ALPHA
    still_yaws: List[float] = []
    initial_yaws: List[float] = []
    all_rates: List[Tuple[float, float]] = []  # (t, unbiased_rate_dps)
    state = "still"

    step_values: List[int] = []
    for kind, t, f in events:
        if kind == "activity":
            state = f["state"]
            step_values.append(int(f["steps"]))
        elif kind == "motion":
            ax, ay, az = f["ax"], f["ay"], f["az"]
            gx, gy, gz = f["gx"], f["gy"], f["gz"]
            if gravity is None:
                gravity = [ax, ay, az]
            else:
                gravity = [
                    gravity[0] + alpha * (ax - gravity[0]),
                    gravity[1] + alpha * (ay - gravity[1]),
                    gravity[2] + alpha * (az - gravity[2]),
                ]
            norm = math.sqrt(gravity[0] ** 2 + gravity[1] ** 2 + gravity[2] ** 2)
            if norm < 0.3:
                continue
            yaw = (gx * gravity[0] + gy * gravity[1] + gz * gravity[2]) / norm
            if t - t0 <= calib_window:
                initial_yaws.append(yaw)
            if state == "still" and math.sqrt(gx * gx + gy * gy + gz * gz) < 8.0:
                still_yaws.append(yaw)
            all_rates.append((t, yaw))

    bias_samples = initial_yaws or still_yaws or [0.0]
    bias_dps = sum(bias_samples) / len(bias_samples)
    still_noise_dps = 0.0
    if len(still_yaws) >= 2:
        mean_s = sum(still_yaws) / len(still_yaws)
        still_noise_dps = math.sqrt(sum((y - mean_s) ** 2 for y in still_yaws) / len(still_yaws))

    unbiased_abs = [abs(yaw - bias_dps) for _, yaw in all_rates]
    peak_yaw_dps = max(unbiased_abs) if unbiased_abs else 0.0

    total_steps = (step_values[-1] - step_values[0]) if len(step_values) >= 2 else 0
    measured_step_len = (
        round(known_distance_m / total_steps, 4)
        if (known_distance_m is not None and known_distance_m > 0 and total_steps > 0)
        else None
    )

    step_len_used = measured_step_len or config.STEP_LENGTH_M
    tracker = PathTracker(step_length_m=step_len_used, snap_turns=config.SNAP_TURNS)
    tracker.start(t0)
    feed(tracker, events)
    final_pose = tracker.pose

    # Suggested thresholds based on observed noise floor & peak turn rate
    suggested_still_dps = round(max(2.5, min(8.0, 3.0 * still_noise_dps + 1.0)), 1)
    suggested_turn_rate_dps = (
        round(max(18.0, min(45.0, 0.35 * peak_yaw_dps)), 1)
        if peak_yaw_dps >= 40.0
        else config.TURN_RATE_DPS
    )

    return {
        "duration_s": round(duration_s, 2),
        "motion_samples": len(all_rates),
        "activity_samples": len(step_values),
        "total_steps": total_steps,
        "bias_dps": round(bias_dps, 3),
        "still_noise_dps": round(still_noise_dps, 3),
        "peak_yaw_dps": round(peak_yaw_dps, 1),
        "measured_step_length_m": measured_step_len,
        "step_length_used_m": step_len_used,
        "final_x_m": round(final_pose.x_m, 2),
        "final_y_m": round(final_pose.y_m, 2),
        "final_heading_deg": round(final_pose.heading_deg, 1),
        "end_distance_from_start_m": round(math.hypot(final_pose.x_m, final_pose.y_m), 2),
        "peak_uncertainty_deg": round(tracker.uncertainty_deg, 1),
        "suggested_still_gyro_dps": suggested_still_dps,
        "suggested_turn_rate_dps": suggested_turn_rate_dps,
        "points": tracker.points,
    }


def print_analysis(path: str, stats: dict, known_distance_m: Optional[float] = None) -> None:
    print("\n=== Calibration Report (%s) ===" % path)
    print("  Duration:            %.2f s  (%d motion, %d activity samples)"
          % (stats["duration_s"], stats["motion_samples"], stats["activity_samples"]))
    print("  Steps counted:       %d steps" % stats["total_steps"])
    print("  Initial gyro bias:   %+.3f deg/s  (still noise std: %.3f deg/s)"
          % (stats["bias_dps"], stats["still_noise_dps"]))
    print("  Peak turn yaw rate:  %.1f deg/s" % stats["peak_yaw_dps"])
    if stats["measured_step_length_m"] is not None:
        print("  Known walk distance: %.2f m  ->  Measured STEP_LENGTH_M = %.4f m/step"
              % (known_distance_m, stats["measured_step_length_m"]))
    else:
        print("  Step length used:    %.3f m/step (pass --distance-m <meters> to calibrate STEP_LENGTH_M)"
              % stats["step_length_used_m"])
    print("  Reconstructed end:   x=%.2f m, y=%.2f m, heading=%.1f deg (|pos|=%.2f m from start)"
          % (stats["final_x_m"], stats["final_y_m"], stats["final_heading_deg"],
             stats["end_distance_from_start_m"]))
    print("\n--- Suggested config.py values ---")
    if stats["measured_step_length_m"] is not None:
        print("  STEP_LENGTH_M  = %.3f" % stats["measured_step_length_m"])
    print("  STILL_GYRO_DPS = %.1f" % stats["suggested_still_gyro_dps"])
    print("  TURN_RATE_DPS  = %.1f" % stats["suggested_turn_rate_dps"])
    print("\n--- Top-down ASCII Trace (+x right, +y up) ---")
    print(render_ascii_trace(stats["points"]))


def run_live_session(seconds: float, label: str, known_distance_m: Optional[float] = None) -> int:
    number = band_source.require_band_number()
    print("Connecting to Vexo-HACK-%02d (Band #%d) over Bluetooth..." % (number, number))
    print("  Reminder: close any open dashboard tab, and double-tap Band #%d so it blinks blue." % number)

    tracker = PathTracker()
    log_dir = config.LOG_DIR if os.path.isabs(config.LOG_DIR) else os.path.join(REPO_ROOT, config.LOG_DIR)
    logger = SampleLogger(log_dir, label=label)
    taps = [0]

    def on_double_tap():
        taps[0] += 1
        print("  [EVENT] double-tap #%d detected!" % taps[0])

    def on_link(status):
        print("  [LINK] %s" % status)

    try:
        band = band_source.connect(
            tracker,
            logger=logger,
            on_double_tap=on_double_tap,
            on_link=on_link,
        )
    except BaseException:
        logger.close()
        try:
            os.remove(logger.path)
        except OSError:
            pass
        raise

    try:
        info = getattr(band, "info", None)
        fw = getattr(info, "firmware", "unknown") if info else "unknown"
        print("Connected to %s (number=%d, firmware=%s)!" % (band.name, band.number, fw))
        print("Logging raw motion & step samples to: %s" % logger.path)

        # Confirm LED control visually on the wrist: blink green briefly, then amber breathe
        band.set_led("#00ff00", brightness=0.8, pattern="blink", period=400)
        tracker.start(time.time())
        print("\nStand still for %.1f s to calibrate resting gyro bias..." % config.CALIBRATION_S)
        band.wait(min(seconds, config.CALIBRATION_S))

        remaining = max(0.0, seconds - config.CALIBRATION_S)
        if remaining > 0:
            band.set_led("#ffb000", brightness=0.8, pattern="breathe", period=2000)
            print("Bias calibrated (%.3f deg/s). Walk or turn now for %.1f s (Ctrl+C to finish early)..."
                  % (tracker.bias, remaining))
            deadline = time.time() + remaining
            last_print = 0.0
            try:
                while time.time() < deadline:
                    band.wait(0.25)
                    now = time.time()
                    if now - last_print >= 1.0:
                        last_print = now
                        p = tracker.pose
                        print("  [LIVE] steps=%3d  state=%-5s  x=%+5.2f m  y=%+5.2f m  heading=%+6.1f deg  unc=%.1f deg"
                              % (p.steps, tracker.state, p.x_m, p.y_m, p.heading_deg, tracker.uncertainty_deg))
            except KeyboardInterrupt:
                print("\nStopping early...")

        tracker.stop()
        band.set_led("#00ff00", brightness=0.8, pattern="solid", period=1000)
        band.wait(0.5)
        band.led_off()
    finally:
        logger.close()
        band.disconnect()

    events = read_log(logger.path)
    if events:
        stats = analyze_calibration(events, known_distance_m=known_distance_m)
        print_analysis(logger.path, stats, known_distance_m=known_distance_m)
    else:
        print("No samples recorded in %s." % logger.path)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="connect to Band #80, test LED & streams, measure bias")
    mode.add_argument("--record", action="store_true", help="record a live calibration walk to data/logs/")
    mode.add_argument("--analyze", metavar="CSV", help="compute calibration values from an existing CSV log")
    parser.add_argument("--seconds", type=float, default=10.0, help="recording duration in seconds (default: 10)")
    parser.add_argument("--distance-m", type=float, default=None, help="known walked distance in metres (for STEP_LENGTH_M)")
    parser.add_argument("--label", default="calib", help="CSV filename prefix in data/logs/ (default: calib)")
    args = parser.parse_args(argv)

    if args.analyze:
        events = read_log(args.analyze)
        stats = analyze_calibration(events, known_distance_m=args.distance_m)
        print_analysis(args.analyze, stats, known_distance_m=args.distance_m)
        return 0

    label = "check" if args.check else args.label
    return run_live_session(seconds=args.seconds, label=label, known_distance_m=args.distance_m)


if __name__ == "__main__":
    sys.exit(main())
