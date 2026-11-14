"""Accessibility add-ons: phone vibration, phone compass and arrival prompts.

    from assist import attach
    helper = attach(app, send=hub.broadcast)   # hub: assist.phone_server.PhoneHub, or None

attach() does not change app.py. It wraps the app's output so every result also goes to
the phone as a vibration pattern, and it watches the return trip for saved landmarks.
"""
from assist.arrival import ArrivalWatcher
from assist.compass import CompassCorrector
from assist.haptics import HAPTIC_PATTERNS, cue_for_instruction, cue_for_result, haptic_message


class Assist:
    def __init__(self, app, send=None):
        self.app = app
        self.send = send                    # fn(dict) that delivers a message to the phone, or None
        self.compass = CompassCorrector(app.tracker)
        self.arrival = ArrivalWatcher(app, self.notify)
        self._output = app.output
        self._call_tool = app.call_tool
        app.output = self._wrapped_output
        app.call_tool = self._wrapped_call_tool

    # --- hooks ---------------------------------------------------------------------
    def _wrapped_output(self, result):
        result = self._output(result)
        cue = cue_for_result(result)
        if cue:
            self._send(haptic_message(cue, result.say))
        return result

    def _wrapped_call_tool(self, name, args=None):
        result = self._call_tool(name, args)
        if result.ok and name == "start_route":
            self.compass.reset()
            self.arrival.disarm()
        elif result.ok and name == "navigate_to":
            self.arrival.arm((args or {}).get("target", "start"))
        elif result.ok and name == "reanchor":
            self.arrival.reached((args or {}).get("landmark_id"))
        return result

    # --- phone input ---------------------------------------------------------------
    def on_phone_message(self, msg: dict):
        """Messages from assist/phone.html: compass readings and the confirm button."""
        kind = msg.get("type")
        if kind == "compass":
            try:
                t, heading = float(msg["t"]) / 1000.0, float(msg["heading"])
            except (KeyError, TypeError, ValueError):
                return
            self.compass.on_compass(t, heading)
        elif kind == "confirm":
            self.arrival.confirm()

    def confirm(self):
        """Call this on a double-tap of the band: 'yes, I am at that landmark'."""
        return self.arrival.confirm()

    # --- output --------------------------------------------------------------------
    def notify(self, say: str, cue: str):
        """A line from the helpers themselves (an arrival prompt): speak it and buzz it."""
        if self.app.mode != "light-only":
            self.app.speak(say)
        self._send(haptic_message(cue, say))

    def _send(self, msg):
        if self.send is not None and self.app.mode != "light-only":
            self.send(msg)


def attach(app, send=None) -> Assist:
    return Assist(app, send)


__all__ = ["Assist", "attach", "ArrivalWatcher", "CompassCorrector", "HAPTIC_PATTERNS",
           "cue_for_instruction", "cue_for_result", "haptic_message"]
