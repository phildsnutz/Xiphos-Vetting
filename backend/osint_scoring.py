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

from dataclasses import dataclass
from typing import Optional
from fgamlogit import VendorInputV5, OwnershipProfile, DataQuality, ExecProfile, DoDContext


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
    identifiers = enrichment.get("identifiers", {})
    findings = enrichment.get("findings", [])
    risk_signals = enrichment.get("risk_signals", [])

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
        ownership_pct_resolved=base_input.ownership.ownership_pct_resolved,
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

    if identifiers.get("cage") and not dq.has_cage:
        dq.has_cage = True
        changes.append(f"CAGE code verified via SAM.gov: {identifiers['cage']}")

    if identifiers.get("uei") and not dq.has_cage:
        # UEI is the successor to CAGE for SAM registration
        dq.has_cage = True
        changes.append(f"UEI verified via SAM.gov: {identifiers['uei']}")

    if identifiers.get("duns") and not dq.has_duns:
        dq.has_duns = True
        changes.append(f"DUNS verified: {identifiers['duns']}")

    # SAM.gov registered entities have CAGE and are government-vetted
    if identifiers.get("sam_status") == "active":
        if not dq.has_cage:
            dq.has_cage = True
            changes.append("CAGE inferred from active SAM.gov registration")

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

    # Publicly traded detection: ticker, CIK, or explicit flag from OSINT
    is_public = identifiers.get("publicly_traded", False)
    has_ticker = bool(identifiers.get("ticker"))
    has_cik = bool(identifiers.get("cik"))

    if (is_public or has_ticker or has_cik) and not own.publicly_traded:
        own.publicly_traded = True
        source = identifiers.get("ticker") or f"CIK {identifiers.get('cik', '')}"
        changes.append(f"Publicly traded: {source}")

    # SEC-registered entities have public financial disclosures
    if has_cik or has_ticker:
        if not own.beneficial_owner_known:
            own.beneficial_owner_known = True
            # Beneficial ownership is INFERRED from SEC CIK; requires manual verification
            changes.append("[INFERRED] Beneficial ownership inferred from SEC CIK -- requires manual verification")
        # Lower confidence on ownership percentage: CIK presence doesn't guarantee we found real beneficial owner
        own.ownership_pct_resolved = max(own.ownership_pct_resolved, 0.60)
        if not dq.has_audited_financials:
            dq.has_audited_financials = True
            changes.append("Audited financials inferred from SEC registration")

    # LEI holders have verified legal entity identity
    if identifiers.get("lei"):
        if not own.beneficial_owner_known:
            own.beneficial_owner_known = True
            # LEI verifies entity identity but not ultimate beneficial ownership
            changes.append("[INFERRED] Beneficial ownership inferred from LEI registration -- requires manual verification")
        # Lower confidence: LEI doesn't guarantee we have ultimate beneficial ownership
        own.ownership_pct_resolved = max(own.ownership_pct_resolved, 0.60)

    # -------------------------------------------------------------------
    # 2. Ownership: update from corporate registry and LEI parent chains
    # -------------------------------------------------------------------
    relationships = enrichment.get("relationships", [])

    if relationships:
        ultimate_parents = [r for r in relationships if r.get("type") == "ultimate_parent"]
        if ultimate_parents:
            own.beneficial_owner_known = True
            own.ownership_pct_resolved = max(own.ownership_pct_resolved, 0.85)
            changes.append(f"Ultimate parent identified via GLEIF: {ultimate_parents[0].get('parent_name', 'N/A')}")

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
    incorporation_date = identifiers.get("incorporation_date") or identifiers.get("initial_registration_date")
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
            if src in ("opencorporates", "uk_companies_house") and "officer" in title.lower():
                import re
                nums = re.findall(r'(\d+)', title)
                if nums:
                    count = max(int(n) for n in nums)
                    if count > ex.known_execs and count < 500:
                        ex.known_execs = count
                        changes.append(f"Executive roster: {count} officers from {src}")
                        break

    # -------------------------------------------------------------------
    # 2d. Adverse media: count from GDELT findings
    # -------------------------------------------------------------------
    gdelt_adverse = 0
    for f in findings:
        if f.get("source") == "gdelt_media" and f.get("severity") in ("high", "critical"):
            gdelt_adverse += 1
    if gdelt_adverse > ex.adverse_media:
        ex.adverse_media = gdelt_adverse
        changes.append(f"Adverse media: {gdelt_adverse} significant hit(s) from GDELT")

    # -------------------------------------------------------------------
    # 2e. PEP connections: count from OpenSanctions PEP findings
    # -------------------------------------------------------------------
    pep_hits = 0
    for f in findings:
        if f.get("source") == "opensanctions_pep" and f.get("severity") in ("high", "critical", "medium"):
            pep_hits += 1
    if pep_hits > ex.pep_execs:
        ex.pep_execs = pep_hits
        own.pep_connection = True
        changes.append(f"PEP exposure: {pep_hits} match(es) from OpenSanctions PEP database")

    # -------------------------------------------------------------------
    # 2f. Litigation history: count from CourtListener findings
    # -------------------------------------------------------------------
    litigation_hits = 0
    for f in findings:
        if f.get("source") == "courtlistener":
            litigation_hits += 1
    if litigation_hits > ex.litigation_history:
        ex.litigation_history = litigation_hits
        changes.append(f"Litigation history: {litigation_hits} case(s) from CourtListener")

    # -------------------------------------------------------------------
    # 2g. State-owned detection from corporate registry
    # -------------------------------------------------------------------
    if not own.state_owned:
        for f in findings:
            src = f.get("source", "")
            detail = (f.get("detail", "") + " " + f.get("title", "")).lower()
            if src in ("opencorporates", "gleif_lei", "uk_companies_house"):
                if any(kw in detail for kw in ("state-owned", "state owned", "government", "soe", "crown corporation", "public body")):
                    # Keyword matching "government" is not definitive; flag for review instead
                    own.state_owned = False  # Don't set as hard fact
                    changes.append(f"[INFERRED] Possible state-owned entity (keyword match '{src}') -- requires manual verification")
                    # Add as a soft risk signal for scoring instead
                    extra_signals.append({
                        "signal": "possible_state_owned",
                        "severity": "medium",
                        "source": src,
                        "detail": f"Keyword match suggests possible state ownership",
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
    # -------------------------------------------------------------------

    # CSL matches (Trade.gov Consolidated Screening List)
    for f in findings:
        if f.get("source") == "trade_csl" and f.get("severity") in ("critical", "high"):
            extra_signals.append({
                "signal": "csl_screening_match",
                "severity": f["severity"],
                "source": "trade_csl",
                "detail": f["title"],
                "scoring_impact": "sanctions_raw_override",
            })

    # SAM.gov exclusions
    for f in findings:
        if f.get("source") == "sam_gov" and f.get("category") == "exclusion":
            extra_signals.append({
                "signal": "federal_exclusion",
                "severity": f["severity"],
                "source": "sam_gov",
                "detail": f["title"],
                "scoring_impact": "hard_stop_candidate",
            })

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
                changes.append(f"Shell risk: corporate beneficial owner detected via UK PSC register")

    # UK company number as identifier
    if identifiers.get("uk_company_number"):
        changes.append(f"UK Company Number verified: {identifiers['uk_company_number']}")

    # -------------------------------------------------------------------
    # 5. FARA (Foreign Agents Registration Act) signals (v2.5)
    # -------------------------------------------------------------------

    # FARA registrant match (vendor is registered as foreign agent)
    for sig in risk_signals:
        if sig.get("signal") == "fara_registrant":
            sev = sig.get("severity", "high")
            scoring_impact = "sanctions_raw_override" if sev == "critical" else "hard_stop_candidate"
            extra_signals.append({
                "signal": "fara_foreign_agent",
                "severity": sev,
                "source": "fara",
                "detail": sig["detail"],
                "scoring_impact": scoring_impact,
            })
            # FARA registration implies foreign government connection (but inferred, not confirmed)
            if not own.state_owned and sev in ("critical", "high"):
                own.state_owned = False  # Don't set as hard fact; mark as risk signal
                changes.append(f"[INFERRED] Foreign government connection inferred from FARA registration -- requires verification")
                extra_signals.append({
                    "signal": "fara_foreign_connection",
                    "severity": sev,
                    "source": "fara",
                    "detail": "FARA registration suggests foreign government principal involvement",
                    "scoring_impact": "ownership_risk_increase",
                })
            if not own.pep_connection:
                own.pep_connection = True
                changes.append("[INFERRED] PEP connection inferred from FARA foreign agent registration -- requires verification")

    # FARA foreign principal match (vendor IS the foreign government/entity)
    for sig in risk_signals:
        if sig.get("signal") == "fara_foreign_principal":
            sev = sig.get("severity", "high")
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

    return OSINTAugmentation(
        vendor_input=augmented,
        extra_risk_signals=extra_signals,
        verified_identifiers=identifiers,
        changes=changes,
    )
