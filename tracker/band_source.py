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


def connect(tracker, logger=None, on_double_tap=None, on_link=None, on_uncertain=None, usb=False,
            on_metric=None):
    """Connect to the team's band, stream motion and steps into tracker, log every sample.

    on_double_tap(): called on a double-tap (starts one listening turn).
    on_link(text): called with "connected", "reconnecting" or "reconnected".
    on_uncertain(is_uncertain): called when tracker.heading_uncertain transitions False<->True.
    usb: use the USB cable instead of Bluetooth (still only the team's band number).
    on_metric(kind, fields): band readings for a dashboard: "info", "activity",
        "battery", "temperature", "event".
    Returns the connected band (vexo_open.sync.Band).
    """
    metric = on_metric or (lambda kind, fields: None)
    number = require_band_number()
    if on_uncertain is not None:
        tracker.on_uncertainty(on_uncertain)
    if KIT_PYTHON not in sys.path:
        sys.path.insert(0, KIT_PYTHON)
    from vexo_open.sync import Band

    if usb:
        band = Band.connect(number, transport="serial", auto_reconnect=True)
    else:
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
        metric("activity", dict(steps=e.steps, cadence=e.cadence, state=e.state, motion=e.motion))
        if logger:
            logger.log("activity", e.time, dict(steps=e.steps, state=e.state))

    band.on("motion", motion)
    band.on("activity", activity)
    band.on("battery", lambda e: metric("battery", dict(percent=e.percent, millivolts=e.millivolts, state=e.state)))
    band.on("temperature", lambda e: metric("temperature", dict(celsius=e.celsius)))
    band.on("event", lambda e: metric("event", dict(kind=e.kind, arg=e.arg)))
    if on_double_tap:
        band.on("double-tap", lambda e: on_double_tap())
    if on_link:
        band.on("reconnecting", lambda e: on_link("reconnecting"))
        band.on("reconnected", lambda e: on_link("reconnected"))   # the library re-applies LED and streams
    band.configure(motion=config.MOTION_RATE_HZ, sensors="both", activity=config.ACTIVITY_RATE, events=True,
                   battery=True, temperature=5)
    metric("info", dict(name=band.name, firmware=band.info.firmware, transport="USB" if usb else "Bluetooth"))
    if on_link:
        on_link("connected")
    return band
