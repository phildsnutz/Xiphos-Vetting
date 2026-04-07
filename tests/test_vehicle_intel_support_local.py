import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from osint import contract_opportunities_archive_fixture, contract_opportunities_public, gao_bid_protests_fixture  # noqa: E402
import vehicle_intel_support  # noqa: E402


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "vehicle_intelligence" / "public_html"
WAYBACK_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "vehicle_intelligence" / "contract_vehicle_wayback_fixture.json"
GAO_PUBLIC_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "vehicle_intelligence" / "gao_public"


def test_contract_opportunities_archive_fixture_returns_lineage_relationships():
    result = contract_opportunities_archive_fixture.enrich("ITEAMS")

    assert result.source == "contract_opportunities_archive_fixture"
    assert len(result.relationships) >= 6
    assert any(rel["rel_type"] == "awarded_under" for rel in result.relationships)
    assert any(rel["rel_type"] == "funded_by" for rel in result.relationships)
    assert any(finding.title.startswith("Archived lineage trail") for finding in result.findings)
    assert len(result.findings) >= 3


def test_gao_bid_protests_fixture_returns_protest_findings():
    result = gao_bid_protests_fixture.enrich("ITEAMS")

    assert result.source == "gao_bid_protests_fixture"
    assert len(result.findings) == 3
    assert all(finding.category == "bid_protest" for finding in result.findings)
    assert any(finding.raw_data["status"] == "dismissed" for finding in result.findings)
    assert any(finding.raw_data["status"] == "corrective_action" for finding in result.findings)


def test_contract_opportunities_public_reads_seeded_notice_pages():
    result = contract_opportunities_public.enrich(
        "ITEAMS",
        contract_opportunity_notice_fixture_pages=[str(FIXTURE_DIR / "iteams_notice_live_fixture.html")],
    )

    assert result.source == "contract_opportunities_public"
    assert any(rel["rel_type"] == "awarded_under" for rel in result.relationships)
    assert any(rel["rel_type"] == "funded_by" for rel in result.relationships)
    assert any(rel["rel_type"] == "performed_at" for rel in result.relationships)
    assert any(finding.source == "contract_opportunities_public" for finding in result.findings)


def test_vehicle_intel_support_builds_context_supplement():
    support = vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name="ITEAMS",
        vendor={"id": "case-1", "name": "Amentum", "vendor_input": {}},
    )

    assert support is not None
    assert support["vehicle_name"] == "ITEAMS"
    assert support["connectors_run"] == 3
    assert support["connectors_with_data"] == 3
    assert any(rel["rel_type"] == "predecessor_of" for rel in support["relationships"])
    assert any(rel["rel_type"] == "funded_by" for rel in support["relationships"])
    assert any(event["connector"] == "gao_bid_protests_fixture" for event in support["events"])
    assert any("Protester:" in event["assessment"] for event in support["events"])
    assert any(finding["source"] == "contract_opportunities_archive_fixture" for finding in support["findings"])
    assert any(finding["source"] == "contract_opportunities_public" for finding in support["findings"])


def test_vehicle_intel_support_uses_catalog_defaults_for_leia():
    support = vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name="LEIA",
        vendor={"id": "case-2", "name": "SMX", "vendor_input": {}},
    )

    assert support is not None
    assert support["vehicle_name"] == "LEIA"
    assert support["connectors_run"] == 3
    assert support["connectors_with_data"] == 2
    assert any(rel["rel_type"] == "awarded_under" for rel in support["relationships"])
    assert any(rel["data_source"] == "contract_opportunities_public" for rel in support["relationships"])
    assert any(finding["source"] == "contract_opportunities_archive_fixture" for finding in support["findings"])


@pytest.mark.parametrize(
    ("vehicle_name", "expected_customer"),
    [
        ("SEWP", "NASA SEWP Program Office"),
        ("CIO-SP4", "NIH Information Technology Acquisition and Assessment Center"),
        ("Alliant 2", "GSA Federal Acquisition Service"),
        ("VETS 2", "GSA Federal Acquisition Service"),
    ],
)
def test_vehicle_intel_support_uses_catalog_defaults_for_broader_seeded_vehicle_set(vehicle_name, expected_customer):
    support = vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name=vehicle_name,
        vendor={"id": f"support-{vehicle_name.lower()}", "name": vehicle_name, "vendor_input": {}},
    )

    assert support is not None
    assert support["vehicle_name"] == vehicle_name
    assert support["connectors_run"] == 3
    assert support["connectors_with_data"] == 1
    assert any(rel["rel_type"] == "predecessor_of" for rel in support["relationships"])
    assert any(expected_customer in rel.get("evidence", "") for rel in support["relationships"] if rel["rel_type"] == "funded_by")
    assert any(finding["source"] == "contract_opportunities_public" for finding in support["findings"])


def test_vehicle_intel_support_includes_public_html_vehicle_connector_when_seeded():
    support = vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name="ITEAMS",
        vendor={
            "id": "case-1",
            "name": "Amentum",
            "vendor_input": {
                "seed_metadata": {
                    "contract_vehicle_public_html_fixture_pages": [
                        str(FIXTURE_DIR / "iteams_lineage_snapshot.html"),
                        str(FIXTURE_DIR / "iteams_archive_notice.html"),
                    ]
                }
            },
        },
    )

    assert support is not None
    assert support["connectors_run"] == 4
    assert support["connectors_with_data"] == 4
    assert any(rel["data_source"] == "public_html_contract_vehicle" for rel in support["relationships"])
    assert any(finding["source"] == "public_html_contract_vehicle" for finding in support["findings"])


def test_vehicle_intel_support_includes_wayback_vehicle_connector_when_seeded():
    support = vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name="ITEAMS",
        vendor={
            "id": "case-1",
            "name": "Amentum",
            "vendor_input": {
                "seed_metadata": {
                    "contract_vehicle_archive_seed_urls": ["https://sam.gov/opportunity/ITEAMS"],
                    "contract_vehicle_wayback_fixture_path": str(WAYBACK_FIXTURE_PATH),
                }
            },
        },
    )

    assert support is not None
    assert support["connectors_run"] == 4
    assert support["connectors_with_data"] == 4
    assert any(rel["data_source"] == "contract_vehicle_wayback" for rel in support["relationships"])
    assert any(finding["source"] == "contract_vehicle_wayback" for finding in support["findings"])


def test_vehicle_intel_support_includes_gao_public_connector_when_seeded():
    support = vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name="ITEAMS",
        vendor={
            "id": "case-1",
            "name": "Amentum",
            "vendor_input": {
                "seed_metadata": {
                    "gao_public_html_fixture_pages": [
                        str(GAO_PUBLIC_FIXTURE_DIR / "gao_docket_iteams_fixture.html"),
                        str(GAO_PUBLIC_FIXTURE_DIR / "gao_decision_iteams_fixture.html"),
                    ]
                }
            },
        },
    )

    assert support is not None
    assert support["connectors_run"] == 4
    assert support["connectors_with_data"] == 4
    assert any(event["connector"] == "gao_bid_protests_public" for event in support["events"])
    assert any(finding["source"] == "gao_bid_protests_public" for finding in support["findings"])
