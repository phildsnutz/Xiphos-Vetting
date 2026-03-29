import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fgamlogit import DataQuality, DoDContext, ExecProfile, OwnershipProfile, VendorInputV5
from osint_scoring import augment_from_enrichment


def _base_vendor() -> VendorInputV5:
    return VendorInputV5(
        name="Example Vendor",
        country="US",
        ownership=OwnershipProfile(
            publicly_traded=False,
            state_owned=False,
            beneficial_owner_known=False,
            ownership_pct_resolved=0.0,
            shell_layers=0,
            pep_connection=False,
            foreign_ownership_pct=0.0,
            foreign_ownership_is_allied=True,
        ),
        data_quality=DataQuality(
            has_lei=False,
            has_cage=False,
            has_duns=False,
            has_tax_id=False,
            has_audited_financials=False,
            years_of_records=0,
        ),
        exec_profile=ExecProfile(
            known_execs=0,
            adverse_media=0,
            pep_execs=0,
            litigation_history=0,
        ),
        dod=DoDContext(),
    )


def test_osint_scoring_ignores_low_confidence_cik_for_public_company_upgrade():
    enrichment = {
        "identifiers": {
            "cik": "1234567",
            "cik_confidence": "low",
        },
        "findings": [],
        "relationships": [],
        "risk_signals": [],
    }

    augmented = augment_from_enrichment(_base_vendor(), enrichment)

    assert augmented.vendor_input.ownership.publicly_traded is False
    assert augmented.vendor_input.ownership.beneficial_owner_known is False


def test_osint_scoring_public_market_signal_does_not_claim_control_resolution():
    enrichment = {
        "identifiers": {
            "ticker": "BA",
            "cik": "12927",
            "cik_confidence": "high",
        },
        "findings": [],
        "relationships": [],
        "risk_signals": [],
    }

    augmented = augment_from_enrichment(_base_vendor(), enrichment)

    assert augmented.vendor_input.ownership.publicly_traded is True
    assert augmented.vendor_input.data_quality.has_audited_financials is True
    assert augmented.vendor_input.ownership.beneficial_owner_known is False
    assert augmented.vendor_input.ownership.ownership_pct_resolved <= 0.45


def test_osint_scoring_clears_stale_public_company_state_without_current_signal():
    base = _base_vendor()
    base.ownership.publicly_traded = True
    base.ownership.beneficial_owner_known = True
    base.ownership.ownership_pct_resolved = 0.9

    enrichment = {
        "identifiers": {},
        "findings": [],
        "relationships": [],
        "risk_signals": [],
    }

    augmented = augment_from_enrichment(base, enrichment)

    assert augmented.vendor_input.ownership.publicly_traded is False
    assert augmented.vendor_input.ownership.beneficial_owner_known is False
    assert augmented.vendor_input.ownership.ownership_pct_resolved <= 0.35


def test_osint_scoring_lei_does_not_claim_control_resolution_without_owner_path():
    enrichment = {
        "identifiers": {
            "lei": "549300DV5B5ZO815U462",
        },
        "findings": [],
        "relationships": [],
        "risk_signals": [],
    }

    augmented = augment_from_enrichment(_base_vendor(), enrichment)

    assert augmented.vendor_input.data_quality.has_lei is True
    assert augmented.vendor_input.ownership.beneficial_owner_known is False
    assert augmented.vendor_input.ownership.ownership_pct_resolved <= 0.30


def test_osint_scoring_uses_owned_by_relationships_to_resolve_ownership():
    enrichment = {
        "identifiers": {},
        "findings": [],
        "relationships": [
            {
                "type": "owned_by",
                "source_entity": "Example Vendor",
                "target_entity": "Acorn Growth",
            }
        ],
        "risk_signals": [],
    }

    augmented = augment_from_enrichment(_base_vendor(), enrichment)

    assert augmented.vendor_input.ownership.publicly_traded is False
    assert augmented.vendor_input.ownership.beneficial_owner_known is True
    assert augmented.vendor_input.ownership.ownership_pct_resolved >= 0.65


def test_osint_scoring_uses_first_party_beneficial_owner_descriptor_to_partially_resolve_ownership():
    enrichment = {
        "identifiers": {},
        "findings": [
            {
                "source": "public_html_ownership",
                "category": "ownership",
                "title": "Public site beneficial ownership descriptor: Service-Disabled Veteran",
                "detail": "Yorktown Systems Group, Inc., owned by a Service-Disabled Veteran.",
                "severity": "info",
                "confidence": 0.78,
                "structured_fields": {
                    "ownership_descriptor": "Service-Disabled Veteran",
                    "ownership_descriptor_scope": "self_disclosed_owner_descriptor",
                },
            }
        ],
        "relationships": [],
        "risk_signals": [],
    }

    augmented = augment_from_enrichment(_base_vendor(), enrichment)

    assert augmented.vendor_input.ownership.beneficial_owner_known is False
    assert augmented.vendor_input.ownership.named_beneficial_owner_known is False
    assert augmented.vendor_input.ownership.owner_class_known is True
    assert augmented.vendor_input.ownership.owner_class == "Service-Disabled Veteran"
    assert augmented.vendor_input.ownership.ownership_pct_resolved >= 0.55
    assert augmented.vendor_input.ownership.control_resolution_pct >= 0.35


