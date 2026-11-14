"""Unit tests for tracker uncertainty model and CSV replay CLI."""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker import band_source  # noqa: E402
from tracker.events import feed, synthetic_walk  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402


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
        # Stand still for calibration
        for i in range(60):
            tr.on_motion(t0 + i * 0.04, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
        # Rapid alternating yaw reversals above turn_rate_dps without settling
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

            # Re-anchoring clears uncertainty and fires False once.
            tr.reanchor(0.0, 10.0, 0.0)
            self.assertEqual(tr.uncertainty_deg, 0.0)
            self.assertFalse(tr.heading_uncertain)
            self.assertEqual(transitions, [True, False])

            # Redundant reanchor while already certain does not fire again.
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
        # A 35-deg turn is ignored with default min_turn_deg=45, but snaps to 90 when min_turn_deg=30?
        # 90 * round(35/90) is still 0, whereas a 50-deg turn snaps to 90 with min_turn_deg=45
        # and stays 0 with min_turn_deg=60.
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


if __name__ == "__main__":
    unittest.main()
