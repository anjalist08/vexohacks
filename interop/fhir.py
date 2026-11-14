"""Export routes as an HL7 FHIR R4 Bundle, so health systems can read them.

Health systems (EHRs, care-coordination and mobility-rehab tools) read FHIR, the HL7
standard for health data over REST/JSON. This module turns what the store already
records into standard resources with standard codes, and adds no dependency:

    Device       the Vexo band that did the sensing
    Patient      a pseudonymous reference only (an id you pass in, no name or birth date)
    Observation  steps per route (LOINC 55423-8) and distance walked (LOINC 55430-3), UCUM units
    Location     each saved landmark: its label, floor and note
    Provenance   which program made the data, and whether it was live, a replay or synthetic

Run it on the saved routes file:

    python3 -m interop.fhir data/routes.json > bundle.json
    python3 -m interop.fhir data/routes.json --patient-id demo-123 --source sim

Limits: the band has no GPS, so a Location carries the route's local metres (an
extension), not latitude and longitude. Nothing is uploaded: the bundle is a file the
user chooses to share. Synthetic or replayed data is labelled as such in Provenance.
"""
import argparse
import json
import math
import sys
import time
import uuid
from typing import List, Optional

from store.route_store import Route, RouteStore

FHIR_VERSION = "4.0.1"
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
EXT_LOCAL_POSITION = "urn:vexohacks:fhir:local-position"   # x/y metres from the route start
SOURCES = ("live", "replay", "synthetic")

_NS = uuid.UUID("6f1d3c52-8a1e-4c1b-9f0e-2b6a7d9e4c10")   # stable ids for the same route


def _id(*parts) -> str:
    return str(uuid.uuid5(_NS, "/".join(str(p) for p in parts)))


def _ts(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _entry(resource: dict) -> dict:
    return {"fullUrl": "urn:uuid:%s" % resource["id"], "resource": resource}


def _ref(resource: dict) -> dict:
    return {"reference": "urn:uuid:%s" % resource["id"]}


def _distance(route: Route) -> float:
    p = route.points
    return sum(math.hypot(b.x_m - a.x_m, b.y_m - a.y_m) for a, b in zip(p, p[1:]))


def device_resource() -> dict:
    return {"resourceType": "Device", "id": _id("device", "vexo-band"),
            "deviceName": [{"name": "Vexo band", "type": "user-friendly-name"}],
            "type": {"text": "Wrist-worn inertial sensor (pedometer and gyroscope)"}}


def patient_resource(patient_id: str) -> dict:
    """A pseudonymous Patient: only the id the caller supplies, no personal details."""
    return {"resourceType": "Patient", "id": _id("patient", patient_id),
            "identifier": [{"system": "urn:vexohacks:patient", "value": patient_id}]}


def _observation(route: Route, kind: str, code: str, display: str, value: float, unit: str,
                 ucum: str, patient: dict, device: dict) -> dict:
    pts = route.points
    obs = {"resourceType": "Observation", "id": _id("obs", kind, route.id, pts[0].t if pts else 0),
           "status": "final",
           "category": [{"coding": [{"system": OBS_CATEGORY, "code": "activity", "display": "Activity"}]}],
           "code": {"coding": [{"system": LOINC, "code": code, "display": display}], "text": display},
           "subject": _ref(patient), "device": _ref(device),
           "valueQuantity": {"value": value, "unit": unit, "system": UCUM, "code": ucum},
           "note": [{"text": "Route: %s" % route.title}]}
    if pts:
        obs["effectivePeriod"] = {"start": _ts(pts[0].t), "end": _ts(pts[-1].t)}
    return obs


def route_observations(route: Route, patient: dict, device: dict) -> List[dict]:
    steps = route.points[-1].steps - route.points[0].steps if route.points else 0
    return [
        _observation(route, "steps", "55423-8", "Number of steps in unspecified time Pedometer",
                     steps, "steps", "{steps}", patient, device),
        _observation(route, "distance", "55430-3", "Walking distance unspecified time Pedometer",
                     round(_distance(route), 2), "m", "m", patient, device),
    ]


def landmark_locations(route: Route) -> List[dict]:
    out = []
    for lm in route.landmarks:
        p = route.points[lm.point_index]
        loc = {"resourceType": "Location", "id": _id("location", route.id, lm.id),
               "identifier": [{"system": "urn:vexohacks:landmark", "value": lm.id}],
               "status": "active", "name": lm.label, "mode": "instance",
               "extension": [{"url": EXT_LOCAL_POSITION, "extension": [
                   {"url": "route", "valueString": route.id},
                   {"url": "x-metres", "valueDecimal": round(p.x_m, 2)},
                   {"url": "y-metres", "valueDecimal": round(p.y_m, 2)}]}]}
        if lm.note:
            loc["description"] = lm.note
        if lm.floor:
            loc["physicalType"] = {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/location-physical-type",
                "code": "lvl", "display": "Level"}], "text": "Floor %s" % lm.floor}
        out.append(loc)
    return out


def provenance_resource(targets: List[dict], source: str, device: dict, recorded: float) -> dict:
    return {"resourceType": "Provenance", "id": _id("provenance", recorded, len(targets)),
            "target": [_ref(t) for t in targets], "recorded": _ts(recorded),
            "agent": [{"type": {"text": "device"}, "who": _ref(device)}],
            "entity": [{"role": "source", "what": {"display": "data source: %s" % source}}]}


def to_bundle(routes: List[Route], patient_id: str = "anonymous", source: str = "live",
              now: Optional[float] = None) -> dict:
    """A FHIR R4 collection Bundle for these routes. `source` is live, replay or synthetic."""
    if source not in SOURCES:
        raise ValueError("source must be one of %s" % ", ".join(SOURCES))
    now = time.time() if now is None else now
    device, patient = device_resource(), patient_resource(patient_id)
    data = []
    for route in routes:
        data += route_observations(route, patient, device) + landmark_locations(route)
    resources = [device, patient] + data
    if data:
        resources.append(provenance_resource(data, source, device, now))
    return {"resourceType": "Bundle", "id": _id("bundle", now, patient_id), "type": "collection",
            "meta": {"lastUpdated": _ts(now)}, "timestamp": _ts(now),
            "entry": [_entry(r) for r in resources]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Export saved routes as a FHIR R4 Bundle (JSON).")
    p.add_argument("routes_file", help="the store's JSON file, e.g. data/routes.json")
    p.add_argument("--patient-id", default="anonymous", help="a pseudonymous id, never a name")
    p.add_argument("--source", choices=SOURCES, default="live", help="how the data was recorded")
    a = p.parse_args(argv)
    bundle = to_bundle(RouteStore(a.routes_file).routes, a.patient_id, a.source)
    json.dump(bundle, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
