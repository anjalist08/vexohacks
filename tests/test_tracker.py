"""Unit tests for tracker uncertainty model and CSV replay CLI."""
import contextlib
import inspect
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tracker  # noqa: E402
from tracker import band_source  # noqa: E402
from tracker.events import feed, synthetic_walk, write_log  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402
from tracker.replay import format_trace, main as replay_main, replay_file  # noqa: E402


class UncertaintySignalTests(unittest.TestCase):
    def test_clean_l_walk_stays_certain(self):
        transitions = []
        ev = synthetic_walk(legs=((20, "left"), (15, None)))
        tr = PathTracker(step_length_m=0.7, snap_turns=True)
        tr.on_uncertainty(transitions.append)
        tr.start(ev[0][1])
        feed(tr, ev)

        self.assertFalse(tr.heading_uncertain)
        self.assertLess(tr.uncertainty_deg, tr.uncertainty_threshold_deg)
        self.assertEqual(transitions, [])

        # Even adding 10 more steps (matching main.py --sim) remains certain.
        last_steps = [f["steps"] for k, t, f in ev if k == "activity"][-1]
        ev2 = synthetic_walk(legs=((10, None),), t0=ev[-1][1] + 0.04, start_steps=last_steps, seed=2)
        feed(tr, ev2)
        self.assertEqual(tr.pose.steps, 45)
        self.assertFalse(tr.heading_uncertain)
        self.assertEqual(transitions, [])

    def test_diagonal_turn_triggers_uncertainty(self):
        transitions = []
        ev = synthetic_walk(legs=((10, 40.0), (10, None)))
        tr = PathTracker(step_length_m=0.7, snap_turns=True)
        tr.on_uncertainty(transitions.append)
        tr.start(ev[0][1])
        feed(tr, ev)

        self.assertTrue(tr.heading_uncertain)
        self.assertGreaterEqual(tr.uncertainty_deg, tr.uncertainty_threshold_deg)
        self.assertEqual(transitions, [True])

    def test_uncalibrated_walking_triggers_uncertainty(self):
        transitions = []
        ev = synthetic_walk(legs=((10, None),), still_s=0.1)
        tr = PathTracker(step_length_m=0.7)
        tr.on_uncertainty(transitions.append)
        tr.start(ev[0][1])
        feed(tr, ev)

        self.assertTrue(tr.heading_uncertain)
        self.assertEqual(transitions, [True])

    def test_freefall_and_chaotic_accel_trigger_uncertainty(self):
        # Free-fall (norm < 0.3 g)
        transitions_ff = []
        tr_ff = PathTracker()
        tr_ff.on_uncertainty(transitions_ff.append)
        t0 = 1_700_000_000.0
        tr_ff.start(t0)
        for i in range(12):
            tr_ff.on_motion(t0 + 2.5 + i * 0.04, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertTrue(tr_ff.heading_uncertain)
        self.assertEqual(transitions_ff, [True])

        # Violent wrist impact / shaking (norm > 2.5 g)
        transitions_hi = []
        tr_hi = PathTracker()
        tr_hi.on_uncertainty(transitions_hi.append)
        tr_hi.start(t0)
        for i in range(12):
            tr_hi.on_motion(t0 + 2.5 + i * 0.04, 2.2, 2.0, 1.0, 5.0, -5.0, 2.0)
        self.assertTrue(tr_hi.heading_uncertain)
        self.assertEqual(transitions_hi, [True])

    def test_chaotic_yaw_jitter_triggers_uncertainty(self):
        transitions = []
        tr = PathTracker()
        tr.on_uncertainty(transitions.append)
        t0 = 1_700_000_000.0
        tr.start(t0)
        for i in range(60):
            tr.on_motion(t0 + i * 0.04, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
        t = t0 + 2.5
        for i in range(12):
            gz = 80.0 if (i % 2 == 0) else -80.0
            tr.on_motion(t + i * 0.08, 0.0, 0.0, 1.0, 0.0, 0.0, gz)
        self.assertTrue(tr.heading_uncertain)
        self.assertEqual(transitions, [True])

    def test_long_unanchored_walk_triggers_uncertainty_and_reanchor_clears(self):
        for snap in (True, False):
            transitions = []
            ev = synthetic_walk(legs=((95, None),))
            tr = PathTracker(step_length_m=0.7, snap_turns=snap)
            tr.on_uncertainty(transitions.append)
            tr.start(ev[0][1])
            feed(tr, ev)

            self.assertTrue(tr.heading_uncertain)
            self.assertEqual(transitions, [True])

            tr.reanchor(0.0, 10.0, 0.0)
            self.assertEqual(tr.uncertainty_deg, 0.0)
            self.assertFalse(tr.heading_uncertain)
            self.assertEqual(transitions, [True, False])

            tr.reanchor(0.0, 10.0, 0.0)
            self.assertEqual(transitions, [True, False])

    def test_start_resets_uncertain_state_and_notifies(self):
        transitions = []
        ev = synthetic_walk(legs=((10, 40.0), (5, None)))
        tr = PathTracker()
        tr.on_uncertainty(transitions.append)
        tr.start(ev[0][1])
        feed(tr, ev)
        self.assertTrue(tr.heading_uncertain)
        self.assertEqual(transitions, [True])

        tr.start(ev[-1][1] + 1.0)
        self.assertEqual(tr.uncertainty_deg, 0.0)
        self.assertFalse(tr.heading_uncertain)
        self.assertEqual(transitions, [True, False])

    def test_tuning_kwargs_override_defaults(self):
        ev = synthetic_walk(legs=((5, 50.0), (5, None)))
        tr_snap = PathTracker(min_turn_deg=45.0, uncertainty_threshold_deg=50.0)
        tr_snap.start(ev[0][1])
        feed(tr_snap, ev)
        self.assertEqual(tr_snap.pose.heading_deg, -90.0)

        tr_ignore = PathTracker(min_turn_deg=60.0, uncertainty_threshold_deg=20.0)
        tr_ignore.start(ev[0][1])
        feed(tr_ignore, ev)
        self.assertEqual(tr_ignore.pose.heading_deg, 0.0)
        self.assertTrue(tr_ignore.heading_uncertain)

    def test_band_source_accepts_on_uncertain_parameter(self):
        sig = inspect.signature(band_source.connect)
        self.assertIn("on_uncertain", sig.parameters)
        self.assertIsNone(sig.parameters["on_uncertain"].default)


class ReplayCliTests(unittest.TestCase):
    def _run_cli(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = replay_main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_replay_csv_file_banner_table_summary_and_ascii_trace(self):
        ev = synthetic_walk(legs=((20, "left"), (15, None)))
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "walk-clean.csv")
            write_log(csv_path, ev)

            rc, stdout, stderr = self._run_cli([csv_path])
            self.assertEqual(rc, 0)
            self.assertEqual(stderr, "")
            lines = stdout.splitlines()
            self.assertEqual(
                lines[0],
                "REPLAY: %s (recorded sensor log, NOT live sensing)" % csv_path,
            )
            self.assertIn("Pose samples:", stdout)
            self.assertIn("-10.50", stdout)
            self.assertIn("14.00", stdout)
            self.assertIn("Total steps           : 35", stdout)
            self.assertIn("Path length           : 24.50 m", stdout)
            self.assertIn("Red LED 'uncertain'   : NO", stdout)
            self.assertIn("Top-down 2D trace", stdout)
            self.assertIn("S", stdout)
            self.assertIn("E", stdout)

    def test_replay_uncertain_walk_flags_red_led(self):
        ev = synthetic_walk(legs=((10, 40.0), (10, None)))
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "walk-diag.csv")
            write_log(csv_path, ev)

            rc, stdout, _ = self._run_cli([csv_path])
            self.assertEqual(rc, 0)
            self.assertIn("RED_LED", stdout)
            self.assertIn("Red LED 'uncertain'   : YES", stdout)

    def test_replay_tuning_flags(self):
        ev = synthetic_walk(legs=((20, "left"), (15, None)))
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "walk.csv")
            write_log(csv_path, ev)

            rc, stdout, _ = self._run_cli(
                [
                    csv_path,
                    "--step-length",
                    "1.0",
                    "--no-snap",
                    "--turn-rate",
                    "22.0",
                    "--turn-settle",
                    "0.5",
                    "--min-turn",
                    "40.0",
                    "--uncertainty-threshold",
                    "10.0",
                ]
            )
            self.assertEqual(rc, 0)
            self.assertIn("Path length           : 35.00 m", stdout)
            self.assertIn("snap_turns=False", stdout)
            self.assertIn("step_length=1.00 m", stdout)
            # With threshold lowered to 10.0 deg, 35 steps (14 deg) triggers RED_LED.
            self.assertIn("Red LED 'uncertain'   : YES", stdout)

            report = replay_file(csv_path, step_length_m=0.8, snap_turns=True)
            self.assertAlmostEqual(report.path_length_m, 28.0, places=2)
            trace = format_trace(report.points, width=50, height=20)
            self.assertIn("S", trace)
            self.assertIn("E", trace)

    def test_replay_directory_sorted_and_empty_directory_handling(self):
        with tempfile.TemporaryDirectory() as empty_dir:
            rc, stdout, _ = self._run_cli([empty_dir])
            self.assertEqual(rc, 0)
            self.assertIn("No logged CSV walks found", stdout)
            self.assertIn("SampleLogger", stdout)

            # Add two CSVs and verify both replay in sorted order.
            write_log(os.path.join(empty_dir, "b-walk.csv"), synthetic_walk(legs=((5, None),)))
            write_log(os.path.join(empty_dir, "a-walk.csv"), synthetic_walk(legs=((10, None),)))
            rc2, stdout2, _ = self._run_cli([empty_dir])
            self.assertEqual(rc2, 0)
            self.assertLess(stdout2.index("a-walk.csv"), stdout2.index("b-walk.csv"))

        # Default data/logs path when not yet created also exits 0 with clear explanation.
        rc_logs, stdout_logs, _ = self._run_cli(["data/logs"])
        self.assertEqual(rc_logs, 0)
        self.assertTrue("No logged CSV walks found" in stdout_logs or "REPLAY:" in stdout_logs)

        # Missing specific file returns non-zero exit code.
        rc_missing, _, stderr_missing = self._run_cli(["/tmp/definitely-no-such-vexo-walk.csv"])
        self.assertEqual(rc_missing, 1)
        self.assertIn("not found", stderr_missing)

    def test_demo_synthetic_flag_labels_output_honestly(self):
        rc, stdout, _ = self._run_cli(["--demo-synthetic"])
        self.assertEqual(rc, 0)
        first_line = stdout.splitlines()[0]
        self.assertTrue(first_line.startswith("SYNTHETIC WALK (not real sensing)"))

    def test_package_exports(self):
        self.assertIs(tracker.PathTracker, PathTracker)
        self.assertIs(tracker.replay_file, replay_file)
        self.assertIs(tracker.format_trace, format_trace)


if __name__ == "__main__":
    unittest.main()
