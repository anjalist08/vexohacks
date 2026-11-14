"""Accessibility add-ons: sound and vibration cues, phone compass, arrival prompts.

    from assist import attach
    helper = attach(app, send=hub.broadcast)        # one send function, or several:
    helper = attach(app, send=fan_out(hub.broadcast, LaptopSound(), webpush_sender))

attach() does not change app.py. It listens to the app's event stream (app.on_event) and
turns it into cues (assist/cues.py) for whatever the person carries:

    start a route           rising three-note chime
    begin travelling        soft double tick when the first steps arrive
    travelling              a quiet tick every TICK_STEPS steps: silence means no steps counted
    a turn coming up        pings from the side of the turn, faster and higher as it nears
    turn left / right       tones in the left / right ear only
    near the destination    rising pings in the last few steps
    arrive                  a resolved chord
    not sure where you are  a low rough buzz

It also watches the return trip for saved landmarks ("are you at the elevator?").
"""
import math

from assist.arrival import ArrivalWatcher
from assist.compass import CompassCorrector
from assist.cues import CUES, cue_for_instruction, cue_for_led, cue_message, pan_for_turn

TICK_STEPS = 5            # a walking tick every this many steps
NEAR_STEPS = 3            # destination pings in the last this many steps


def fan_out(*senders):
    """One send function that passes each message to every sender given."""
    live = [s for s in senders if s is not None]

    def send(msg):
        for s in live:
            s(msg)
    return send


class Assist:
    def __init__(self, app, send=None, ticks: bool = True):
        self.app = app
        self.send = send                    # fn(dict) delivering a cue message, or None
        self.ticks = ticks
        self.compass = CompassCorrector(app.tracker)
        self.arrival = ArrivalWatcher(app, self.notify)
        self._last_say = ""
        self._guidance = None               # the latest guidance event
        self._last_step = None              # (target, index) of the guidance step last cued
        self._near = None                   # steps left to the destination at the last ping
        self._base_steps = None             # steps when the current trip started
        self._last_tick = None
        self._travelling = False
        self._call_tool = app.call_tool
        app.call_tool = self._wrapped_call_tool
        app.on_event(self._on_event)

    # --- the app's events ---------------------------------------------------------------
    def _on_event(self, event: dict):
        handler = getattr(self, "_on_" + str(event.get("type")), None)
        if handler is not None:
            handler(event)

    def _on_say(self, event):
        self._last_say = event.get("text", "")

    def _on_reset(self, event):
        self.compass.reset()
        self.arrival.disarm()
        self._guidance, self._last_step = None, None
        self._new_trip()

    def _on_guidance(self, event):
        was_active = bool(self._guidance and self._guidance.get("active"))
        self._guidance = event
        if event.get("active") and not was_active:
            self._new_trip()
        steps, i = event.get("instructions") or [], event.get("current_index", 0)
        key = (event.get("target_name"), i)
        if event.get("active") and 0 <= i < len(steps) and key != self._last_step:
            self._last_step = key
            cue = cue_for_instruction(steps[i])
            if cue and cue != "arrived":        # arrival comes as its own LED event
                self._emit(cue, steps[i].get("text", ""))

    def _on_led(self, event):
        state = event.get("state")
        if state == "turn_now":
            self._approach_turn(event.get("period"))
            return
        cue = cue_for_led(state)
        if cue:
            self._emit(cue, self._last_say)

    def _on_point(self, event):
        steps = event.get("steps")
        if not isinstance(steps, int) or not self._moving_trip():
            return
        if self._base_steps is None or steps < self._base_steps:
            self._base_steps = self._last_tick = steps
            return
        if steps > self._base_steps and not self._travelling:
            self._travelling = True
            self._emit("travel_start")
            self._last_tick = steps
        elif self.ticks and steps - self._last_tick >= TICK_STEPS:
            self._last_tick = steps
            self._emit("step_tick")
        self._approach_destination(event)

    # --- distance cues ------------------------------------------------------------------
    def _approach_turn(self, period):
        """The guidance says a turn is 1-3 steps away (voice/led_states.turn_now_period)."""
        steps_left = 0 if not period else max(0, round((period - 150) / 65.0))
        turn = None
        if self._guidance:
            nxt = self._guidance.get("current_index", 0) + 1
            items = self._guidance.get("instructions") or []
            if nxt < len(items):
                turn = items[nxt].get("turn")
        if steps_left > 0:
            self._emit("approach", pan=pan_for_turn(turn), pitch=1.0 + 0.15 * (NEAR_STEPS - min(steps_left, NEAR_STEPS)))

    def _approach_destination(self, point):
        g = self._guidance
        if not g or not g.get("active") or not g.get("waypoints"):
            self._near = None
            return
        x, y = g["waypoints"][-1]
        steps_left = int(math.ceil(math.hypot(point["x_m"] - x, point["y_m"] - y) / self.app.tracker.step_length_m))
        if 1 <= steps_left <= NEAR_STEPS and (self._near is None or steps_left < self._near):
            self._near = steps_left
            self._emit("approach", pitch=1.2 + 0.2 * (NEAR_STEPS - steps_left))

    def _moving_trip(self) -> bool:
        route = self.app.store.current
        navigator = getattr(self.app, "navigator", None)
        return bool((navigator is not None and navigator.active) or (route is not None and route.active))

    def _new_trip(self):
        self._base_steps = self._last_tick = None
        self._travelling = False
        self._near = None

    # --- tools -------------------------------------------------------------------------
    def _wrapped_call_tool(self, name, args=None):
        result = self._call_tool(name, args)
        if result.ok and name == "navigate_to":
            self.arrival.arm((args or {}).get("target", "start"))
        elif result.ok and name == "reanchor":
            self.arrival.reached((args or {}).get("landmark_id"))
        return result

    # --- phone input -------------------------------------------------------------------
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

    # --- output ------------------------------------------------------------------------
    def notify(self, say: str, cue: str):
        """A line from the helpers themselves (an arrival prompt): speak it and cue it."""
        if self.app.mode != "light-only":
            self.app.speak(say)
        self._emit(cue, say)

    def _emit(self, cue: str, say: str = "", pan=None, pitch: float = 1.0):
        if cue in CUES and self.send is not None and self.app.mode != "light-only":
            self.send(cue_message(cue, say, pan, pitch))


def attach(app, send=None, ticks: bool = True) -> Assist:
    return Assist(app, send, ticks)


__all__ = ["Assist", "attach", "fan_out", "ArrivalWatcher", "CompassCorrector", "CUES", "cue_message"]
