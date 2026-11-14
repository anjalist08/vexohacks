"""Pure-stdlib RFC 6455 WebSocket server bridging SpatialMemoryApp to the map page.

Run standalone preview (serves static files on 127.0.0.1:8000 and WS on 127.0.0.1:8765):
    python3 -m web.ws_server --sim
    python3 -m web.ws_server --replay data/logs/walk.csv

Safety rules:
- Binds strictly to 127.0.0.1 by default.
- Never reads, logs, or transmits API keys or .env files.
- Explicitly labels SIMULATION and REPLAY modes so synthetic/logged data is never
  presented as live sensing.
"""
import argparse
import base64
import functools
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional
from urllib.parse import unquote, urlsplit

from app import SpatialMemoryApp

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_HEADER_BYTES = 8192
MAX_MESSAGE_BYTES = 1 << 20  # 1 MiB

VALID_MODES = ("LIVE", "SIMULATION", "REPLAY")


def accept_key(sec_key: str) -> str:
    """Compute RFC 6455 Sec-WebSocket-Accept header value."""
    digest = hashlib.sha1((sec_key.strip() + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(opcode: int, payload: bytes) -> bytes:
    """Encode an unmasked server-to-client RFC 6455 WebSocket frame."""
    header = bytearray([0x80 | (opcode & 0x0F)])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(127)
        header.extend(struct.pack(">Q", length))
    return bytes(header) + payload


def _read_exact(sock: socket.socket, count: int) -> bytes:
    buf = bytearray()
    while len(buf) < count:
        chunk = sock.recv(count - len(buf))
        if not chunk:
            raise ConnectionError("WebSocket client closed connection")
        buf.extend(chunk)
    return bytes(buf)


def read_frame(sock: socket.socket):
    """Read one RFC 6455 frame from `sock`. Returns (fin, opcode, payload_bytes)."""
    b1, b2 = _read_exact(sock, 2)
    fin = bool(b1 & 0x80)
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack(">H", _read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _read_exact(sock, 8))[0]
    if length > MAX_MESSAGE_BYTES:
        raise ValueError("WebSocket frame exceeds maximum size")
    mask_key = _read_exact(sock, 4) if masked else None
    payload = _read_exact(sock, length) if length else b""
    if mask_key:
        payload = bytes(b ^ mask_key[i & 3] for i, b in enumerate(payload))
    return fin, opcode, payload


class _ClientConnection:
    """Thread-safe wrapper around one browser WebSocket connection."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self._lock = threading.Lock()
        self.closed = False

    def send_raw_frame(self, opcode: int, payload: bytes) -> bool:
        frame_bytes = encode_frame(opcode, payload)
        with self._lock:
            if self.closed:
                return False
            try:
                self.sock.sendall(frame_bytes)
                return True
            except OSError:
                self.closed = True
                return False

    def send_json(self, message: dict) -> bool:
        data = json.dumps(message, separators=(",", ":")).encode("utf-8")
        return self.send_raw_frame(0x1, data)

    def close(self) -> None:
        with self._lock:
            if self.closed:
                return
            self.closed = True
            try:
                self.sock.sendall(encode_frame(0x8, struct.pack(">H", 1000)))
            except OSError:
                pass
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class MapWebSocketServer:
    """RFC 6455 WebSocket server pushing live route, landmark, LED, and guidance state."""

    def __init__(
        self,
        app: SpatialMemoryApp,
        host: str = "127.0.0.1",
        port: int = 8765,
        mode: str = "SIMULATION",
        link_status: Optional[str] = None,
    ):
        self.app = app
        self._requested_host = host
        self._requested_port = port
        self._bound_host = host
        self._bound_port = port

        norm_mode = (mode or "SIMULATION").upper()
        self.mode = norm_mode if norm_mode in VALID_MODES else "SIMULATION"
        if link_status is not None:
            self.link_status = link_status
        elif self.mode == "LIVE":
            self.link_status = "connected"
        elif self.mode == "REPLAY":
            self.link_status = "replay"
        else:
            self.link_status = "simulated"

        self._led_state = getattr(app, "led_state", "idle")
        self._led_period: Optional[int] = None

        self._server_sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._client_threads: List[threading.Thread] = []
        self._clients: List[_ClientConnection] = []
        self._clients_lock = threading.Lock()
        self._app_lock = threading.RLock()
        self._running = False

    @property
    def host(self) -> str:
        return self._bound_host

    @property
    def port(self) -> int:
        return self._bound_port

    def __enter__(self) -> "MapWebSocketServer":
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    def start(self) -> "MapWebSocketServer":
        """Bind listening socket, subscribe to app events, and start background threads."""
        if self._running:
            return self
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self._requested_host, self._requested_port))
        sock.listen(16)
        addr = sock.getsockname()
        self._bound_host = addr[0]
        self._bound_port = int(addr[1])
        self._server_sock = sock
        self._running = True

        self.app.on_event(self._on_app_event)

        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="map-ws-accept",
            daemon=True,
        )
        self._accept_thread.start()
        return self

    def stop(self) -> None:
        """Stop accepting connections and cleanly close all client sockets."""
        if not self._running:
            return
        self._running = False
        self.app.remove_event_listener(self._on_app_event)

        if self._server_sock is not None:
            try:
                self._server_sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None

        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            client.close()

        if self._accept_thread is not None and self._accept_thread.is_alive():
            self._accept_thread.join(timeout=1.5)
        for t in list(self._client_threads):
            if t.is_alive():
                t.join(timeout=0.5)
        self._client_threads.clear()

    # --- outbound push API -------------------------------------------------------
    def broadcast(self, msg_dict: dict) -> None:
        """Broadcast a JSON dictionary to every connected browser tab."""
        with self._clients_lock:
            clients = list(self._clients)
        dead: List[_ClientConnection] = []
        for client in clients:
            if not client.send_json(msg_dict):
                dead.append(client)
        if dead:
            with self._clients_lock:
                for client in dead:
                    if client in self._clients:
                        self._clients.remove(client)

    def send_mode(self, mode: str) -> None:
        norm = (mode or "SIMULATION").upper()
        self.mode = norm if norm in VALID_MODES else "SIMULATION"
        self.broadcast({"type": "mode", "mode": self.mode})

    def send_link(self, status: str) -> None:
        self.link_status = status
        self.broadcast({"type": "link", "status": status})

    def send_led(self, state: str, period: Optional[int] = None) -> None:
        self._led_state = state
        self._led_period = period
        msg = {"type": "led", "state": state}
        if period is not None:
            msg["period"] = period
        self.broadcast(msg)

    def _on_app_event(self, event: dict) -> None:
        etype = event.get("type")
        if etype == "led":
            self._led_state = event.get("state", self._led_state)
            self._led_period = event.get("period")
        self.broadcast(event)

    # --- connection lifecycle ----------------------------------------------------
    def attach_socket(self, conn: socket.socket) -> None:
        """Spawn a client handler thread for an already-accepted stream socket."""
        if not self._running:
            try:
                conn.close()
            except OSError:
                pass
            return
        t = threading.Thread(
            target=self._handle_client,
            args=(conn,),
            name="map-ws-client",
            daemon=True,
        )
        self._client_threads = [th for th in self._client_threads if th.is_alive()] + [t]
        t.start()

    def _accept_loop(self) -> None:
        while self._running and self._server_sock is not None:
            try:
                conn, _ = self._server_sock.accept()
            except OSError:
                break
            self.attach_socket(conn)

    def _perform_handshake(self, sock: socket.socket) -> bool:
        sock.settimeout(5.0)
        raw = bytearray()
        while b"\r\n\r\n" not in raw and len(raw) < MAX_HEADER_BYTES:
            try:
                chunk = sock.recv(1024)
            except OSError:
                return False
            if not chunk:
                return False
            raw.extend(chunk)

        header_end = raw.find(b"\r\n\r\n")
        if header_end < 0:
            return False

        header_text = bytes(raw[:header_end]).decode("latin-1", errors="replace")
        lines = header_text.split("\r\n")
        if not lines or not lines[0].startswith("GET "):
            self._send_http_error(sock, 400, "Bad Request")
            return False

        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        sec_key = headers.get("sec-websocket-key", "")
        upgrade = headers.get("upgrade", "").lower()
        if not sec_key or "websocket" not in upgrade:
            self._send_http_error(sock, 400, "Bad Request")
            return False

        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: %s\r\n\r\n" % accept_key(sec_key)
        )
        try:
            sock.sendall(response.encode("ascii"))
            sock.settimeout(None)
            return True
        except OSError:
            return False

    @staticmethod
    def _send_http_error(sock: socket.socket, code: int, reason: str) -> None:
        try:
            sock.sendall(("HTTP/1.1 %d %s\r\nConnection: close\r\n\r\n" % (code, reason)).encode("ascii"))
        except OSError:
            pass

    def _build_initial_snapshot(self) -> List[dict]:
        """Snapshot full current app state so a newly opened/refreshed tab is in sync."""
        msgs: List[dict] = []
        with self._app_lock:
            msgs.append({"type": "mode", "mode": self.mode})
            msgs.append({"type": "link", "status": self.link_status})

            led_state = getattr(self.app, "led_state", self._led_state) or "idle"
            led_msg = {"type": "led", "state": led_state}
            if self._led_period is not None:
                led_msg["period"] = self._led_period
            msgs.append(led_msg)

            route = self.app.store.current
            if route is not None:
                breaks = set(getattr(route, "breaks", []))
                for i, pt in enumerate(route.points):
                    msg = {"type": "point", **pt.to_dict()}
                    if i in breaks:
                        msg["jump"] = True       # a re-anchor reset, not a walked step
                    msgs.append(msg)
                for lm in route.landmarks:
                    msgs.append({"type": "landmark", **self.app._landmark_payload(lm)})

            if self.app.navigator is not None:
                msgs.append({"type": "guidance", **self.app.navigator.to_dict()})
            elif self.app.guidance:
                msgs.append({
                    "type": "guidance",
                    "instructions": [i.to_dict() for i in self.app.guidance],
                    "current_index": 0,
                    "active": False,
                    "waypoints": [],
                })
            else:
                msgs.append({
                    "type": "guidance",
                    "instructions": [],
                    "current_index": 0,
                    "active": False,
                    "waypoints": [],
                })

            if self.app.navigator is not None and self.app.navigator.active and self.app.tracker.points:
                msgs.append({"type": "point", **self.app.current_pose.to_dict()})

        return msgs

    def _handle_client(self, sock: socket.socket) -> None:
        if not self._perform_handshake(sock):
            try:
                sock.close()
            except OSError:
                pass
            return

        client = _ClientConnection(sock)
        for msg in self._build_initial_snapshot():
            if not client.send_json(msg):
                client.close()
                return

        with self._clients_lock:
            if not self._running:
                client.close()
                return
            self._clients.append(client)

        fragments: List[bytes] = []
        frag_opcode = 0
        try:
            while self._running and not client.closed:
                try:
                    fin, opcode, payload = read_frame(sock)
                except (ConnectionError, OSError, ValueError):
                    break

                if opcode == 0x8:  # close
                    break
                if opcode == 0x9:  # ping -> pong
                    client.send_raw_frame(0xA, payload)
                    continue
                if opcode == 0xA:  # pong
                    continue

                if opcode in (0x1, 0x2):
                    frag_opcode = opcode
                    fragments = [payload]
                elif opcode == 0x0 and frag_opcode:
                    fragments.append(payload)
                else:
                    continue

                if sum(len(part) for part in fragments) > MAX_MESSAGE_BYTES:
                    break

                if fin:
                    whole = b"".join(fragments)
                    fragments = []
                    if frag_opcode == 0x1:
                        text = whole.decode("utf-8", errors="replace")
                        self._handle_client_message(client, text)
                    frag_opcode = 0
        finally:
            with self._clients_lock:
                if client in self._clients:
                    self._clients.remove(client)
            client.close()

    def _handle_client_message(self, client: _ClientConnection, raw_text: str) -> None:
        text = raw_text.strip()
        if not text:
            return
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None

        if isinstance(parsed, dict):
            mtype = parsed.get("type")
            if mtype == "ping":
                client.send_json({"type": "pong"})
                return
            if mtype == "talk":                  # the page's Talk button: same as a double-tap
                loop = getattr(self, "voice_loop", None)
                if loop is not None and getattr(loop, "band", None) is not None:
                    loop.on_double_tap()
                else:
                    client.send_json({"type": "voice", "state": "error",
                                      "text": "Voice needs the live band: run python3 main.py --band."})
                return
            cmd_text = str(parsed.get("text") or parsed.get("command") or "").strip()
        elif isinstance(parsed, str):
            cmd_text = parsed.strip()
        else:
            cmd_text = text

        if not cmd_text:
            return

        cleaned = cmd_text.lower().strip().rstrip(".!?")
        with self._app_lock:
            if cleaned in ("delete all", "clear all", "forget all"):
                self.app.delete_all()
                self.broadcast({"type": "say", "text": "All routes and landmarks deleted."})
                return
            loop = getattr(self, "voice_loop", None)
            if loop is None:
                self.app.keyword_command(cmd_text)
                return
        # With the live voice loop, typed text is understood by Gemini like speech (keyword
        # fallback inside). Run it off this connection's thread: a model call takes ~1-2 s.
        threading.Thread(target=loop.run_turn, kwargs={"say_text": cmd_text}, daemon=True).start()


# --- Standalone local HTTP + WebSocket preview runner ----------------------------

class _SafeStaticHandler(SimpleHTTPRequestHandler):
    """Serves static project files while strictly blocking dotfiles (.env, .git)."""

    def do_GET(self):
        if self._is_forbidden_path():
            self.send_error(403, "Forbidden")
            return
        super().do_GET()

    def do_HEAD(self):
        if self._is_forbidden_path():
            self.send_error(403, "Forbidden")
            return
        super().do_HEAD()

    def _is_forbidden_path(self) -> bool:
        raw_path = unquote(urlsplit(self.path).path or "/")
        parts = [p for p in raw_path.split("/") if p and p != "."]
        for part in parts:
            if part == ".." or part.startswith(".") or part.lower().endswith(".env"):
                return True
        return False

    def log_message(self, fmt, *args):
        # Keep console focused on spatial memory output.
        pass


def _start_static_http(host: str, port: int, root_dir: str) -> ThreadingHTTPServer:
    handler = functools.partial(_SafeStaticHandler, directory=root_dir)
    httpd = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=httpd.serve_forever, name="map-http", daemon=True)
    thread.start()
    return httpd


def _stream_events(tracker, events, now_ref, stop_event: threading.Event, speed: float = 2.5) -> None:
    if not events:
        return
    prev_t = events[0][1]
    for kind, t, fields in events:
        if stop_event.is_set():
            break
        dt = max(0.0, t - prev_t)
        prev_t = t
        if dt > 0 and speed > 0:
            stop_event.wait(min(0.15, dt / speed))
        now_ref[0] = t
        if kind == "motion":
            tracker.on_motion(t, fields["ax"], fields["ay"], fields["az"],
                              fields["gx"], fields["gy"], fields["gz"])
        elif kind == "activity":
            tracker.on_activity(t, fields["steps"], fields["state"])


def _run_sim_demo(app: SpatialMemoryApp, ws: MapWebSocketServer, now_ref: list,
                  stop_event: threading.Event, speed: float) -> None:
    from tracker.events import synthetic_walk

    # Brief pause so an open browser tab sees the walk from step 0.
    stop_event.wait(1.0)
    if stop_event.is_set():
        return

    with ws._app_lock:
        app.keyword_command("start route")
        app.keyword_command("remember this as the entrance")

    leg1 = synthetic_walk(legs=((20, "left"),), t0=now_ref[0])
    _stream_events(app.tracker, leg1, now_ref, stop_event, speed=speed)
    if stop_event.is_set():
        return

    with ws._app_lock:
        app.keyword_command("remember this as the elevator near the blue sign")

    steps1 = [f["steps"] for k, _, f in leg1 if k == "activity"][-1]
    leg2 = synthetic_walk(legs=((15, None),), t0=now_ref[0] + 0.04, start_steps=steps1, seed=2)
    _stream_events(app.tracker, leg2, now_ref, stop_event, speed=speed)
    if stop_event.is_set():
        return

    with ws._app_lock:
        app.keyword_command("remember this as the coffee bar")
        app.keyword_command("take me back to the entrance")

    # Walk back along the reversed L-route so judges see step-by-step advancing guidance!
    steps2 = [f["steps"] for k, _, f in leg2 if k == "activity"][-1]
    ret_walk = synthetic_walk(
        legs=((0, "around"), (15, "right"), (20, None)),
        t0=now_ref[0] + 0.04,
        start_steps=steps2,
        seed=3,
    )
    _stream_events(app.tracker, ret_walk, now_ref, stop_event, speed=speed)


def main(argv: Optional[List[str]] = None) -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    import keys
    keys.prepare()

    from store.route_store import RouteStore
    from tracker.events import read_log
    from tracker.pdr import PathTracker

    parser = argparse.ArgumentParser(description="Live Spatial Memory Map WebSocket & HTTP preview server.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sim", action="store_true", help="stream a synthetic walk (labelled SIMULATION)")
    group.add_argument("--replay", metavar="CSV", help="stream a logged CSV walk (labelled REPLAY)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--ws-port", type=int, default=8765, help="WebSocket port (default: 8765)")
    parser.add_argument("--http-port", type=int, default=8000, help="HTTP static port (default: 8000)")
    parser.add_argument("--no-http", action="store_true", help="do not start the built-in static HTTP server")
    parser.add_argument("--speed", type=float, default=3.0, help="playback speed multiplier (default: 3.0)")
    args = parser.parse_args(argv)

    mode = "SIMULATION" if args.sim else "REPLAY"
    banner = (
        "SIMULATION: synthetic walk (not live sensing)."
        if mode == "SIMULATION"
        else "REPLAY: recorded walk from %s (not live sensing)." % args.replay
    )
    print(banner)

    now_ref = [time.time()]
    tracker = PathTracker()
    store = RouteStore()
    app = SpatialMemoryApp(
        tracker,
        store,
        speak=lambda s: print("    [SAY] %s" % s),
        led=None,
        clock=lambda: now_ref[0],
    )

    ws = MapWebSocketServer(app, host=args.host, port=args.ws_port, mode=mode).start()
    httpd = None
    if not args.no_http:
        try:
            httpd = _start_static_http(args.host, args.http_port, repo_root)
            print("Map page:  http://localhost:%d/web/" % args.http_port)
        except OSError as exc:
            print("HTTP port %d busy (%s); run python3 -m http.server --bind 127.0.0.1 separately." % (args.http_port, exc))
    print("WebSocket: ws://%s:%d" % (ws.host, ws.port))
    print('Press Ctrl+C to stop, or type commands in the browser map page.')

    stop_event = threading.Event()
    if args.sim:
        worker = threading.Thread(
            target=_run_sim_demo,
            args=(app, ws, now_ref, stop_event, args.speed),
            daemon=True,
        )
        worker.start()
    else:
        events = read_log(args.replay)
        if events:
            now_ref[0] = events[0][1]
        with ws._app_lock:
            app.call_tool("start_route", {"title": "replay"})
        worker = threading.Thread(
            target=_stream_events,
            args=(app.tracker, events, now_ref, stop_event, args.speed),
            daemon=True,
        )
        worker.start()

    try:
        while not stop_event.is_set():
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nStopping servers...")
    finally:
        stop_event.set()
        ws.stop()
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
