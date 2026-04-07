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
import logging
import concurrent.futures
import importlib
import json
from urllib.parse import urlparse
from typing import Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

from event_extraction import compute_report_hash

from . import EnrichmentResult, Finding
from .cache import get_cache
from .evidence_metadata import get_source_metadata
from .connector_registry import ACTIVE_CONNECTOR_ORDER

CONNECTORS = [
    (name, importlib.import_module(f".{name}", __package__))
    for name in ACTIVE_CONNECTOR_ORDER
]

PER_CONNECTOR_TIMEOUT = 45
CONNECTOR_EXECUTION_TIMEOUTS = {
    "dod_sam_exclusions": 12,
    "public_html_ownership": 75,
    "sam_gov": 20,
}

# Retry configuration
# Critical connectors (sanctions, exclusions) get more retries because missing
# a sanctions hit due to a transient network blip is a compliance risk.
CRITICAL_CONNECTORS = {
    "dod_sam_exclusions", "trade_csl", "un_sanctions", "ofac_sdn",
    "eu_sanctions", "uk_hmt_sanctions", "opensanctions_pep",
    "worldbank_debarred",
}
MAX_RETRIES_CRITICAL = 3    # sanctions sources: retry up to 3 times
MAX_RETRIES_STANDARD = 1    # non-critical: retry once
RETRY_BASE_DELAY = 1.0      # base delay in seconds (doubles each retry)
RETRY_MAX_DELAY = 8.0       # cap backoff at 8 seconds
CONNECTOR_MAX_RETRIES = {
    # These SAM endpoints either answer quickly or hang long enough to trip the
    # watchdog. Immediate replay rarely changes the outcome and only stalls the
    # counterparty lane.
    "dod_sam_exclusions": 0,
    "sam_gov": 0,
}

# Country-aware connector filtering.
# US-only connectors query US government databases that won't have data for foreign entities.
# UK-only connectors query UK government databases.
# All other connectors are global and always run.
US_ONLY_CONNECTORS = {
    "dod_sam_exclusions",  # SAM.gov Exclusions (US federal)
    "sam_gov",             # SAM.gov Registration (US federal)
    "sam_subaward_reporting",  # SAM.gov subcontract reporting (US federal)
    "usaspending",         # USAspending (US federal contracts)
    "fpds_contracts",      # FPDS (US federal procurement)
    "sbir_awards",         # SBIR/STTR (US small business R&D)
    "sec_edgar",           # SEC EDGAR (US-listed companies)
    "sec_xbrl",            # SEC XBRL (US-listed financials)
    "epa_echo",            # EPA (US environmental)
    "osha_safety",         # OSHA (US workplace safety)
    "courtlistener",       # CourtListener (US federal/state courts)
    "recap_courts",        # RECAP federal litigation archive
    "fdic_bankfind",       # FDIC (US banking)
    "fara",                # FARA (US foreign agent registration)
    "ofac_sdn",            # OFAC SDN (US Treasury)
}

UK_ONLY_CONNECTORS = {
    "uk_companies_house",  # UK Companies House
    "uk_hmt_sanctions",    # UK HMT/OFSI Sanctions
}

CANADA_ONLY_CONNECTORS = {
    "corporations_canada",  # Canadian federal corporations and ISC disclosures
}

AUSTRALIA_ONLY_CONNECTORS = {
    "australia_abn_asic",  # ABR / ASIC identity corroboration
}

SINGAPORE_ONLY_CONNECTORS = {
    "singapore_acra",  # Singapore ACRA entity profile corroboration
}

NEW_ZEALAND_ONLY_CONNECTORS = {
    "new_zealand_companies_office",  # NZ Companies Register and NZBN corroboration
}

NORWAY_ONLY_CONNECTORS = {
    "norway_brreg",  # Norway Bronnoysund Register Centre
}

NETHERLANDS_ONLY_CONNECTORS = {
    "netherlands_kvk",  # Dutch Chamber of Commerce
}

