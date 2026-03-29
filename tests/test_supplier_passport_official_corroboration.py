from __future__ import annotations

import os
import sys
import importlib


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

supplier_passport = importlib.import_module("supplier_passport")


def test_official_corroboration_counts_uk_and_canada_registry_fields():
    identifier_status = {
        "uk_company_number": {
            "state": "verified_present",
            "value": "12345678",
            "authority_level": "official_registry",
            "verification_tier": "verified",
        },
        "ca_corporation_number": {
            "state": "verified_present",
            "value": "7654321",
            "authority_level": "official_registry",
            "verification_tier": "verified",
        },
        "website": {
            "state": "verified_present",
            "value": "https://example.ca",
            "authority_level": "first_party_self_disclosed",
            "verification_tier": "publicly_disclosed",
        },
    }
    enrichment = {
        "connector_status": {
            "uk_companies_house": {"authority_level": "official_registry", "has_data": True},
            "corporations_canada": {"authority_level": "official_registry", "has_data": True},
        }
    }

    summary = supplier_passport._official_corroboration_summary(identifier_status, enrichment)

    assert summary["coverage_level"] == "strong"
    assert summary["core_official_identifier_count"] == 2
    assert set(summary["core_official_identifiers_verified"]) == {
        "uk_company_number",
        "ca_corporation_number",
    }


def test_official_corroboration_counts_australia_registry_fields():
    identifier_status = {
        "abn": {
            "state": "verified_present",
            "value": "53123456789",
            "authority_level": "official_registry",
            "verification_tier": "verified",
        },
        "acn": {
            "state": "verified_present",
            "value": "123456789",
            "authority_level": "official_registry",
            "verification_tier": "verified",
        },
    }
    enrichment = {
        "connector_status": {
            "australia_abn_asic": {"authority_level": "official_registry", "has_data": True},
        }
    }

    summary = supplier_passport._official_corroboration_summary(identifier_status, enrichment)

    assert summary["coverage_level"] == "strong"
    assert summary["core_official_identifier_count"] == 2
    assert set(summary["core_official_identifiers_verified"]) == {"abn", "acn"}


def test_official_corroboration_counts_new_zealand_registry_fields():
    identifier_status = {
        "nzbn": {
            "state": "verified_present",
            "value": "9429041234567",
            "authority_level": "official_registry",
            "verification_tier": "verified",
        },
        "nz_company_number": {
            "state": "verified_present",
            "value": "9182736",
            "authority_level": "official_registry",
            "verification_tier": "verified",
        },
    }
    enrichment = {
        "connector_status": {
            "new_zealand_companies_office": {"authority_level": "official_registry", "has_data": True},
        }
    }

    summary = supplier_passport._official_corroboration_summary(identifier_status, enrichment)

    assert summary["coverage_level"] == "strong"
    assert summary["core_official_identifier_count"] == 2
    assert set(summary["core_official_identifiers_verified"]) == {"nzbn", "nz_company_number"}


def test_official_corroboration_counts_singapore_registry_fields():
    identifier_status = {
        "uen": {
            "state": "verified_present",
            "value": "201234567N",
            "authority_level": "official_registry",
            "verification_tier": "verified",
        },
        "website": {
            "state": "verified_present",
            "value": "https://example.sg",
            "authority_level": "first_party_self_disclosed",
            "verification_tier": "publicly_disclosed",
        },
    }
    enrichment = {
        "connector_status": {
            "singapore_acra": {"authority_level": "official_registry", "has_data": True},
        }
    }

    summary = supplier_passport._official_corroboration_summary(identifier_status, enrichment)

    assert summary["coverage_level"] == "partial"
    assert summary["core_official_identifier_count"] == 1
    assert set(summary["core_official_identifiers_verified"]) == {"uen"}
    assert summary["relevant_official_connector_count"] == 1


def test_official_corroboration_ignores_irrelevant_blocked_foreign_registries():
    identifier_status = {
        "cage": {
            "state": "verified_present",
            "value": "0EA28",
            "authority_level": "official_registry",
            "verification_tier": "verified",
        },
        "uei": {
            "state": "verified_present",
            "value": "V1HATBT1N7V5",
            "authority_level": "official_registry",
            "verification_tier": "verified",
        },
        "website": {
            "state": "verified_present",
            "value": "https://berryaviation.com",
            "authority_level": "first_party_self_disclosed",
            "verification_tier": "publicly_disclosed",
        },
        "legal_jurisdiction": {
            "state": "verified_present",
            "value": "US-TX",
            "authority_level": "third_party_public",
            "verification_tier": "publicly_captured",
        },
    }
    enrichment = {
        "connector_status": {
            "sam_gov": {"authority_level": "official_registry", "has_data": True},
            "sec_edgar": {"authority_level": "official_regulatory", "has_data": False, "error": "no filing match"},
            "corporations_canada": {"authority_level": "official_registry", "has_data": False, "error": "timeout"},
            "australia_abn_asic": {"authority_level": "official_registry", "has_data": False, "error": "timeout"},
            "singapore_acra": {"authority_level": "official_registry", "has_data": False, "error": "timeout"},
            "new_zealand_companies_office": {"authority_level": "official_registry", "has_data": False, "error": "timeout"},
            "uk_companies_house": {"authority_level": "official_registry", "has_data": False, "error": "timeout"},
        }
    }
    vendor = {"country": "US"}

    summary = supplier_passport._official_corroboration_summary(identifier_status, enrichment, vendor=vendor)

    assert summary["coverage_level"] == "strong"
    assert summary["blocked_connector_count"] == 0
    assert summary["relevant_official_connector_count"] == 1
    assert [item["source"] for item in summary["relevant_connectors"]] == ["sam_gov"]


def test_official_corroboration_counts_norway_registry_field():
    identifier_status = {
        "norway_org_number": {
            "state": "verified_present",
            "value": "982574145",
            "authority_level": "official_registry",
            "verification_tier": "verified",
        },
        "website": {
            "state": "verified_present",
            "value": "https://kongsberg.com",
            "authority_level": "first_party_self_disclosed",
            "verification_tier": "publicly_disclosed",
        },
    }
    enrichment = {
        "connector_status": {
            "norway_brreg": {"authority_level": "official_registry", "has_data": True},
        }
    }

    summary = supplier_passport._official_corroboration_summary(identifier_status, enrichment, vendor={"country": "NO"})

    assert summary["coverage_level"] == "partial"
    assert summary["core_official_identifier_count"] == 1
    assert set(summary["core_official_identifiers_verified"]) == {"norway_org_number"}
    assert summary["relevant_official_connector_count"] == 1


def test_official_corroboration_counts_france_registry_field_and_marks_gated_access():
    identifier_status = {
        "fr_siren": {
            "state": "verified_present",
            "value": "552100554",
            "authority_level": "official_registry",
            "verification_tier": "verified",
        },
        "website": {
            "state": "verified_present",
            "value": "https://hexagone-mission.example.fr",
            "authority_level": "first_party_self_disclosed",
            "verification_tier": "publicly_disclosed",
        },
    }
    enrichment = {
        "connector_status": {
            "france_inpi_rne": {"authority_level": "official_registry", "access_model": "gated_api", "has_data": True},
        }
    }

    summary = supplier_passport._official_corroboration_summary(identifier_status, enrichment, vendor={"country": "FR"})

    assert summary["coverage_level"] == "partial"
    assert summary["core_official_identifier_count"] == 1
    assert set(summary["core_official_identifiers_verified"]) == {"fr_siren"}
    assert summary["gated_connector_count"] == 1
    assert [item["source"] for item in summary["gated_connectors"]] == ["france_inpi_rne"]
