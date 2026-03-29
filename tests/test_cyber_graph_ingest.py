import importlib
import os
import sys

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def cyber_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XIPHOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XIPHOS_KG_DB_PATH", str(tmp_path / "knowledge_graph.db"))
    monkeypatch.setenv("XIPHOS_DB_PATH", str(tmp_path / "xiphos.db"))

    for module_name in ["runtime_paths", "entity_resolution", "knowledge_graph", "cyber_graph_ingest"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    import entity_resolution as er  # type: ignore
    import knowledge_graph as kg  # type: ignore
    import cyber_graph_ingest as cyber  # type: ignore

    kg.init_kg_db()
    return {"er": er, "kg": kg, "cyber": cyber, "kg_path": str(tmp_path / "knowledge_graph.db")}


def test_ingest_cve_findings_reuses_existing_canonical_company_node(cyber_env):
    er = cyber_env["er"]
    kg = cyber_env["kg"]
    cyber = cyber_env["cyber"]

    canonical_id = "company-canonical-001"
    kg.save_entity(
        er.ResolvedEntity(
            id=canonical_id,
            canonical_name="Cyber Product Vendor",
            entity_type="company",
            aliases=["Cyber Product Vendor LLC"],
            identifiers={},
            country="US",
            sources=["seed"],
            confidence=0.95,
            last_updated="2026-03-26T00:00:00Z",
        )
    )

    summary = cyber.ingest_cve_findings(
        "case-cyber-1",
        "Cyber Product Vendor",
        [
            {
                "title": "CVE-2026-0001 remote code execution",
                "detail": "Critical vulnerability impacting the vendor product line",
                "severity": "critical",
                "confidence": 0.99,
            }
        ],
    )

    with kg.get_kg_conn() as conn:
        row = conn.execute(
            """
            SELECT source_entity_id, target_entity_id
            FROM kg_relationships
            WHERE rel_type = 'has_vulnerability'
            """
        ).fetchone()

    assert summary["created_cves"] == 1
    assert summary["created_relationships"] == 1
    assert row["source_entity_id"] == canonical_id
    assert not row["source_entity_id"].startswith("company:")


def test_ingest_nvd_overlay_creates_resolver_canonical_company_node(cyber_env):
    er = cyber_env["er"]
    kg = cyber_env["kg"]
    cyber = cyber_env["cyber"]

    vendor_name = "Cyber Trust Vendor"
    expected_vendor_id = er.generate_entity_id(vendor_name, {})

    summary = cyber.ingest_nvd_overlay(
        "case-cyber-2",
        vendor_name,
        {
            "product_terms": ["Secure Portal"],
            "high_or_critical_cve_count": 2,
            "critical_cve_count": 1,
            "kev_flagged_cve_count": 1,
        },
    )

    with kg.get_kg_conn() as conn:
        vendor_row = conn.execute(
            "SELECT id, canonical_name, entity_type FROM kg_entities WHERE id = ?",
            (expected_vendor_id,),
        ).fetchone()
        rel_row = conn.execute(
            """
            SELECT source_entity_id, target_entity_id, rel_type
            FROM kg_relationships
            WHERE rel_type = 'uses_product'
            """
        ).fetchone()

    assert summary["created_products"] == 1
    assert summary["created_relationships"] == 1
    assert vendor_row["canonical_name"] == vendor_name
    assert vendor_row["entity_type"] == "company"
    assert rel_row["source_entity_id"] == expected_vendor_id
    assert not rel_row["source_entity_id"].startswith("company:")
    assert rel_row["rel_type"] == "uses_product"


def test_ingest_component_supply_chain_creates_typed_nodes_and_case_links(cyber_env):
    kg = cyber_env["kg"]
    cyber = cyber_env["cyber"]

    summary = cyber.ingest_component_supply_chain(
        "case-cyber-3",
        "Critical Widget Co",
        [
            {
                "component_name": "Inertial Sensor Widget",
                "subsystem_name": "Ejection Seat Control Module",
                "platform_name": "F-35",
                "owner_name": "Shenzhen Precision Holdings",
                "owner_type": "holding_company",
                "beneficial_owner_name": "PLA Strategic Systems Group",
                "beneficial_owner_type": "company",
                "country": "CN",
                "confidence": 0.93,
                "risk_level": "high",
                "evidence": "Fixture-backed ownership and subsystem placement chain",
                "data_source": "critical_subsystem_fixture",
            }
        ],
    )

    with kg.get_kg_conn() as conn:
        entities = conn.execute(
            """
            SELECT id, entity_type, canonical_name
            FROM kg_entities
            WHERE entity_type IN ('component', 'subsystem', 'holding_company')
            ORDER BY entity_type, canonical_name
            """
        ).fetchall()
        rel_types = {
            row["rel_type"]
            for row in conn.execute(
                """
                SELECT rel_type
                FROM kg_relationships
                WHERE rel_type IN (
                    'supplies_component',
                    'supplies_component_to',
                    'integrated_into',
                    'owned_by',
                    'beneficially_owned_by'
                )
                """
            ).fetchall()
        }
        linked_types = {
            row["entity_type"]
            for row in conn.execute(
                """
                SELECT e.entity_type
                FROM kg_entity_vendors ev
                JOIN kg_entities e ON e.id = ev.entity_id
                WHERE ev.vendor_id = ?
                """,
                ("case-cyber-3",),
            ).fetchall()
        }

    assert summary["created_components"] == 1
    assert summary["created_subsystems"] == 1
    assert summary["created_holding_companies"] == 1
    assert summary["linked_entities"] >= 4
    assert {row["entity_type"] for row in entities} == {"component", "holding_company", "subsystem"}
    assert {
        "supplies_component",
        "supplies_component_to",
        "integrated_into",
        "owned_by",
        "beneficially_owned_by",
    }.issubset(rel_types)
    assert {"company", "component", "subsystem", "holding_company"}.issubset(linked_types)