FRANCE_ONLY_CONNECTORS = {
    "france_inpi_rne",  # France INPI / RNE
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
    "gleif_bods_ownership_fixture",  # standards-backed local ownership fixture
    "openownership_bods_fixture",  # replayable BODS beneficial ownership fixture
    "openownership_bods_public",  # public Open Ownership style BODS dataset
    "opencorporates",      # OpenCorporates (global)
    "wikidata_company",    # Wikidata (global)
    "public_search_ownership",  # Search discovery -> official site -> first-party ownership hints
    "public_html_ownership",  # First-party public website ownership hints
    "cisa_kev",            # CISA KEV (global, products not countries)
    "mitre_attack_fixture",  # replayable ATT&CK threat intel fixture
    "cisa_advisory_fixture",  # replayable CISA advisory threat intel fixture
    "cyclonedx_spdx_vex_fixture",  # standards-backed local cyber supply-chain fixture
    "public_assurance_evidence_fixture",  # first-party public assurance evidence fixture
    "osv_dev",             # open source package vulnerabilities
    "deps_dev",            # dependency + provenance + repository metadata
    "openssf_scorecard",   # repository hygiene posture
    "eu_sanctions",        # EU CFSP (global)
}

IDENTIFIER_AUTHORITY_PRIORITY = {
    "official_registry": 0,
    "official_program_system": 1,
    "official_regulatory": 2,
    "first_party_self_disclosed": 3,
    "third_party_public": 4,
    "analyst_curated_fixture": 5,
    "standards_modeled_fixture": 6,
}

WEBSITE_SOURCE_PRIORITY = {
    "public_search_ownership": 0,
    "public_html_ownership": 1,
    "sam_gov": 2,
    "sec_edgar": 2,
    "uk_companies_house": 2,
    "singapore_acra": 2,
    "new_zealand_companies_office": 2,
    "norway_brreg": 2,
    "netherlands_kvk": 2,
    "france_inpi_rne": 2,
    "opencorporates": 3,
    "wikidata_company": 4,
}

COMMON_MULTI_PART_TLDS = {
    "co.uk",
    "org.uk",
    "gov.uk",
    "ac.uk",
    "co.nz",
    "com.au",
    "net.au",
    "org.au",
    "com.sg",
}

CONNECTOR_REPLAY_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "public_html_ownership": (
        "website",
        "first_party_pages",
        "public_html_fixture_page",
        "public_html_fixture_pages",
        "public_html_fixture_only",
    ),
    "openownership_bods_public": (
        "openownership_bods_url",
        "bods_url",
        "openownership_bods_path",
        "bods_path",
        "uk_company_number",
        "lei",
    ),
    "gleif_lei": (
        "lei",
        "gleif_cache_path",
        "gleif_lei_cache_path",
    ),
    "osv_dev": ("package_inventory",),
    "deps_dev": ("package_inventory",),
    "openssf_scorecard": ("repository_urls",),
    "careers_scraper": ("website", "sam_website"),
}

