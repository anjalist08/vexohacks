"""On the way back, ask "are you at the elevator?" near each saved landmark.

The tracked position drifts, so it cannot say for sure that the user has reached a
landmark. It can say the user should be close. Then the app asks, and a "yes" (a
double-tap of the band, or the big button on the phone page) re-anchors the position
there with the existing reanchor tool, which removes the drift built up so far.
"""
import math

RADIUS_STEPS = 3          # PLACEHOLDER: ask when within this many steps of a landmark


class ArrivalWatcher:
    def __init__(self, app, notify, radius_steps: float = RADIUS_STEPS):
        self.app = app
        self.notify = notify                 # fn(say, cue)
        self.radius_steps = radius_steps
        self.pending = []                    # [(landmark_id or "start", label, point_index)]
        self.asking = None                   # the entry being asked about
        self.target = None                   # where the guidance leads
        app.tracker.on_sample(self.check)

    @property
    def radius_m(self) -> float:
        return self.radius_steps * self.app.tracker.step_length_m

    def arm(self, target: str):
        """Guidance has started towards target (a landmark id or "start")."""
        route = self.app.store.current
        lm = self.app.store.get_landmark(target)
        self.target = lm.id if lm is not None else "start"
        here = self.app.tracker.pose
        entries = [(l.id, l.label, l.point_index) for l in route.landmarks]
        if self.target == "start":
            entries.append(("start", "start", 0))
        # Landmarks the user stands at already are not asked about.
        self.pending = [e for e in entries if self._distance(here, e[2]) > self.radius_m]
        self.asking = None

    def disarm(self):
        self.pending, self.asking, self.target = [], None, None

    def check(self, sample):
        if not self.pending:
            return
        for entry in list(self.pending):
            if self._distance(sample, entry[2]) <= self.radius_m:
                self.pending.remove(entry)
                self.asking = entry
                self.notify("Are you at the %s? Double-tap to say yes." % entry[1], "confirm_prompt")
                return

    def confirm(self):
        """The user said yes: re-anchor at the landmark asked about."""
        if self.asking is None:
            return None
        lm_id, label, index = self.asking
        self.asking = None
        # Reset the position only. The reanchor tool also resets the heading to the one
        # recorded at the landmark, which on the way back points the opposite way.
        p = self.app.store.current.points[index]
        tracker = self.app.tracker
        tracker.reanchor(p.x_m, p.y_m, tracker.heading, self.app.clock())
        navigator = getattr(self.app, "navigator", None)
        if navigator is not None and not navigator.active:
            self.disarm()               # the app's live guidance has announced the arrival
        elif lm_id == self.target and navigator is None:
            self.notify("You have reached the %s." % label, "arrived")
            self.disarm()
        else:
            self.notify("Got it, you're at the %s." % label, "landmark_saved")
        return lm_id

    def reached(self, landmark_id):
        """The user re-anchored by voice ("I'm at the elevator")."""
        self.pending = [e for e in self.pending if e[0] != landmark_id]
        if self.asking and self.asking[0] == landmark_id:
            self.asking = None

    def _distance(self, pose, index: int) -> float:
        p = self.app.store.current.points[index]
        return math.hypot(pose.x_m - p.x_m, pose.y_m - p.y_m)
