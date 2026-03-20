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
import hashlib
import concurrent.futures
from typing import Optional
from datetime import datetime

from event_extraction import compute_report_hash

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
# REMOVED: bis_entity_list (hardcoded entity names, redundant with trade_csl)
# REMOVED: cfius_risk (pure rule engine, no API; geography scoring handles this in fgamlogit)

# REMOVED: ITAR/Export Control rule-based connectors (no real APIs; export control handled in fgamlogit)
# usml_classifier, end_use_risk, deemed_export - all static keyword/rule matching, zero API calls

# REMOVED: University Research Security (hardcoded lists, niche academic use only)
# foreign_talent_programs, institutional_risk - static PLA/talent program lists

# REMOVED: Grants Compliance (fapiis_check, do_not_pay - simulated data only)
# REMOVED: regulatory_compliance (hardcoded FDA/REACH/conflict minerals lists, no real API)

# v5.2 connectors (free, no-auth or free-tier APIs)
from . import cisa_kev
from . import wikidata_company
from . import google_news
from . import fpds_contracts

# v5.3 connectors (authoritative government sources, free)
from . import ofac_sdn
from . import eu_sanctions
from . import sbir_awards
from . import sec_xbrl
from . import uk_hmt_sanctions

# Ordered by priority: sanctions/exclusions first, then identity, then context
# All connectors query REAL external APIs. Zero hardcoded/simulated data.
CONNECTORS = [
    # --- Sanctions & Restricted Parties ---
    ("dod_sam_exclusions", dod_sam_exclusions),      # SAM.gov Exclusions API (real API, no simulation fallback)
    ("trade_csl", trade_csl),                        # Consolidated Screening List (13 US govt lists incl. BIS Entity List)
    ("un_sanctions", un_sanctions),                  # UN Security Council direct XML feed
    ("opensanctions_pep", opensanctions_pep),        # PEP screening via OpenSanctions

    # --- International Debarment ---
    ("worldbank_debarred", worldbank_debarred),      # World Bank/IDB/ADB/AfDB/EBRD debarments
    ("icij_offshore", icij_offshore),                # Panama/Paradise/Pandora Papers

    # --- Foreign Influence & Agent Registration ---
    ("fara", fara),                                  # DOJ FARA foreign agent registrations

    # --- Adverse Media ---
    ("gdelt_media", gdelt_media),                    # Adverse media via GDELT
    ("google_news", google_news),                    # Google News RSS (free, no auth)

    # --- Corporate Identity & Ownership ---
    ("sec_edgar", sec_edgar),                        # SEC filings, ownership, financials
    ("gleif_lei", gleif_lei),                        # LEI, parent chains
    ("opencorporates", opencorporates),              # Global corporate registry, officers
    ("uk_companies_house", uk_companies_house),      # UK PSC/beneficial ownership
    ("wikidata_company", wikidata_company),           # Wikidata company metadata (free SPARQL)

    # --- Government Contracts & Registration ---
    ("sam_gov", sam_gov),                            # SAM registration, entity data
    ("usaspending", usaspending),                    # Federal contract history
    ("fpds_contracts", fpds_contracts),              # FPDS federal procurement history (free API)

    # --- Regulatory & Compliance ---
    ("epa_echo", epa_echo),                          # EPA environmental violations (real API)
    ("osha_safety", osha_safety),                    # OSHA workplace safety violations

    # --- Litigation & Financial Regulation ---
    ("courtlistener", courtlistener),                # Federal/state litigation
    ("fdic_bankfind", fdic_bankfind),                # FDIC bank regulatory data

    # --- Vulnerability Intelligence ---
    ("cisa_kev", cisa_kev),                          # CISA Known Exploited Vulnerabilities (free JSON)

    # --- v5.3: Additional authoritative sources ---
    ("ofac_sdn", ofac_sdn),                          # OFAC SDN direct XML (US Treasury)
    ("eu_sanctions", eu_sanctions),                   # EU CFSP Consolidated Sanctions (European Commission)
    ("uk_hmt_sanctions", uk_hmt_sanctions),           # UK HMT/OFSI Sanctions (HM Treasury)
    ("sbir_awards", sbir_awards),                     # SBIR/STTR Awards (positive legitimacy signal)
    ("sec_xbrl", sec_xbrl),                          # SEC XBRL financial data (revenue, assets, debt ratios)
]

PER_CONNECTOR_TIMEOUT = 30

