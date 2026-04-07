import importlib
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from osint import EnrichmentResult, contract_opportunities_archive_fixture, contract_opportunities_public, gao_bid_protests_fixture, usaspending_vehicle_live  # noqa: E402
import vehicle_intel_support  # noqa: E402


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "vehicle_intelligence" / "public_html"
WAYBACK_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "vehicle_intelligence" / "contract_vehicle_wayback_fixture.json"
GAO_PUBLIC_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "vehicle_intelligence" / "gao_public"
LIVE_VEHICLE_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "vehicle_intelligence" / "usaspending_vehicle_live_fixture.json"


def _vendor(name: str, *, seed_metadata: dict | None = None) -> dict:
    payload = {"contract_vehicle_live_fixture_path": str(LIVE_VEHICLE_FIXTURE_PATH)}
    if seed_metadata:
        payload.update(seed_metadata)
    return {
        "id": f"support-{name.lower().replace(' ', '-')}",
        "name": name,
        "vendor_input": {
            "seed_metadata": payload,
        },
    }


def _init_graph_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos-test.db"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge-graph.db"))
    monkeypatch.delenv("XIPHOS_PG_URL", raising=False)
    monkeypatch.setenv("XIPHOS_DB_ENGINE", "sqlite")
    monkeypatch.setenv("HELIOS_DB_ENGINE", "sqlite")
    for module_name in ["db", "knowledge_graph", "vehicle_intel_support", "teaming_intelligence"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
    import knowledge_graph  # noqa: E402
    import vehicle_intel_support as reloaded_support  # noqa: E402

    knowledge_graph.init_kg_db()
    return knowledge_graph, reloaded_support


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


def test_usaspending_vehicle_live_replays_fixture_and_emits_market_relationships():
    result = usaspending_vehicle_live.enrich(
        "OASIS",
        contract_vehicle_live_fixture_path=str(LIVE_VEHICLE_FIXTURE_PATH),
        prime_contractor_name="Science Applications International Corporation",
    )

    assert result.source == "usaspending_vehicle_live"
    assert any(rel["rel_type"] == "prime_contractor_of" for rel in result.relationships)
    assert any(rel["rel_type"] == "subcontractor_of" for rel in result.relationships)
    assert any(rel["rel_type"] == "competed_on" for rel in result.relationships)
    assert any(rel["rel_type"] == "funded_by" for rel in result.relationships)
    assert result.structured_fields["observed_vendors"][0]["vendor_name"] == "Science Applications International Corporation"
    assert any(finding.title.startswith("Live award picture:") for finding in result.findings)


def test_vehicle_intel_support_builds_context_supplement():
    support = vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name="ITEAMS",
        vendor=_vendor("Amentum"),
    )

    assert support is not None
    assert support["vehicle_name"] == "ITEAMS"
    assert support["connectors_run"] == 4
    assert support["connectors_with_data"] == 4
    assert any(rel["rel_type"] == "predecessor_of" for rel in support["relationships"])
    assert any(rel["rel_type"] == "funded_by" for rel in support["relationships"])
    assert any(rel["data_source"] == "usaspending_vehicle_live" for rel in support["relationships"])
    assert any(event["connector"] == "gao_bid_protests_fixture" for event in support["events"])
    assert any("Protester:" in event["assessment"] for event in support["events"])
    assert any(finding["source"] == "contract_opportunities_archive_fixture" for finding in support["findings"])
    assert any(finding["source"] == "contract_opportunities_public" for finding in support["findings"])
    assert any(finding["source"] == "usaspending_vehicle_live" for finding in support["findings"])
    assert any(row["vendor_name"] == "Amentum Services, Inc." for row in support["observed_vendors"])