CONNECTOR_CACHE_VARIANT_KEYS: dict[str, tuple[str, ...]] = {
    "public_html_ownership": (
        "website",
        "official_website",
        "domain",
        "first_party_pages",
        "public_html_fixture_page",
        "public_html_fixture_pages",
        "public_html_fixture_only",
    ),
    "openownership_bods_public": (
        "openownership_bods_url",
        "bods_url",
        "openownership_bods_path",
        "bods_path",
        "uk_company_number",
        "lei",
    ),
    "gleif_lei": ("lei", "gleif_cache_path", "gleif_lei_cache_path"),
    "corporations_canada": ("corporations_canada_url", "ca_corporation_number", "business_number"),
    "australia_abn_asic": ("australia_abn_asic_url", "abn", "acn"),
    "singapore_acra": ("singapore_acra_url", "uen"),
    "new_zealand_companies_office": ("new_zealand_companies_office_url", "nzbn", "nz_company_number"),
    "norway_brreg": ("norway_brreg_url", "norway_org_number"),
    "netherlands_kvk": ("netherlands_kvk_url", "kvk_number"),
    "france_inpi_rne": ("france_inpi_rne_url", "fr_siren"),
    "osv_dev": ("package_inventory",),
    "deps_dev": ("package_inventory",),
    "openssf_scorecard": ("repository_urls",),
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
        elif name in CANADA_ONLY_CONNECTORS:
            if cc in {"CA", "CAN"} or not cc:
                filtered.append((name, mod))
        elif name in AUSTRALIA_ONLY_CONNECTORS:
            if cc in {"AU", "AUS"} or not cc:
                filtered.append((name, mod))
        elif name in SINGAPORE_ONLY_CONNECTORS:
            if cc in {"SG", "SGP"} or not cc:
                filtered.append((name, mod))
        elif name in NEW_ZEALAND_ONLY_CONNECTORS:
            if cc in {"NZ", "NZL"} or not cc:
                filtered.append((name, mod))
        elif name in NORWAY_ONLY_CONNECTORS:
            if cc in {"NO", "NOR"} or not cc:
                filtered.append((name, mod))
        elif name in NETHERLANDS_ONLY_CONNECTORS:
            if cc in {"NL", "NLD"} or not cc:
                filtered.append((name, mod))
        elif name in FRANCE_ONLY_CONNECTORS:
            if cc in {"FR", "FRA"} or not cc:
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


def _connector_timeout(connector_name: str = "") -> int:
    return int(CONNECTOR_EXECUTION_TIMEOUTS.get(connector_name, PER_CONNECTOR_TIMEOUT))


def _run_connector_once(mod, vendor_name: str, country: str, ids: dict, timeout_s: int = PER_CONNECTOR_TIMEOUT):
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
    thread.join(timeout=timeout_s)

    if thread.is_alive():
        raise TimeoutError(f"Connector timed out after {timeout_s}s")
    if exc[0]:
        raise exc[0]
    return result[0]


def _is_retryable(error: Exception) -> bool:
    """Determine if an error is transient and worth retrying."""
    err_str = str(error).lower()
    # Retryable: timeouts, connection errors, rate limits, server errors
    retryable_patterns = [
        "timeout", "timed out", "connection", "reset by peer",
        "503", "502", "429", "rate limit", "temporarily unavailable",
        "server error", "internal server error", "gateway",
        "eof", "broken pipe", "network", "dns",
    ]
    return any(p in err_str for p in retryable_patterns)


def _run_connector_with_timeout(mod, vendor_name: str, country: str, ids: dict, connector_name: str = ""):
    """
    Run a single connector with retry + exponential backoff.

    Critical connectors (sanctions lists) get more retries because a missed
    sanctions hit due to a transient network blip is a compliance failure.
    """
    max_retries = CONNECTOR_MAX_RETRIES.get(
        connector_name,
        MAX_RETRIES_CRITICAL if connector_name in CRITICAL_CONNECTORS else MAX_RETRIES_STANDARD,
    )
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            return _run_connector_once(
                mod,
                vendor_name,
                country,
                ids,
                timeout_s=_connector_timeout(connector_name),
            )
        except Exception as e:
            last_error = e
            if attempt < max_retries and _is_retryable(e):
                delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                logger.warning(
                    "Connector %s attempt %d/%d failed (%s), retrying in %.1fs",
                    connector_name, attempt + 1, max_retries + 1, str(e)[:100], delay,
                )
                time.sleep(delay)
            else:
                break

    # All retries exhausted
    if last_error:
        raise last_error
    raise RuntimeError(f"Connector {connector_name} failed with no error captured")


def _run_connector_cached(mod, vendor_name: str, country: str, ids: dict, connector_name: str = "", skip_cache: bool = False):
    """
    Cache-aware connector runner. Checks cache first, falls back to live call with retry.
    Stores successful results back into cache for future lookups.
    """
    cache = get_cache()
    cache_variant = _connector_cache_variant(connector_name, ids)

    # Check cache first (unless explicitly skipped, e.g. during re-enrich)
    if not skip_cache and cache.enabled:
        try:
            cached = cache.get(vendor_name, connector_name, country, variant=cache_variant)
        except TypeError as exc:
            if "variant" not in str(exc):
                raise
            cached = cache.get(vendor_name, connector_name, country)
        if cached is not None:
            logger.debug("Cache hit for %s/%s", connector_name, vendor_name)
            # Reconstruct EnrichmentResult from cached dict
            findings = [
                Finding(
                    source=f.get("source", connector_name),
                    category=f.get("category", ""),
                    title=f.get("title", ""),
                    detail=f.get("detail", ""),
                    severity=f.get("severity", "info"),
                    confidence=f.get("confidence", 0.0),
                    url=f.get("url", ""),
                    raw_data=f.get("raw_data", {}) or {},
                    timestamp=f.get("timestamp", ""),
                    source_class=get_source_metadata(
                        f.get("source", connector_name),
                        source_class=f.get("source_class", ""),
                        authority_level=f.get("authority_level", ""),
                        access_model=f.get("access_model", ""),
                    )["source_class"],
                    authority_level=get_source_metadata(
                        f.get("source", connector_name),
                        source_class=f.get("source_class", ""),
                        authority_level=f.get("authority_level", ""),
                        access_model=f.get("access_model", ""),
                    )["authority_level"],
                    access_model=get_source_metadata(
                        f.get("source", connector_name),
                        source_class=f.get("source_class", ""),
                        authority_level=f.get("authority_level", ""),
                        access_model=f.get("access_model", ""),
                    )["access_model"],
                    artifact_ref=f.get("artifact_ref", ""),
                    structured_fields=f.get("structured_fields", {}) or {},
                )
                for f in cached.get("findings", [])
            ]
            result_metadata = get_source_metadata(
                connector_name,
                source_class=cached.get("source_class", ""),
                authority_level=cached.get("authority_level", ""),
                access_model=cached.get("access_model", ""),
            )
            return EnrichmentResult(
                source=connector_name,
                vendor_name=vendor_name,
                findings=findings,
                identifiers=cached.get("identifiers", {}),
                relationships=cached.get("relationships", []),
                risk_signals=cached.get("risk_signals", []),
                elapsed_ms=0,  # instant from cache
                source_class=result_metadata["source_class"],
                authority_level=result_metadata["authority_level"],
                access_model=result_metadata["access_model"],
                artifact_refs=cached.get("artifact_refs", []) or [],
                structured_fields=cached.get("structured_fields", {}) or {},
            )

    # Cache miss: run the connector with retry logic
    result = _run_connector_with_timeout(mod, vendor_name, country, ids, connector_name=connector_name)

    # Store successful result in cache
    if cache.enabled and not result.error:
        cache_payload = {
            "findings": [
                {
                    "source": f.source, "category": f.category,
                    "title": f.title, "detail": f.detail,
                    "severity": f.severity, "confidence": f.confidence,
                    "url": f.url, "raw_data": f.raw_data,
                    "timestamp": f.timestamp,
                    "source_class": f.source_class,
                    "authority_level": f.authority_level,
                    "access_model": f.access_model,
                    "artifact_ref": f.artifact_ref,
                    "structured_fields": f.structured_fields,
                }
                for f in result.findings
            ],
            "identifiers": result.identifiers,
            "relationships": result.relationships,
            "risk_signals": result.risk_signals,
            "source_class": result.source_class,
            "authority_level": result.authority_level,
            "access_model": result.access_model,
            "artifact_refs": result.artifact_refs,
            "structured_fields": result.structured_fields,
        }
        try:
            cache.put(vendor_name, connector_name, country, cache_payload, variant=cache_variant)
        except TypeError as exc:
            if "variant" not in str(exc):
                raise
            cache.put(vendor_name, connector_name, country, cache_payload)

    return result


def _error_result(source: str, vendor_name: str, error: str, retries: int = 0) -> EnrichmentResult:
    r = EnrichmentResult(
        source=source,
        vendor_name=vendor_name,
        error=error,
    )
    # Attach retry metadata so downstream consumers know this was attempted multiple times
    r._retries = retries  # type: ignore[attr-defined]
    return r


def _build_finding_payload(vendor_name: str, finding: Finding | dict) -> dict:
    """Normalize a finding into a consistent report-safe payload."""
    if isinstance(finding, Finding):
        source = finding.source
        metadata = get_source_metadata(
            source,
            source_class=finding.source_class,
            authority_level=finding.authority_level,
            access_model=finding.access_model,
        )
        payload = {
            "source": source,
            "category": finding.category,
            "title": finding.title,
            "detail": finding.detail,
            "severity": finding.severity,
            "confidence": finding.confidence,
            "url": finding.url,
            "raw_data": finding.raw_data,
            "artifact_ref": finding.artifact_ref,
            "structured_fields": finding.structured_fields or {},
            **metadata,
        }
    else:
        source = finding.get("source", "")
        metadata = get_source_metadata(
            source,
            source_class=finding.get("source_class", ""),
            authority_level=finding.get("authority_level", ""),
            access_model=finding.get("access_model", ""),
        )
        payload = {
            "source": source,
            "category": finding.get("category", ""),
            "title": finding.get("title", ""),
            "detail": finding.get("detail", ""),
            "severity": finding.get("severity", "info"),
            "confidence": finding.get("confidence", 0.0),
            "url": finding.get("url", ""),
            "raw_data": finding.get("raw_data", {}) or {},
            "artifact_ref": finding.get("artifact_ref", "") or "",
            "structured_fields": finding.get("structured_fields", {}) or {},
            **metadata,
        }
    payload["finding_id"] = finding.get("finding_id") if isinstance(finding, dict) and finding.get("finding_id") else _stable_finding_id(vendor_name, payload)
    return payload


def _increment(counter: dict[str, int], key: str) -> None:
    if not key:
        return
    counter[key] = counter.get(key, 0) + 1


def _normalize_identifier_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        try:
            return json.dumps(value, sort_keys=True)
        except TypeError:
            return str(value).strip().upper()
    if isinstance(value, (list, tuple, set)):
        normalized_items = [_normalize_identifier_value(item) for item in value]
        normalized_items = [item for item in normalized_items if item]
        return json.dumps(sorted(normalized_items))
    if isinstance(value, str):
        return value.strip().upper()
    return str(value).strip().upper()


def _identifier_source_priority(source: str, connector_status: dict[str, Any], connector_metadata: dict[str, str]) -> int:
    status = connector_status.get(source) if isinstance(connector_status.get(source), dict) else {}
    authority = str(status.get("authority_level") or connector_metadata.get("authority_level") or "")
    return IDENTIFIER_AUTHORITY_PRIORITY.get(authority, 99)


def _website_source_priority(source: str, connector_status: dict[str, Any], connector_metadata: dict[str, str]) -> tuple[int, int]:
    return (
        WEBSITE_SOURCE_PRIORITY.get(source, 99),
        _identifier_source_priority(source, connector_status, connector_metadata),
    )


def _website_value_priority(value) -> tuple[int, int, int, int]:
    raw = str(value or "").strip()
    if not raw:
        return (99, 99, 99, 999)

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or parsed.path.split("/", 1)[0]).lower().strip()
    host = host.rsplit("@", 1)[-1].split(":", 1)[0]
    path = parsed.path if parsed.netloc else ""
    query = parsed.query if parsed.netloc else ""

    host_without_www = host[4:] if host.startswith("www.") else host
    labels = [label for label in host_without_www.split(".") if label]
    if len(labels) <= 2:
        extra_subdomain_penalty = 0
    else:
        suffix = ".".join(labels[-2:])
        root_label_count = 3 if suffix in COMMON_MULTI_PART_TLDS else 2
        extra_subdomain_penalty = 1 if len(labels) > root_label_count else 0

    path_penalty = 0 if path in {"", "/"} else 1
    query_penalty = 0 if not query else 1
    host_length = len(host_without_www or host)
    return (extra_subdomain_penalty, path_penalty, query_penalty, host_length)