# Country-aware connector filtering.
# US-only connectors query US government databases that won't have data for foreign entities.
# UK-only connectors query UK government databases.
# All other connectors are global and always run.
US_ONLY_CONNECTORS = {
    "dod_sam_exclusions",  # SAM.gov Exclusions (US federal)
    "sam_gov",             # SAM.gov Registration (US federal)
    "usaspending",         # USAspending (US federal contracts)
    "fpds_contracts",      # FPDS (US federal procurement)
    "sbir_awards",         # SBIR/STTR (US small business R&D)
    "sec_edgar",           # SEC EDGAR (US-listed companies)
    "sec_xbrl",            # SEC XBRL (US-listed financials)
    "epa_echo",            # EPA (US environmental)
    "osha_safety",         # OSHA (US workplace safety)
    "courtlistener",       # CourtListener (US federal/state courts)
    "fdic_bankfind",       # FDIC (US banking)
    "fara",                # FARA (US foreign agent registration)
    "ofac_sdn",            # OFAC SDN (US Treasury)
}

UK_ONLY_CONNECTORS = {
    "uk_companies_house",  # UK Companies House
    "uk_hmt_sanctions",    # UK HMT/OFSI Sanctions
}

# These always run regardless of country
GLOBAL_CONNECTORS = {
    "trade_csl",           # US CSL but screens ALL entities (not just US)
    "un_sanctions",        # UN (global)
    "opensanctions_pep",   # OpenSanctions (global)
    "worldbank_debarred",  # World Bank (global)
    "icij_offshore",       # ICIJ (global)
    "gdelt_media",         # GDELT (global media)
    "google_news",         # Google News (global)
    "gleif_lei",           # GLEIF (global)
    "opencorporates",      # OpenCorporates (global)
    "wikidata_company",    # Wikidata (global)
    "cisa_kev",            # CISA KEV (global, products not countries)
    "eu_sanctions",        # EU CFSP (global)
}

# Country codes that should get US-specific connectors
US_JURISDICTIONS = {"US", "USA", "PR", "GU", "VI", "AS", "MP"}


def _filter_connectors_by_country(connectors: list, country: str) -> list:
    """Filter connectors based on vendor country. Returns only relevant connectors."""
    cc = (country or "").strip().upper()
    if len(cc) == 3:
        from fgamlogit import _normalize_country
        cc = _normalize_country(cc)

    filtered = []
    for name, mod in connectors:
        if name in GLOBAL_CONNECTORS:
            filtered.append((name, mod))
        elif name in US_ONLY_CONNECTORS:
            if cc in US_JURISDICTIONS or not cc:
                # Run US connectors for US vendors or when country is unknown
                filtered.append((name, mod))
        elif name in UK_ONLY_CONNECTORS:
            if cc == "GB" or not cc:
                filtered.append((name, mod))
        else:
            # Unknown connector category: always run
            filtered.append((name, mod))

    return filtered


def _stable_finding_id(vendor_name: str, finding: dict) -> str:
    key = "|".join([
        str(vendor_name or "").strip().lower(),
        str(finding.get("source", "")).strip().lower(),
        str(finding.get("category", "")).strip().lower(),
        str(finding.get("title", "")).strip().lower(),
        str(finding.get("detail", "")).strip().lower(),
        str(finding.get("url", "")).strip().lower(),
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _run_connector_with_timeout(mod, vendor_name: str, country: str, ids: dict):
    """Run a single connector with a hard timeout so one slow source cannot stall the pipeline."""
    import threading

    result = [None]
    exc = [None]

    def _target():
        try:
            result[0] = mod.enrich(vendor_name, country, **ids)
        except Exception as err:  # pragma: no cover - connector-specific failures are normalized below
            exc[0] = err

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=PER_CONNECTOR_TIMEOUT)

    if thread.is_alive():
        raise TimeoutError(f"Connector timed out after {PER_CONNECTOR_TIMEOUT}s")
    if exc[0]:
        raise exc[0]
    return result[0]


def _error_result(source: str, vendor_name: str, error: str) -> EnrichmentResult:
    return EnrichmentResult(
        source=source,
        vendor_name=vendor_name,
        error=error,
    )


def enrich_vendor_streaming(
    vendor_name: str,
    country: str = "",
    connectors: Optional[list[str]] = None,
    timeout: int = 60,
    **ids,
):
    """
    Generator that yields (event_type, data) tuples as each connector completes.

    Events:
        ("start", {"total_connectors": N, "connector_names": [...]})
        ("connector_done", {"name": ..., "has_data": ..., "findings_count": ..., "elapsed_ms": ..., "index": ...})
        ("connector_error", {"name": ..., "error": ..., "index": ...})
        ("complete", {full report dict})
    """
    t0 = time.time()

    active = CONNECTORS
    if connectors:
        active = [(name, mod) for name, mod in CONNECTORS if name in connectors]

    # Filter connectors by vendor country (skip US-only sources for foreign vendors)
    active = _filter_connectors_by_country(active, country)

    yield ("start", {
        "total_connectors": len(active),
        "connector_names": [name for name, _ in active],
    })

    results: list[EnrichmentResult] = []
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(active))) as executor:
        futures = {}
        for name, mod in active:
            f = executor.submit(_run_connector_with_timeout, mod, vendor_name, country, ids)
            futures[f] = name

        processed: set[concurrent.futures.Future] = set()
        try:
            for f in concurrent.futures.as_completed(futures, timeout=timeout):
                processed.add(f)
                name = futures[f]
                completed += 1
                try:
                    r = f.result()
                    results.append(r)
                    yield ("connector_done", {
                        "name": name,
                        "has_data": r.has_data,
                        "findings_count": len(r.findings),
                        "elapsed_ms": r.elapsed_ms,
                        "index": completed,
                        "total": len(active),
                    })
                except Exception as e:
                    results.append(_error_result(name, vendor_name, str(e)))
                    yield ("connector_error", {
                        "name": name,
                        "error": str(e)[:200],
                        "index": completed,
                        "total": len(active),
                    })
        except concurrent.futures.TimeoutError:
            pass

        for f, name in futures.items():
            if f in processed:
                continue
            f.cancel()
            completed += 1
            timeout_error = f"Connector timed out after overall {timeout}s pipeline timeout"
            results.append(_error_result(name, vendor_name, timeout_error))
            yield ("connector_error", {
                "name": name,
                "error": timeout_error,
                "index": completed,
                "total": len(active),
            })

    # Build final report (same aggregation as enrich_vendor)
    report = _build_report(vendor_name, country, results, t0)
    yield ("complete", report)