def test_vehicle_intel_support_uses_catalog_defaults_for_leia():
    support = vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name="LEIA",
        vendor=_vendor("SMX"),
    )

    assert support is not None
    assert support["vehicle_name"] == "LEIA"
    assert support["connectors_run"] == 4
    assert support["connectors_with_data"] == 3
    assert any(rel["rel_type"] == "awarded_under" for rel in support["relationships"])
    assert any(rel["data_source"] == "contract_opportunities_public" for rel in support["relationships"])
    assert any(finding["source"] == "contract_opportunities_archive_fixture" for finding in support["findings"])
    assert any(finding["source"] == "usaspending_vehicle_live" for finding in support["findings"])
    assert any(rel["rel_type"] == "competed_on" for rel in support["relationships"])


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
        vendor=_vendor(vehicle_name),
    )

    assert support is not None
    assert support["vehicle_name"] == vehicle_name
    assert support["connectors_run"] == 4
    assert support["connectors_with_data"] == 2
    assert any(rel["rel_type"] == "predecessor_of" for rel in support["relationships"])
    assert any(expected_customer in rel.get("evidence", "") for rel in support["relationships"] if rel["rel_type"] == "funded_by")
    assert any(finding["source"] == "contract_opportunities_public" for finding in support["findings"])
    assert any(finding["source"] == "usaspending_vehicle_live" for finding in support["findings"])


def test_vehicle_intel_support_live_collector_supports_non_seeded_vehicle():
    support = vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name="OASIS",
        vendor=_vendor("Science Applications International Corporation"),
    )

    assert support is not None
    assert support["vehicle_name"] == "OASIS"
    assert support["connectors_run"] == 3
    assert support["connectors_with_data"] == 1
    assert any(rel["rel_type"] == "prime_contractor_of" for rel in support["relationships"])
    assert any(rel["rel_type"] == "competed_on" for rel in support["relationships"])
    assert any(rel["rel_type"] == "funded_by" for rel in support["relationships"])
    assert any(finding["source"] == "usaspending_vehicle_live" for finding in support["findings"])
    assert any(row["vendor_name"] == "Science Applications International Corporation" for row in support["observed_vendors"])


def test_vehicle_intel_support_market_scope_stays_on_live_vehicle_collector_only():
    support = vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name="OASIS",
        vendor=_vendor("Science Applications International Corporation"),
        support_scope="market",
    )

    assert support is not None
    assert support["vehicle_name"] == "OASIS"
    assert support["support_scope"] == "market"
    assert support["connectors_run"] == 1
    assert support["connectors_with_data"] == 1
    assert all(rel["data_source"] == "usaspending_vehicle_live" for rel in support["relationships"])
    assert all(finding["source"] == "usaspending_vehicle_live" for finding in support["findings"])
    assert any(row["vendor_name"] == "Science Applications International Corporation" for row in support["observed_vendors"])


def test_vehicle_intel_support_syncs_official_relationships_without_duplicates(tmp_path, monkeypatch):
    knowledge_graph, support_module = _init_graph_runtime(tmp_path, monkeypatch)

    support = support_module.build_vehicle_intelligence_support(
        vehicle_name="OASIS",
        vendor=_vendor("Science Applications International Corporation"),
        sync_graph=True,
        support_scope="market",
    )

    assert support is not None
    graph_sync = support["graph_sync"]
    assert graph_sync["enabled"] is True
    assert graph_sync["relationship_count"] > 0
    assert graph_sync["syncable_relationship_count"] >= graph_sync["relationship_count"]

    with knowledge_graph.get_kg_conn() as conn:
        first_count = conn.execute("SELECT COUNT(*) FROM kg_relationships").fetchone()[0]

    repeat = support_module.build_vehicle_intelligence_support(
        vehicle_name="OASIS",
        vendor=_vendor("Science Applications International Corporation"),
        sync_graph=True,
        support_scope="market",
    )

    assert repeat["graph_sync"]["relationship_count"] == 0
    assert repeat["graph_sync"]["reused_relationship_count"] == graph_sync["syncable_relationship_count"]
    with knowledge_graph.get_kg_conn() as conn:
        second_count = conn.execute("SELECT COUNT(*) FROM kg_relationships").fetchone()[0]
    assert second_count == first_count


