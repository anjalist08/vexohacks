"""Scripted demo of the guidance cues and the arrival prompt, on a synthetic walk.

    python3 -m assist.demo             cues printed (no band, no phone, no headphones)
    python3 -m assist.demo --sound     also play each cue on this laptop's audio output

SIMULATION: a made-up walk, not real sensing. assist/phone_server.py --demo runs the
same script to a phone, which plays every sound in its headphones and vibrates.
"""
import argparse
import sys
import time

from app import SpatialMemoryApp
from assist import attach, fan_out
from store.route_store import RouteStore
from tracker.events import feed, synthetic_walk
from tracker.pdr import PathTracker

_PAN = {-1.0: " (left ear)", 1.0: " (right ear)"}


def print_cue(msg):
    if msg["cue"] == "step_tick":
        print("    [TICK]")
        return
    side = _PAN.get(msg["sound"]["pan"], "")
    print("    [CUE] %-14s%s  buzz %s" % (msg["cue"], side, msg["pattern"] or "-"))


def run(send=print_cue, pause=0.0, speak=None):
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

    def walk(events, what):
        print("\n  (walking: %s)" % what)
        for e in events:                 # in real time when paused, so cues are heard in order
            feed(app.tracker, [e])
            if pause and e[0] == "activity":
                time.sleep(pause / 15.0)
        now[0] = events[-1][1]

    def more(legs, what, seed):
        steps = app.tracker._last_steps or 5000
        walk(synthetic_walk(legs=legs, t0=now[0] + 0.04, start_steps=steps, seed=seed, still_s=0.5), what)

    user("start route")
    user("remember this as the entrance")
    walk(walk1, "20 steps, turn left, 15 steps")
    user("remember this as the elevator")
    more(((10, None),), "10 more steps", seed=2)
    user("take me back to the entrance")
    more(((0, "around"), (9, None)), "turn around, 9 steps back", seed=3)
    print('\n  (double-tap: "yes")')
    helper.confirm()
    time.sleep(pause)
    more(((15, "right"), (18, None)), "15 steps, turn right, 18 steps", seed=4)
    print('\n  (double-tap: "yes")')
    helper.confirm()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sound", action="store_true", help="play each cue on this laptop's audio output")
    a = p.parse_args(argv)
    if not a.sound:
        return run()
    from assist.earcons import LaptopSound
    return run(send=fan_out(print_cue, LaptopSound()), pause=1.5)


if __name__ == "__main__":
    sys.exit(main())
