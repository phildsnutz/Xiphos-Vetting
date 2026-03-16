"""
OSINT Enrichment Orchestrator

Runs all connectors against a vendor and produces a unified enrichment
report with cross-referenced findings, risk signals, and discovered IDs.

Usage:
    from osint.enrichment import enrich_vendor
    report = enrich_vendor("BAE Systems plc", country="GB")
    print(report["summary"])
    for f in report["findings"]:
        print(f["severity"], f["title"])
"""

import time
import concurrent.futures
from typing import Optional
from datetime import datetime

from . import EnrichmentResult, Finding

# Import all connectors
from . import sec_edgar
from . import sam_gov
from . import usaspending
from . import trade_csl
from . import gleif_lei
from . import opencorporates
from . import icij_offshore
from . import gdelt_media
from . import courtlistener
from . import opensanctions_pep
from . import fdic_bankfind
from . import worldbank_debarred
from . import epa_echo
from . import uk_companies_house
from . import osha_safety
from . import un_sanctions
from . import fara

# Priority OSINT connectors
from . import dod_sam_exclusions
from . import bis_entity_list
from . import cfius_risk

# Ordered by priority: sanctions/exclusions first, then identity, then context
CONNECTORS = [
    # --- Sanctions & Restricted Parties (primary) ---
    ("dod_sam_exclusions", dod_sam_exclusions),      # DoD EPLS - Excluded Parties List
    ("bis_entity_list", bis_entity_list),            # Bureau of Industry & Security Entity List
    ("cfius_risk", cfius_risk),                      # CFIUS risk assessment (foreign investment)
    ("trade_csl", trade_csl),                        # Consolidated Screening List (13 US lists)
    ("un_sanctions", un_sanctions),                  # UN Security Council direct XML feed
    ("opensanctions_pep", opensanctions_pep),        # PEP screening via OpenSanctions

    # --- International Debarment ---
    ("worldbank_debarred", worldbank_debarred),      # World Bank/IDB/ADB/AfDB/EBRD debarments
    ("icij_offshore", icij_offshore),                # Panama/Paradise/Pandora Papers

    # --- Foreign Influence & Agent Registration ---
    ("fara", fara),                                  # DOJ FARA foreign agent registrations

    # --- Adverse Media ---
    ("gdelt_media", gdelt_media),                    # Adverse media via GDELT

    # --- Corporate Identity & Ownership ---
    ("sec_edgar", sec_edgar),                        # SEC filings, ownership, financials
    ("gleif_lei", gleif_lei),                        # LEI, parent chains
    ("opencorporates", opencorporates),              # Global corporate registry, officers
    ("uk_companies_house", uk_companies_house),      # UK PSC/beneficial ownership

    # --- Government Contracts & Exclusions ---
    ("sam_gov", sam_gov),                            # SAM registration, exclusions
    ("usaspending", usaspending),                    # Federal contract history

    # --- Regulatory Compliance ---
    ("epa_echo", epa_echo),                          # EPA environmental violations
    ("osha_safety", osha_safety),                    # OSHA workplace safety violations

    # --- Litigation & Financial Regulation ---
    ("courtlistener", courtlistener),                # Federal/state litigation
    ("fdic_bankfind", fdic_bankfind),                # FDIC bank regulatory data
]


def enrich_vendor(
    vendor_name: str,
    country: str = "",
    connectors: Optional[list[str]] = None,
    parallel: bool = True,
    timeout: int = 60,
    **ids,
) -> dict:
    """
    Run OSINT enrichment across all (or specified) connectors.

    Args:
        vendor_name: Primary name to search
        country: ISO-2 country code
        connectors: List of connector names to run (default: all)
        parallel: Run connectors concurrently (default: True)
        timeout: Max seconds for all connectors (default: 60)
        **ids: Known identifiers (cik, lei, uei, cage, etc.)

    Returns:
        Unified enrichment report dict
    """
    t0 = time.time()

    # Filter connectors if specified
    active = CONNECTORS
    if connectors:
        active = [(name, mod) for name, mod in CONNECTORS if name in connectors]

    # Run enrichment
    results: list[EnrichmentResult] = []

    if parallel and len(active) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(active)) as executor:
            futures = {}
            for name, mod in active:
                f = executor.submit(mod.enrich, vendor_name, country, **ids)
                futures[f] = name

            for f in concurrent.futures.as_completed(futures, timeout=timeout):
                try:
                    results.append(f.result())
                except Exception as e:
                    name = futures[f]
                    results.append(EnrichmentResult(
                        source=name, vendor_name=vendor_name, error=str(e)
                    ))
    else:
        for name, mod in active:
            try:
                results.append(mod.enrich(vendor_name, country, **ids))
            except Exception as e:
                results.append(EnrichmentResult(
                    source=name, vendor_name=vendor_name, error=str(e)
                ))

    # Aggregate results
    all_findings: list[dict] = []
    all_identifiers: dict = {}
    all_relationships: list[dict] = []
    all_risk_signals: list[dict] = []
    connector_status: dict = {}
    errors: list[str] = []

    for r in results:
        connector_status[r.source] = {
            "has_data": r.has_data,
            "findings_count": len(r.findings),
            "elapsed_ms": r.elapsed_ms,
            "error": r.error,
        }

        if r.error:
            errors.append(f"{r.source}: {r.error}")

        for f in r.findings:
            all_findings.append({
                "source": f.source,
                "category": f.category,
                "title": f.title,
                "detail": f.detail,
                "severity": f.severity,
                "confidence": f.confidence,
                "url": f.url,
            })

        all_identifiers.update(r.identifiers)
        all_relationships.extend(r.relationships)
        all_risk_signals.extend(r.risk_signals)

    # Sort findings by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    all_findings.sort(key=lambda f: severity_order.get(f["severity"], 5))

    # Compute summary stats
    critical_count = sum(1 for f in all_findings if f["severity"] == "critical")
    high_count = sum(1 for f in all_findings if f["severity"] == "high")
    medium_count = sum(1 for f in all_findings if f["severity"] == "medium")

    # Determine overall risk signal
    if critical_count > 0:
        overall_risk = "CRITICAL"
    elif high_count > 0:
        overall_risk = "HIGH"
    elif medium_count > 0:
        overall_risk = "MEDIUM"
    else:
        overall_risk = "LOW"

    total_ms = int((time.time() - t0) * 1000)

    return {
        "vendor_name": vendor_name,
        "country": country,
        "enriched_at": datetime.utcnow().isoformat() + "Z",
        "total_elapsed_ms": total_ms,
        "overall_risk": overall_risk,
        "summary": {
            "findings_total": len(all_findings),
            "critical": critical_count,
            "high": high_count,
            "medium": medium_count,
            "connectors_run": len(results),
            "connectors_with_data": sum(1 for r in results if r.has_data),
            "errors": len(errors),
        },
        "identifiers": all_identifiers,
        "findings": all_findings,
        "relationships": all_relationships,
        "risk_signals": all_risk_signals,
        "connector_status": connector_status,
        "errors": errors,
    }