def _website_host_key(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or parsed.path.split("/", 1)[0]).lower().strip()
    host = host.rsplit("@", 1)[-1].split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _same_first_party_website(left, right) -> bool:
    left_host = _website_host_key(left)
    right_host = _website_host_key(right)
    return bool(left_host and right_host and left_host == right_host)


def _merge_identifier_value(
    all_identifiers: dict,
    identifier_sources: dict[str, list[str]],
    connector_status: dict[str, Any],
    connector_metadata: dict[str, str],
    source: str,
    key: str,
    value,
) -> None:
    if value in (None, "", []):
        return

    existing = all_identifiers.get(key)
    if existing in (None, "", []):
        all_identifiers[key] = value
        identifier_sources.setdefault(str(key), [])
        if source not in identifier_sources[str(key)]:
            identifier_sources[str(key)].append(source)
        return

    if _normalize_identifier_value(existing) == _normalize_identifier_value(value):
        identifier_sources.setdefault(str(key), [])
        if source not in identifier_sources[str(key)]:
            identifier_sources[str(key)].append(source)
        return

    current_sources = [
        str(existing_source)
        for existing_source in (identifier_sources.get(str(key)) or [])
        if isinstance(existing_source, str) and existing_source.strip()
    ]
    current_priority = min(
        (
            _identifier_source_priority(existing_source, connector_status, connector_metadata)
            for existing_source in current_sources
        ),
        default=99,
    )
    incoming_priority = _identifier_source_priority(source, connector_status, connector_metadata)
    if key == "website":
        if _same_first_party_website(existing, value):
            if source in current_sources or incoming_priority < current_priority:
                all_identifiers[key] = value
                updated_sources = [source]
                for existing_source in current_sources:
                    if existing_source != source:
                        updated_sources.append(existing_source)
                identifier_sources[str(key)] = updated_sources
                return
        current_value_priority = _website_value_priority(existing)
        incoming_value_priority = _website_value_priority(value)
        current_website_priority = min(
            (
                _website_source_priority(existing_source, connector_status, connector_metadata)
                for existing_source in current_sources
            ),
            default=(99, 99),
        )
        incoming_website_priority = _website_source_priority(source, connector_status, connector_metadata)
        if (incoming_value_priority, incoming_website_priority) < (current_value_priority, current_website_priority):
            all_identifiers[key] = value
            identifier_sources[str(key)] = [source]
        return
    if source in current_sources and incoming_priority == current_priority and all(existing_source == source for existing_source in current_sources):
        all_identifiers[key] = value
        identifier_sources[str(key)] = [source]
        return
    if incoming_priority < current_priority:
        all_identifiers[key] = value
        identifier_sources[str(key)] = [source]


