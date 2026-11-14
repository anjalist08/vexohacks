"""Web Push: notifications to the phone page itself, with no app to install.

An iPhone (iOS 16.4 or newer) lets a web page send notifications once the page is added
to the Home Screen. A notification buzzes the iPhone, and when the phone is locked it
should reach a paired Apple Watch like other iPhone notifications. Android Chrome takes
the same pushes with no Home Screen step, and they also arrive while the screen is off.

Like assist/notify.py, only the key moments are sent, with fixed generic words: the
"are you at ...?" prompt, arrival and "not sure where you are". Turns stay with the
spoken audio, because every notification feels the same and can arrive late.

How it works: the phone subscribes and hands the laptop an address at Apple's (or
Google's) push service plus two keys. The laptop signs each request with its own key
pair (VAPID, RFC 8292) and encrypts the message for that phone (RFC 8291), so the push
service only carries bytes it cannot read. Both sides need the internet.

Needs `python3 -m pip install cryptography` on the laptop. Files, kept out of git:
    data/push/vapid_private.pem      the laptop's signing key (made on first use)
    data/push/subscriptions.json     the phones that subscribed
"""
import base64
import hashlib
import hmac
import json
import os
import struct
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, List, Optional
from urllib.parse import urlsplit

from assist.notify import MESSAGES, REPEAT_S

PUSH_DIR = os.path.join("data", "push")
DEFAULT_CONTACT = "mailto:noreply@example.com"   # VAPID "sub": a contact for the push service


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def _ec():
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        return ec
    except ImportError:
        raise RuntimeError("iPhone notifications need:  python3 -m pip install cryptography") from None


def _public_bytes(key) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return key.public_key().public_bytes(serialization.Encoding.X962,
                                         serialization.PublicFormat.UncompressedPoint)


def encrypt(plaintext: bytes, p256dh: str, auth: str, salt: bytes = None, server_key=None) -> bytes:
    """Encrypt one message for one subscription (RFC 8291, aes128gcm, a single record)."""
    ec = _ec()
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ua_public = unb64u(p256dh)
    auth_secret = unb64u(auth)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _public_bytes(server_key)
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = server_key.exchange(ec.ECDH(), peer)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    body = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    return salt + struct.pack(">IB", 4096, len(as_public)) + as_public + body


class Vapid:
    """The laptop's signing key pair. The public half goes to the page."""

    def __init__(self, path: Optional[str] = None, contact: str = DEFAULT_CONTACT):
        from cryptography.hazmat.primitives import serialization
        ec = _ec()
        self.contact = contact
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                self.key = serialization.load_pem_private_key(f.read(), password=None)
        else:
            self.key = ec.generate_private_key(ec.SECP256R1())
            if path:
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                pem = self.key.private_bytes(serialization.Encoding.PEM,
                                             serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption())
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(pem)
        self.public_key = b64u(_public_bytes(self.key))

    def header(self, endpoint: str, now: float = None) -> str:
        """The Authorization header for a request to this endpoint (RFC 8292)."""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        ec = _ec()
        parts = urlsplit(endpoint)
        claims = {"aud": "%s://%s" % (parts.scheme, parts.netloc),
                  "exp": int((now or time.time()) + 12 * 3600), "sub": self.contact}
        signing = b64u(b'{"typ":"JWT","alg":"ES256"}') + "." + b64u(json.dumps(claims).encode())
        r, s = decode_dss_signature(self.key.sign(signing.encode(), ec.ECDSA(hashes.SHA256())))
        token = signing + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        return "vapid t=%s, k=%s" % (token, self.public_key)


def _post(url: str, body: bytes, headers: dict, timeout: float = 10.0) -> int:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def valid_subscription(sub) -> bool:
    """A subscription from the page: an https endpoint and the two keys, nothing odd."""
    try:
        keys = sub["keys"]
        ok = (urlsplit(sub["endpoint"]).scheme == "https" and len(sub["endpoint"]) < 2048 and
              len(unb64u(keys["p256dh"])) == 65 and len(unb64u(keys["auth"])) == 16)
        return bool(ok)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


class WebPushSender:
    """Call it with a cue message (assist.cues.cue_message), like NtfySender."""

    def __init__(self, vapid: Vapid, store_path: Optional[str] = None,
                 post: Callable[[str, bytes, dict], int] = _post,
                 clock: Callable[[], float] = time.monotonic, background: bool = True):
        self.vapid = vapid
        self.store_path = store_path
        self.post = post
        self.clock = clock
        self.background = background
        self.sent = 0
        self._lock = threading.Lock()
        self._last = {}
        self._warned = False
        self.subscriptions: List[dict] = []
        if store_path and os.path.exists(store_path):
            with open(store_path) as f:
                self.subscriptions = [s for s in json.load(f) if valid_subscription(s)]

    def subscribe(self, sub: dict) -> bool:
        if not valid_subscription(sub):
            return False
        clean = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["keys"]["p256dh"],
                                                       "auth": sub["keys"]["auth"]}}
        with self._lock:
            self.subscriptions = [s for s in self.subscriptions if s["endpoint"] != clean["endpoint"]]
            self.subscriptions.append(clean)
            self._save()
        return True

    def _save(self):
        if not self.store_path:
            return
        os.makedirs(os.path.dirname(self.store_path) or ".", exist_ok=True)
        fd = os.open(self.store_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self.subscriptions, f)

    def __call__(self, msg: dict) -> bool:
        cue = msg.get("cue")
        if cue not in MESSAGES or not self.subscriptions:
            return False
        now = self.clock()
        if now - self._last.get(cue, -1e9) < REPEAT_S:
            return False
        self._last[cue] = now
        title, text, _ = MESSAGES[cue]                  # never msg["say"]: it can hold names
        payload = json.dumps({"title": title, "body": text, "cue": cue}).encode()
        if self.background:
            threading.Thread(target=self._send_all, args=(payload,), daemon=True).start()
        else:
            self._send_all(payload)
        return True

    def _send_all(self, payload: bytes):
        with self._lock:
            subs = list(self.subscriptions)
        gone = []
        for sub in subs:
            try:
                status = self.post(sub["endpoint"], encrypt(payload, **sub["keys"]), {
                    "Authorization": self.vapid.header(sub["endpoint"]),
                    "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
                    "TTL": "60", "Urgency": "high"})
            except Exception as e:                      # offline: warn once, keep going
                status = None
                if not self._warned:
                    self._warned = True
                    print("    [PUSH] could not send a notification (%s). Guidance goes on without it."
                          % type(e).__name__)
            if status in (404, 410):                    # the phone unsubscribed
                gone.append(sub["endpoint"])
            elif status is not None and 200 <= status < 300:
                self.sent += 1
            elif status is not None and not self._warned:
                self._warned = True
                print("    [PUSH] the push service answered %d." % status)
        if gone:
            with self._lock:
                self.subscriptions = [s for s in self.subscriptions if s["endpoint"] not in gone]
                self._save()


def default_sender(contact: str = DEFAULT_CONTACT) -> WebPushSender:
    return WebPushSender(Vapid(os.path.join(PUSH_DIR, "vapid_private.pem"), contact),
                         os.path.join(PUSH_DIR, "subscriptions.json"))
