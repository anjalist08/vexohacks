"""LED vocabulary (BUILD plan, "Feedback vocabulary", with the plan amendments).

The band cannot vibrate, so each state is a colour and pattern plus a spoken line.
Blue is never used: the band forces solid blue while the microphone is on, and
set_led fails with "denied" then. Listen, switch the mic off, then set the LED.
"""
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass
class LedCue:
    color: Optional[str]          # "#rrggbb", or None for off
    pattern: str = "solid"        # solid, blink, breathe, flash, rainbow, off
    period: int = 1000            # ms per cycle, 100..10000
    hold_s: float = 0.0           # show this long, then switch to `then`
    then: Optional[str] = None


STATES = {
    "idle":           LedCue(None, "off"),
    "route_started":  LedCue("#00ff00", "blink", 400, hold_s=1.5, then="recording"),
    "recording":      LedCue("#ffb000", "breathe", 2000),                     # amber
    "landmark_saved": LedCue("#a020f0", "solid", 1000, hold_s=1.5, then="recording"),
    "navigating":     LedCue("#ffffff", "breathe", 2000),                     # white, unlike recording
    "turn_now":       LedCue("#ffffff", "blink", 500),
    "arrived":        LedCue("#00ff00", "solid", 1000, hold_s=1.5, then="arrived_party"),
    "arrived_party":  LedCue(None, "rainbow", 2000),
    "uncertain":      LedCue("#ff0000", "blink", 500),
}


def turn_now_period(steps_left: int) -> int:
    """Blink faster as the turn gets closer: 800 ms far away, 150 ms at the corner."""
    return int(max(150, min(800, 150 + steps_left * 65)))


class LedController:
    """Shows LED states on a band (or anything with set_led / led_off)."""

    def __init__(self, band=None, brightness: float = 1.0):
        self.band = band
        self.brightness = brightness
        self.state = "idle"
        self.period_override: Optional[int] = None
        self._timer: Optional[threading.Timer] = None

    def show(self, state: str, period: int = None) -> bool:
        """Switch to a state. Returns False if the band refused (e.g. mic on) or is absent."""
        if state not in STATES:
            raise KeyError(state)
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self.state = state
        self.period_override = period
        ok = self._apply()
        cue = STATES[state]
        if cue.hold_s and cue.then:
            self._timer = threading.Timer(cue.hold_s, self.show, args=(cue.then,))
            self._timer.daemon = True
            self._timer.start()
        return ok

    def reapply(self) -> bool:
        """Call after a reconnect: the band resets its LED when the link drops."""
        return self._apply()

    def _apply(self) -> bool:
        if self.band is None:
            return False
        cue = STATES[self.state]
        try:
            if cue.pattern == "off":
                self.band.led_off()
            else:
                self.band.set_led(cue.color or "#ffffff", brightness=self.brightness, pattern=cue.pattern,
                                  period=self.period_override or cue.period)
            return True
        except Exception as e:      # VexoError "denied" while the mic is on, or a dropped link
            if getattr(e, "code", None) in ("denied", "not-connected"):
                return False
            raise
