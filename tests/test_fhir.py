"""FHIR export tests on a synthetic walk. Run: python3 -m unittest"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import SpatialMemoryApp  # noqa: E402
from interop import fhir  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import feed, synthetic_walk  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402


def recorded_app(path=None):
    walk = synthetic_walk(legs=((20, "left"), (15, None)))
    app = SpatialMemoryApp(PathTracker(step_length_m=0.7), RouteStore(path), speak=lambda s: None,
                           clock=lambda: walk[0][1])
    app.call_tool("start_route", {"title": "clinic visit"})
    feed(app.tracker, walk)
    app.call_tool("remember_landmark", {"label": "elevator", "floor": "B2", "note": "near the blue sign"})
    app.call_tool("stop_route")
    return app


def by_type(bundle, kind):
    return [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == kind]


class FhirExportTests(unittest.TestCase):
    def setUp(self):
        self.bundle = fhir.to_bundle(recorded_app().store.routes, "demo-1", "synthetic", now=1.8e9)

    def test_bundle_shape(self):
        b = self.bundle
        self.assertEqual((b["resourceType"], b["type"]), ("Bundle", "collection"))
        for e in b["entry"]:
            self.assertEqual(e["fullUrl"], "urn:uuid:" + e["resource"]["id"])
        json.dumps(b)   # plain JSON, nothing exotic

    def test_references_resolve(self):
        urls = {e["fullUrl"] for e in self.bundle["entry"]}
        text = json.dumps(self.bundle)
        for ref in set(part.split('"')[0] for part in text.split('"reference": "')[1:]):
            self.assertIn(ref, urls)

    def test_observations_use_loinc_and_ucum(self):
        obs = {o["code"]["coding"][0]["code"]: o for o in by_type(self.bundle, "Observation")}
        self.assertEqual(obs["55423-8"]["valueQuantity"]["value"], 35)
        self.assertEqual(obs["55423-8"]["valueQuantity"]["code"], "{steps}")
        self.assertAlmostEqual(obs["55430-3"]["valueQuantity"]["value"], 24.5, places=0)
        self.assertEqual(obs["55430-3"]["valueQuantity"]["system"], fhir.UCUM)

    def test_landmark_becomes_location(self):
        (loc,) = by_type(self.bundle, "Location")
        self.assertEqual(loc["name"], "elevator")
        self.assertEqual(loc["description"], "near the blue sign")
        self.assertEqual(loc["physicalType"]["text"], "Floor B2")

    def test_patient_is_pseudonymous_and_source_labelled(self):
        (patient,) = by_type(self.bundle, "Patient")
        self.assertEqual(set(patient), {"resourceType", "id", "identifier"})
        (prov,) = by_type(self.bundle, "Provenance")
        self.assertIn("synthetic", prov["entity"][0]["what"]["display"])

    def test_bad_source_is_rejected(self):
        with self.assertRaises(ValueError):
            fhir.to_bundle([], source="made-up")

    def test_cli_reads_saved_routes(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "routes.json")
            recorded_app(path)
            out = os.path.join(d, "bundle.json")
            stdout = sys.stdout
            with open(out, "w") as f:
                sys.stdout = f
                try:
                    self.assertEqual(fhir.main([path, "--source", "synthetic"]), 0)
                finally:
                    sys.stdout = stdout
            with open(out) as f:
                self.assertEqual(len(by_type(json.load(f), "Location")), 1)


if __name__ == "__main__":
    unittest.main()
