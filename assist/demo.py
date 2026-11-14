"""Scripted demo of the vibration cues and the arrival prompt, on a synthetic walk.

    python3 -m assist.demo

SIMULATION: a made-up walk, not real sensing. No band and no phone are needed: each
vibration is printed. assist/phone_server.py --demo runs the same script and makes a
connected phone really vibrate.
"""
import time

from app import SpatialMemoryApp
from assist import attach
from store.route_store import RouteStore
from tracker.events import feed, synthetic_walk
from tracker.pdr import PathTracker


def print_haptic(msg):
    print("    [BUZZ] %-14s %s" % (msg["cue"], msg["pattern"]))


def run(send=print_haptic, pause=0.0, speak=None):
    print("SIMULATION: a synthetic walk, not real sensing.\n")
    say = speak or (lambda text: print("    [SAY] %s" % text))
    walk1 = synthetic_walk(legs=((20, "left"), (15, None)))
    now = [walk1[0][1]]
    app = SpatialMemoryApp(PathTracker(), RouteStore(), speak=say, clock=lambda: now[0])
    helper = attach(app, send=send)

    def user(text):
        print('\n> "%s"' % text)
        result = app.keyword_command(text)
        time.sleep(pause)
        return result

    def walk(legs, what, seed):
        steps = app.tracker._last_steps or 5000
        events = synthetic_walk(legs=legs, t0=now[0] + 0.04, start_steps=steps, seed=seed, still_s=0.5)
        print("\n  (walking: %s)" % what)
        feed(app.tracker, events)
        now[0] = events[-1][1]
        time.sleep(pause)

    user("start route")
    user("remember this as the entrance")
    print("\n  (walking: 20 steps, turn left, 15 steps)")
    feed(app.tracker, walk1)
    now[0] = walk1[-1][1]
    user("remember this as the elevator")
    walk(((10, None),), "10 more steps", seed=2)
    user("take me back to the entrance")
    walk(((0, "around"), (9, None)), "turn around, 9 steps back", seed=3)
    print('\n  (double-tap: "yes")')
    helper.confirm()
    time.sleep(pause)
    walk(((15, "right"), (18, None)), "15 steps, turn right, 18 steps", seed=4)
    print('\n  (double-tap: "yes")')
    helper.confirm()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