def test_vehicle_intel_support_caches_identical_support_bundle(monkeypatch):
    vehicle_intel_support.clear_vehicle_intelligence_support_cache()
    calls = {"archive": 0, "gao": 0, "live": 0, "sync": 0}

    def fake_archive(vehicle_name):
        calls["archive"] += 1
        return EnrichmentResult(source="contract_opportunities_archive_fixture", vendor_name=vehicle_name)

    def fake_gao(vehicle_name):
        calls["gao"] += 1
        return EnrichmentResult(source="gao_bid_protests_fixture", vendor_name=vehicle_name)

    def fake_live(vehicle_name, **ids):
        calls["live"] += 1
        result = EnrichmentResult(
            source="usaspending_vehicle_live",
            vendor_name=vehicle_name,
            structured_fields={
                "observed_vendors": [
                    {
                        "vendor_name": "Science Applications International Corporation",
                        "role": "prime",
                        "award_amount": 188000000,
                    }
                ]
            },
        )
        result.findings = []
        result.relationships = [
            {
                "rel_type": "prime_contractor_of",
                "source_name": "Science Applications International Corporation",
                "target_name": vehicle_name,
                "data_source": "usaspending_vehicle_live",
                "authority_level": "official_program_system",
                "source_class": "public_connector",
                "access_model": "public_api",
                "confidence": 0.8,
                "evidence": "Observed prime relationship.",
                "evidence_summary": "Observed prime relationship.",
                "source_urls": ["https://www.usaspending.gov/search/"],
            }
        ]
        return result

    def fake_sync(*, vehicle_name, support_bundle):
        calls["sync"] += 1
        return {
            "enabled": True,
            "relationship_count": len(support_bundle.get("relationships") or []),
            "reused_relationship_count": 0,
            "syncable_relationship_count": len(support_bundle.get("relationships") or []),
        }

    monkeypatch.setattr(vehicle_intel_support, "archive_fixture_enrich", fake_archive)
    monkeypatch.setattr(vehicle_intel_support, "gao_fixture_enrich", fake_gao)
    monkeypatch.setattr(vehicle_intel_support, "usaspending_vehicle_live_enrich", fake_live)
    monkeypatch.setattr(vehicle_intel_support, "sync_vehicle_support_graph", fake_sync)

    first = vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name="OASIS",
        vendor=_vendor("Science Applications International Corporation"),
        sync_graph=True,
        support_scope="market",
    )
    second = vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name="OASIS",
        vendor=_vendor("Science Applications International Corporation"),
        sync_graph=True,
        support_scope="market",
    )

    assert first["observed_vendors"][0]["vendor_name"] == "Science Applications International Corporation"
    assert second["graph_sync"]["relationship_count"] == 0
    assert second["graph_sync"]["reused_relationship_count"] == 1
    assert second["graph_sync"]["cached"] is True
    assert calls == {"archive": 0, "gao": 0, "live": 1, "sync": 1}


def test_vehicle_intel_support_includes_public_html_vehicle_connector_when_seeded():
    support = vehicle_intel_support.build_vehicle_intelligence_support(
        vehicle_name="ITEAMS",
        vendor={
            "id": "case-1",
            "name": "Amentum",
            "vendor_input": {
                "seed_metadata": {
                    "contract_vehicle_live_fixture_path": str(LIVE_VEHICLE_FIXTURE_PATH),
                    "contract_vehicle_public_html_fixture_pages": [
                        str(FIXTURE_DIR / "iteams_lineage_snapshot.html"),
                        str(FIXTURE_DIR / "iteams_archive_notice.html"),
                    ]
                }
            },
        },
    )

    assert support is not None
    assert support["connectors_run"] == 5
    assert support["connectors_with_data"] == 5
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
                    "contract_vehicle_live_fixture_path": str(LIVE_VEHICLE_FIXTURE_PATH),
                    "contract_vehicle_archive_seed_urls": ["https://sam.gov/opportunity/ITEAMS"],
                    "contract_vehicle_wayback_fixture_path": str(WAYBACK_FIXTURE_PATH),
                }
            },
        },
    )

    assert support is not None
    assert support["connectors_run"] == 5
    assert support["connectors_with_data"] == 5
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
                    "contract_vehicle_live_fixture_path": str(LIVE_VEHICLE_FIXTURE_PATH),
                    "gao_public_html_fixture_pages": [
                        str(GAO_PUBLIC_FIXTURE_DIR / "gao_docket_iteams_fixture.html"),
                        str(GAO_PUBLIC_FIXTURE_DIR / "gao_decision_iteams_fixture.html"),
                    ]
                }
            },
        },
    )

    assert support is not None
    assert support["connectors_run"] == 5
    assert support["connectors_with_data"] == 5
    assert any(event["connector"] == "gao_bid_protests_public" for event in support["events"])
    assert any(finding["source"] == "gao_bid_protests_public" for finding in support["findings"])
