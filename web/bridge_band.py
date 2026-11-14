"""A band connected through Chrome (web/band-bridge.js), for when Python cannot use Bluetooth.

Chrome connects to the band with Web Bluetooth, like the kit's dashboard, and relays its
events here over the local WebSocket. BridgeBand looks like the kit's sync Band to the rest
of the app (on / off / configure / set_led / led_off / wait), so the tracker, the LED
controller and the voice loop work unchanged. Commands go back to the page as `band_cmd`.

Only the team's band: the page connects to config.BAND and checks the number.
"""
import base64
import threading
import time
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional

import config


class BridgeBand:
    def __init__(self, send: Callable[[dict], None], number: Optional[int] = None):
        self._send = send
        self.number = number if number is not None else config.BAND
        self.name = "Vexo-HACK-%02d" % self.number if self.number else "band"
        self.connected = False
        self.audio = False                     # the voice loop checks this to switch the mic off
        self.storage = None                    # no on-band storage over the bridge
        self.transport_kind = "chrome"
        self._handlers: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()

    # --- the band interface the app uses ---------------------------------------
    def on(self, kind: str, fn: Callable) -> None:
        with self._lock:
            self._handlers.setdefault(kind, []).append(fn)

    def off(self, kind: str, fn: Callable) -> None:
        with self._lock:
            if fn in self._handlers.get(kind, []):
                self._handlers[kind].remove(fn)

    def configure(self, **settings) -> None:
        if "audio" in settings:
            self.audio = bool(settings["audio"])
        self._send({"type": "band_cmd", "op": "configure", "args": settings})

    def set_led(self, color: str = "#ffffff", brightness: float = 1.0, pattern: str = "solid",
                period: int = 1000) -> None:
        self._send({"type": "band_cmd", "op": "setLed",
                    "args": {"color": color, "brightness": brightness, "pattern": pattern, "period": period}})

    def led_off(self) -> None:
        self._send({"type": "band_cmd", "op": "ledOff", "args": {}})

    def wait(self, seconds: float) -> None:
        time.sleep(max(0.0, float(seconds or 0)))

    def disconnect(self) -> None:
        self.connected = False

    # --- from the page ---------------------------------------------------------
    def receive(self, msg: dict) -> None:
        """One `band_event` from the page: call the handlers for its kind."""
        kind = msg.get("kind")
        fields = {k: v for k, v in msg.items() if k not in ("type", "kind")}
        if kind == "audio":
            try:
                fields["opus"] = base64.b64decode(fields.get("opus") or "")
            except (ValueError, TypeError):
                return
        if kind == "event":
            fields["kind"] = fields.pop("event", None)
        event = SimpleNamespace(**fields)
        self._dispatch(kind, event)
        if kind == "event" and event.kind:     # also as "tap", "double-tap", ...
            self._dispatch(event.kind, event)

    def _dispatch(self, kind: str, event) -> None:
        with self._lock:
            handlers = list(self._handlers.get(kind, []))
        for fn in handlers:
            try:
                fn(event)
            except Exception as exc:          # one bad handler must not stop the stream
                print("    [BRIDGE] handler for %s failed: %s" % (kind, exc.__class__.__name__))


def wire(band: BridgeBand, tracker, logger=None, on_double_tap=None, on_metric=None) -> None:
    """Feed the tracker and the voice loop from the bridged band, as band_source.connect does."""
    metric = on_metric or (lambda kind, fields: None)

    def motion(m):
        tracker.on_motion(m.time, m.ax, m.ay, m.az, m.gx, m.gy, m.gz)
        if logger:
            logger.log("motion", m.time, dict(ax=m.ax, ay=m.ay, az=m.az, gx=m.gx, gy=m.gy, gz=m.gz))

    def activity(e):
        tracker.on_activity(e.time, e.steps, e.state)
        metric("activity", dict(steps=e.steps, cadence=e.cadence, state=e.state, motion=e.motion))
        if logger:
            logger.log("activity", e.time, dict(steps=e.steps, state=e.state))

    band.on("motion", motion)
    band.on("activity", activity)
    band.on("battery", lambda e: metric("battery", dict(percent=e.percent, millivolts=e.millivolts, state=e.state)))
    band.on("temperature", lambda e: metric("temperature", dict(celsius=e.celsius)))
    band.on("event", lambda e: metric("event", dict(kind=e.kind, arg=getattr(e, "arg", None))))
    if on_double_tap:
        band.on("double-tap", lambda e: on_double_tap())


def configure_streams(band: BridgeBand) -> None:
    """What band_source.connect turns on, sent to the page once Chrome has connected."""
    band.configure(motion=config.MOTION_RATE_HZ, sensors="both", activity=config.ACTIVITY_RATE,
                   events=True, battery=True, temperature=5)
