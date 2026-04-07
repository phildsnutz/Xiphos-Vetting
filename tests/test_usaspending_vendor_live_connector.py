import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from osint.usaspending_vendor_live import enrich  # type: ignore  # noqa: E402


FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "fixtures",
    "procurement_footprint",
    "vendor_procurement_support_fixture.json",
)


def test_vendor_live_collector_replays_procurement_fixture():
    result = enrich(
        "PARSONS CORPORATION",
        vendor_procurement_fixture_path=FIXTURE_PATH,
    )

    assert result.findings
    assert any(finding.title.startswith("Federal procurement footprint:") for finding in result.findings)
    assert any(rel.get("rel_type") == "prime_on_vehicle" for rel in result.relationships)
    assert any(rel.get("rel_type") == "subcontractor_on_vehicle" for rel in result.relationships)

    structured = result.structured_fields
    assert structured["prime_vehicles"][0]["vehicle_name"] == "OASIS"
    assert structured["sub_vehicles"][0]["vehicle_name"] == "OASIS"
    assert structured["upstream_primes"][0]["name"] == "SMARTRONIX, LLC"
    assert structured["downstream_subcontractors"][0]["name"] == "HII MISSION TECHNOLOGIES CORP"
