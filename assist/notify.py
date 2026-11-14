"""Phone notifications through ntfy, so an iPhone and an Apple Watch buzz too.

iPhone browsers cannot vibrate a web page, and the Apple Watch has no browser. A
notification does buzz both: the iPhone, or the Watch's tap on the wrist when the phone
is locked. Every notification feels the same, and it can arrive a second or more late,
so only the key moments are sent: the "are you at ...?" prompt, arrival, and "not
sure where you are". Turn-by-turn stays with the spoken audio.

Setup on the phone: install the free "ntfy" app and subscribe to your topic.
On the laptop:

    python3 -m assist.phone_server --demo --ntfy new          # makes and prints a topic
    python3 -m assist.phone_server --demo --ntfy <your topic>

Privacy: messages go through the ntfy server (ntfy.sh unless --ntfy-server says
otherwise). Only the fixed generic words below are sent, never a landmark name, a route,
a position or anything the user said. Anyone who knows the topic can read and send to
it, so the topic is long and random: keep it to yourself, or run your own ntfy server.
"""
import secrets
import threading
import time
import urllib.request
from typing import Callable, Optional

DEFAULT_SERVER = "https://ntfy.sh"

# cue -> (title, message, priority). Generic words only: see "Privacy" above.
MESSAGES = {
    "confirm_prompt": ("Check", "Are you at a saved place? Double-tap for yes.", "high"),
    "arrived":        ("Arrived", "You have arrived.", "high"),
    "uncertain":      ("Not sure", "Not sure where you are. Say where you are.", "high"),
}

REPEAT_S = 3.0            # the same cue again within this many seconds is not sent


def new_topic() -> str:
    """A long random topic name that nobody can guess."""
    return "vexo-" + secrets.token_urlsafe(18)


def _post(url: str, body: bytes, headers: dict, timeout: float = 5.0) -> int:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


class NtfySender:
    """Call it with a haptic message (assist.haptics.haptic_message). Sends in the background,
    so a slow network never holds up guidance."""

    def __init__(self, topic: str, server: str = DEFAULT_SERVER,
                 post: Callable[[str, bytes, dict], int] = _post,
                 clock: Callable[[], float] = time.monotonic, background: bool = True):
        if not topic or len(topic) < 12 or "/" in topic:
            raise ValueError("Use a long random topic, e.g. from --ntfy new.")
        self.url = server.rstrip("/") + "/" + topic
        self.post = post
        self.clock = clock
        self.background = background
        self.sent = 0
        self._last = {}
        self._warned = False

    def __call__(self, msg: dict) -> bool:
        cue = msg.get("cue")
        if cue not in MESSAGES:
            return False
        now = self.clock()
        if now - self._last.get(cue, -1e9) < REPEAT_S:
            return False
        self._last[cue] = now
        title, text, priority = MESSAGES[cue]           # never msg["say"]: it can hold names
        headers = {"Title": title, "Priority": priority, "Tags": "vexo"}
        if self.background:
            threading.Thread(target=self._send, args=(text.encode(), headers), daemon=True).start()
        else:
            self._send(text.encode(), headers)
        return True

    def _send(self, body: bytes, headers: dict):
        try:
            self.post(self.url, body, headers)
            self.sent += 1
        except Exception as e:                          # offline, blocked: warn once, keep going
            if not self._warned:
                self._warned = True
                print("    [NTFY] could not send a notification (%s). Guidance goes on without it."
                      % type(e).__name__)


def fan_out(*senders: Optional[Callable[[dict], object]]) -> Callable[[dict], None]:
    """One send function that passes each message to every sender given."""
    live = [s for s in senders if s is not None]

    def send(msg):
        for s in live:
            s(msg)
    return send