def _dependency_identifier_value(source: dict | EnrichmentResult, key: str):
    identifiers = source.identifiers if isinstance(source, EnrichmentResult) else source
    if not isinstance(identifiers, dict):
        return ""
    if key == "website":
        for candidate_key in ("website", "official_website", "domain"):
            value = identifiers.get(candidate_key)
            if value not in (None, "", []):
                return value
        return ""
    if key in {"package_inventory", "repository_urls", "openownership_bods_url"}:
        return identifiers.get(key)
    return identifiers.get(key)


def _connector_cache_variant(connector_name: str, ids: dict) -> str:
    keys = CONNECTOR_CACHE_VARIANT_KEYS.get(connector_name, ())
    if not keys:
        return ""
    parts: list[str] = []
    for key in keys:
        value = _dependency_identifier_value(ids, key)
        normalized = _normalize_identifier_value(value)
        if normalized:
            parts.append(f"{key}={normalized}")
    return "|".join(parts)


def _reconcile_first_party_website(
    all_identifiers: dict,
    identifier_sources: dict[str, list[str]],
) -> None:
    try:
        from . import public_html_ownership
    except Exception:
        return

    if not isinstance(all_identifiers, dict):
        return
    preferred = public_html_ownership._resolve_website(all_identifiers)
    if not preferred:
        return

    current = str(all_identifiers.get("website") or "").strip()
    if current and public_html_ownership._same_first_party_host(current, preferred):
        normalized_current = public_html_ownership._root_website(current) or public_html_ownership._normalize_website(current)
        if normalized_current != preferred:
            all_identifiers["website"] = preferred
        return

    raw_pages = all_identifiers.get("first_party_pages")
    has_first_party_pages = bool(raw_pages) and isinstance(raw_pages, (str, list, tuple, set))
    if not current or has_first_party_pages:
        all_identifiers["website"] = preferred
        merged_sources: list[str] = []
        for key in ("first_party_pages", "official_website", "domain", "website"):
            for source in identifier_sources.get(str(key), []) or []:
                normalized = str(source or "").strip()
                if normalized and normalized not in merged_sources:
                    merged_sources.append(normalized)
        if merged_sources:
            identifier_sources["website"] = merged_sources


