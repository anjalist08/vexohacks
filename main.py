"""Wearable spatial memory on the Vexo band.

    python3 main.py --sim             scripted demo on a synthetic walk (no band, no keys)
    python3 main.py --replay FILE     replay a logged real walk, then type commands (label it a replay)
    python3 main.py --band            live band (set BAND in config.py first), type commands

Typed commands use the keyword fallback, e.g. "start route", "remember this as the elevator",
"where was the elevator", "take me back to the start", "I'm at the elevator", "quit".
The voice loop (double-tap, Deepgram, Gemini, ElevenLabs) is built in voice/.
"""
import argparse
import sys

import config
from app import SpatialMemoryApp
from store.route_store import RouteStore
from tracker.events import SampleLogger, feed, read_log, synthetic_walk
from tracker.pdr import PathTracker


class PrintLed:
    """Stands in for the LED when there is no band: prints each state."""

    def __init__(self):
        self.state = "idle"
        self.brightness = 1.0

    def show(self, state, period=None):
        self.state = state
        print("    [LED] %s" % state)
        return True


def say(text):
    print("    [SAY] %s" % text)


def run_sim():
    print("SIMULATION: a synthetic walk, not real sensing.\n")
    walk1 = synthetic_walk(legs=((20, "left"), (15, None)))
    now = [walk1[0][1]]
    app = SpatialMemoryApp(PathTracker(), RouteStore(), speak=say, led=PrintLed(), clock=lambda: now[0])

    def user(text):
        print('\n> "%s"' % text)
        return app.keyword_command(text)

    def walk(events, what):
        print("\n  (walking: %s)" % what)
        feed(app.tracker, events)
        now[0] = events[-1][1]
        p = app.tracker.pose
        print("    [POS] x=%.1f m  y=%.1f m  heading=%.0f deg  steps=%d" % (p.x_m, p.y_m, p.heading_deg, p.steps))

    user("start route")
    user("remember this as the entrance")
    walk(walk1, "20 steps, stop and turn left, 15 steps")
    user("remember this as the elevator near the blue sign")
    last_steps = [f["steps"] for k, t, f in walk1 if k == "activity"][-1]
    walk(synthetic_walk(legs=((10, None),), t0=now[0] + 0.04, start_steps=last_steps, seed=2), "10 more steps")
    user("where was the elevator")
    result = user("take me back to the entrance")
    print("\nReturn guidance, computed from the recorded path:")
    for i in result.data.get("instructions", []):
        print("   %-8s %3d steps  %5.1f m   %s" % (i["turn"], i["steps"], i["distance_m"], i["text"]))
    return 0 if result.ok else 1


def repl(app):
    print('Type a command ("quit" to stop, "delete all" to forget every route).')
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text in ("quit", "exit"):
            break
        if text == "delete all":
            app.store.delete_all()
            print("    All routes deleted.")
            continue
        if text:
            app.keyword_command(text)


def run_replay(path):
    print("REPLAY of a logged walk (%s). This is not live sensing.\n" % path)
    events = read_log(path)
    now = [events[0][1]]
    app = SpatialMemoryApp(PathTracker(), RouteStore(), speak=say, led=PrintLed(), clock=lambda: now[0])
    app.call_tool("start_route", {"title": "replay"})
    feed(app.tracker, events)
    now[0] = events[-1][1]
    p = app.tracker.pose
    print("    [POS] x=%.1f m  y=%.1f m  heading=%.0f deg  steps=%d" % (p.x_m, p.y_m, p.heading_deg, p.steps))
    repl(app)
    return 0


def run_band():
    from tracker import band_source
    from voice.led_states import LedController
    band_source.require_band_number()
    tracker = PathTracker()
    logger = SampleLogger(config.LOG_DIR)
    led = LedController()
    app = SpatialMemoryApp(tracker, RouteStore(config.ROUTES_FILE), speak=say, led=led)
    band = band_source.connect(
        tracker, logger,
        on_double_tap=lambda: print("\n    (double-tap: the voice loop is not built yet, type instead)"),
        on_link=lambda s: print("\n    [LINK] %s" % s))
    led.band = band
    print("Connected to %s. Logging every sample to %s" % (band.name, logger.path))
    try:
        repl(app)
    finally:
        logger.close()
        band.disconnect()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--sim", action="store_true", help="scripted demo on a synthetic walk")
    g.add_argument("--replay", metavar="FILE", help="replay a logged walk CSV")
    g.add_argument("--band", action="store_true", help="use the team's band (config.BAND)")
    a = p.parse_args(argv)
    if a.sim:
        return run_sim()
    if a.replay:
        return run_replay(a.replay)
    return run_band()


if __name__ == "__main__":
    sys.exit(main())
