"""Accessibility add-ons: phone vibration, phone compass and arrival prompts.

    from assist import attach
    helper = attach(app, send=hub.broadcast)   # hub: assist.phone_server.PhoneHub, or None

attach() does not change app.py. It listens to the app's event stream (app.on_event) and
turns guidance and LED events into vibration patterns for the phone, and it watches the
return trip for saved landmarks.
"""
from assist.arrival import ArrivalWatcher
from assist.compass import CompassCorrector
from assist.haptics import (HAPTIC_PATTERNS, cue_for_instruction, cue_for_led, cue_for_result,
                            haptic_message)


class Assist:
    def __init__(self, app, send=None):
        self.app = app
        self.send = send                    # fn(dict) that delivers a message to the phone, or None
        self.compass = CompassCorrector(app.tracker)
        self.arrival = ArrivalWatcher(app, self.notify)
        self._last_step = None              # (target, index) of the guidance step last buzzed
        self._last_say = ""
        self._call_tool = app.call_tool
        app.call_tool = self._wrapped_call_tool
        app.on_event(self._on_event)

    # --- hooks ---------------------------------------------------------------------
    def _on_event(self, event: dict):
        kind = event.get("type")
        if kind == "say":
            self._last_say = event.get("text", "")
        elif kind == "reset":
            self.compass.reset()
            self.arrival.disarm()
            self._last_step = None
        elif kind == "guidance":
            steps, i = event.get("instructions") or [], event.get("current_index", 0)
            key = (event.get("target_name"), i)
            if event.get("active") and 0 <= i < len(steps) and key != self._last_step:
                self._last_step = key
                cue = cue_for_instruction(steps[i])
                if cue and cue != "arrived":        # arrival comes as its own LED event
                    self._send(haptic_message(cue, steps[i].get("text", "")))
        elif kind == "led":
            cue = cue_for_led(event.get("state"))
            if cue:
                self._send(haptic_message(cue, self._last_say))

    def _wrapped_call_tool(self, name, args=None):
        result = self._call_tool(name, args)
        if result.ok and name == "navigate_to":
            self.arrival.arm((args or {}).get("target", "start"))
        elif result.ok and name == "reanchor":
            self.arrival.reached((args or {}).get("landmark_id"))
        return result

    # --- phone input ---------------------------------------------------------------
    def on_phone_message(self, msg: dict):
        """Messages from assist/phone.html: compass readings and the Yes button."""
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
           "cue_for_instruction", "cue_for_led", "cue_for_result", "haptic_message"]
