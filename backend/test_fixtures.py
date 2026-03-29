"""
Standardized vendor profiles for Helios test suites.

Provides pre-built VendorInputV5 objects representing common archetypes
encountered in defense and commercial vendor vetting. Import these into
any test file to avoid duplicating setup boilerplate.

Usage:
    from test_fixtures import CLEAN_US_PRIME, ADVERSARY_SOE, ...

Each fixture is a callable that returns a FRESH VendorInputV5 instance
(so tests can mutate without cross-contamination).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("XIPHOS_SCREENING_FALLBACK", "1")

from fgamlogit import (
    OwnershipProfile, DataQuality, ExecProfile, DoDContext, VendorInputV5,
)


# ============================================================================
# ARCHETYPE FACTORIES
# ============================================================================

def clean_us_prime() -> VendorInputV5:
    """Tier 0 US prime contractor. Publicly traded, full docs, clean execs.
    Expected: TIER_4, APPROVED, probability < 10%."""
    return VendorInputV5(
        name="Northstar Defense Systems Inc",
        country="US",
        ownership=OwnershipProfile(
            publicly_traded=True,
            beneficial_owner_known=True,
            ownership_pct_resolved=1.0,
        ),
        data_quality=DataQuality(
            has_lei=True, has_cage=True, has_duns=True,
            has_tax_id=True, has_audited_financials=True,
            years_of_records=25,
        ),
        exec_profile=ExecProfile(known_execs=12),
        dod=DoDContext(
            sensitivity="ELEVATED",
            supply_chain_tier=0,
        ),
    )


def allied_conditional() -> VendorInputV5:
    """UK-based Tier 1 subsystem vendor. Allied but some data gaps.
    Expected: TIER_3_CONDITIONAL, moderate probability."""
    return VendorInputV5(
        name="Meridian Avionics Ltd",
        country="GB",
        ownership=OwnershipProfile(
            publicly_traded=False,
            beneficial_owner_known=True,
            ownership_pct_resolved=0.85,
            foreign_ownership_pct=0.15,
            foreign_ownership_is_allied=True,
        ),
        data_quality=DataQuality(
            has_lei=True, has_cage=False, has_duns=True,
            has_tax_id=True, has_audited_financials=False,
            years_of_records=8,
        ),
        exec_profile=ExecProfile(known_execs=4),
        dod=DoDContext(
            sensitivity="CONTROLLED",
            supply_chain_tier=1,
        ),
    )


def adversary_soe() -> VendorInputV5:
    """State-owned enterprise from comprehensively sanctioned country.
    Expected: hard stop, TIER_1_DISQUALIFIED, probability = 1.0."""
    return VendorInputV5(
        name="Oboronprom Military Industrial",
        country="RU",
        ownership=OwnershipProfile(
            state_owned=True,
            beneficial_owner_known=False,
            ownership_pct_resolved=0.0,
            shell_layers=4,
        ),
        data_quality=DataQuality(),
        exec_profile=ExecProfile(),
        dod=DoDContext(
            sensitivity="ELEVATED",
            supply_chain_tier=2,
        ),
    )


def opaque_shell_company() -> VendorInputV5:
    """UAE-based entity with deep shell layering and unresolved ownership.
    Expected: TIER_2, multiple soft flags, high probability."""
    return VendorInputV5(
        name="Gulf Strategic Holdings FZE",
        country="AE",
        ownership=OwnershipProfile(
            publicly_traded=False,
            beneficial_owner_known=False,
            ownership_pct_resolved=0.20,
            shell_layers=7,
            pep_connection=True,
            foreign_ownership_pct=0.60,
            foreign_ownership_is_allied=False,
        ),
        data_quality=DataQuality(
            has_lei=False, has_cage=False, has_duns=False,
            has_tax_id=False, has_audited_financials=False,
            years_of_records=1,
        ),
        exec_profile=ExecProfile(
            known_execs=0,
            adverse_media=5,
        ),
        dod=DoDContext(
            sensitivity="ENHANCED",
            supply_chain_tier=3,
        ),
    )


def clean_commercial() -> VendorInputV5:
    """Domestic commercial vendor with no DoD context.
    Expected: TIER_4_CLEAR, low probability, no DoD factors."""
    return VendorInputV5(
        name="Pacific Coast Supply Co",
        country="US",
        ownership=OwnershipProfile(
            publicly_traded=False,
            beneficial_owner_known=True,
            ownership_pct_resolved=0.95,
        ),
        data_quality=DataQuality(
            has_lei=False, has_cage=False, has_duns=True,
            has_tax_id=True, has_audited_financials=True,
            years_of_records=12,
        ),
        exec_profile=ExecProfile(known_execs=3),
        dod=DoDContext(sensitivity="COMMERCIAL"),
    )


def sap_candidate() -> VendorInputV5:
    """US vendor being evaluated for SAP program. Zero foreign ownership.
    Expected: TIER_4_CRITICAL_QUALIFIED if clean, hard stop if any foreign."""
    return VendorInputV5(
        name="Sentinel Cryptographic Systems LLC",
        country="US",
        ownership=OwnershipProfile(
            publicly_traded=False,
            beneficial_owner_known=True,
            ownership_pct_resolved=1.0,
            foreign_ownership_pct=0.0,
        ),
        data_quality=DataQuality(
            has_lei=True, has_cage=True, has_duns=True,
            has_tax_id=True, has_audited_financials=True,
            years_of_records=10,
        ),
        exec_profile=ExecProfile(known_execs=6),
        dod=DoDContext(
            sensitivity="CRITICAL_SAP",
            supply_chain_tier=1,
        ),
    )


def cmmc_pending() -> VendorInputV5:
    """US Tier 2 supplier with CMMC certification gap.
    Expected: TIER_3 with CMMC soft flag, REQUIRES_REVIEW from Layer 1."""
    return VendorInputV5(
        name="Ironclad Machining Corp",
        country="US",
        ownership=OwnershipProfile(
            publicly_traded=False,
            beneficial_owner_known=True,
            ownership_pct_resolved=0.90,
        ),
        data_quality=DataQuality(
            has_lei=False, has_cage=True, has_duns=True,
            has_tax_id=True, has_audited_financials=False,
            years_of_records=6,
        ),
        exec_profile=ExecProfile(known_execs=2),
        dod=DoDContext(
            sensitivity="CONTROLLED",
            supply_chain_tier=2,
            cmmc_readiness=0.65,
            regulatory_gate_proximity=0.45,
        ),
    )


def single_source_critical() -> VendorInputV5:
    """Sole-source component supplier from a moderate-risk jurisdiction.
    Expected: single source soft flag, elevated probability."""
    return VendorInputV5(
        name="Ankara Precision Optics AS",
        country="TR",
        ownership=OwnershipProfile(
            publicly_traded=False,
            beneficial_owner_known=True,
            ownership_pct_resolved=0.75,
            foreign_ownership_pct=0.30,
            foreign_ownership_is_allied=False,
        ),
        data_quality=DataQuality(
            has_lei=False, has_cage=False, has_duns=False,
            has_tax_id=True, has_audited_financials=False,
            years_of_records=4,
        ),
        exec_profile=ExecProfile(known_execs=1, litigation_history=2),
        dod=DoDContext(
            sensitivity="ELEVATED",
            supply_chain_tier=2,
            single_source_risk=0.85,
            itar_exposure=0.40,
        ),
    )


def chinese_tech_company() -> VendorInputV5:
    """Chinese private tech firm, not state-owned but high geo risk.
    Expected: high probability, geography and foreign ownership depth flags."""
    return VendorInputV5(
        name="Shenzhen Integrated Circuits Co Ltd",
        country="CN",
        ownership=OwnershipProfile(
            publicly_traded=False,
            beneficial_owner_known=False,
            ownership_pct_resolved=0.40,
            foreign_ownership_pct=0.0,
        ),
        data_quality=DataQuality(
            has_lei=False, has_cage=False, has_duns=False,
            has_tax_id=False, has_audited_financials=False,
            years_of_records=3,
        ),
        exec_profile=ExecProfile(known_execs=0, adverse_media=2),
        dod=DoDContext(
            sensitivity="ELEVATED",
            supply_chain_tier=3,
            geopolitical_sector_exposure=0.70,
            ear_control_status=0.50,
        ),
    )


# ============================================================================
# CONVENIENCE DICT (for parametrized tests)
# ============================================================================

ALL_FIXTURES = {
    "clean_us_prime": clean_us_prime,
    "allied_conditional": allied_conditional,
    "adversary_soe": adversary_soe,
    "opaque_shell_company": opaque_shell_company,
    "clean_commercial": clean_commercial,
    "sap_candidate": sap_candidate,
    "cmmc_pending": cmmc_pending,
    "single_source_critical": single_source_critical,
    "chinese_tech_company": chinese_tech_company,
}
