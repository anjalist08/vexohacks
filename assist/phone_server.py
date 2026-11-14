"""Serves assist/phone.html to the phone and talks to it over a websocket.

    python3 -m assist.phone_server --demo      synthetic walk; a connected phone vibrates
    python3 -m assist.phone_server --learn     plays every vibration pattern, with its name

Open the address it prints on the phone (same Wi-Fi), and tap Start. The phone then
gets {"type": "haptic", ...} messages and sends back compass readings and "confirm".

The phone's compass only works on an https:// page. Give the server a certificate:
    python3 -m assist.phone_server --demo --cert cert.pem --key key.pem
(see assist/README.md). Vibration works on Android Chrome over plain http too.

The server listens on the local network, so it serves nothing but this one page, and the
page and websocket need the random token in the printed address. Stdlib only.
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


def make_handler(hub: PhoneHub, token: str):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parts = urlsplit(self.path)
            if parse_qs(parts.query).get("k", [""])[0] != token:
                self.send_error(403)
                return
            if parts.path == "/ws" and self.headers.get("Upgrade", "").lower() == "websocket":
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
            if parts.path not in ("/", "/phone.html"):
                self.send_error(404)
                return
            with open(PAGE, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def start(hub: PhoneHub, host="0.0.0.0", port=8765, cert=None, key=None):
    """Start the server on a background thread. Returns (server, address to open)."""
    token = secrets.token_urlsafe(8)
    server = http.server.ThreadingHTTPServer((host, port), make_handler(hub, token))
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
    g.add_argument("--learn", action="store_true", help="play every vibration pattern with its name")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="0.0.0.0", help="0.0.0.0 so the phone can reach it")
    p.add_argument("--cert", help="certificate file, for https (needed for the compass)")
    p.add_argument("--key", help="its private key file")
    a = p.parse_args(argv)

    hub = PhoneHub()
    server, url = start(hub, a.host, a.port, a.cert, a.key)
    print("On the phone (same Wi-Fi), open:\n\n    %s\n\nthen tap Start. Ctrl-C to stop." % url)
    hub.connected.wait()
    time.sleep(1.5)
    try:
        if a.learn:
            from assist.haptics import HAPTIC_PATTERNS, haptic_message
            for cue in HAPTIC_PATTERNS:
                name = cue.replace("_", " ")
                print("    [BUZZ] %s" % name)
                hub.broadcast(haptic_message(cue, name))
                time.sleep(3.0)
        else:
            from assist import demo

            def send(msg):
                demo.print_haptic(msg)
                hub.broadcast(msg)
            demo.run(send=send, pause=3.0)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
