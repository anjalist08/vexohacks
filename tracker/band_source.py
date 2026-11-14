"""Live band -> PathTracker. Not yet run on real hardware: Gate A checks it.

Rules from the kit (vexo-open-kit/AGENTS.md):
- Use only the team's own band: config.BAND, never 42 or a number from an example.
- One program at a time: close the kit dashboard before running this.
- Double-tap the band before connecting, so it can be found for 60 seconds.
- Agents must not run this. A person runs it from their own Terminal.
"""
import os
import sys

import config

KIT_PYTHON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vexo-open-kit", "python")


def require_band_number() -> int:
    if config.BAND is None:
        raise SystemExit("Set BAND in config.py to the number on your band's bag first "
                         "(the band is called Vexo-HACK-NN).")
    return config.BAND


def connect(tracker, logger=None, on_double_tap=None, on_link=None):
    """Connect to the team's band, stream motion and steps into tracker, log every sample.

    on_double_tap(): called on a double-tap (starts one listening turn).
    on_link(text): called with "connected", "reconnecting" or "reconnected".
    Returns the connected band (vexo_open.sync.Band).
    """
    number = require_band_number()
    if KIT_PYTHON not in sys.path:
        sys.path.insert(0, KIT_PYTHON)
    from vexo_open.sync import Band

    band = Band.connect(number, auto_reconnect=True)
    if band.number != number:          # Band.connect already checks; belt and braces
        band.disconnect()
        raise SystemExit("Connected to band %s, expected %s. Disconnected." % (band.number, number))

    def motion(m):
        tracker.on_motion(m.time, m.ax, m.ay, m.az, m.gx, m.gy, m.gz)
        if logger:
            logger.log("motion", m.time, dict(ax=m.ax, ay=m.ay, az=m.az, gx=m.gx, gy=m.gy, gz=m.gz))

    def activity(e):
        tracker.on_activity(e.time, e.steps, e.state)
        if logger:
            logger.log("activity", e.time, dict(steps=e.steps, state=e.state))

    band.on("motion", motion)
    band.on("activity", activity)
    if on_double_tap:
        band.on("double-tap", lambda e: on_double_tap())
    if on_link:
        band.on("reconnecting", lambda e: on_link("reconnecting"))
        band.on("reconnected", lambda e: on_link("reconnected"))   # the library re-applies LED and streams
    band.configure(motion=config.MOTION_RATE_HZ, sensors="both", activity=config.ACTIVITY_RATE, events=True)
    if on_link:
        on_link("connected")
    return band