def _should_replay_connector(
    connector_name: str,
    report: dict,
    seed_identifiers: dict,
    result_by_source: dict[str, EnrichmentResult],
) -> bool:
    dependency_keys = CONNECTOR_REPLAY_DEPENDENCIES.get(connector_name, ())
    if not dependency_keys:
        return False
    report_identifiers = report.get("identifiers") if isinstance(report.get("identifiers"), dict) else {}
    available_dependency_keys = [
        key
        for key in dependency_keys
        if _normalize_identifier_value(_dependency_identifier_value(report_identifiers, key))
    ]
    if not available_dependency_keys:
        return False
    current_result = result_by_source.get(connector_name)
    if current_result is None:
        return True
    seed_changed = any(
        _normalize_identifier_value(_dependency_identifier_value(seed_identifiers, key))
        != _normalize_identifier_value(_dependency_identifier_value(report_identifiers, key))
        for key in available_dependency_keys
    )
    current_mismatch = any(
        _normalize_identifier_value(_dependency_identifier_value(current_result, key))
        != _normalize_identifier_value(_dependency_identifier_value(report_identifiers, key))
        for key in available_dependency_keys
    )
    return seed_changed or current_mismatch or not current_result.has_data


def _build_report_with_replays(
    vendor_name: str,
    country: str,
    active: list[tuple[str, Any]],
    results: list[EnrichmentResult],
    t0: float,
    *,
    seed_identifiers: dict | None = None,
    seed_identifier_sources: dict | None = None,
    seed_connector_status: dict | None = None,
    force: bool = False,
) -> tuple[dict, list[EnrichmentResult], list[str]]:
    active_by_name = {name: mod for name, mod in active}
    replayed: list[str] = []
    report = _build_report(
        vendor_name,
        country,
        results,
        t0,
        seed_identifiers=seed_identifiers,
        seed_identifier_sources=seed_identifier_sources,
        seed_connector_status=seed_connector_status,
    )
    attempted: set[str] = set()
    while True:
        result_by_source = {result.source: result for result in results}
        replay_names = [
            name
            for name, _ in active
            if name not in attempted
            and _should_replay_connector(name, report, seed_identifiers or {}, result_by_source)
        ]
        if not replay_names:
            return report, results, replayed

        replay_ids = {**(seed_identifiers or {}), **(report.get("identifiers") or {})}
        replay_results: list[EnrichmentResult] = []
        for name in replay_names:
            mod = active_by_name[name]
            try:
                replay_results.append(
                    _run_connector_cached(
                        mod,
                        vendor_name,
                        country,
                        replay_ids,
                        connector_name=name,
                        skip_cache=True,
                    )
                )
            except Exception as exc:
                replay_results.append(_error_result(name, vendor_name, str(exc)))
        replayed.extend(replay_names)
        attempted.update(replay_names)
        results = [result for result in results if result.source not in replay_names] + replay_results
        report = _build_report(
            vendor_name,
            country,
            results,
            t0,
            seed_identifiers=seed_identifiers,
            seed_identifier_sources=seed_identifier_sources,
            seed_connector_status=seed_connector_status,
        )


