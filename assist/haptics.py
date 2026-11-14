"""Vibration patterns for the phone, one per guidance cue.

The band has no vibration motor, so the buzz comes from the phone the person carries
(assist/phone.html, which calls navigator.vibrate). Each pattern is a list of
milliseconds: buzz, pause, buzz, ... Left and right differ by the number of pulses, so
they can be told apart without looking. Every cue is also spoken and shown on the page.
"""
from typing import Optional

HAPTIC_PATTERNS = {
    "straight":       [80],                               # one tick: keep going
    "turn_left":      [150, 120, 150],                    # two pulses
    "turn_right":     [150, 120, 150, 120, 150],          # three pulses
    "turn_around":    [700],                              # one long buzz
    "arrived":        [700, 200, 150, 120, 150],          # long, then two short
    "uncertain":      [90, 70, 90, 70, 90, 70, 90],       # four fast: not sure where you are
    "route_started":  [100, 100, 300],
    "landmark_saved": [300],
    "confirm_prompt": [300, 250, 300],                    # "are you at the ...?"
}

_TURN_CUES = {"straight": "straight", "left": "turn_left", "right": "turn_right",
              "around": "turn_around", "arrive": "arrived"}

# LED states (voice/led_states.py) that have a vibration of their own.
_LED_CUES = {"route_started": "route_started", "landmark_saved": "landmark_saved",
             "arrived": "arrived", "uncertain": "uncertain"}


def cue_for_instruction(instruction) -> Optional[str]:
    """The cue for one interfaces.Instruction (or its dict)."""
    turn = instruction["turn"] if isinstance(instruction, dict) else instruction.turn
    return _TURN_CUES.get(turn)


def cue_for_led(state: Optional[str]) -> Optional[str]:
    """The cue for an LED state, if it has one."""
    return _LED_CUES.get(state)


def cue_for_result(result) -> Optional[str]:
    """The cue for a ToolResult: the first turn of new guidance, else its LED state."""
    steps = (result.data or {}).get("instructions")
    if steps:
        return cue_for_instruction(steps[0])
    return cue_for_led(result.led)


def haptic_message(cue: str, say: str = "") -> dict:
    """The JSON message assist/phone.html understands."""
    return {"type": "haptic", "cue": cue, "pattern": HAPTIC_PATTERNS[cue], "say": say or ""}
