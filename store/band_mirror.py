"""Mirror saved landmarks to Vexo band on-device storage slots (P2).

Rules (vexo-open-kit/AGENTS.md Rule 6 & Safety Rule 1):
- Storage has keys 0..999, each holding at most 232 UTF-8 bytes.
- Storage is public on the band: NEVER store API keys, tokens, passwords, or secrets.
- Band storage accepts at most 10 writes/sec and can fail with 'busy' or
  'not-connected', so every storage call is guarded and non-fatal.
- This module never imports or connects to a band; callers inject a `storage` object
  supporting `put(key_int, text)`, `get_text(key_int)`, and `delete(key_int)`.
"""
import json
import re
from typing import Dict, List, Optional

from interfaces import Landmark

MAX_SLOT_BYTES = 232
TOTAL_BAND_SLOTS = 1000

# Defensive pattern so nothing resembling a bearer/API secret is ever written to band slots.
_SECRET_RE = re.compile(
    r"(VEXO_[A-Z_]*KEY|GEMINI_API_KEY|GOOGLE_API_KEY|OPENAI_API_KEY|DEEPGRAM_API_KEY|"
    r"ELEVENLABS_API_KEY|AIza[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z_-]{20,})",
    re.IGNORECASE,
)


def _sanitize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = _SECRET_RE.sub("[redacted]", str(value)).strip()
    return cleaned or None


def _truncate_chars(text: str, length: int) -> str:
    if length <= 0:
        return ""
    if len(text) <= length:
        return text
    if length <= 1:
        return text[:length]
    return text[: length - 1].rstrip() + "…"


def encode_landmark_slot(landmark: Landmark, max_bytes: int = MAX_SLOT_BYTES) -> str:
    """Serialize safe landmark fields into JSON guaranteed <= max_bytes UTF-8 bytes."""
    if max_bytes < 48:
        raise ValueError("max_bytes must be at least 48")

    lm_id = _sanitize_text(landmark.id) or "lm0"
    label = _sanitize_text(landmark.label) or "place"
    floor = _sanitize_text(landmark.floor)
    note = _sanitize_text(landmark.note)
    point_index = int(landmark.point_index)

    def _pack(lbl: str, flr: Optional[str], nt: Optional[str]) -> str:
        payload = {"id": lm_id, "label": lbl, "point_index": point_index}
        if flr:
            payload["floor"] = flr
        if nt:
            payload["note"] = nt
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    candidate = _pack(label, floor, note)
    if len(candidate.encode("utf-8")) <= max_bytes:
        return candidate

    # 1. Binary-search truncate `note` first so label and floor stay intact.
    if note:
        lo, hi = 0, len(note)
        best: Optional[str] = None
        while lo <= hi:
            mid = (lo + hi) // 2
            nt = _truncate_chars(note, mid) if mid > 0 else None
            s = _pack(label, floor, nt)
            if len(s.encode("utf-8")) <= max_bytes:
                best = s
                lo = mid + 1
            else:
                hi = mid - 1
        if best is not None:
            return best
        note = None

    # 2. Trim `floor` if unusually long.
    if floor and len(floor) > 12:
        floor = _truncate_chars(floor, 12)
        candidate = _pack(label, floor, None)
        if len(candidate.encode("utf-8")) <= max_bytes:
            return candidate

    # 3. Binary-search truncate `label` ( dropping floor if still needed ).
    for flr in (floor, None):
        lo, hi = 1, len(label)
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            s = _pack(_truncate_chars(label, mid), flr, None)
            if len(s.encode("utf-8")) <= max_bytes:
                best = s
                lo = mid + 1
            else:
                hi = mid - 1
        if best is not None:
            return best

    fallback = json.dumps({"id": lm_id[:12], "label": "lm", "point_index": point_index}, separators=(",", ":"))
    return fallback


def decode_landmark_slot(raw: Optional[str]) -> Optional[Landmark]:
    """Parse a JSON slot string back into a Landmark, or None if empty/invalid."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        lm_id = str(data["id"])
        label = str(data["label"])
        point_index = int(data["point_index"])
        floor = str(data["floor"]) if data.get("floor") is not None else None
        note = str(data["note"]) if data.get("note") is not None else None
        return Landmark(id=lm_id, label=label, point_index=point_index, floor=floor, note=note)
    except (ValueError, KeyError, TypeError):
        return None


class BandLandmarkMirror:
    """Mirrors RouteStore landmarks into injected band storage slots."""

    def __init__(self, storage=None, base_slot: int = 0, max_slots: int = 200):
        if base_slot < 0 or max_slots < 1 or base_slot + max_slots > TOTAL_BAND_SLOTS:
            raise ValueError("Slot range must fit within 0..999")
        self.storage = storage
        self.base_slot = base_slot
        self.max_slots = max_slots
        self._slots_by_id: Dict[str, int] = {}
        self._ids_by_slot: Dict[int, str] = {}

    def slot_for(self, landmark_id: str) -> Optional[int]:
        return self._slots_by_id.get(landmark_id)

    def _allocate_slot(self, landmark_id: str) -> Optional[int]:
        if landmark_id in self._slots_by_id:
            return self._slots_by_id[landmark_id]

        m = re.match(r"^lm(\d+)$", landmark_id)
        if m:
            preferred = self.base_slot + ((int(m.group(1)) - 1) % self.max_slots)
            if preferred not in self._ids_by_slot:
                self._slots_by_id[landmark_id] = preferred
                self._ids_by_slot[preferred] = landmark_id
                return preferred

        for offset in range(self.max_slots):
            slot = self.base_slot + offset
            if slot not in self._ids_by_slot:
                self._slots_by_id[landmark_id] = slot
                self._ids_by_slot[slot] = landmark_id
                return slot
        return None

    def mirror(self, landmark: Landmark) -> Optional[int]:
        """Write `landmark` (<= 232 UTF-8 bytes) to its slot. Returns slot index or None."""
        if self.storage is None:
            return None
        slot = self._allocate_slot(landmark.id)
        if slot is None:
            return None
        payload = encode_landmark_slot(landmark, MAX_SLOT_BYTES)
        try:
            self.storage.put(slot, payload)
            return slot
        except Exception:
            return None

    def read(self, slot: int) -> Optional[Landmark]:
        """Read back a Landmark from `slot`, returning None if absent or on error."""
        if self.storage is None:
            return None
        try:
            raw = self.storage.get_text(slot)
        except Exception:
            return None
        return decode_landmark_slot(raw)

    def read_all(self) -> List[Landmark]:
        """Read back all landmarks mirrored during this session."""
        out: List[Landmark] = []
        for slot in sorted(self._ids_by_slot):
            lm = self.read(slot)
            if lm is not None:
                out.append(lm)
        return out

    def delete(self, landmark_id: str) -> bool:
        """Delete a mirrored landmark slot by landmark id."""
        slot = self._slots_by_id.pop(landmark_id, None)
        if slot is None:
            return False
        self._ids_by_slot.pop(slot, None)
        if self.storage is None:
            return False
        try:
            self.storage.delete(slot)
            return True
        except Exception:
            return False

    def clear(self) -> None:
        """Delete all slots tracked by this mirror."""
        for lm_id in list(self._slots_by_id):
            self.delete(lm_id)