def _build_report(vendor_name: str, country: str, results: list, t0: float) -> dict:
    """Build the unified enrichment report from connector results."""
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
            finding_payload = {
                "source": f.source, "category": f.category,
                "title": f.title, "detail": f.detail,
                "severity": f.severity, "confidence": f.confidence,
                "url": f.url,
            }
            finding_payload["finding_id"] = _stable_finding_id(vendor_name, finding_payload)
            all_findings.append(finding_payload)
        all_identifiers.update(r.identifiers)
        all_relationships.extend(r.relationships)
        all_risk_signals.extend(r.risk_signals)

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    all_findings.sort(key=lambda f: severity_order.get(f["severity"], 5))

    critical_count = sum(1 for f in all_findings if f["severity"] == "critical")
    high_count = sum(1 for f in all_findings if f["severity"] == "high")
    medium_count = sum(1 for f in all_findings if f["severity"] == "medium")

    if critical_count > 0:
        overall_risk = "CRITICAL"
    elif high_count > 0:
        overall_risk = "HIGH"
    elif medium_count > 0:
        overall_risk = "MEDIUM"
    else:
        overall_risk = "LOW"

    total_ms = int((time.time() - t0) * 1000)

    report = {
        "vendor_name": vendor_name, "country": country,
        "enriched_at": datetime.utcnow().isoformat() + "Z",
        "total_elapsed_ms": total_ms, "overall_risk": overall_risk,
        "summary": {
            "findings_total": len(all_findings), "critical": critical_count,
            "high": high_count, "medium": medium_count,
            "connectors_run": len(results),
            "connectors_with_data": sum(1 for r in results if r.has_data),
            "errors": len(errors),
        },
        "identifiers": all_identifiers, "findings": all_findings,
        "relationships": all_relationships, "risk_signals": all_risk_signals,
        "connector_status": connector_status, "errors": errors,
    }
    report["report_hash"] = compute_report_hash(report)
    return report


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

    # Filter connectors by vendor country (skip US-only sources for foreign vendors)
    active = _filter_connectors_by_country(active, country)

    # Run enrichment
    results: list[EnrichmentResult] = []

    if parallel and len(active) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(active))) as executor:
            futures = {}
            for name, mod in active:
                f = executor.submit(_run_connector_with_timeout, mod, vendor_name, country, ids)
                futures[f] = name

            processed: set[concurrent.futures.Future] = set()
            try:
                for f in concurrent.futures.as_completed(futures, timeout=timeout):
                    processed.add(f)
                    try:
                        results.append(f.result())
                    except Exception as e:
                        name = futures[f]
                        results.append(_error_result(name, vendor_name, str(e)))
            except concurrent.futures.TimeoutError:
                pass

            for f, name in futures.items():
                if f in processed:
                    continue
                f.cancel()
                results.append(
                    _error_result(
                        name,
                        vendor_name,
                        f"Connector timed out after overall {timeout}s pipeline timeout",
                    )
                )
    else:
        for name, mod in active:
            try:
                results.append(_run_connector_with_timeout(mod, vendor_name, country, ids))
            except Exception as e:
                results.append(_error_result(name, vendor_name, str(e)))

    return _build_report(vendor_name, country, results, t0)
