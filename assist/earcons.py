"""Play the cue sounds on the laptop, for headphones paired with the laptop.

    python3 -m assist.earcons            plays every cue once, with its name
    python3 -m assist.earcons --save DIR writes each cue as a WAV file

The sounds are made here from the note lists in assist/cues.py (stdlib only, no audio
files in the repository), as 16-bit stereo WAV, and played with the system's own player:
afplay on macOS, paplay or aplay on Linux, winsound on Windows. With no player found it
says so once and carries on: the phone and the spoken line still carry every cue.
"""
import argparse
import io
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave

RATE = 22050


def _wave(kind: str, phase: float) -> float:
    x = phase % 1.0
    if kind == "square":
        return 1.0 if x < 0.5 else -1.0
    if kind == "triangle":
        return 4.0 * abs(x - 0.5) - 1.0
    return math.sin(2.0 * math.pi * x)


def render(sound: dict, rate: int = RATE, volume: float = 1.0) -> bytes:
    """A WAV file (bytes) for one sound: {"notes": [...], "pan": -1..1}."""
    notes = sound["notes"]
    total = max(n["at"] + n["ms"] for n in notes) + 30
    frames = int(rate * total / 1000.0)
    mix = [0.0] * frames
    for n in notes:
        start, length = int(rate * n["at"] / 1000.0), int(rate * n["ms"] / 1000.0)
        attack, release = max(1, int(rate * 0.005)), max(1, int(rate * min(0.06, n["ms"] / 3000.0)))
        for i in range(length):
            env = min(1.0, i / attack, (length - i) / release)
            mix[start + i] += n["gain"] * env * _wave(n.get("wave", "sine"), n["f"] * i / rate)
    pan = max(-1.0, min(1.0, sound.get("pan", 0.0)))
    left, right = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)   # equal power
    out = bytearray()
    for v in mix:
        v = max(-1.0, min(1.0, v * volume))
        out += struct.pack("<hh", int(v * left * 32767), int(v * right * 32767))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(out))
    return buf.getvalue()


def _player():
    if sys.platform == "darwin" and shutil.which("afplay"):
        return lambda path: subprocess.run(["afplay", path], check=False)
    if sys.platform.startswith("win"):
        import winsound
        return lambda path: winsound.PlaySound(path, winsound.SND_FILENAME)
    for cmd in (["paplay"], ["aplay", "-q"]):
        if shutil.which(cmd[0]):
            return lambda path, cmd=cmd: subprocess.run(cmd + [path], check=False,
                                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None


class LaptopSound:
    """Call it with a cue message (assist.cues.cue_message). Plays in the background, one
    sound at a time; a newer cue replaces any that are still waiting."""

    def __init__(self, ticks: bool = True, volume: float = 1.0, play=None):
        self.ticks = ticks
        self.volume = volume
        self._play = play if play is not None else _player()
        self._dir = tempfile.mkdtemp(prefix="vexo-cues-")
        self._files = {}
        self._pending = None
        self._wake = threading.Condition()
        self.played = []
        if self._play is None:
            print("    [SOUND] no audio player found on this computer: cues are spoken and sent to the phone only.")
        else:
            threading.Thread(target=self._loop, daemon=True).start()

    def __call__(self, msg: dict) -> bool:
        if self._play is None or msg.get("type") != "cue" or not msg.get("sound"):
            return False
        if msg["cue"] == "step_tick" and not self.ticks:
            return False
        with self._wake:
            # Ticks never push out a real cue that is still waiting.
            if not (msg["cue"] == "step_tick" and self._pending and self._pending["cue"] != "step_tick"):
                self._pending = msg
            self._wake.notify()
        return True

    def _file(self, msg) -> str:
        key = repr((msg["sound"]["notes"], msg["sound"]["pan"]))
        if key not in self._files:
            path = os.path.join(self._dir, "cue%d.wav" % len(self._files))
            with open(path, "wb") as f:
                f.write(render(msg["sound"], volume=self.volume))
            self._files[key] = path
        return self._files[key]

    def _loop(self):
        while True:
            with self._wake:
                while self._pending is None:
                    self._wake.wait()
                msg, self._pending = self._pending, None
            try:
                self._play(self._file(msg))
                self.played.append(msg["cue"])
            except Exception as e:                     # a broken player must not stop guidance
                print("    [SOUND] could not play a cue (%s)." % type(e).__name__)
                time.sleep(1.0)


def main(argv=None):
    from assist.cues import CUES, cue_message
    p = argparse.ArgumentParser(description="Play or save the guidance cue sounds.")
    p.add_argument("--save", metavar="DIR", help="write each cue as a WAV file instead of playing it")
    a = p.parse_args(argv)
    for cue in CUES:
        msg = cue_message(cue)
        if a.save:
            os.makedirs(a.save, exist_ok=True)
            with open(os.path.join(a.save, cue + ".wav"), "wb") as f:
                f.write(render(msg["sound"]))
            continue
        player = _player()
        if player is None:
            print("No audio player found (afplay, paplay, aplay or winsound). Try --save DIR.")
            return 1
        print("    %s" % cue.replace("_", " "))
        path = os.path.join(tempfile.gettempdir(), "vexo-cue.wav")
        with open(path, "wb") as f:
            f.write(render(msg["sound"]))
        player(path)
        time.sleep(0.6)
    if a.save:
        print("Saved %d cue sounds in %s" % (len(CUES), a.save))
    return 0


if __name__ == "__main__":
    sys.exit(main())