def enrich_vendor_streaming(
    vendor_name: str,
    country: str = "",
    connectors: Optional[list[str]] = None,
    timeout: int = 90,
    force: bool = False,
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

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(active)))
    try:
        futures = {}
        for name, mod in active:
            f = executor.submit(
                _run_connector_cached,
                mod,
                vendor_name,
                country,
                ids,
                connector_name=name,
                skip_cache=force,
            )
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
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    # Build final report and replay any connector whose required identifiers were
    # only discovered after the first pass.
    report, _results, _replayed = _build_report_with_replays(
        vendor_name,
        country,
        active,
        results,
        t0,
        force=force,
    )
    yield ("complete", report)


def _build_report(
    vendor_name: str,
    country: str,
    results: list,
    t0: float,
    seed_identifiers: dict | None = None,
    seed_identifier_sources: dict | None = None,
    seed_connector_status: dict | None = None,
) -> dict:
    """Build the unified enrichment report from connector results."""
    all_findings: list[dict] = []
    all_identifiers: dict = {
        str(key): value
        for key, value in (seed_identifiers or {}).items()
        if value not in (None, "", [])
    }
    identifier_sources: dict[str, list[str]] = {
        str(key): [
            str(source)
            for source in values
            if isinstance(source, str) and source.strip()
        ]
        for key, values in (seed_identifier_sources or {}).items()
        if isinstance(values, list)
    }
    all_relationships: list[dict] = []
    all_risk_signals: list[dict] = []
    connector_status: dict = {
        str(source): dict(status)
        for source, status in (seed_connector_status or {}).items()
        if isinstance(source, str) and isinstance(status, dict)
    }
    errors: list[str] = []
    source_class_counts: dict[str, int] = {}
    authority_level_counts: dict[str, int] = {}
    access_model_counts: dict[str, int] = {}

    for r in results:
        connector_metadata = get_source_metadata(
            r.source,
            source_class=getattr(r, "source_class", ""),
            authority_level=getattr(r, "authority_level", ""),
            access_model=getattr(r, "access_model", ""),
        )
        connector_status[r.source] = {
            "has_data": r.has_data,
            "findings_count": len(r.findings),
            "elapsed_ms": r.elapsed_ms,
            "error": r.error,
            "artifact_refs": list(getattr(r, "artifact_refs", []) or []),
            "structured_fields": dict(getattr(r, "structured_fields", {}) or {}),
            **connector_metadata,
        }
        _increment(source_class_counts, connector_metadata["source_class"])
        _increment(authority_level_counts, connector_metadata["authority_level"])
        _increment(access_model_counts, connector_metadata["access_model"])
        if r.error:
            errors.append(f"{r.source}: {r.error}")
        for f in r.findings:
            all_findings.append(_build_finding_payload(vendor_name, f))
        for key, value in (r.identifiers or {}).items():
            _merge_identifier_value(
                all_identifiers,
                identifier_sources,
                connector_status,
                connector_metadata,
                r.source,
                str(key),
                value,
            )
        all_relationships.extend(r.relationships)
        all_risk_signals.extend(r.risk_signals)

    _reconcile_first_party_website(all_identifiers, identifier_sources)

    # Cross-correlate sanctions findings across all 8 lists
    try:
        from osint.cross_correlator import cross_correlate_sanctions
        xc_findings = cross_correlate_sanctions(all_findings, vendor_name)
        for xf in xc_findings:
            all_findings.append(_build_finding_payload(vendor_name, xf))
        if xc_findings:
            logger.info("Cross-correlation generated %d sanctions findings for %s", len(xc_findings), vendor_name)
    except Exception as e:
        logger.warning("Cross-correlation (sanctions) failed for %s: %s", vendor_name, e)

    # Cross-domain correlation: sanctions + SEC enforcement + litigation + supply chain
    try:
        from osint.cross_correlator import cross_correlate_domains
        cd_findings = cross_correlate_domains(all_findings, vendor_name)
        for cdf in cd_findings:
            all_findings.append(_build_finding_payload(vendor_name, cdf))
        if cd_findings:
            logger.info("Cross-domain correlation generated %d findings for %s", len(cd_findings), vendor_name)
    except Exception as e:
        logger.warning("Cross-domain correlation failed for %s: %s", vendor_name, e)

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    all_findings.sort(key=lambda f: severity_order.get(f["severity"], 5))

    critical_count = sum(1 for f in all_findings if f["severity"] == "critical")
    high_count = sum(1 for f in all_findings if f["severity"] == "high")
    medium_count = sum(1 for f in all_findings if f["severity"] == "medium")

    # overall_risk should reflect the PROPORTIONAL risk posture, not just
    # the single worst finding. One HIGH out of 58 clean findings is not
    # an overall HIGH risk profile. Use ratio-aware thresholds.
    total = len(all_findings) or 1
    critical_ratio = critical_count / total
    high_ratio = high_count / total

    if critical_count >= 3 or critical_ratio > 0.10:
        overall_risk = "CRITICAL"
    elif critical_count > 0 and total < 10:
        # Few findings and one is critical = still critical
        overall_risk = "CRITICAL"
    elif critical_count > 0:
        # Single critical in a large clean finding set = HIGH, not CRITICAL
        overall_risk = "HIGH"
    elif high_count >= 3 or high_ratio > 0.15:
        overall_risk = "HIGH"
    elif high_count > 0 and total < 10:
        overall_risk = "HIGH"
    elif high_count > 0:
        # Few HIGH findings in a large clean set = MEDIUM
        overall_risk = "MEDIUM"
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
        "identifiers": all_identifiers, "identifier_sources": identifier_sources, "findings": all_findings,
        "relationships": all_relationships, "risk_signals": all_risk_signals,
        "connector_status": connector_status, "errors": errors,
        "evidence_lanes": {
            "source_classes": source_class_counts,
            "authority_levels": authority_level_counts,
            "access_models": access_model_counts,
        },
    }
    report["report_hash"] = compute_report_hash(report)
    return report


