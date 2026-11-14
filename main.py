"""Wearable spatial memory on the Vexo band.

    python3 main.py --sim             scripted demo on a synthetic walk (no band, no keys)
    python3 main.py --replay FILE     replay a logged real walk + live map page (label it a replay)
    python3 main.py --band            live band (set BAND in config.py first) + voice loop + live map page
    python3 main.py --band --usb      the same over the USB cable
    python3 main.py --bridge          the band connects through Chrome (click "Connect band" on the map page)

Typed commands use the keyword fallback, e.g. "start route", "remember this as the elevator",
"where was the elevator", "take me back to the start", "I'm at the elevator", "quit".
On --band, double-tap triggers one spoken turn: band mic -> Deepgram -> Gemini 4 -> ElevenLabs -> LED.
"""
import argparse
import os
import sys
import threading

import keys

keys.prepare()   # before any AI SDK or the kit's speech module is imported

import config  # noqa: E402
from app import SpatialMemoryApp  # noqa: E402
from store.band_mirror import BandLandmarkMirror  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import SampleLogger, feed, read_log, synthetic_walk  # noqa: E402
from tracker.wrist import make_tracker  # noqa: E402
from web.ws_server import MapWebSocketServer, _start_static_http, start_haptic_pump, start_status_pump  # noqa: E402

PHONE = {"token": None}     # set by --phone: other devices on the Wi-Fi may open the phone page with it


def _lan_ip() -> str:
    """This laptop's address on the Wi-Fi (no packet is sent)."""
    import socket as _socket
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


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


def _start_web_servers(app, mode, host="127.0.0.1", ws_port=8765, http_port=8000, enable_ws=True, enable_http=True):
    ws = None
    httpd = None
    token = PHONE["token"]
    if token:
        host = "0.0.0.0"          # reachable from the phone; other devices need the token (ws_server)
    if enable_ws:
        try:
            ws = MapWebSocketServer(app, host=host, port=ws_port, mode=mode).start()
            ws.phone_token = token
            print("WebSocket: ws://%s:%d" % (ws.host, ws.port))
            ws._haptic_stop = threading.Event()
            start_haptic_pump(ws, app, ws._haptic_stop)       # phone buzz cues
        except OSError as exc:
            print("WebSocket port %d busy (%s); continuing without map feed." % (ws_port, exc))
    if enable_http:
        try:
            httpd = _start_static_http(host, http_port, REPO_ROOT, phone_token=token)
            print("Map page:  http://localhost:%d/web/" % http_port)
        except OSError:
            print("Map page:  http://localhost:%d/web/ (using existing server on port %d)" % (http_port, http_port))
    print("Phone (simulation on this laptop): http://localhost:%d/web/phone.html?ws_port=%d" % (http_port, ws_port))
    if token:
        print("Phone (on the same Wi-Fi):  http://%s:%d/web/phone.html?ws_port=%d&token=%s"
              % (_lan_ip(), http_port, ws_port, token))
        print("  Anyone with this link can steer the app: share it only with your own phone.")
    return ws, httpd


def _stop_web_servers(ws, httpd):
    if ws is not None and getattr(ws, "_haptic_stop", None) is not None:
        ws._haptic_stop.set()
    if ws is not None:
        ws.stop()
    if httpd is not None:
        httpd.shutdown()
        httpd.server_close()


def run_sim():
    print("SIMULATION: a synthetic walk, not real sensing.\n")
    walk1 = synthetic_walk(legs=((20, "left"), (15, None)))
    now = [walk1[0][1]]
    app = SpatialMemoryApp(make_tracker(synthetic=True), RouteStore(), speak=say, led=PrintLed(), clock=lambda: now[0])

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
            app.delete_all()
            print("    All routes deleted.")
            continue
        if text:
            app.keyword_command(text)


