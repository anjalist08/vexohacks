"""Serves assist/phone.html to the phone and talks to it over a websocket.

    python3 -m assist.phone_server --demo      synthetic walk; the phone plays every cue
    python3 -m assist.phone_server --learn     plays every cue (sound and vibration), with its name

Open the address it prints on the phone (same Wi-Fi), and tap Start. The phone then
gets {"type": "cue", ...} messages (a sound for headphones, a vibration, a line of text)
and sends back compass readings and "confirm".

The phone's compass only works on an https:// page. Give the server a certificate:
    python3 -m assist.phone_server --demo --cert cert.pem --key key.pem
(see assist/README.md). Vibration works on Android Chrome over plain http too.

    python3 -m assist.phone_server --demo --webpush --cert cert.pem --key key.pem
                                               notifications on iPhone / Apple Watch, no app

The server listens on the local network, so it serves nothing but this one page (and its
service worker and manifest), and every address needs the random token in the printed
address. Stdlib only, except --webpush, which needs the cryptography package.
"""
import argparse
import http.server
import json
import os
import secrets
import socket
import ssl
import struct
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vexo-open-kit", "examples", "python"))
from tiny_websocket import accept_key, frame, read_exactly, read_frame  # noqa: E402

PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phone.html")


class PhoneHub:
    """Connected phones. broadcast() sends to all; on_message gets what they send."""

    def __init__(self, on_message=None):
        self.on_message = on_message or (lambda msg: None)
        self._clients = []
        self._lock = threading.Lock()
        self.connected = threading.Event()

    def broadcast(self, msg: dict):
        data = frame(1, json.dumps(msg).encode(), mask=False)
        with self._lock:
            for sock in list(self._clients):
                try:
                    sock.sendall(data)
                except OSError:
                    self._clients.remove(sock)

    def serve_client(self, sock):
        with self._lock:
            self._clients.append(sock)
        self.connected.set()
        try:
            while True:
                final, opcode, data = read_frame(lambda n: read_exactly(sock, n))
                if opcode == 8:
                    break
                if opcode == 9:
                    with self._lock:
                        sock.sendall(frame(10, data, mask=False))
                    continue
                if opcode != 1 or not final:
                    continue
                try:
                    msg = json.loads(data.decode("utf-8"))
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    self.on_message(msg)
        except (OSError, ValueError, ConnectionError, struct.error):
            pass
        finally:
            with self._lock:
                if sock in self._clients:
                    self._clients.remove(sock)
            try:
                sock.close()
            except OSError:
                pass


SERVICE_WORKER = """// Shows Web Push notifications from the laptop (assist/webpush.py).
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  const title = typeof data.title === 'string' ? data.title : 'Vexo';
  const body = typeof data.body === 'string' ? data.body : '';
  event.waitUntil(self.registration.showNotification(title, { body: body, tag: 'vexo', renotify: true }));
});
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: 'window' }).then((list) =>
    list.length ? list[0].focus() : self.clients.openWindow(self.registration.scope)));
});
"""

MAX_BODY = 4096