def enrich_vendor(
    vendor_name: str,
    country: str = "",
    connectors: Optional[list[str]] = None,
    parallel: bool = True,
    timeout: int = 60,
    force: bool = False,
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
    seed_identifier_sources = (
        ids.pop("__seed_identifier_sources", {})
        if isinstance(ids.get("__seed_identifier_sources"), dict)
        else {}
    )
    seed_connector_status = (
        ids.pop("__seed_connector_status", {})
        if isinstance(ids.get("__seed_connector_status"), dict)
        else {}
    )
    seed_identifiers = {
        str(key): value
        for key, value in ids.items()
        if not str(key).startswith("__")
    }

    # Filter connectors if specified
    active = CONNECTORS
    if connectors:
        active = [(name, mod) for name, mod in CONNECTORS if name in connectors]

    # Filter connectors by vendor country (skip US-only sources for foreign vendors)
    active = _filter_connectors_by_country(active, country)

    # Run enrichment
    results: list[EnrichmentResult] = []

    if parallel and len(active) > 1:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(active)))
        try:
            futures = {}
            for name, mod in active:
                f = executor.submit(
                    _run_connector_cached,
                    mod,
                    vendor_name,
                    country,
                    ids,
                    connector_name=name,
                    skip_cache=force,
                )
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
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    else:
        for name, mod in active:
            try:
                results.append(
                    _run_connector_cached(
                        mod,
                        vendor_name,
                        country,
                        ids,
                        connector_name=name,
                        skip_cache=force,
                    )
                )
            except Exception as e:
                results.append(_error_result(name, vendor_name, str(e)))

    report, _results, _replayed = _build_report_with_replays(
        vendor_name,
        country,
        active,
        results,
        t0,
        seed_identifiers=seed_identifiers,
        seed_identifier_sources=seed_identifier_sources,
        seed_connector_status=seed_connector_status,
        force=force,
    )
    return report