def run_replay(path, ws_port=8765, http_port=8000, no_web=False):
    print("REPLAY of a logged walk (%s). This is not live sensing.\n" % path)
    events = read_log(path)
    now = [events[0][1]] if events else [0.0]
    app = SpatialMemoryApp(make_tracker(), RouteStore(), speak=say, led=PrintLed(), clock=lambda: now[0])
    ws, httpd = _start_web_servers(
        app, mode="REPLAY", ws_port=ws_port, http_port=http_port,
        enable_ws=not no_web, enable_http=not no_web,
    )
    status_stop = threading.Event()
    if ws is not None:
        start_status_pump(ws, app.tracker, status_stop)
    try:
        app.call_tool("start_route", {"title": "replay"})
        if events:
            feed(app.tracker, events)
            now[0] = events[-1][1]
        p = app.tracker.pose
        print("    [POS] x=%.1f m  y=%.1f m  heading=%.0f deg  steps=%d" % (p.x_m, p.y_m, p.heading_deg, p.steps))
        repl(app)
    finally:
        status_stop.set()
        _stop_web_servers(ws, httpd)
    return 0


class _QueuedSpeaker:
    """Speaks in a background thread, one line after another. Speaking (ElevenLabs request
    plus playback) takes seconds; called directly it held up the band's data and the map."""

    def __init__(self, inner):
        import queue
        self._inner = inner
        self._q = queue.Queue()
        threading.Thread(target=self._run, name="speaker", daemon=True).start()

    def __call__(self, text):
        self._q.put(text)
        return text

    def _run(self):
        while True:
            text = self._q.get()
            try:
                self._inner(text)
            except Exception as exc:
                print("    [speech failed] %s" % exc)


def run_band(ws_port=8765, http_port=8000, no_web=False, usb=False):
    from tracker import band_source
    from voice.elevenlabs_tts import ElevenLabsSpeaker
    from voice.led_states import LedController
    from voice.loop import VoiceLoop

    band_source.require_band_number()
    log_dir = config.LOG_DIR if os.path.isabs(config.LOG_DIR) else os.path.join(REPO_ROOT, config.LOG_DIR)
    routes_file = config.ROUTES_FILE if os.path.isabs(config.ROUTES_FILE) else os.path.join(REPO_ROOT, config.ROUTES_FILE)
    tracker = make_tracker()
    logger = SampleLogger(log_dir)
    led = LedController()
    speaker = _QueuedSpeaker(ElevenLabsSpeaker())   # speaking never blocks the band or the map
    app = SpatialMemoryApp(tracker, RouteStore(routes_file), speak=speaker, led=led)
    voice_loop = VoiceLoop(app, listen_seconds=config.LISTEN_SECONDS)
    ws, httpd = _start_web_servers(
        app, mode="LIVE", ws_port=ws_port, http_port=http_port,
        enable_ws=not no_web, enable_http=not no_web,
    )

    def on_link(status):
        print("\n    [LINK] %s" % status)
        if status == "reconnected":
            led.reapply()
        if ws is not None:
            ws.send_link(status)

    try:
        band = band_source.connect(
            tracker,
            logger,
            on_double_tap=voice_loop.on_double_tap,
            on_link=on_link,
            usb=usb,
            on_metric=ws.send_metric if ws is not None else None,   # battery etc. for the Band card
        )
    except BaseException:
        _stop_web_servers(ws, httpd)
        logger.close()
        raise

    led.band = band
    voice_loop.band = band
    if ws is not None:
        ws.voice_loop = voice_loop       # the page's Talk button and typed text use it
    if getattr(band, "storage", None) is not None:
        app.band_mirror = BandLandmarkMirror(band.storage)
    voice_loop.start_background()
    status_stop = threading.Event()
    if ws is not None:
        log_url = "/" + os.path.relpath(logger.path, REPO_ROOT).replace(os.sep, "/")

        def status_extra():
            logger.flush()          # so the page's log link has everything so far
            return {"log": log_url}

        start_status_pump(ws, tracker, status_stop, extra=status_extra)
    if ws is not None:
        print("Map:  http://localhost:%d/web/trail.html?ws_port=%d   (team map: http://localhost:%d/web/?ws_port=%d)"
              % (http_port, ws.port, http_port, ws.port))
    print("Connected to %s. Double-tap the band to speak, or type commands below." % band.name)
    print("Logging every sample to %s" % logger.path)
    print('Press "start route" on the map page (or type it here), hold your arm still a moment, then walk.')
    try:
        repl(app)
    finally:
        status_stop.set()
        voice_loop.stop()
        _stop_web_servers(ws, httpd)
        logger.close()
        band.disconnect()
    return 0


