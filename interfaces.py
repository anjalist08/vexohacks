"""Shared data shapes and the tool list. Every folder builds against this file.

Do not change a field or a tool here without telling the whole team (see AGENTS.md):
the tracker, the store, the voice loop and the map page all depend on it.

Coordinates: metres from the route start. +y is the direction you faced at
"start route", +x is to its right. Heading is in degrees, clockwise from +y,
so 0 = straight ahead at the start, 90 = right, -90 = left, 180 = behind.
"""
from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class PoseSample:
    """One point on the route. The tracker emits one whenever new steps arrive."""
    t: float              # seconds (unix time from the band's reading)
    x_m: float
    y_m: float
    heading_deg: float    # heading used for this move (snapped if SNAP_TURNS)
    steps: int            # steps since the route started

    def to_dict(self):
        return asdict(self)


@dataclass
class Landmark:
    id: str               # short stable id such as "lm1"
    label: str            # what the user called it, e.g. "elevator"
    point_index: int      # index into the route's points
    floor: Optional[str] = None       # spoken floor label such as "B2"
    note: Optional[str] = None        # free text, e.g. "near the blue sign"
    transcript: Optional[str] = None  # what was said when it was saved

    def to_dict(self):
        return asdict(self)


@dataclass
class Instruction:
    """One spoken step of return guidance. Code computes it, never the model."""
    turn: str             # "straight", "left", "right", "around" or "arrive"
    steps: int
    distance_m: float
    text: str             # e.g. "Turn left, walk 18 steps."

    def to_dict(self):
        return asdict(self)


@dataclass
class ToolResult:
    """What every tool returns: words to say and an LED state to show."""
    ok: bool
    say: str
    led: Optional[str] = None                 # a state name from voice/led_states.py
    data: dict = field(default_factory=dict)  # extra detail for the map page


# The tools Gemini may call. Names and parameters match app.SpatialMemoryApp methods.
# Gemini picks the tool and matches names. It never supplies coordinates, distances
# or turn directions.
TOOLS = [
    {"name": "start_route", "description": "Start recording a new route from where the user stands.",
     "parameters": {"title": {"type": "string", "description": "a short name for the route", "required": False}}},
    {"name": "stop_route", "description": "Stop recording the current route.", "parameters": {}},
    {"name": "remember_landmark", "description": "Save the user's current position under a name.",
     "parameters": {"label": {"type": "string", "description": "what to call this place", "required": True},
                    "floor": {"type": "string", "description": "spoken floor label such as B2", "required": False},
                    "note": {"type": "string", "description": "anything else the user said about it", "required": False}}},
    {"name": "save_note", "description": "Attach a note to a landmark, or to the current position.",
     "parameters": {"text": {"type": "string", "required": True},
                    "landmark_id": {"type": "string", "description": "an id from the landmark list", "required": False}}},
    {"name": "find_landmark", "description": "Find saved landmarks that match what the user said.",
     "parameters": {"query": {"type": "string", "required": True}}},
    {"name": "navigate_to", "description": "Guide the user back along the recorded path.",
     "parameters": {"target": {"type": "string", "description": "a landmark id, or 'start'", "required": True}}},
    {"name": "reanchor", "description": "The user says they are at a saved landmark: reset the position there.",
     "parameters": {"landmark_id": {"type": "string", "required": True}}},
    {"name": "ask_user", "description": "Ask a short clarifying question, e.g. when two landmarks match.",
     "parameters": {"question": {"type": "string", "required": True}}},
    {"name": "set_mode", "description": "Choose how guidance is given.",
     "parameters": {"mode": {"type": "string", "enum": ["both", "light-only", "voice-only"], "required": True}}},
]

OUTPUT_MODES = ("both", "light-only", "voice-only")
