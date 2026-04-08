import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from osint import EnrichmentResult, Finding  # type: ignore  # noqa: E402
import vendor_ownership_support  # type: ignore  # noqa: E402


def test_vendor_ownership_support_builds_bundle_and_merges_into_enrichment(monkeypatch):
    vendor_ownership_support.clear_vendor_ownership_support_cache()

    def fake_gleif(vendor_name, country="", **ids):
        result = EnrichmentResult(
            source="gleif_lei",
            vendor_name=vendor_name,
            source_class="public_connector",
            authority_level="official_registry",
            access_model="public_api",
        )
        result.identifiers["lei"] = "549300ABC123XYZ78901"
        result.findings.append(
            Finding(
                source="gleif_lei",
                category="ownership",
                title="Ultimate parent: Horizon Holdings",
                detail="LEI: 549300PARENT000000001",
                severity="info",
                confidence=0.91,
                source_class="public_connector",
                authority_level="official_registry",
                access_model="public_api",
            )
        )
        result.relationships.append(
            {
                "type": "beneficially_owned_by",
                "source_entity": vendor_name,
                "source_entity_type": "company",
                "source_identifiers": {"lei": "549300ABC123XYZ78901"},
                "target_entity": "Horizon Holdings",
                "target_entity_type": "holding_company",
                "target_identifiers": {"lei": "549300PARENT000000001"},
                "country": "US",
                "data_source": "gleif_lei",
                "confidence": 0.91,
                "evidence": "GLEIF Level 2 ultimate parent relationship",
                "artifact_ref": "gleif://549300ABC123XYZ78901/ultimate_parent/549300PARENT000000001",
                "source_class": "public_connector",
                "authority_level": "official_registry",
                "access_model": "public_api",
            }
        )
        return result

    def fake_empty(vendor_name, country="", **ids):
        return EnrichmentResult(source="empty", vendor_name=vendor_name)

    monkeypatch.setattr(vendor_ownership_support, "gleif_lei_enrich", fake_gleif)
    monkeypatch.setattr(vendor_ownership_support, "openownership_bods_public_enrich", fake_empty)
    monkeypatch.setattr(vendor_ownership_support, "norway_brreg_enrich", fake_empty)
    monkeypatch.setattr(vendor_ownership_support, "france_inpi_rne_enrich", fake_empty)
    monkeypatch.setattr(vendor_ownership_support, "public_html_ownership_enrich", fake_empty)

    bundle = vendor_ownership_support.build_vendor_ownership_support(
        vendor_id="v-own",
        vendor={"id": "v-own", "name": "Horizon Mission Systems LLC", "country": "US", "vendor_input": {"ownership": {}}},
        enrichment={"identifiers": {"lei": "549300ABC123XYZ78901"}, "summary": {}},
        sync_graph=False,
    )

    assert bundle is not None
    assert bundle["connectors_run"] >= 1
    assert bundle["connectors_with_data"] == 1
    assert bundle["oci_summary"]["controlling_parent_known"] is True
    assert bundle["oci_summary"]["controlling_parent"] == "Horizon Holdings"
    assert any("Controlling parent" in line or "parent path" in line for line in bundle["control_lines"])
    assert bundle["metrics"]["official_connectors_with_data"] == 1

    merged = vendor_ownership_support.merge_enrichment_with_ownership_support(
        {"identifiers": {}, "findings": [], "relationships": [], "summary": {}},
        bundle,
    )
    assert merged["identifiers"]["lei"] == "549300ABC123XYZ78901"
    assert merged["summary"]["connectors_with_data"] == 1
    assert len(merged["findings"]) == 1
    assert len(merged["relationships"]) == 1