def run_bridge(ws_port=8765, http_port=8000):
    """The band connects through Chrome (Web Bluetooth, like the kit's dashboard); this
    program does everything else. Use it when Python itself cannot use Bluetooth."""
    from tracker import band_source
    from voice.elevenlabs_tts import ElevenLabsSpeaker
    from voice.led_states import LedController
    from voice.loop import VoiceLoop
    from web import bridge_band

    band_source.require_band_number()
    log_dir = config.LOG_DIR if os.path.isabs(config.LOG_DIR) else os.path.join(REPO_ROOT, config.LOG_DIR)
    routes_file = config.ROUTES_FILE if os.path.isabs(config.ROUTES_FILE) else os.path.join(REPO_ROOT, config.ROUTES_FILE)
    tracker = make_tracker()                      # the same tracker as --band (WristTracker by default)
    logger = SampleLogger(log_dir)
    led = LedController()
    speaker = _QueuedSpeaker(ElevenLabsSpeaker())   # speaking never blocks the band or the map
    app = SpatialMemoryApp(tracker, RouteStore(routes_file), speak=speaker, led=led)
    voice_loop = VoiceLoop(app, listen_seconds=config.LISTEN_SECONDS)
    ws, httpd = _start_web_servers(app, mode="LIVE", ws_port=ws_port, http_port=http_port)
    if ws is None:
        print("The map page server could not start; the Chrome bridge needs it.")
        return 1
    band = bridge_band.BridgeBand(ws.broadcast)
    bridge_band.wire(band, tracker, logger, on_double_tap=voice_loop.on_double_tap, on_metric=ws.send_metric)

    def on_status(msg):
        status = msg.get("status", "")
        print("\n    [CHROME] band %s" % status)
        ws.send_link(status)
        if status in ("connected", "reconnected"):
            band.connected = True
            ws.send_metric("info", {"name": msg.get("name") or band.name,
                                    "transport": msg.get("transport") or "Chrome Bluetooth",
                                    "firmware": msg.get("firmware")})
            bridge_band.configure_streams(band)
            led.reapply()
        elif status == "disconnected":
            band.connected = False

    ws.bridge = band
    ws.on_bridge_status = on_status
    ws.voice_loop = voice_loop
    led.band = band
    voice_loop.band = band
    voice_loop.start_background()
    print("Open in Chrome:  http://localhost:%d/web/trail.html?ws_port=%d   (or the team map http://localhost:%d/web/)"
          % (http_port, ws_port, http_port))
    print("Double-tap the band, then click \"Connect band (Chrome)\" and pick it in the list.")
    print("Logging every sample to %s" % logger.path)
    try:
        repl(app)
    finally:
        voice_loop.stop()
        _stop_web_servers(ws, httpd)
        logger.close()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--sim", action="store_true", help="scripted demo on a synthetic walk")
    g.add_argument("--replay", metavar="FILE", help="replay a logged walk CSV")
    g.add_argument("--band", action="store_true", help="use the team's band (config.BAND)")
    g.add_argument("--bridge", action="store_true",
                   help="the band connects through Chrome's Bluetooth (click Connect band on the map page)")
    p.add_argument("--ws-port", type=int, default=8765, help="WebSocket port for the map page (default: 8765)")
    p.add_argument("--http-port", type=int, default=8000, help="HTTP port for the map page (default: 8000)")
    p.add_argument("--usb", action="store_true", help="with --band: use the USB cable instead of Bluetooth")
    p.add_argument("--phone", action="store_true",
                   help="let your phone on the same Wi-Fi open the phone page (vibration); prints a link with a secret token")
    p.add_argument("--no-web", action="store_true", help="disable local HTTP/WebSocket servers on --band/--replay")
    a = p.parse_args(argv)
    if a.phone:
        import secrets
        PHONE["token"] = secrets.token_urlsafe(9)
    if a.sim:
        return run_sim()
    if a.replay:
        return run_replay(a.replay, ws_port=a.ws_port, http_port=a.http_port, no_web=a.no_web)
    if a.bridge:
        return run_bridge(ws_port=a.ws_port, http_port=a.http_port)
    return run_band(ws_port=a.ws_port, http_port=a.http_port, no_web=a.no_web, usb=a.usb)


if __name__ == "__main__":
    sys.exit(main())
