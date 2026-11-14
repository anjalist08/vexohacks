# interop/: health-system interoperability (HL7 FHIR R4)

Health systems use different APIs and data formats, so this folder exports what the app
records in the one format most of them already read: **HL7 FHIR R4 JSON**, with standard
codes (LOINC, UCUM). It needs no new dependency and does not change any shared file.

    python3 -m interop.fhir data/routes.json > bundle.json
    python3 -m interop.fhir data/routes.json --patient-id demo-123 --source synthetic

| App data | FHIR resource | Standard codes |
| --- | --- | --- |
| The band | `Device` | |
| The wearer | `Patient` (a pseudonymous id only, no name or birth date) | |
| Steps per route | `Observation` | LOINC 55423-8, UCUM `{steps}` |
| Distance per route | `Observation` | LOINC 55430-3, UCUM `m` |
| Each landmark | `Location` (label, floor, note) | location-physical-type `lvl` |
| Live, replay or synthetic | `Provenance` | |

The output is a `collection` Bundle. A FHIR server (for example a HAPI FHIR test server)
or a FHIR validator can read it, and it can be POSTed to a server as-is after you change
`type` to `transaction`.

Limits: the band has no GPS, so a `Location` holds the route's local x/y metres in an
extension, not latitude and longitude. Nothing is uploaded: the bundle is a file the user
chooses to share. Synthetic and replayed walks are labelled as such in `Provenance`.

Tests: `tests/test_fhir.py`.
