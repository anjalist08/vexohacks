"""Wearable spatial memory on the Vexo band.

    python3 main.py --sim             scripted demo on a synthetic walk (no band, no keys)
    python3 main.py --replay FILE     replay a logged real walk, then type commands (label it a replay)
    python3 main.py --band            live band (set BAND in config.py first), type commands
    python3 main.py --band --usb      the same over the USB cable

Add --web to any of them for the live dashboard at http://127.0.0.1:8000 (--port to change it).
With --web, commands are typed on the dashboard page instead of in the terminal.

Typed commands use the keyword fallback, e.g. "start route", "remember this as the elevator",
"where was the elevator", "take me back to the start", "I'm at the elevator", "quit".
The voice loop (double-tap, Deepgram, Gemini, ElevenLabs) is built in voice/.
"""
import argparse
import sys
import threading
import time

import keys

keys.prepare()   # before any AI SDK or the kit's speech module is imported

import config  # noqa: E402
from app import SpatialMemoryApp  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import SampleLogger, feed, read_log, synthetic_walk  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402


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


def feed_paced(tracker, events, speed):
    """Feed events at speed x real time, so the dashboard shows the walk unfold."""
    start_wall, start_t = time.time(), events[0][1]
    for kind, t, f in events:
        delay = (t - start_t) / speed - (time.time() - start_wall)
        if delay > 0:
            time.sleep(delay)
        feed(tracker, [(kind, t, f)])


def run_sim(web_port=None, speed=3.0):
    print("SIMULATION: a synthetic walk, not real sensing.\n")
    walk1 = synthetic_walk(legs=((20, "left"), (15, None)))
    now = [walk1[0][1]]
    app = SpatialMemoryApp(PathTracker(), RouteStore(), speak=say, led=PrintLed(), clock=lambda: now[0])
    dash = start_dashboard(app, "SIMULATION", web_port) if web_port else None
    if dash:
        print("Open the dashboard now; the walk starts in 5 seconds.")
        time.sleep(5)

    def user(text):
        print('\n> "%s"' % text)
        result = app.keyword_command(text)
        if dash:
            time.sleep(1.5)
        return result

    def walk(events, what):
        print("\n  (walking: %s)" % what)
        if dash:
            feed_paced(app.tracker, events, speed)
        else:
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
    if dash:
        wait_forever()
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


def run_replay(path, web_port=None, speed=1.0):
    print("REPLAY of a logged walk (%s). This is not live sensing.\n" % path)
    events = read_log(path)
    now = [events[0][1]]
    app = SpatialMemoryApp(PathTracker(), RouteStore(), speak=say, led=PrintLed(), clock=lambda: now[0])
    dash = start_dashboard(app, "REPLAY", web_port) if web_port else None
    app.call_tool("start_route", {"title": "replay"})
    if dash:
        feed_paced(app.tracker, events, speed)
    else:
        feed(app.tracker, events)
    now[0] = events[-1][1]
    p = app.tracker.pose
    print("    [POS] x=%.1f m  y=%.1f m  heading=%.0f deg  steps=%d" % (p.x_m, p.y_m, p.heading_deg, p.steps))
    if dash:
        wait_forever()
    else:
        repl(app)
    return 0


def start_dashboard(app, label, port):
    from web.server import Dashboard
    dash = Dashboard(app, label)
    dash.serve(port)
    print("Dashboard: http://127.0.0.1:%d" % port)
    return dash


def wait_forever():
    print("Running. Stop with Ctrl+C.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


def run_band(usb=False, web_port=None):
    from tracker import band_source
    from voice.led_states import LedController
    band_source.require_band_number()
    tracker = PathTracker()
    logger = SampleLogger(config.LOG_DIR)
    led = LedController()
    app = SpatialMemoryApp(tracker, RouteStore(config.ROUTES_FILE), speak=say, led=led)
    dash = start_dashboard(app, "LIVE", web_port) if web_port else None

    def link(status):
        print("\n    [LINK] %s" % status)
        if dash:
            dash.set_link(status)

    band = band_source.connect(
        tracker, logger,
        on_double_tap=lambda: print("\n    (double-tap: the voice loop is not built yet, type instead)"),
        on_link=link, usb=usb)
    led.band = band
    print("Connected to %s over %s. Logging every sample to %s" % (band.name, "USB" if usb else "Bluetooth", logger.path))
    try:
        if dash:
            wait_forever()          # commands come from the dashboard page
        else:
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
    p.add_argument("--usb", action="store_true", help="with --band: use the USB cable instead of Bluetooth")
    p.add_argument("--web", action="store_true", help="serve the live dashboard")
    p.add_argument("--port", type=int, default=8000, help="dashboard port (default 8000)")
    p.add_argument("--speed", type=float, default=None, help="with --web: playback speed for --sim / --replay")
    a = p.parse_args(argv)
    port = a.port if a.web else None
    if a.sim:
        return run_sim(port, a.speed or 3.0)
    if a.replay:
        return run_replay(a.replay, port, a.speed or 1.0)
    return run_band(usb=a.usb, web_port=port)


if __name__ == "__main__":
    sys.exit(main())
