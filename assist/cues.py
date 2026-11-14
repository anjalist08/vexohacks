"""The guidance cues: one vocabulary for sound, vibration and notifications.

The band has no speaker and no vibration motor. Every cue is therefore given to the
person through whatever they carry: a short sound in their headphones (AirPods,
bone-conduction or any Bluetooth headphones, paired with the phone or the laptop), a
vibration on an Android phone, and the spoken line. Each cue is defined once here; the
phone page (assist/phone.html) and the laptop (assist/earcons.py) play the same sounds.

A sound is a list of notes: frequency (Hz), start time and length (ms), wave and
loudness (0..1), plus a stereo position: -1 is the left ear only, +1 the right ear.
Turns and the pings before a turn come from the side of the turn.

Design rules: every sound is short (under a second) and quiet, so it never hides
traffic or a screen reader; no two cues share a rhythm; rising means "start" or "is
this right?", a resolved chord means "arrived", a low rough buzz means "not sure".
"""
from typing import Optional

C4, E4, G4, C5, E5, G5, A5, C6 = 262, 330, 392, 523, 659, 784, 880, 1047


def _n(f, at, ms, wave="sine", gain=0.35):
    return {"f": f, "at": at, "ms": ms, "wave": wave, "gain": gain}


CUES = {
    # cue:            (vibration ms on/off,               notes,                                      pan)
    "route_started":  ([100, 100, 300],                   [_n(G4, 0, 120), _n(C5, 140, 120), _n(E5, 280, 220)], 0.0),
    "travel_start":   ([60],                              [_n(1200, 0, 30, "triangle", 0.2), _n(1200, 90, 30, "triangle", 0.2)], 0.0),
    "step_tick":      ([],                                [_n(900, 0, 25, "triangle", 0.12)], 0.0),
    "straight":       ([80],                              [_n(G5, 0, 90)], 0.0),
    "turn_left":      ([150, 120, 150],                   [_n(600, 0, 110), _n(600, 170, 110)], -1.0),
    "turn_right":     ([150, 120, 150, 120, 150],         [_n(600, 0, 110), _n(600, 170, 110), _n(600, 340, 110)], 1.0),
    "turn_around":    ([700],                             [_n(440, 0, 200), _n(330, 220, 320)], 0.0),
    "approach":       ([40],                              [_n(1000, 0, 60, "sine", 0.25)], 0.0),
    "landmark_saved": ([300],                             [_n(A5, 0, 160)], 0.0),
    "confirm_prompt": ([300, 250, 300],                   [_n(E5, 0, 130), _n(A5, 170, 200)], 0.0),
    "arrived":        ([700, 200, 150, 120, 150],         [_n(C5, 0, 500, gain=0.25), _n(E5, 120, 380, gain=0.25),
                                                           _n(G5, 240, 260, gain=0.25), _n(C6, 360, 420, gain=0.3)], 0.0),
    "uncertain":      ([90, 70, 90, 70, 90, 70, 90],      [_n(110, 0, 220, "square", 0.12), _n(110, 300, 220, "square", 0.12)], 0.0),
}

# Cues that are heard but never shown or announced: they would flood a screen reader.
QUIET_CUES = {"step_tick", "approach", "travel_start"}

_TURN_CUES = {"straight": "straight", "left": "turn_left", "right": "turn_right",
              "around": "turn_around", "arrive": "arrived"}

# LED states (voice/led_states.py) that have a cue of their own. "turn_now" is the
# approach to a turn and is handled with its distance, see assist.Assist.
_LED_CUES = {"route_started": "route_started", "landmark_saved": "landmark_saved",
             "arrived": "arrived", "uncertain": "uncertain"}


def cue_for_instruction(instruction) -> Optional[str]:
    """The cue for one interfaces.Instruction (or its dict)."""
    turn = instruction["turn"] if isinstance(instruction, dict) else instruction.turn
    return _TURN_CUES.get(turn)


def cue_for_led(state: Optional[str]) -> Optional[str]:
    return _LED_CUES.get(state)


def pan_for_turn(turn: Optional[str]) -> float:
    return {"left": -1.0, "right": 1.0}.get(turn or "", 0.0)


def cue_message(cue: str, say: str = "", pan: Optional[float] = None, pitch: float = 1.0) -> dict:
    """The message the phone page and the laptop player understand.

    pan overrides the cue's own stereo position (approach pings take the side of the
    coming turn); pitch scales every frequency (pings rise as a turn gets closer)."""
    pattern, notes, own_pan = CUES[cue]
    notes = [dict(n, f=round(n["f"] * pitch)) for n in notes] if pitch != 1.0 else [dict(n) for n in notes]
    return {"type": "cue", "cue": cue, "pattern": list(pattern), "say": say or "",
            "quiet": cue in QUIET_CUES,
            "sound": {"notes": notes, "pan": own_pan if pan is None else max(-1.0, min(1.0, pan))}}
