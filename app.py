"""The tools, in one place. Gemini's tool calls, the typed fallback and the demo
script all run through SpatialMemoryApp.call_tool, so they behave the same.

Gemini picks a tool and its arguments. Code validates them, runs them against the
stored route, and returns a ToolResult: what to say, and which LED state to show.
"""
import re
import time
from typing import Callable, List, Optional

import config
from interfaces import OUTPUT_MODES, TOOLS, Instruction, Landmark, PoseSample, ToolResult
from store.band_mirror import BandLandmarkMirror
from store.guidance import GuidanceSession
from store.route_store import RouteStore
from tracker.pdr import PathTracker

TOOL_NAMES = {t["name"]: t for t in TOOLS}


class SpatialMemoryApp:
    def __init__(
        self,
        tracker: PathTracker,
        store: RouteStore,
        speak: Callable[[str], None] = print,
        led=None,
        clock: Callable[[], float] = time.time,
        band_mirror: Optional[BandLandmarkMirror] = None,
    ):
        self.tracker = tracker
        self.store = store
        self.speak = speak
        self.led = led                    # voice.led_states.LedController, or None
        self.clock = clock
        self.mode = config.OUTPUT_MODE
        self.guidance: List[Instruction] = []   # Instructions of the current return trip
        self.navigator: Optional[GuidanceSession] = None
        self.band_mirror = band_mirror
        self.led_state = "idle"
        self._event_listeners: List[Callable[[dict], None]] = []
        tracker.on_sample(self.on_pose)

    # --- event bus for live UI / WebSocket ---------------------------------------
    def on_event(self, fn: Callable[[dict], None]) -> None:
        """Subscribe to app events ('point', 'landmark', 'guidance', 'led', 'say', 'reset')."""
        if fn not in self._event_listeners:
            self._event_listeners.append(fn)

    def remove_event_listener(self, fn: Callable[[dict], None]) -> None:
        if fn in self._event_listeners:
            self._event_listeners.remove(fn)

    def _emit(self, event: dict) -> None:
        for fn in list(self._event_listeners):
            fn(event)

    def _say_text(self, text: str) -> None:
        if self.mode != "light-only" and text:
            self.speak(text)
            self._emit({"type": "say", "text": text})

    def _show_led(self, state: str, period: Optional[int] = None) -> None:
        self.led_state = state
        if self.mode != "voice-only":
            if self.led is not None:
                if period is not None:
                    try:
                        self.led.show(state, period=period)
                    except TypeError:
                        self.led.show(state)
                else:
                    self.led.show(state)
            payload = {"type": "led", "state": state}
            if period is not None:
                payload["period"] = period
            self._emit(payload)

    def _cancel_guidance(self, emit_event: bool = True) -> None:
        was_active = self.navigator is not None and self.navigator.active
        if self.navigator is not None:
            self.navigator.cancel()
        if was_active and emit_event and self.navigator is not None:
            self._emit({"type": "guidance", **self.navigator.to_dict()})

    def _landmark_payload(self, lm: Landmark) -> dict:
        payload = lm.to_dict()
        try:
            route = self.store.route_of(lm)
            if 0 <= lm.point_index < len(route.points):
                pt = route.points[lm.point_index]
                payload["x_m"] = pt.x_m
                payload["y_m"] = pt.y_m
        except KeyError:
            pass
        return payload

    # --- live pose handling & step-by-step guidance ------------------------------
    def on_pose(self, sample: PoseSample) -> None:
        """Handle each PoseSample emitted by the tracker."""
        navigating_active = self.navigator is not None and self.navigator.active
        if not navigating_active:
            self.store.add_point(sample)
        self._emit({"type": "point", **sample.to_dict()})

        if navigating_active and self.navigator is not None:
            upd = self.navigator.update(sample)
            if upd.say:
                self._say_text(upd.say)
            if upd.led:
                self._show_led(upd.led, period=upd.led_period)
            if upd.advanced or upd.arrived:
                self._emit({"type": "guidance", **self.navigator.to_dict()})

    # --- dispatch ----------------------------------------------------------------
    def call_tool(self, name: str, args: Optional[dict] = None) -> ToolResult:
        """Validate a tool call (from Gemini or the fallback), run it, and output it."""
        args = dict(args or {})
        spec = TOOL_NAMES.get(name)
        if spec is None:
            return self.output(ToolResult(False, "Sorry, I can't do that.", "uncertain"))
        params = spec["parameters"]
        unknown = [k for k in args if k not in params]
        missing = [k for k, p in params.items() if p.get("required") and not args.get(k)]
        if unknown or missing:
            return self.output(ToolResult(False, "Sorry, I didn't catch that.", "uncertain",
                                          {"unknown": unknown, "missing": missing}))
        return self.output(getattr(self, name)(**args))

    def output(self, result: ToolResult) -> ToolResult:
        if result.say:
            self._say_text(result.say)
        if result.led:
            self._show_led(result.led)
        return result

    # --- tools ---------------------------------------------------------------------
    def start_route(self, title: str = None) -> ToolResult:
        self._cancel_guidance(emit_event=False)
        self.guidance = []
        self.navigator = None
        first = self.tracker.start(self.clock())
        route = self.store.start_route(title, first)
        self._emit({"type": "reset", "route": route.id, "title": route.title})
        self._emit({"type": "point", **first.to_dict()})
        self._emit({"type": "guidance", "instructions": [], "current_index": 0, "active": False, "waypoints": []})
        return ToolResult(True, "Route started. Stand still for a moment.", "route_started", {"route": route.id})

    def stop_route(self) -> ToolResult:
        self._cancel_guidance()
        self.tracker.stop()
        self.store.stop_route()
        return ToolResult(True, "Route saved.", "idle")

    def remember_landmark(self, label: str, floor: str = None, note: str = None) -> ToolResult:
        if self.store.current is None:
            return ToolResult(False, "Start a route first.", "uncertain")
        lm = self.store.remember_landmark(label, floor, note)
        if self.band_mirror is not None:
            self.band_mirror.mirror(lm)
        self._emit({"type": "landmark", **self._landmark_payload(lm)})
        return ToolResult(True, "Saved: %s." % lm.label, "landmark_saved", {"landmark": lm.to_dict()})

    def save_note(self, text: str, landmark_id: str = None) -> ToolResult:
        if landmark_id and self.store.get_landmark(landmark_id) is None:
            return ToolResult(False, "I don't know that place. Which one did you mean?", "uncertain")
        if self.store.current is None and not landmark_id:
            return ToolResult(False, "Start a route first.", "uncertain")
        updated_lm = self.store.save_note(text, landmark_id)
        if updated_lm is not None:
            if self.band_mirror is not None:
                self.band_mirror.mirror(updated_lm)
            self._emit({"type": "landmark", **self._landmark_payload(updated_lm)})
        return ToolResult(True, "Note saved.", None)

    def find_landmark(self, query: str) -> ToolResult:
        found = self.store.find_landmark(query)
        if not found:
            return ToolResult(False, "I don't have a saved place like that.", None)
        best = [lm for lm, s in found if s == found[0][1]]
        if len(best) > 1:
            names = " or ".join(lm.label for lm in best)
            return ToolResult(True, "Did you mean %s?" % names, None, {"matches": [lm.to_dict() for lm in best]})
        lm = found[0][0]
        route = self.store.route_of(lm)
        extra = (" Note: %s." % lm.note) if lm.note else ""
        floor = (" on floor %s" % lm.floor) if lm.floor else ""
        if route is self.store.current:
            steps = int(round(self.store.distance_back(lm.point_index) / self.tracker.step_length_m))
            text = "The %s%s is about %d steps back along your route.%s" % (lm.label, floor, steps, extra)
        else:
            text = "The %s%s is on an earlier route, %s.%s" % (lm.label, floor, route.title, extra)
        return ToolResult(True, text, None, {"landmark": lm.to_dict()})

    def navigate_to(self, target: str) -> ToolResult:
        route = self.store.current
        if route is None or len(route.points) < 2:
            return ToolResult(False, "There is no recorded route to follow yet.", "uncertain")
        if target.lower() in ("start", "the start", "beginning", "entrance") and self.store.get_landmark(target) is None:
            index, name = 0, "start"
        else:
            lm = self.store.get_landmark(target)
            if lm is None:
                return ToolResult(False, "I don't know that place. Which one did you mean?", "uncertain")
            if self.store.route_of(lm) is not route:
                return ToolResult(False, "The %s is on an earlier route, so I can't guide you there." % lm.label,
                                  "uncertain")
            index, name = lm.point_index, lm.label
        self._cancel_guidance(emit_event=False)
        self.navigator = self.store.plan_return_session(
            index,
            name,
            self.tracker.pose.heading_deg,
            self.tracker.step_length_m,
            from_pose=self.tracker.pose,
        )
        self.guidance = self.navigator.instructions
        self._emit({"type": "guidance", **self.navigator.to_dict()})
        steps = [i.text for i in self.guidance]
        say = steps[0] if len(steps) == 1 else " Then ".join([steps[0]] + [s[0].lower() + s[1:] for s in steps[1:]])
        return ToolResult(True, say, "navigating", {"instructions": [i.to_dict() for i in self.guidance]})

    def reanchor(self, landmark_id: str) -> ToolResult:
        lm = self.store.get_landmark(landmark_id)
        if lm is None or self.store.route_of(lm) is not self.store.current:
            return ToolResult(False, "I don't know that place on this route.", "uncertain")
        self._cancel_guidance()
        p = self.store.current.points[lm.point_index]
        self.tracker.reanchor(p.x_m, p.y_m, p.heading_deg, self.clock())
        return ToolResult(True, "Got it, you're at the %s." % lm.label, "recording")

    def ask_user(self, question: str) -> ToolResult:
        return ToolResult(True, question, None)

    def set_mode(self, mode: str) -> ToolResult:
        if mode not in OUTPUT_MODES:
            return ToolResult(False, "Modes are both, light only or voice only.", None)
        self.mode = mode
        if self.led is not None:
            self.led.brightness = 0.3 if mode == "light-only" else 1.0
        return ToolResult(True, "Output mode: %s." % mode.replace("-", " "), None)

    def delete_all(self) -> None:
        """Forget every route and landmark, cancel active guidance, and notify UI."""
        self._cancel_guidance(emit_event=False)
        self.guidance = []
        self.navigator = None
        self.tracker.stop()
        self.store.delete_all()
        if self.band_mirror is not None:
            self.band_mirror.clear()
        self._show_led("idle")
        self._emit({"type": "reset"})

    # --- typed fallback ------------------------------------------------------------
    def keyword_command(self, text: str) -> ToolResult:
        """Rule-based stand-in for Gemini, for the typed box and when the APIs fail."""
        name, args = parse_keywords(text, self.store)
        return self.call_tool(name, args)

    def landmark_summary(self) -> str:
        """Short text for the model's prompt: the ids and names it may use."""
        return "; ".join("%s=%s%s" % (l.id, l.label, " (floor %s)" % l.floor if l.floor else "")
                         for l in self.store.all_landmarks()) or "none"


