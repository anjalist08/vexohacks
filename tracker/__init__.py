"""Pedestrian dead reckoning, sensor event logging, and deterministic CSV replay."""
from tracker.events import (
    COLUMNS,
    Event,
    SampleLogger,
    feed,
    read_log,
    synthetic_walk,
    write_log,
)
from tracker.pdr import PathTracker, wrap_deg

_REPLAY_EXPORTS = (
    "PoseRow",
    "ReplayReport",
    "format_report",
    "format_trace",
    "render_ascii_trace",
    "replay_events",
    "replay_file",
)

__all__ = [
    "COLUMNS",
    "Event",
    "PathTracker",
    "PoseRow",
    "ReplayReport",
    "SampleLogger",
    "feed",
    "format_report",
    "format_trace",
    "read_log",
    "render_ascii_trace",
    "replay_events",
    "replay_file",
    "synthetic_walk",
    "wrap_deg",
    "write_log",
]


def __getattr__(name: str):
    if name in _REPLAY_EXPORTS:
        from tracker import replay as _replay
        return getattr(_replay, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
