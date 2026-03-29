"""
OSINT-to-Scoring Bridge

Takes an OSINT enrichment report and produces augmented scoring inputs.
Updates VendorInputV5 fields based on discovered data, and generates
additional risk signals that feed into the Bayesian scoring engine.

Original scoring weights (from deep-research-report.md):
  - Ownership/Control:    25%
  - Sanctions/Restricted: 25%
  - Executive/Network:    15%
  - Supply Chain Geo:     15%
  - Opacity/Data Quality: 10%
  - Program Relevance:    10%
"""

import math
from dataclasses import dataclass, field
from fgamlogit import VendorInputV5, OwnershipProfile, DataQuality, ExecProfile
from ownership_control_intelligence import (
    build_oci_summary,
    extract_owner_class_evidence,
    relationship_supports_named_owner_resolution,
)


def _relationship_supports_control_resolution(relationship: dict) -> bool:
    return relationship_supports_named_owner_resolution(relationship)


# =============================================================================
# SOURCE RELIABILITY WEIGHTS
# =============================================================================
# Each OSINT connector is assigned a reliability tier based on:
#   - Authoritative: Government primary source (0.95)
#   - High: Regulated/audited data (0.85)
#   - Medium: Established commercial/NGO source (0.70)
#   - Low: Media/crowdsourced (0.50)
# Findings from higher-reliability sources carry more weight in scoring.
SOURCE_RELIABILITY: dict[str, float] = {
    # Authoritative (0.95) -- Government primary sources
    "dod_sam_exclusions": 0.95,   # SAM.gov Exclusions API (Treasury/GSA)
    "trade_csl": 0.95,            # Consolidated Screening List (Commerce/State/Treasury)
    "un_sanctions": 0.95,         # UN Security Council (direct XML)
    "sam_gov": 0.95,              # SAM.gov Entity Registration (GSA)
    "sam_subaward_reporting": 0.95,  # SAM.gov Acquisition Subaward Reporting (GSA)
    "fpds_contracts": 0.90,       # FPDS federal procurement (USAspending)
    "epa_echo": 0.90,             # EPA Enforcement (government)
    "osha_safety": 0.90,          # OSHA Violations (DOL)
    "cisa_kev": 0.90,             # CISA Known Exploited Vulnerabilities
    "fara": 0.90,                 # DOJ FARA Registry

    # High (0.85) -- Regulated/audited registries
    "sec_edgar": 0.85,            # SEC EDGAR (public company filings)
    "gleif_lei": 0.85,            # GLEIF LEI Registry
    "uk_companies_house": 0.85,   # UK Companies House (government)
    "corporations_canada": 0.85,  # Corporations Canada (government)
    "australia_abn_asic": 0.85,   # ABR / ASIC (government)
    "singapore_acra": 0.85,       # Singapore ACRA (government)
    "new_zealand_companies_office": 0.85,  # NZ Companies Office / NZBN
    "norway_brreg": 0.85,         # Norway Brreg (government)
    "netherlands_kvk": 0.85,      # Netherlands KVK (government)
    "france_inpi_rne": 0.85,      # France INPI / RNE (government)
    "worldbank_debarred": 0.85,   # World Bank Debarment
    "opensanctions_pep": 0.80,    # OpenSanctions (aggregated, well-maintained)
    "courtlistener": 0.80,        # CourtListener (federal court records)
    "fdic_bankfind": 0.80,        # FDIC BankFind (government)
    "usaspending": 0.85,          # USAspending.gov

    # Medium (0.70) -- Commercial/NGO sources
    "opencorporates": 0.70,       # OpenCorporates (aggregated corporate data)
    "icij_offshore": 0.70,        # ICIJ Offshore Leaks (investigative journalism)
    "wikidata_company": 0.60,     # Wikidata (crowdsourced, variable quality)

    # Low (0.50) -- Media/aggregated news
    "gdelt_media": 0.50,          # GDELT adverse media
    "google_news": 0.45,          # Google News RSS

    # v5.3 additions
    "ofac_sdn": 0.95,             # OFAC SDN direct (US Treasury, most authoritative)
    "eu_sanctions": 0.92,         # EU CFSP Consolidated Sanctions (European Commission)
    "uk_hmt_sanctions": 0.92,     # UK HMT/OFSI Sanctions (HM Treasury)
    "sbir_awards": 0.85,          # SBIR.gov (government R&D awards)
    "sec_xbrl": 0.90,             # SEC XBRL financial data (audited financials)
}

# Default for unknown sources
DEFAULT_RELIABILITY = 0.60


def get_source_reliability(source: str) -> float:
    """Get reliability weight for an OSINT source."""
    return SOURCE_RELIABILITY.get(source, DEFAULT_RELIABILITY)


@dataclass
class OSINTAugmentation:
    """Result of processing an enrichment report for scoring."""
    # Updated vendor input (with OSINT-discovered data)
    vendor_input: VendorInputV5
    # Additional risk signals not captured by the standard scoring factors
    extra_risk_signals: list[dict]
    # Data quality improvements (what OSINT verified)
    verified_identifiers: dict
    # Summary of what changed
    changes: list[str]
    # Data provenance: maps scoring factor -> list of (source, detail) that contributed
    provenance: dict = field(default_factory=dict)


