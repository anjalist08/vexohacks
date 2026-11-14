"""The dashboard's server: Python's built-in web server, nothing to install.

    GET  /          the dashboard page (web/index.html)
    GET  /state     the whole state as JSON
    GET  /events    live updates (Server-Sent Events): one JSON state per change, at most 10 a second
    POST /command   {"text": "..."} runs a typed command through app.keyword_command

It listens on 127.0.0.1 only, and no API key ever reaches the page. A POST from another
website (a different Origin) is refused, so a web page cannot steer the band.
"""
import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List

from voice.led_states import STATES

PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
MAX_RATE_HZ = 10.0


class Dashboard:
    """Collects the app's state and pushes it to every open page."""

    def __init__(self, app, label: str = "LIVE"):
        self.app = app
        self.label = label                  # "LIVE", "SIMULATION" or "REPLAY"
        self.link = "connected" if label == "LIVE" else "none"
        self.last_say = ""
        self.last_result = None
        self.band = {}                      # latest band readings by kind, from set_metric
        self.events = []                    # last few tap/gesture events
        self._clients: List[queue.Queue] = []
        self._lock = threading.Lock()
        self._pending = False
        self._last_push = 0.0
        app.tracker.on_sample(lambda s: self.changed())
        app.on_result.append(self._on_result)

    # --- inputs ----------------------------------------------------------------
    def _on_result(self, result):
        if result.say:
            self.last_say = result.say
        self.last_result = {"ok": result.ok, "say": result.say, "led": result.led}
        self.changed()

    def set_link(self, status: str):
        self.link = status
        self.changed()

    def set_metric(self, kind: str, fields: dict):
        """A band reading (info, activity, battery, temperature, event) for the Band card."""
        if kind == "event":
            self.events = ([dict(fields, time=time.time())] + self.events)[:5]
        else:
            self.band[kind] = dict(fields, time=time.time())
        self.changed()

    # --- state -------------------------------------------------------------------
    def state(self) -> dict:
        app, store = self.app, self.app.store
        route = store.current
        led_state = getattr(app.led, "state", None) or "idle"
        cue = STATES.get(led_state)
        pose = app.tracker.pose
        return {
            "label": self.label,
            "link": self.link,
            "mode": app.mode,
            "led": {"state": led_state, "color": cue.color if cue else None,
                    "pattern": cue.pattern if cue else "off", "period": cue.period if cue else 1000},
            "route": None if route is None else {
                "id": route.id, "title": route.title, "active": route.active,
                "points": [[round(p.x_m, 3), round(p.y_m, 3)] for p in route.points],
                "notes": route.notes},
            "pose": {"x": pose.x_m, "y": pose.y_m, "heading": pose.heading_deg, "steps": pose.steps},
            "tracking": {"running": app.tracker.running, "calibrated": app.tracker.calibrated,
                         "state": app.tracker.state, "step_length_m": app.tracker.step_length_m,
                         "yaw_rate": round(getattr(app.tracker, "yaw_rate", 0.0), 1),
                         "bias": round(app.tracker.bias, 2)},
            "band": self.band,
            "events": self.events,
            "landmarks": [dict(l.to_dict(), x=route.points[l.point_index].x_m, y=route.points[l.point_index].y_m)
                          for l in (route.landmarks if route else [])],
            "guidance": [i.to_dict() for i in app.guidance],
            "say": self.last_say,
            "result": self.last_result,
            "time": time.time(),
        }

    # --- pushing -------------------------------------------------------------------
    def changed(self):
        """Something changed: push the state now, or within 1/MAX_RATE_HZ seconds."""
        with self._lock:
            if self._pending:
                return
            wait = self._last_push + 1.0 / MAX_RATE_HZ - time.time()
            if wait > 0:
                self._pending = True
                t = threading.Timer(wait, self._push_later)
                t.daemon = True
                t.start()
                return
        self._push()

    def _push_later(self):
        with self._lock:
            self._pending = False
        self._push()

    def _push(self):
        with self._lock:
            self._last_push = time.time()
            clients = list(self._clients)
        if not clients:
            return
        data = json.dumps(self.state())
        for q in clients:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=50)
        with self._lock:
            self._clients.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    # --- serving -------------------------------------------------------------------
    def serve(self, port: int = 8000, host: str = "127.0.0.1") -> ThreadingHTTPServer:
        """Start serving in a background thread. Returns the server (call .shutdown() to stop)."""
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body: bytes, kind: str):
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    with open(PAGE, "rb") as f:
                        self._send(200, f.read(), "text/html; charset=utf-8")
                elif path == "/state":
                    self._send(200, json.dumps(dashboard.state()).encode(), "application/json")
                elif path == "/events":
                    self._events()
                else:
                    self._send(404, b"not found", "text/plain")

            def _events(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                q = dashboard.subscribe()
                try:
                    self.wfile.write(("data: %s\n\n" % json.dumps(dashboard.state())).encode())
                    self.wfile.flush()
                    while True:
                        try:
                            data = q.get(timeout=15)
                            self.wfile.write(("data: %s\n\n" % data).encode())
                        except queue.Empty:
                            self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    dashboard.unsubscribe(q)

            def do_POST(self):
                if self.path != "/command":
                    return self._send(404, b"not found", "text/plain")
                origin = self.headers.get("Origin")
                if origin and origin.split("//", 1)[-1] != self.headers.get("Host", ""):
                    return self._send(403, b"other sites may not send commands", "text/plain")
                try:
                    size = min(int(self.headers.get("Content-Length", "0")), 4096)
                    text = str(json.loads(self.rfile.read(size) or b"{}").get("text", "")).strip()[:300]
                except (ValueError, AttributeError):
                    return self._send(400, b"send JSON like {\"text\": \"...\"}", "text/plain")
                if not text:
                    return self._send(400, b"empty command", "text/plain")
                if text.lower() == "delete all":
                    dashboard.app.store.delete_all()
                    dashboard.app.guidance = []
                    dashboard.changed()
                    body = {"ok": True, "say": "All routes deleted."}
                else:
                    r = dashboard.app.keyword_command(text)
                    body = {"ok": r.ok, "say": r.say, "led": r.led}
                self._send(200, json.dumps(body).encode(), "application/json")

        server = ThreadingHTTPServer((host, port), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