def make_handler(hub: PhoneHub, token: str, push=None):
    """push: an assist.webpush.WebPushSender, or None for no notifications."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _authorised(self):
            parts = urlsplit(self.path)
            if parse_qs(parts.query).get("k", [""])[0] != token:
                self.send_error(403)
                return None
            return parts.path

        def _reply(self, status, body=b"", kind="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            path = self._authorised()
            if path is None:
                return
            if path != "/push/subscribe" or push is None:
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                size = -1
            if not 0 < size <= MAX_BODY:
                self.send_error(400)
                return
            try:
                sub = json.loads(self.rfile.read(size).decode("utf-8"))
            except ValueError:
                sub = None
            if not isinstance(sub, dict) or not push.subscribe(sub):
                self.send_error(400)
                return
            print("    [PUSH] a phone subscribed to notifications.")
            self._reply(204)

        def do_GET(self):
            path = self._authorised()
            if path is None:
                return
            if path == "/ws" and self.headers.get("Upgrade", "").lower() == "websocket":
                key = self.headers.get("Sec-WebSocket-Key", "")
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept_key(key))
                self.end_headers()
                self.wfile.flush()
                self.close_connection = True
                hub.serve_client(self.connection)
                return
            if path == "/push/key":
                if push is None:
                    self.send_error(404)
                    return
                self._reply(200, json.dumps({"key": push.vapid.public_key}).encode())
                return
            if path == "/sw.js":
                self._reply(200, SERVICE_WORKER.encode(), "text/javascript; charset=utf-8")
                return
            if path == "/manifest.json":
                manifest = {"name": "Vexo guidance", "short_name": "Vexo", "display": "standalone",
                            "start_url": "/?k=" + token, "scope": "/",
                            "background_color": "#000000", "theme_color": "#000000"}
                self._reply(200, json.dumps(manifest).encode(), "application/manifest+json")
                return
            if path not in ("/", "/phone.html"):
                self.send_error(404)
                return
            with open(PAGE, "rb") as f:
                body = f.read().replace(b"__TOKEN__", token.encode())
            self._reply(200, body, "text/html; charset=utf-8")

    return Handler


def start(hub: PhoneHub, host="0.0.0.0", port=8766, cert=None, key=None, push=None, token=None):
    """Start the server on a background thread. Returns (server, address to open)."""
    token = token or secrets.token_urlsafe(8)
    server = http.server.ThreadingHTTPServer((host, port), make_handler(hub, token, push))
    server.daemon_threads = True
    scheme = "http"
    if cert and key:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    shown = lan_address() if host in ("0.0.0.0", "") else host
    return server, "%s://%s:%d/?k=%s" % (scheme, shown, server.server_address[1], token)


def saved_token(path: str) -> str:
    """The page token kept across restarts, so a Home Screen icon keeps working."""
    if os.path.exists(path):
        with open(path) as f:
            text = f.read().strip()
        if len(text) >= 8:
            return text
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    text = secrets.token_urlsafe(8)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return text


def lan_address() -> str:
    """This computer's address on the Wi-Fi (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--demo", action="store_true", help="run the synthetic-walk demo to the phone")
    g.add_argument("--learn", action="store_true", help="play every cue (sound and vibration) with its name")
    p.add_argument("--laptop-sound", action="store_true",
                   help="also play the cue sounds on this laptop (headphones paired with the laptop)")
    p.add_argument("--port", type=int, default=8766, help="8766: the map page uses 8765")
    p.add_argument("--host", default="0.0.0.0", help="0.0.0.0 so the phone can reach it")
    p.add_argument("--cert", help="certificate file, for https (needed for the compass)")
    p.add_argument("--key", help="its private key file")
    p.add_argument("--webpush", action="store_true",
                   help="notifications to the page itself (iPhone: add it to the Home Screen); needs https")
    p.add_argument("--push-contact", default=None,
                   help="contact the push services may use, mailto: or https: (default %s)" % "a placeholder")
    p.add_argument("--ntfy", metavar="TOPIC",
                   help="also notify through the ntfy app; 'new' makes a topic")
    p.add_argument("--ntfy-server", default=None, help="your own ntfy server (default https://ntfy.sh)")
    a = p.parse_args(argv)

    from assist import notify
    ntfy = push = None
    if a.ntfy:
        topic = notify.new_topic() if a.ntfy == "new" else a.ntfy
        ntfy = notify.NtfySender(topic, a.ntfy_server or notify.DEFAULT_SERVER)
        print("ntfy: in the ntfy app, subscribe to this topic (keep it private):\n\n"
              "    %s\n\nOnly generic words are sent (see assist/notify.py).\n" % topic)
    token = None
    if a.webpush:
        if not (a.cert and a.key):
            p.error("--webpush needs --cert and --key: phones only allow notifications on https pages")
        from assist import webpush
        push = webpush.default_sender(a.push_contact or webpush.DEFAULT_CONTACT)
        token = saved_token(os.path.join(webpush.PUSH_DIR, "page_token"))

    hub = PhoneHub()
    server, url = start(hub, a.host, a.port, a.cert, a.key, push=push, token=token)
    print("On the phone (same Wi-Fi), open:\n\n    %s\n\nthen tap Start. Ctrl-C to stop." % url)
    if push is not None:
        print("iPhone: in Safari tap Share, then Add to Home Screen, open it from the Home Screen,\n"
              "and tap Start to allow notifications. %d phone(s) subscribed so far." % len(push.subscriptions))
    if ntfy is None and push is None:
        hub.connected.wait()
    else:
        input("\nPress Enter to begin, once the phone is set up. ")
    time.sleep(1.5)
    from assist import fan_out
    laptop = None
    if a.laptop_sound:
        from assist.earcons import LaptopSound
        laptop = LaptopSound()
    send_all = fan_out(hub.broadcast, ntfy, push, laptop)
    try:
        if a.learn:
            from assist.cues import CUES, cue_message
            for cue in CUES:
                name = cue.replace("_", " ")
                print("    [CUE] %s" % name)
                send_all(cue_message(cue, name))
                time.sleep(3.0)
        else:
            from assist import demo

            def send(msg):
                demo.print_cue(msg)
                send_all(msg)
            demo.run(send=send, pause=3.0)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