def augment_from_enrichment(
    base_input: VendorInputV5,
    enrichment: dict,
) -> OSINTAugmentation:
    """
    Process an OSINT enrichment report and augment scoring inputs.

    This function reads enrichment findings and identifiers, then:
    1. Updates data quality flags (LEI, CAGE, etc.) based on discovered IDs
    2. Adjusts ownership profile if corporate registry data is available
    3. Enriches executive profile if officer data was found
    4. Produces extra risk signals from screening list matches, exclusions, etc.

    Args:
        base_input: The current VendorInputV5 for scoring
        enrichment: The enrichment report dict from enrich_vendor()

    Returns:
        OSINTAugmentation with updated input and signals
    """
    changes = []
    extra_signals = []
    provenance: dict[str, list[dict]] = {}  # factor -> [{source, detail, reliability}]
    identifiers = enrichment.get("identifiers", {})
    findings = enrichment.get("findings", [])
    risk_signals = enrichment.get("risk_signals", [])
    relationships = enrichment.get("relationships", [])
    ownership_relationships = [
        rel
        for rel in relationships
        if rel.get("type") in {"owned_by", "beneficially_owned_by", "ultimate_parent"}
    ]

    def _track(factor: str, source: str, detail: str):
        """Record which source contributed to a scoring factor."""
        if factor not in provenance:
            provenance[factor] = []
        provenance[factor].append({
            "source": source,
            "detail": detail,
            "reliability": get_source_reliability(source),
        })

    # Clone the input profiles (including ALL v5 fields)
    dq = DataQuality(
        has_lei=base_input.data_quality.has_lei,
        has_cage=base_input.data_quality.has_cage,
        has_duns=base_input.data_quality.has_duns,
        has_tax_id=base_input.data_quality.has_tax_id,
        has_audited_financials=base_input.data_quality.has_audited_financials,
        years_of_records=base_input.data_quality.years_of_records,
    )
    own = OwnershipProfile(
        publicly_traded=base_input.ownership.publicly_traded,
        state_owned=base_input.ownership.state_owned,
        beneficial_owner_known=base_input.ownership.beneficial_owner_known,
        named_beneficial_owner_known=base_input.ownership.named_beneficial_owner_known,
        controlling_parent_known=base_input.ownership.controlling_parent_known,
        owner_class_known=base_input.ownership.owner_class_known,
        owner_class=base_input.ownership.owner_class,
        ownership_pct_resolved=base_input.ownership.ownership_pct_resolved,
        control_resolution_pct=base_input.ownership.control_resolution_pct,
        shell_layers=base_input.ownership.shell_layers,
        pep_connection=base_input.ownership.pep_connection,
        foreign_ownership_pct=base_input.ownership.foreign_ownership_pct,
        foreign_ownership_is_allied=base_input.ownership.foreign_ownership_is_allied,
    )
    ex = ExecProfile(
        known_execs=base_input.exec_profile.known_execs,
        adverse_media=base_input.exec_profile.adverse_media,
        pep_execs=base_input.exec_profile.pep_execs,
        litigation_history=base_input.exec_profile.litigation_history,
    )

    # -------------------------------------------------------------------
    # 1. Data Quality: update from discovered identifiers
    # -------------------------------------------------------------------
    if identifiers.get("lei") and not dq.has_lei:
        dq.has_lei = True
        changes.append(f"LEI verified via GLEIF: {identifiers['lei']}")
        _track("data_quality", "gleif_lei", f"LEI: {identifiers['lei']}")

    if identifiers.get("cage") and not dq.has_cage:
        dq.has_cage = True
        changes.append(f"CAGE code verified via SAM.gov: {identifiers['cage']}")
        _track("data_quality", "sam_gov", f"CAGE: {identifiers['cage']}")

    if identifiers.get("uei") and not dq.has_cage:
        dq.has_cage = True
        changes.append(f"UEI verified via SAM.gov: {identifiers['uei']}")
        _track("data_quality", "sam_gov", f"UEI: {identifiers['uei']}")

    if identifiers.get("duns") and not dq.has_duns:
        dq.has_duns = True
        changes.append(f"DUNS verified: {identifiers['duns']}")

    # UEI replaces DUNS for federal purposes. If we have UEI, treat as equivalent to DUNS
    if identifiers.get("uei") and not dq.has_duns:
        dq.has_duns = True
        changes.append(f"UEI verified (replaces DUNS for federal registration): {identifiers['uei']}")

    # SAM.gov registered entities have CAGE and are government-vetted
    if identifiers.get("sam_status") == "active":
        if not dq.has_cage:
            dq.has_cage = True
            changes.append("CAGE inferred from active SAM.gov registration")
        if not dq.has_duns:
            dq.has_duns = True
            changes.append("UEI/DUNS inferred from active SAM.gov registration")

    # FPDS contract history implies CAGE registration (can't get federal contracts without it)
    fpds_count = identifiers.get("fpds_contract_count", 0)
    if fpds_count and int(fpds_count) > 0:
        if not dq.has_cage:
            dq.has_cage = True
            changes.append(f"[INFERRED] CAGE inferred from {fpds_count} federal contract awards in FPDS")
        if not dq.has_duns:
            dq.has_duns = True
            changes.append("[INFERRED] DUNS/UEI inferred from federal contract history")

    # Wikidata employee count and stock exchange are strong identity signals
    if identifiers.get("employee_count") and dq.years_of_records == 0:
        # Large established company with known employee count: infer operating history
        try:
            emp = int(identifiers["employee_count"])
            if emp > 1000:
                dq.years_of_records = 20  # Conservative estimate for large company
                changes.append(f"[INFERRED] Operating history estimated 20+ years ({emp} employees)")
            elif emp > 100:
                dq.years_of_records = 10
                changes.append(f"[INFERRED] Operating history estimated 10+ years ({emp} employees)")
        except (ValueError, TypeError):
            pass

    if identifiers.get("cik"):
        # SEC registrant implies tax ID and audited financials
        if not dq.has_tax_id:
            dq.has_tax_id = True
            changes.append(f"Tax ID inferred from SEC CIK: {identifiers['cik']}")
        if not dq.has_audited_financials:
            # Check if entity has recent 10-K filings
            for f in findings:
                if f.get("source") == "sec_edgar" and "registrant" in f.get("title", "").lower():
                    dq.has_audited_financials = True
                    changes.append("Audited financials verified via SEC EDGAR filings")
                    break

    # Publicly traded detection: ticker, confident CIK, or explicit flag from
    # validated OSINT. Low-confidence CIKs often reflect a parent, lender, or
    # counterparty and should not flip the vendor into a public-company profile.
    is_public = identifiers.get("publicly_traded", False)
    has_ticker = bool(identifiers.get("ticker"))
    has_cik = bool(identifiers.get("cik"))
    has_confident_cik = has_cik and str(identifiers.get("cik_confidence") or "").lower() != "low"
    has_public_market_signal = bool(is_public or has_ticker or has_confident_cik)

    # Clear stale public-company classifications when the current enrichment run
    # does not validate a current market signal. This keeps auto-augmented
    # ownership state from persisting across later reruns.
    had_stale_public_company_state = own.publicly_traded and not has_public_market_signal
    if had_stale_public_company_state:
        own.publicly_traded = False
        changes.append("Cleared stale publicly traded classification (no current ticker or confident CIK)")

    if has_public_market_signal and not own.publicly_traded:
        own.publicly_traded = True
        source = identifiers.get("ticker") or f"CIK {identifiers.get('cik', '')}"
        changes.append(f"Publicly traded: {source}")

    # SEC-registered entities have public financial disclosures, but that does
    # not by itself establish beneficial ownership or a control path.
    if has_confident_cik or has_ticker:
        if not dq.has_audited_financials:
            dq.has_audited_financials = True
            changes.append("Audited financials confirmed via SEC registration")
        changes.append("Public market disclosure verified via current ticker / SEC registration")

    # LEI holders have verified legal entity identity, not automatically
    # beneficial ownership resolution.
    has_lei = bool(identifiers.get("lei"))
    if has_lei:
        dq.has_lei = True
        changes.append(f"LEI verified: {identifiers.get('lei', '')[:20]}")

    # Reset stale ownership inflation when the current run only proves identity
    # transparency, not an actual ownership/control relationship.
    if not ownership_relationships and not own.state_owned:
        transparency_cap = None
        if has_public_market_signal and has_lei:
            transparency_cap = 0.55
        elif has_public_market_signal:
            transparency_cap = 0.45
        elif has_lei:
            transparency_cap = 0.30
        elif had_stale_public_company_state:
            transparency_cap = 0.35

        if transparency_cap is not None and own.ownership_pct_resolved > transparency_cap:
            own.ownership_pct_resolved = transparency_cap
            changes.append(
                f"Ownership control resolution capped at {int(transparency_cap * 100)}% "
                "without direct ownership/control evidence"
            )

        if (
            (has_public_market_signal or has_lei or had_stale_public_company_state)
            and own.beneficial_owner_known
        ):
            own.beneficial_owner_known = False
            own.named_beneficial_owner_known = False
            changes.append(
                "Cleared beneficial-owner status: current evidence verifies identity/disclosure, not control path"
            )

    # SAM.gov CAGE code = government-verified entity identity
    if identifiers.get("cage"):
        dq.has_cage = True
        changes.append(f"CAGE verified: {identifiers.get('cage')}")
    if identifiers.get("uei"):
        dq.has_duns = True  # UEI replaces DUNS for SAM-registered entities
        changes.append(f"UEI verified: {identifiers.get('uei')}")

    # -------------------------------------------------------------------
    # 1b. Executive identity extraction from OSINT findings
    # -------------------------------------------------------------------
    # Extract executive/officer names from SEC EDGAR, SAM.gov, GLEIF,
    # OpenCorporates, and UK Companies House findings. This fills the
    # "No executive data available" gap.
    exec_names_found = set()
    for f in findings:
        src = f.get("source", "")
        detail = f.get("detail", "")
        title = f.get("title", "")
        cat = f.get("category", "")

        # SAM.gov POC (Points of Contact) and registered officers
        if src == "sam_gov" and any(kw in detail.lower() for kw in (
            "point of contact", "poc", "registered", "authorized representative"
        )):
            import re
            # Look for name patterns in SAM data
            for pattern in [r"Name:\s*([A-Z][a-z]+ [A-Z][a-z]+)", r"POC:\s*([A-Z][a-z]+ [A-Z][a-z]+)"]:
                for match in re.finditer(pattern, detail):
                    exec_names_found.add(match.group(1))

        # SEC EDGAR officer/director data from proxy statements
        if src == "sec_edgar" and any(kw in (title + detail).lower() for kw in (
            "def 14a", "proxy", "officer", "director", "executive",
        )):
            import re
            for match in re.finditer(r"(?:officer|director|executive)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)", detail, re.IGNORECASE):
                exec_names_found.add(match.group(1))

        # OpenCorporates officer listings
        if src == "opencorporates" and "officer" in cat.lower():
            import re
            for match in re.finditer(r"(?:Officer|Director|Secretary):\s*([A-Z][a-z]+ [A-Z][a-z]+)", detail):
                exec_names_found.add(match.group(1))

        # GLEIF authorized officials
        if src == "gleif_lei" and "authorized" in detail.lower():
            import re
            for match in re.finditer(r"(?:Official|Representative):\s*([A-Z][a-z]+ [A-Z][a-z]+)", detail):
                exec_names_found.add(match.group(1))

        # Leadership appointments in collected public reporting
        if src in {"google_news", "gdelt_media", "public_search", "rss_public", "public_html_ownership"}:
            import re
            haystack = f"{title}. {detail}"
            for pattern in (
                r"\b(?:promotes?|appointed?|names?)\s+([A-Z][a-z]+ [A-Z][a-z]+)\s+to\s+(?:president|ceo|chief executive officer|chair(?:man|woman)?|vice president|chief operating officer|chief financial officer)\b",
                r"\b([A-Z][a-z]+ [A-Z][a-z]+)\s+(?:named|appointed|promoted)\s+(?:as|to)\s+(?:the\s+)?(?:president|ceo|chief executive officer|chair(?:man|woman)?|vice president|chief operating officer|chief financial officer)\b",
            ):
                for match in re.finditer(pattern, haystack, re.IGNORECASE):
                    exec_names_found.add(match.group(1))

    # Update exec profile with discovered names
    if exec_names_found:
        exec_count = len(exec_names_found)
        if exec_count > ex.known_execs:
            ex.known_execs = exec_count
            changes.append(f"Executive roster: {exec_count} officers identified from OSINT ({', '.join(list(exec_names_found)[:3])}{'...' if exec_count > 3 else ''})")

    # For publicly traded companies, even without individual names,
    # we know officers exist because SEC requires disclosure
    if own.publicly_traded and ex.known_execs == 0:
        # SEC-registered public companies are required to disclose officers
        ex.known_execs = 5  # Conservative minimum for a publicly traded company
        changes.append("Executive roster: 5+ officers inferred (SEC disclosure requirement for publicly traded entity)")

    # -------------------------------------------------------------------
    # 2. Ownership: update from corporate registry and current control-path
    #    evidence
    # -------------------------------------------------------------------
    if relationships:
        ultimate_parents = [r for r in relationships if r.get("type") == "ultimate_parent"]
        if ultimate_parents:
            own.beneficial_owner_known = True
            own.named_beneficial_owner_known = True
            own.controlling_parent_known = True
            own.ownership_pct_resolved = max(own.ownership_pct_resolved, 0.85)
            own.control_resolution_pct = max(own.control_resolution_pct, 0.85)
            changes.append(f"Ultimate parent identified via GLEIF: {ultimate_parents[0].get('parent_name', 'N/A')}")
        if ownership_relationships:
            strong_ownership_relationships = [
                relationship for relationship in ownership_relationships if _relationship_supports_control_resolution(relationship)
            ]
            target_names = [
                str(r.get("target_entity") or r.get("parent_name") or "").strip()
                for r in strong_ownership_relationships
            ]
            unique_targets = [name for name in dict.fromkeys(target_names) if name]
            if strong_ownership_relationships:
                own.beneficial_owner_known = True
                own.named_beneficial_owner_known = True
                if any(r.get("type") in {"beneficially_owned_by", "ultimate_parent", "parent_of"} for r in strong_ownership_relationships):
                    own.controlling_parent_known = True
                relationship_resolution = (
                    0.85
                    if any(r.get("type") in {"beneficially_owned_by", "ultimate_parent"} for r in strong_ownership_relationships)
                    else 0.65
                )
                own.ownership_pct_resolved = max(own.ownership_pct_resolved, relationship_resolution)
                own.control_resolution_pct = max(own.control_resolution_pct, relationship_resolution)
                if has_public_market_signal or has_lei or had_stale_public_company_state:
                    own.ownership_pct_resolved = min(own.ownership_pct_resolved, relationship_resolution)
                if unique_targets:
                    changes.append(
                        "Ownership path identified via current enrichment relationships: "
                        + ", ".join(unique_targets[:2])
                        + ("..." if len(unique_targets) > 2 else "")
                    )
            else:
                changes.append("Weak ownership hints observed but not enough to resolve beneficial owner")

    descriptor_owner_findings = extract_owner_class_evidence(findings)
    if descriptor_owner_findings:
        descriptor = str(
            descriptor_owner_findings[0].get("descriptor")
            or "self-disclosed beneficial owner class"
        )
        descriptor_resolution = 0.55
        own.owner_class_known = True
        own.owner_class = descriptor
        if own.ownership_pct_resolved < descriptor_resolution:
            own.ownership_pct_resolved = descriptor_resolution
        if own.control_resolution_pct < 0.35:
            own.control_resolution_pct = 0.35
        changes.append(
            "Beneficial ownership partially resolved via first-party descriptor disclosure: "
            + descriptor
        )
        has_strong_named_owner_path = any(
            _relationship_supports_control_resolution(relationship)
            for relationship in ownership_relationships
        )
        if own.beneficial_owner_known and not has_strong_named_owner_path:
            own.beneficial_owner_known = False
        if own.named_beneficial_owner_known and not has_strong_named_owner_path:
            own.named_beneficial_owner_known = False
            own.controlling_parent_known = False
            changes.append(
                "Descriptor-only ownership evidence kept as owner class, not promoted to named beneficial owner"
            )

    oci_summary = build_oci_summary(
        {
            "beneficial_owner_known": own.beneficial_owner_known,
            "named_beneficial_owner_known": own.named_beneficial_owner_known,
            "controlling_parent_known": own.controlling_parent_known,
            "owner_class_known": own.owner_class_known,
            "owner_class": own.owner_class,
            "ownership_pct_resolved": own.ownership_pct_resolved,
            "control_resolution_pct": own.control_resolution_pct,
        },
        findings,
        relationships,
    )
    own.beneficial_owner_known = bool(oci_summary.get("named_beneficial_owner_known"))
    own.named_beneficial_owner_known = bool(oci_summary.get("named_beneficial_owner_known"))
    own.controlling_parent_known = bool(oci_summary.get("controlling_parent_known"))
    own.owner_class_known = bool(oci_summary.get("owner_class_known"))
    own.owner_class = str(oci_summary.get("owner_class") or own.owner_class or "")
    own.ownership_pct_resolved = max(own.ownership_pct_resolved, float(oci_summary.get("ownership_resolution_pct") or 0.0))
    own.control_resolution_pct = max(own.control_resolution_pct, float(oci_summary.get("control_resolution_pct") or 0.0))

    # Check for OpenCorporates officer data
    for f in findings:
        if f.get("source") == "opencorporates" and "officers" in f.get("category", ""):
            # Extract active officer count from finding
            title = f.get("title", "")
            if "active" in title:
                try:
                    active_count = int(title.split("active")[0].strip().split()[-1])
                    if active_count > ex.known_execs:
                        ex.known_execs = active_count
                        changes.append(f"Executive roster updated: {active_count} active officers from OpenCorporates")
                except (ValueError, IndexError):
                    pass

    # -------------------------------------------------------------------
    # 2b. Years of records: extract incorporation date from OSINT
    # -------------------------------------------------------------------
    incorporation_date = (
        identifiers.get("incorporation_date")
        or identifiers.get("initial_registration_date")
        or identifiers.get("founded_year")
    )
    if not incorporation_date:
        # Try to find it in OpenCorporates findings
        for f in findings:
            if f.get("source") == "opencorporates" and "incorporated" in f.get("detail", "").lower():
                detail = f.get("detail", "")
                # Look for 4-digit year
                import re
                year_match = re.search(r'(\d{4})', detail)
                if year_match:
                    incorporation_date = year_match.group(1)
                    break
    if not incorporation_date:
        # Try GLEIF initial registration date
        for f in findings:
            if f.get("source") == "gleif_lei" and "registration" in f.get("detail", "").lower():
                detail = f.get("detail", "")
                import re
                year_match = re.search(r'(\d{4})', detail)
                if year_match:
                    incorporation_date = year_match.group(1)
                    break
    if not incorporation_date:
        for f in findings:
            if f.get("source") == "public_html_ownership" and str(f.get("title", "")).lower().startswith("public site operating history hint"):
                value = (f.get("structured_fields", {}) or {}).get("identifier_value")
                if value:
                    incorporation_date = value
                    break

    if incorporation_date and dq.years_of_records == 0:
        try:
            from datetime import datetime
            if len(str(incorporation_date)) == 4:
                year = int(incorporation_date)
            else:
                year = int(str(incorporation_date)[:4])
            years = datetime.now().year - year
            if 0 < years < 200:
                dq.years_of_records = years
                changes.append(f"Operating history: {years} years (incorporated {year})")
        except (ValueError, TypeError):
            pass

    # -------------------------------------------------------------------
    # 2c. Executive data: extract from OpenCorporates officer count
    # -------------------------------------------------------------------
    # Try identifiers first (structured data), then fall back to title parsing
    officers_count = identifiers.get("officers_count") or identifiers.get("active_officers")
    if officers_count and isinstance(officers_count, (int, float)) and int(officers_count) > ex.known_execs:
        ex.known_execs = int(officers_count)
        changes.append(f"Executive roster: {ex.known_execs} officers from corporate registry")
    elif ex.known_execs == 0:
        # Fallback: try any finding that mentions officers
        for f in findings:
            src = f.get("source", "")
            title = f.get("title", "")
            if src in ("opencorporates", "uk_companies_house", "corporations_canada", "australia_abn_asic", "singapore_acra", "new_zealand_companies_office", "norway_brreg", "netherlands_kvk", "france_inpi_rne") and "officer" in title.lower():
                import re
                nums = re.findall(r'(\d+)', title)
                if nums:
                    count = max(int(n) for n in nums)
                    if count > ex.known_execs and count < 500:
                        ex.known_execs = count
                        changes.append(f"Executive roster: {count} officers from {src}")
                        break

    # -------------------------------------------------------------------
    # 2d. Adverse media: RELIABILITY-WEIGHTED count from all media sources
    # -------------------------------------------------------------------
    # Instead of raw counts, weight each finding by source reliability.
    # This means 3 CourtListener findings (0.80) outweigh 5 Google News hits (0.45).
    weighted_adverse = 0.0
    raw_adverse = 0
    for f in findings:
        src = f.get("source", "")
        sev = f.get("severity", "info")
        cat = f.get("category", "")
        if cat == "adverse_media" and sev in ("high", "critical", "medium"):
            reliability = get_source_reliability(src)
            weighted_adverse += reliability
            raw_adverse += 1
            _track("executive", src, f"Adverse media: {f.get('title','')[:50]}")
    # Also count GDELT specifically (legacy path)
    for f in findings:
        if f.get("source") == "gdelt_media" and f.get("severity") in ("high", "critical"):
            if f.get("category") != "adverse_media":  # Avoid double-counting
                reliability = get_source_reliability("gdelt_media")
                weighted_adverse += reliability
                raw_adverse += 1
    # Convert weighted count to effective integer (round up)
    effective_adverse = int(math.ceil(weighted_adverse))
    if effective_adverse > ex.adverse_media:
        ex.adverse_media = effective_adverse
        changes.append(f"Adverse media: {raw_adverse} findings across sources (weighted effective: {effective_adverse})")

    # -------------------------------------------------------------------
    # 2e. PEP connections: count from OpenSanctions PEP findings
    # -------------------------------------------------------------------
    pep_hits = 0
    for f in findings:
        if f.get("source") == "opensanctions_pep" and f.get("severity") in ("high", "critical", "medium"):
            pep_hits += 1
            _track("executive", "opensanctions_pep", f"PEP: {f.get('title','')[:50]}")
    if pep_hits > ex.pep_execs:
        ex.pep_execs = pep_hits
        own.pep_connection = True
        changes.append(f"PEP exposure: {pep_hits} match(es) from OpenSanctions PEP database")

    # -------------------------------------------------------------------
    # 2f. Litigation history: RELIABILITY-WEIGHTED from all legal sources
    # -------------------------------------------------------------------
    weighted_litigation = 0.0
    raw_litigation = 0
    for f in findings:
        src = f.get("source", "")
        if src in ("courtlistener", "osha_safety", "epa_echo") and f.get("severity") not in ("info",):
            reliability = get_source_reliability(src)
            weighted_litigation += reliability
            raw_litigation += 1
            _track("executive", src, f"Legal: {f.get('title','')[:50]}")
    effective_litigation = int(math.ceil(weighted_litigation))
    if effective_litigation > ex.litigation_history:
        ex.litigation_history = effective_litigation
        changes.append(f"Litigation/compliance: {raw_litigation} findings (weighted effective: {effective_litigation})")

    # -------------------------------------------------------------------
    # 2g. State-owned detection from corporate registry
    # -------------------------------------------------------------------
    if not own.state_owned:
        for f in findings:
            src = f.get("source", "")
            detail = (f.get("detail", "") + " " + f.get("title", "")).lower()
            if src in ("opencorporates", "gleif_lei", "uk_companies_house", "corporations_canada", "australia_abn_asic", "singapore_acra", "new_zealand_companies_office", "norway_brreg", "netherlands_kvk", "france_inpi_rne"):
                if any(kw in detail for kw in ("state-owned", "state owned", "government", "soe", "crown corporation", "public body")):
                    # Keyword matching is not definitive; flag for review, do NOT change state_owned boolean
                    changes.append(f"[INFERRED] Possible state-owned entity (keyword match '{src}') -- requires manual verification")
                    # Add as a soft risk signal for scoring instead
                    extra_signals.append({
                        "signal": "possible_state_owned",
                        "severity": "medium",
                        "source": src,
                        "detail": "Keyword match suggests possible state ownership",
                        "scoring_impact": "ownership_risk_increase",
                    })
                    break

    # -------------------------------------------------------------------
    # 2h. Foreign ownership from GLEIF parent chain country
    # -------------------------------------------------------------------
    if own.foreign_ownership_pct == 0.0 and relationships:
        for r in relationships:
            parent_country = r.get("parent_country", "").upper()
            entity_country = base_input.country.upper()
            if parent_country and parent_country != entity_country:
                # Foreign parent detected
                pct = r.get("ownership_pct", 0.51)  # Default to majority if not specified
                own.foreign_ownership_pct = min(1.0, pct)
                from fgamlogit import ALLIED_NATIONS
                own.foreign_ownership_is_allied = parent_country in ALLIED_NATIONS
                changes.append(f"Foreign ownership detected: parent in {parent_country} ({pct*100:.0f}%)")
                break

    # -------------------------------------------------------------------
    # 3. Extra risk signals from OSINT findings
    # (Each signal includes source reliability for gated escalation)
    # -------------------------------------------------------------------

    # Reliability floor for hard-stop escalation: only authoritative sources (>= 0.80)
    # can trigger hard stops or sanctions overrides. Lower-reliability sources
    # downgrade to ownership_risk_increase or data_quality_penalty.
    HARD_STOP_RELIABILITY_FLOOR = 0.80

    def _signal(signal: str, severity: str, source: str, detail: str, impact: str):
        """Create a risk signal with reliability gating.
        If impact is hard_stop_candidate or sanctions_raw_override but source
        reliability is below the floor, downgrade to ownership_risk_increase."""
        rel = get_source_reliability(source)
        actual_impact = impact
        if impact in ("hard_stop_candidate", "sanctions_raw_override") and rel < HARD_STOP_RELIABILITY_FLOOR:
            actual_impact = "ownership_risk_increase"
            changes.append(f"[GATED] {source} ({rel:.2f} reliability) signal downgraded from {impact} to {actual_impact}")
        extra_signals.append({
            "signal": signal, "severity": severity, "source": source,
            "detail": detail, "scoring_impact": actual_impact, "reliability": rel,
        })

    # CSL matches (Trade.gov Consolidated Screening List)
    for f in findings:
        if f.get("source") == "trade_csl" and f.get("severity") in ("critical", "high"):
            _signal("csl_screening_match", f["severity"], "trade_csl", f["title"], "sanctions_raw_override")

    # SAM.gov exclusions
    for f in findings:
        if f.get("source") == "sam_gov" and f.get("category") == "exclusion":
            _signal("federal_exclusion", f["severity"], "sam_gov", f["title"], "hard_stop_candidate")

    # SAM.gov inactive registration
    for sig in risk_signals:
        if sig.get("signal") == "sam_inactive_registration":
            extra_signals.append({
                "signal": "sam_inactive",
                "severity": "high",
                "source": "sam_gov",
                "detail": sig["detail"],
                "scoring_impact": "data_quality_penalty",
            })

    # Company dissolved (OpenCorporates)
    for sig in risk_signals:
        if sig.get("signal") == "company_dissolved":
            extra_signals.append({
                "signal": "entity_dissolved",
                "severity": "high",
                "source": "opencorporates",
                "detail": sig["detail"],
                "scoring_impact": "hard_stop_candidate",
            })

    # Recently incorporated (potential shell)
    for sig in risk_signals:
        if sig.get("signal") == "recently_incorporated":
            extra_signals.append({
                "signal": "potential_shell",
                "severity": "medium",
                "source": "opencorporates",
                "detail": sig["detail"],
                "scoring_impact": "ownership_risk_increase",
            })
            # Increase shell layers if recently incorporated
            if own.shell_layers == 0:
                own.shell_layers = 1
                changes.append("Shell risk flagged: recently incorporated entity")

    # LEI lapsed
    for sig in risk_signals:
        if sig.get("signal") == "lei_lapsed":
            dq.has_lei = False  # Override: LEI exists but is lapsed
            changes.append("LEI status: LAPSED (downgraded)")

    # No federal contracts (for US entities claiming to be defense contractors)
    for sig in risk_signals:
        if sig.get("signal") == "no_federal_contracts":
            extra_signals.append({
                "signal": "no_contract_history",
                "severity": "low",
                "source": "usaspending",
                "detail": "No federal contract awards found since 2020",
                "scoring_impact": "data_quality_concern",
            })

    # Missing SEC filings
    for sig in risk_signals:
        if sig.get("signal") == "no_recent_annual_report":
            extra_signals.append({
                "signal": "missing_annual_report",
                "severity": "medium",
                "source": "sec_edgar",
                "detail": "No 10-K found in recent filing history",
                "scoring_impact": "data_quality_penalty",
            })

    # -------------------------------------------------------------------
    # 4. New connector signals (v2.4)
    # -------------------------------------------------------------------

    # World Bank debarment
    for f in findings:
        if f.get("source") == "worldbank_debarred" and f.get("severity") in ("critical", "high"):
            extra_signals.append({
                "signal": "worldbank_debarment",
                "severity": f["severity"],
                "source": "worldbank_debarred",
                "detail": f["title"],
                "scoring_impact": "hard_stop_candidate",
            })

    # UN Security Council sanctions (direct match = automatic hard stop)
    for f in findings:
        if f.get("source") == "un_sanctions" and f.get("severity") == "critical":
            extra_signals.append({
                "signal": "un_sanctions_match",
                "severity": "critical",
                "source": "un_sanctions",
                "detail": f["title"],
                "scoring_impact": "sanctions_raw_override",
            })

    # EPA environmental violations
    for sig in risk_signals:
        if sig.get("signal") == "environmental_violations":
            sev = sig.get("severity", "medium")
            extra_signals.append({
                "signal": "environmental_compliance_issues",
                "severity": sev,
                "source": "epa_echo",
                "detail": sig["detail"],
                "scoring_impact": "data_quality_penalty" if sev == "medium" else "ownership_risk_increase",
            })

    # OSHA workplace safety violations
    for sig in risk_signals:
        if sig.get("signal") == "workplace_safety_violations":
            sev = sig.get("severity", "medium")
            extra_signals.append({
                "signal": "workplace_safety_issues",
                "severity": sev,
                "source": "osha_safety",
                "detail": sig["detail"],
                "scoring_impact": "data_quality_penalty" if sev != "critical" else "hard_stop_candidate",
            })

    # UK Companies House: inactive/dissolved company
    for sig in risk_signals:
        if sig.get("signal") == "uk_company_inactive":
            extra_signals.append({
                "signal": "uk_entity_inactive",
                "severity": "high",
                "source": "uk_companies_house",
                "detail": sig["detail"],
                "scoring_impact": "hard_stop_candidate",
            })

    # UK Companies House: corporate beneficial owner (layered ownership)
    for sig in risk_signals:
        if sig.get("signal") == "corporate_beneficial_owner":
            extra_signals.append({
                "signal": "layered_beneficial_ownership",
                "severity": "medium",
                "source": "uk_companies_house",
                "detail": sig["detail"],
                "scoring_impact": "ownership_risk_increase",
            })
            # Increase shell layers for corporate PSCs
            if own.shell_layers < 2:
                own.shell_layers += 1
                changes.append("Shell risk: corporate beneficial owner detected via UK PSC register")

    # UK company number as identifier
    if identifiers.get("uk_company_number"):
        changes.append(f"UK Company Number verified: {identifiers['uk_company_number']}")

    if identifiers.get("ca_corporation_number"):
        changes.append(f"Canada Corporation Number verified: {identifiers['ca_corporation_number']}")

    if identifiers.get("abn"):
        changes.append(f"ABN verified: {identifiers['abn']}")

    if identifiers.get("uen"):
        changes.append(f"UEN verified: {identifiers['uen']}")

    if identifiers.get("nz_company_number"):
        changes.append(f"NZ Company Number verified: {identifiers['nz_company_number']}")

    if identifiers.get("nzbn"):
        changes.append(f"NZBN verified: {identifiers['nzbn']}")

    # -------------------------------------------------------------------
    # 5. FARA (Foreign Agents Registration Act) signals (v2.5)
    # -------------------------------------------------------------------

    # FARA registrant match (vendor is registered as foreign agent)
    for sig in risk_signals:
        if sig.get("signal") == "fara_registrant":
            sev = sig.get("severity", "high")
            detail_lower = sig.get("detail", "").lower()

            # Terminated FARA registrations are informational, NOT hard stops.
            # Many allied defense companies had historical FARA registrations that have since ended.
            is_terminated = "terminated" in detail_lower or "inactive" in detail_lower
            if is_terminated:
                extra_signals.append({
                    "signal": "fara_historical",
                    "severity": "low",
                    "source": "fara",
                    "detail": sig["detail"],
                    "scoring_impact": "ownership_risk_increase",
                })
                changes.append("[INFO] Historical FARA registration found (terminated) -- no active foreign agent status")
            else:
                # Active FARA registration: this is a significant signal
                scoring_impact = "sanctions_raw_override" if sev == "critical" else "hard_stop_candidate"
                extra_signals.append({
                    "signal": "fara_foreign_agent",
                    "severity": sev,
                    "source": "fara",
                    "detail": sig["detail"],
                    "scoring_impact": scoring_impact,
                })
                # Active FARA implies foreign government connection
                if not own.state_owned and sev in ("critical", "high"):
                    own.state_owned = False  # Don't set as hard fact; mark as risk signal
                    changes.append("[INFERRED] Foreign government connection inferred from active FARA registration -- requires verification")
                    extra_signals.append({
                        "signal": "fara_foreign_connection",
                        "severity": sev,
                        "source": "fara",
                        "detail": "Active FARA registration suggests foreign government principal involvement",
                        "scoring_impact": "ownership_risk_increase",
                    })
                if not own.pep_connection:
                    own.pep_connection = True
                    changes.append("[INFERRED] PEP connection inferred from active FARA foreign agent registration -- requires verification")

    # FARA foreign principal match (vendor IS the foreign government/entity)
    for sig in risk_signals:
        if sig.get("signal") == "fara_foreign_principal":
            sev = sig.get("severity", "high")
            detail_lower = sig.get("detail", "").lower()
            is_terminated = "terminated" in detail_lower or "inactive" in detail_lower
            if is_terminated:
                extra_signals.append({
                    "signal": "fara_historical_principal",
                    "severity": "low",
                    "source": "fara",
                    "detail": sig["detail"],
                    "scoring_impact": "ownership_risk_increase",
                })
            else:
                extra_signals.append({
                    "signal": "fara_is_foreign_principal",
                    "severity": sev,
                    "source": "fara",
                    "detail": sig["detail"],
                    "scoring_impact": "sanctions_raw_override" if sev == "critical" else "hard_stop_candidate",
                })
            # Entity IS a foreign principal -- high confidence but still from FARA registry, not verified
            # Do NOT set state_owned=True from FARA alone; add as risk signal
            own.pep_connection = True
            changes.append("[INFERRED] Entity identified as FARA foreign principal -- requires legal verification before state-owned designation")

    # FARA registrant ID as identifier
    if identifiers.get("fara_registrant_id"):
        changes.append(f"FARA Registrant ID: {identifiers['fara_registrant_id']}")
    if identifiers.get("fara_principal_id"):
        changes.append(f"FARA Foreign Principal ID: {identifiers['fara_principal_id']}")

    # -------------------------------------------------------------------
    # POST-PROCESS: Apply reliability gating to ALL extra_risk_signals
    # Signals from sources below HARD_STOP_RELIABILITY_FLOOR get downgraded.
    # -------------------------------------------------------------------
    for sig in extra_signals:
        src = sig.get("source", "unknown")
        impact = sig.get("scoring_impact", "")
        if "reliability" not in sig:
            sig["reliability"] = get_source_reliability(src)
        if impact in ("hard_stop_candidate", "sanctions_raw_override"):
            if sig["reliability"] < HARD_STOP_RELIABILITY_FLOOR:
                sig["scoring_impact"] = "ownership_risk_increase"
                changes.append(f"[GATED] {src} ({sig['reliability']:.2f}) downgraded from {impact}")

    # -------------------------------------------------------------------
    # Build augmented VendorInputV5
    # -------------------------------------------------------------------
    augmented = VendorInputV5(
        name=base_input.name,
        country=base_input.country,
        ownership=own,
        data_quality=dq,
        exec_profile=ex,
        dod=base_input.dod,
    )

    # Add provenance from findings (track which sources contributed)
    for f in findings:
        src = f.get("source", "unknown")
        sev = f.get("severity", "info")
        if sev in ("critical", "high", "medium"):
            cat = f.get("category", "general")
            factor_map = {
                "exclusion": "sanctions",
                "sanctions": "sanctions",
                "pep": "executive",
                "adverse_media": "executive",
                "litigation": "executive",
                "ownership": "ownership",
                "compliance": "data_quality",
            }
            factor = factor_map.get(cat, "general")
            _track(factor, src, f.get("title", "")[:80])

    return OSINTAugmentation(
        vendor_input=augmented,
        extra_risk_signals=extra_signals,
        verified_identifiers=identifiers,
        changes=changes,
        provenance=provenance,
    )
