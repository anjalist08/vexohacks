"""Record a timeline for the 60-second working-demo video by running the REAL Wayback code
on a SYNTHETIC walk (tracker/events.synthetic_walk). Not live sensing: the video says so.

    python3 demo-video/simulate.py        # writes demo-video/timeline.json

What runs for real: SpatialMemoryApp (app.py), the wrist tracker (tracker/wrist.py), the route
store and return guidance (store/), the buzz coach (store/haptics.py), and keyword_command
(the same tools Gemini picks from). Every position, step count, spoken line, LED state and
buzz cue in the video comes from this run. The walk itself is made up: an L-shaped hallway,
12 steps, a right turn, 9 steps; then back.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app import SpatialMemoryApp, parse_keywords  # noqa: E402
from store.haptics import HapticCoach     # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import synthetic_walk  # noqa: E402
from tracker.wrist import make_tracker     # noqa: E402

SAMPLE_S = 0.1     # how often the screen state is sampled
COACH_S = 0.2      # the coach runs 5 times a second, as in web/ws_server.py


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
    coach = HapticCoach(clock=lambda: rec.now[0])

    def on_event(e):
        k = e.get("type")
        if k == "say":
            rec.ev("say", text=e["text"])
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
        facing = getattr(tracker, "facing", None)
        facing = tracker.raw_heading if facing is None else facing
        rec.samples.append(dict(t=round(rec.now[0], 3), x=round(p.x_m, 3), y=round(p.y_m, 3),
                                heading=round(p.heading_deg, 1), facing=round(facing, 1), steps=p.steps,
                                led=rec.led, hint=rec.hint, guiding=bool(app.navigator and app.navigator.active)))

    next_sample = [0.0]
    next_coach = [0.0]

    def tick(t):
        rec.now[0] = t
        if t >= next_coach[0]:
            next_coach[0] = t + COACH_S
            facing = getattr(tracker, "facing", None)
            facing = tracker.raw_heading if facing is None else facing
            out = coach.update(app.navigator, facing, app.current_pose, bool(getattr(tracker, "heading_uncertain", False)))
            rec.hint = out["hint"]
            if out["cue"]:
                rec.ev("buzz", cue=out["cue"], error=out["hint"].get("error_deg"))
        if t >= next_sample[0]:
            next_sample[0] = t + SAMPLE_S
            sample()

    def walk(events, phase):
        rec.ev("phase", name=phase + ":start")
        for kind, t, f in events:
            tick(t)
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
    user("take me back to the entrance", "navigate")
    wait(2.6, "wrong_way")                       # the coach buzzes "turn around / wrong way"
    back = synthetic_walk(legs=((0, "around"), (9, "left"), (16, None)), still_s=0.3, turn_s=1.6,
                          t0=rec.now[0] + 0.04, start_steps=last_steps, seed=4)
    walk(back, "walk_back")
    wait(2.0, "arrived")

    out = dict(
        note="Synthetic walk driven through the real Wayback code (app.py, tracker/wrist.py, store/guidance.py, store/haptics.py). Not live sensing.",
        t0=t0, samples=[dict(s, t=round(s["t"] - t0, 3)) for s in rec.samples],
        events=[dict(e, t=round(e["t"] - t0, 3)) for e in rec.events],
    )
    with open(os.path.join(HERE, "timeline.json"), "w") as f:
        json.dump(out, f, indent=0)
    for e in out["events"]:
        if e["kind"] in ("user", "say", "buzz", "landmark", "led", "guidance"):
            extra = {k: v for k, v in e.items() if k not in ("t", "kind", "waypoints")}
            print("%7.2f %-9s %s" % (e["t"], e["kind"], extra))
    s = out["samples"][-1]
    print("final pose: x=%.2f y=%.2f steps=%d  samples=%d" % (s["x"], s["y"], s["steps"], len(out["samples"])))


if __name__ == "__main__":
    main()