def parse_keywords(text: str, store: RouteStore):
    t = text.strip().lower().rstrip(".!?")

    def target_of(phrase):
        if re.search(r"\b(start|beginning)\b", phrase):
            return "start"
        found = store.find_landmark(phrase)
        return found[0][0].id if found else phrase.strip() or "start"

    if re.match(r"^(stop|end|finish)( the)? route", t):
        return "stop_route", {}
    if re.match(r"^(start|begin|new)( a| the)? route", t):
        m = re.search(r"route[, ]+(?:called |named )?(.*)", t)
        return "start_route", {"title": m.group(1).strip()} if m and m.group(1).strip() else {}
    m = re.match(r"^(?:set )?(?:mode|output)[: ]+(both|light[- ]only|voice[- ]only)", t)
    if m:
        return "set_mode", {"mode": m.group(1).replace(" ", "-")}
    m = re.match(r"^(?:take me|bring me|guide me|navigate|go)(?: back)?(?: to)?\s*(.*)$", t)
    if m:
        return "navigate_to", {"target": target_of(m.group(1))}
    m = re.match(r"^(?:i'm|i am|we're|we are) (?:at|by|next to) (.*)$", t)
    if m:
        found = store.find_landmark(m.group(1))
        return "reanchor", {"landmark_id": found[0][0].id if found else m.group(1)}
    m = re.match(r"^(?:where(?:'s| is| was| did)?|find)\s+(.*)$", t)
    if m:
        return "find_landmark", {"query": m.group(1)}
    m = re.match(r"^note[: ]+(.*)$", t)
    if m:
        return "save_note", {"text": m.group(1)}
    m = re.match(r"^(?:remember|save|mark)(?: this)?(?: place)?(?: as| is)?\s+(.*)$", t) or \
        re.match(r"^this is\s+(.*)$", t)
    if m:
        label, _, note = m.group(1).partition(" near ")
        label = re.sub(r"^(the|a|an)\s+", "", label.strip())
        args = {"label": label}
        if note:
            args["note"] = "near " + note
        return "remember_landmark", args
    return "ask_user", {"question": "Sorry, I didn't understand. Try 'remember this as the elevator' "
                                    "or 'take me back to the start'."}
