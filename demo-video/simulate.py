"""Record a timeline for the 60-second working-demo video by running the REAL Wayback code
on a SYNTHETIC walk (tracker/events.synthetic_walk). Not live sensing: the video says so.

    python3 demo-video/simulate.py        # writes demo-video/timeline.json

What runs for real: SpatialMemoryApp (app.py), the wrist tracker (tracker/wrist.py), the route
store and the return plan (store/), and keyword_command (the same tools Gemini picks from).
While guiding, the iPhone-only app's newest rules (branch clean-app, ios/.../PhoneBrain.swift)
are ported below: one direction spoken at a time ("In 4 steps, turn left", "Turn left now, then
walk 13 steps"), arrival two steps early, and one buzz rule: a steady pulse while facing the way
to walk, silence while not. Every position, step count, spoken line, LED state and
buzz cue in the video comes from this run. The walk itself is made up: an L-shaped hallway,
12 steps, a right turn, 9 steps; then back.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app import SpatialMemoryApp, parse_keywords  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import synthetic_walk  # noqa: E402
from tracker.wrist import make_tracker     # noqa: E402
import config                             # noqa: E402

SAMPLE_S = 0.1     # how often the screen state is sampled
COACH_S = 0.2      # the coach runs 5 times a second, as in web/ws_server.py


class PhoneNav:
    """Port of Navigation in ios/Wayback/Wayback/Standalone/PhoneBrain.swift (branch clean-app)."""

    def __init__(self, corners, steps, target, step_length):
        self.corners, self.steps, self.target, self.L = corners, steps, target, step_length
        self.cum = [0.0]
        for a, b in zip(corners, corners[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.headings = [math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) for a, b in zip(corners, corners[1:])]
        self.total = self.cum[-1]
        self.segment, self.progress, self.offset = 0, 0.0, 0.0
        self.active = True
        self.turned, self.warned = set(), set()

    def locate(self, x, y):
        best = None
        for j in range(max(0, self.segment - 1), len(self.headings)):
            a, b = self.corners[j], self.corners[j + 1]
            dx, dy = b[0] - a[0], b[1] - a[1]
            l2 = dx * dx + dy * dy
            t = 0 if l2 == 0 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / l2))
            d = math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy))
            if best is None or d < best[2] - 1e-9:
                best = (j, t, d)
        j, t, d = best
        self.segment = j
        self.progress = self.cum[j] + t * (self.cum[j + 1] - self.cum[j])
        self.offset = d

    def update(self, x, y):
        if not self.active:
            return []
        out = []
        self.locate(x, y)
        if self.total - self.progress <= 2 * self.L:
            self.active = False
            return [("arrived", "You have reached the %s." % self.target, "arrived", None)]
        for k in range(1, max(len(self.headings), 1)):
            ahead = self.cum[k] - self.progress
            if ahead < -1:
                continue
            n = ahead / self.L
            turn, count = self.steps[k]["turn"], self.steps[k]["count"]
            verb = "Turn around" if turn == "around" else "Turn %s" % turn
            if turn == "straight":
                if n <= 1.5 and k not in self.turned:
                    self.turned.add(k); self.warned.add(k)
                    out.append(("say", "Continue straight for %d steps." % count, "navigating", None))
            elif n <= 1.5 and k not in self.turned:
                self.turned.add(k); self.warned.add(k)
                out.append(("say", "%s now, then walk %d steps." % (verb, count), "turn_now", 150))
            elif n <= 5 and k not in self.warned:
                self.warned.add(k)
                out.append(("say", "In %d steps, %s." % (max(1, int(round(n))), verb.lower()), "turn_now",
                            int(max(150, min(800, 150 + n * 65)))))
            break
        return out

    def steps_to_corner(self, x, y):
        if self.segment + 1 >= len(self.corners):
            return None
        c = self.corners[self.segment + 1]
        return int(round(math.hypot(c[0] - x, c[1] - y) / self.L))


class PhoneCoach:
    """Port of Coach in PhoneBrain.swift (branch clean-app): one rule. A steady pulse (tick every
    0.6 s) while the phone points along the way to walk; silence while it does not."""

    def __init__(self, clock):
        self.clock, self.aligned, self.last, self.leg, self.arrived_sent = clock, False, {}, None, False

    def due(self, cue, every):
        now = self.clock()
        if now - self.last.get(cue, -1e9) >= every:
            self.last[cue] = now
            return True
        return False

    def update(self, nav, facing, x, y):
        if nav is None:
            return {"active": False}, None
        if not nav.active:
            if not self.arrived_sent:
                self.arrived_sent = True
                return {"arrived": True, "target": nav.target}, "arrived"
            return {"arrived": True, "target": nav.target}, None
        error = (nav.headings[min(nav.segment, len(nav.headings) - 1)] - facing + 180) % 360 - 180
        steps_left = nav.steps_to_corner(x, y)
        nxt = nav.steps[nav.segment + 1]["turn"] if nav.segment + 1 < len(nav.steps) - 1 else None
        hint = {"active": True, "error_deg": round(error, 1), "target": nav.target}
        if steps_left is not None:
            hint["steps_left"] = steps_left
        if nxt and nxt != "straight":
            hint["next_turn"] = nxt
        if self.leg != nav.segment:
            self.leg, self.aligned = nav.segment, False
        if abs(error) > 35 or (not self.aligned and abs(error) > 22):
            self.aligned = False
            hint["state"] = "wrong_right" if error > 0 else "wrong_left"
            return hint, None
        self.aligned = True
        hint["state"] = "on_track"
        return hint, ("tick" if self.due("tick", 0.6) else None)


class Recorder:
    def __init__(self):
        self.now = [0.0]
        self.events = []        # discrete: user / say / led / landmark / guidance / buzz / phase
        self.samples = []       # continuous: pose, facing, led, hint
        self.led = "idle"
        self.hint = {}

    def ev(self, kind, **data):
        self.events.append(dict(t=round(self.now[0], 3), kind=kind, **data))


def main():
    rec = Recorder()
    store = RouteStore()          # in memory: every run starts from nothing
    walk_out = synthetic_walk(legs=((12, "right"), (9, None)), seed=3)
    rec.now[0] = walk_out[0][1]
    t0 = rec.now[0]
    tracker = make_tracker(synthetic=True)
    app = SpatialMemoryApp(tracker, store, speak=lambda s: None, led=None, clock=lambda: rec.now[0])
    coach = PhoneCoach(clock=lambda: rec.now[0])
    phone = {"nav": None, "pulse": None, "override": None}     # the iPhone app's own guidance (ported)

    def on_event(e):
        k = e.get("type")
        if phone["nav"] is not None and k in ("say", "led", "guidance"):
            return                       # guidance comes from the ported iPhone rules, not app.navigator
        if k == "say":
            # the iPhone app says just "Route started." (no hold-still wait on clean-app)
            rec.ev("say", text="Route started." if e["text"].startswith("Route started") else e["text"])
        elif k == "led":
            rec.led = e["state"]
            rec.ev("led", state=e["state"], period=e.get("period"))
        elif k == "landmark":
            rec.ev("landmark", label=e.get("label"), x=e.get("x_m"), y=e.get("y_m"))
        elif k == "guidance":
            rec.ev("guidance", index=e.get("current_index"), active=e.get("active"),
                   instructions=[i.get("text") for i in e.get("instructions", [])],
                   waypoints=e.get("waypoints"), target=e.get("target_name"))
    app.on_event(on_event)

    def user(text, phase):
        name, args = parse_keywords(text, store)      # the same tool list Gemini picks from
        rec.ev("user", text=text, phase=phase, tool=name, args=args)
        r = app.call_tool(name, args)
        rec.ev("tool", ok=r.ok, say=r.say, led=r.led, data={k: v for k, v in r.data.items() if k in ("label", "target", "instructions")})
        if r.led:
            rec.led = r.led
        return r

    def sample(force=False):
        p = app.current_pose
        if phone["override"] is not None:          # re-anchored at the destination after arrival
            p = type(p)(p.t, phone["override"][0], phone["override"][1], p.heading_deg, p.steps)
        facing = getattr(tracker, "facing", None)
        facing = tracker.raw_heading if facing is None else facing
        rec.samples.append(dict(t=round(rec.now[0], 3), x=round(p.x_m, 3), y=round(p.y_m, 3),
                                heading=round(p.heading_deg, 1), facing=round(facing, 1), steps=p.steps,
                                led=rec.led, hint=rec.hint, guiding=bool(phone["nav"] and phone["nav"].active)))

    next_sample = [0.0]
    next_coach = [0.0]

    def tick(t):
        rec.now[0] = t
        if t >= next_coach[0]:
            next_coach[0] = t + COACH_S
            facing = getattr(tracker, "facing", None)
            facing = tracker.raw_heading if facing is None else facing
            nav = phone["nav"]
            p = app.current_pose
            if nav is not None and nav.active:
                was = nav.segment
                for kind, text, led, period in nav.update(p.x_m, p.y_m):
                    rec.ev("say", text=text)
                    rec.led = led
                    rec.ev("led", state=led, period=period)
                    if kind == "arrived":
                        rec.ev("guidance", index=len(nav.steps) - 1, active=False, instructions=[s["text"] for s in nav.steps],
                               waypoints=[list(c) for c in nav.corners], target=nav.target)
                        phone["override"] = nav.corners[-1]
                if nav.active and nav.segment != was:
                    rec.ev("guidance", index=nav.segment, active=True, instructions=[s["text"] for s in nav.steps],
                           waypoints=[list(c) for c in nav.corners], target=nav.target)
            hint, cue = coach.update(nav, facing, p.x_m, p.y_m)
            rec.hint = hint
            if nav is not None and nav.active:
                on = hint.get("state") == "on_track"
                if on != phone["pulse"]:
                    phone["pulse"] = on
                    rec.ev("pulse", on=on, error=hint.get("error_deg"))
            if cue:
                rec.ev("buzz", cue=cue, error=hint.get("error_deg"))
        if t >= next_sample[0]:
            next_sample[0] = t + SAMPLE_S
            sample()

    def walk(events, phase):
        rec.ev("phase", name=phase + ":start")
        for kind, t, f in events:
            tick(t)
            if phone["override"] is not None:      # arrived: the walker stops here
                break
            if kind == "motion":
                tracker.on_motion(t, f["ax"], f["ay"], f["az"], f["gx"], f["gy"], f["gz"])
            elif kind == "activity":
                tracker.on_activity(t, f["steps"], f["state"])
        rec.ev("phase", name=phase + ":end")

    def wait(seconds, phase):
        rec.ev("phase", name=phase + ":start")
        end = rec.now[0] + seconds
        t = rec.now[0]
        while t < end:
            tick(t)
            t += 0.04
        rec.now[0] = end
        rec.ev("phase", name=phase + ":end")

    # Beat 2: start the route and pin the entrance (the walk begins with ~2.5 s of standing still)
    user("start route", "start")
    user("remember this as the entrance", "entrance")
    # Beat 3: walk the L
    walk(walk_out, "walk_out")
    user("remember this as the elevator", "elevator")
    # Beat 4: ask to go back while still facing down the hall (the wrong way)
    last_steps = [f["steps"] for k, t, f in walk_out if k == "activity"][-1]
    phone["nav"] = "pending"                     # from here the iPhone app's rules speak, not app.navigator
    user("take me back to the entrance", "navigate")
    # the iPhone app takes over guidance with the plan app.navigate_to computed (corners and legs)
    n = app.navigator
    ins = [i.to_dict() for i in n.instructions]
    steps = [{"turn": i["turn"], "count": i["steps"], "text": i["text"]} for i in ins]
    phone["nav"] = PhoneNav([tuple(w) for w in n.waypoints], steps, n.target_name, config.STEP_LENGTH_M)
    rec.ev("guidance", index=0, active=True, instructions=[x["text"] for x in steps],
           waypoints=[list(w) for w in n.waypoints], target=n.target_name)
    rec.ev("say", text=steps[0]["text"])            # one direction at a time; the rest come at each corner
    rec.led = "navigating"
    rec.ev("led", state="navigating", period=None)
    wait(2.6, "wrong_way")                       # facing away: no pulse, the banner says turn around
    back = synthetic_walk(legs=((0, "around"), (9, "left"), (16, None)), still_s=0.3, turn_s=1.6,
                          t0=rec.now[0] + 0.04, start_steps=last_steps, seed=4)
    walk(back, "walk_back")
    wait(2.0, "arrived")
    assert phone["override"] is not None, "the walk back never arrived"

    out = dict(
        note="Synthetic walk driven through the real Wayback code (app.py, tracker/wrist.py, store/), with the iPhone app's clean-app guidance and pulse rules ported from PhoneBrain.swift. Not live sensing.",
        t0=t0, samples=[dict(s, t=round(s["t"] - t0, 3)) for s in rec.samples],
        events=[dict(e, t=round(e["t"] - t0, 3)) for e in rec.events],
    )
    with open(os.path.join(HERE, "timeline.json"), "w") as f:
        json.dump(out, f, indent=0)
    for e in out["events"]:
        if e["kind"] in ("user", "say", "landmark", "led", "guidance", "pulse") or (e["kind"] == "buzz" and e["cue"] != "tick"):
            extra = {k: v for k, v in e.items() if k not in ("t", "kind", "waypoints")}
            print("%7.2f %-9s %s" % (e["t"], e["kind"], extra))
    s = out["samples"][-1]
    print("final pose: x=%.2f y=%.2f steps=%d  samples=%d" % (s["x"], s["y"], s["steps"], len(out["samples"])))


if __name__ == "__main__":
    main()
