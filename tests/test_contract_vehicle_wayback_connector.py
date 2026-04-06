import os
import sys
from pathlib import Path


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from osint import contract_vehicle_wayback  # noqa: E402


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "vehicle_intelligence"
    / "contract_vehicle_wayback_fixture.json"
)


def test_contract_vehicle_wayback_uses_seeded_fixture_captures():
    result = contract_vehicle_wayback.enrich(
        "ITEAMS",
        contract_vehicle_archive_seed_urls=["https://sam.gov/opportunity/ITEAMS"],
        contract_vehicle_wayback_fixture_path=str(FIXTURE_PATH),
    )

    assert result.source == "contract_vehicle_wayback"
    assert result.error == ""
    assert result.structured_fields["used_fixture"] is True
    assert result.structured_fields["captures_resolved"] == 2
    assert any(rel["data_source"] == "contract_vehicle_wayback" for rel in result.relationships)
    assert any(rel["rel_type"] == "awarded_under" and rel["source_name"] == "OASIS" for rel in result.relationships)
    assert any(rel["rel_type"] == "predecessor_of" and rel["source_name"] == "IPIESS" for rel in result.relationships)
    assert any(finding.source == "contract_vehicle_wayback" for finding in result.findings)