def test_osint_scoring_does_not_treat_third_party_public_owned_by_as_named_beneficial_owner():
    enrichment = {
        "identifiers": {},
        "findings": [],
        "relationships": [
            {
                "type": "owned_by",
                "source_entity": "Yorktown Systems Group",
                "target_entity": "Yorktown Funds",
                "access_model": "search_public_html",
                "authority_level": "third_party_public",
                "confidence": 0.72,
                "data_source": "public_search_ownership",
            }
        ],
        "risk_signals": [],
    }

    augmented = augment_from_enrichment(_base_vendor(), enrichment)

    assert augmented.vendor_input.ownership.beneficial_owner_known is False
    assert augmented.vendor_input.ownership.named_beneficial_owner_known is False
    assert augmented.vendor_input.ownership.owner_class_known is False
    assert augmented.vendor_input.ownership.ownership_pct_resolved == 0.0


def test_osint_scoring_does_not_resolve_ownership_from_low_confidence_search_snippet():
    enrichment = {
        "identifiers": {},
        "findings": [],
        "relationships": [
            {
                "type": "owned_by",
                "source_entity": "Yorktown Systems Group",
                "target_entity": "Offset Systems Group (OSG) JV executive management team",
                "access_model": "search_snippet_only",
                "confidence": 0.56,
                "data_source": "public_search_ownership",
            }
        ],
        "risk_signals": [],
    }

    augmented = augment_from_enrichment(_base_vendor(), enrichment)

    assert augmented.vendor_input.ownership.beneficial_owner_known is False
    assert augmented.vendor_input.ownership.named_beneficial_owner_known is False
    assert augmented.vendor_input.ownership.owner_class_known is False
    assert augmented.vendor_input.ownership.ownership_pct_resolved == 0.0


def test_osint_scoring_keeps_lei_and_owned_by_without_public_company_flag():
    base = _base_vendor()
    base.ownership.publicly_traded = True
    base.ownership.beneficial_owner_known = True
    base.ownership.ownership_pct_resolved = 0.9

    enrichment = {
        "identifiers": {
            "lei": "549300DV5B5ZO815U462",
        },
        "findings": [],
        "relationships": [
            {
                "type": "owned_by",
                "source_entity": "Example Vendor",
                "target_entity": "Bristow Group",
            }
        ],
        "risk_signals": [],
    }

    augmented = augment_from_enrichment(base, enrichment)

    assert augmented.vendor_input.data_quality.has_lei is True
    assert augmented.vendor_input.ownership.publicly_traded is False
    assert augmented.vendor_input.ownership.beneficial_owner_known is True
    assert augmented.vendor_input.ownership.ownership_pct_resolved >= 0.65
    assert augmented.vendor_input.ownership.ownership_pct_resolved < 0.75


def test_osint_scoring_does_not_treat_cage_and_uei_as_ownership_resolution():
    enrichment = {
        "identifiers": {
            "cage": "4VJW9",
            "uei": "L5LMQSN59YE5",
        },
        "findings": [],
        "relationships": [],
        "risk_signals": [],
    }

    augmented = augment_from_enrichment(_base_vendor(), enrichment)

    assert augmented.vendor_input.data_quality.has_cage is True
    assert augmented.vendor_input.data_quality.has_duns is True
    assert augmented.vendor_input.ownership.beneficial_owner_known is False
    assert augmented.vendor_input.ownership.ownership_pct_resolved == 0.0


def test_osint_scoring_uses_founded_year_from_first_party_profile_hint():
    enrichment = {
        "identifiers": {
            "founded_year": "2008",
        },
        "findings": [],
        "relationships": [],
        "risk_signals": [],
    }

    augmented = augment_from_enrichment(_base_vendor(), enrichment)

    assert augmented.vendor_input.data_quality.years_of_records >= 15


def test_osint_scoring_extracts_named_executive_from_public_reporting():
    enrichment = {
        "identifiers": {},
        "findings": [
            {
                "source": "google_news",
                "category": "adverse_media",
                "title": "Women at the top: Yorktown promotes Suzanne Mathew to president",
                "detail": "Business Alabama reports Yorktown promotes Suzanne Mathew to president.",
            }
        ],
        "relationships": [],
        "risk_signals": [],
    }

    augmented = augment_from_enrichment(_base_vendor(), enrichment)

    assert augmented.vendor_input.exec_profile.known_execs >= 1
