"""
SEC EDGAR Full-Text Search Connector - LIVE API

Real-time queries to SEC's EFTS full-text search API for:
  - Company filings (10-K, 10-Q, 8-K, DEF 14A)
  - Filing dates and form types
  - Company identity and regulatory status

API: https://efts.sec.gov/LATEST/search-index
No authentication required.
User-Agent header with contact email required.
"""

import json
import re
import time
import logging
import html
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from difflib import SequenceMatcher

from . import EnrichmentResult, Finding

logger = logging.getLogger(__name__)

EFTS = "https://efts.sec.gov/LATEST"
USER_AGENT = "Xiphos/5.2 (compliance-tool@xiphos.dev)"

# Corporate suffixes to strip for name comparison
_CORP_SUFFIXES = re.compile(
    r"\b(LLC|INC|CORP|CORPORATION|INCORPORATED|LIMITED|LTD|PLC|LP|LLP|CO|COMPANY|HOLDINGS|GROUP|ENTERPRISES)\b\.?",
    re.IGNORECASE,
)
_FINANCING_DOC_NAME_HINTS = (
    "ex10",
    "ex-10",
    "credit",
    "loan",
    "facility",
    "revolver",
    "guarant",
    "security",
    "cash",
    "treasury",
    "account",
    "deposit",
    "lockbox",
    "escrow",
    "custod",
    "control",
)
_FINANCING_PATTERNS: tuple[tuple[re.Pattern[str], str, float, str], ...] = (
    (
        re.compile(r"(?:with|and)\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,120}?)\s*,\s+as administrative agent\b", re.IGNORECASE),
        "administrative_agent",
        0.86,
        "backed_by",
    ),
    (
        re.compile(r"(?:with|and)\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,120}?)\s*,\s+as collateral agent\b", re.IGNORECASE),
        "collateral_agent",
        0.84,
        "backed_by",
    ),
    (
        re.compile(r"(?:with|and)\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,120}?)\s*,\s+as (?:lender|swingline lender|issuing bank)\b", re.IGNORECASE),
        "lender",
        0.82,
        "backed_by",
    ),
    (
        re.compile(
            r"(?:with|and)\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,120}?)\s*,\s+as (?:account bank|depositary bank|depository bank|cash management bank|paying agent|disbursing agent|collection bank|lockbox bank|lock-box bank|custodian|escrow agent|securities intermediary|control bank|treasury management provider)\b",
            re.IGNORECASE,
        ),
        "account_bank",
        0.80,
        "routes_payment_through",
    ),
    (
        re.compile(
            r"(?:credit agreement|loan agreement|term loan facility|revolving credit facility|revolver).{0,80}?(?:with|among)\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,120}?)(?=,?\s+as\b|,|\sand\b|$)",
            re.IGNORECASE,
        ),
        "credit_facility_counterparty",
        0.80,
        "backed_by",
    ),
    (
        re.compile(r"(?:receivables?|payments?|collections?)\s+(?:are|were)\s+(?:processed|settled|swept|routed)\s+(?:through|via)\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,120})", re.IGNORECASE),
        "payment_bank",
        0.76,
        "routes_payment_through",
    ),
    (
        re.compile(
            r"(?:collection account|deposit account|disbursement account|concentration account|lockbox|lock-box|operating account|cash collateral account|blocked account|escrow account|reserve account)\s+(?:is|was|are|were)?\s*(?:maintained|held|opened)?\s*(?:through|with|at)\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,120})",
            re.IGNORECASE,
        ),
        "deposit_account_bank",
        0.74,
        "routes_payment_through",
    ),
    (
        re.compile(
            r"(?:letters? of credit|l/cs?)\s+(?:issued|provided|supported)\s+(?:by|through)\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,120}?)(?=[.;]|\s+(?:support|supports|under|pursuant|for)\b|$)",
            re.IGNORECASE,
        ),
        "issuing_bank",
        0.78,
        "backed_by",
    ),
    (
        re.compile(
            r"(?:cash management|treasury management|merchant processing|payment processing)\s+(?:services|arrangements?)\s+(?:are|were)?\s*(?:provided|handled|performed)?\s*(?:by|through)\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,120}?)(?=[.;]|$)",
            re.IGNORECASE,
        ),
        "treasury_provider",
        0.76,
        "routes_payment_through",
    ),
)


def _normalize_for_match(name: str) -> str:
    """Normalize a company name for fuzzy matching."""
    name = name.upper().strip()
    name = _CORP_SUFFIXES.sub("", name)
    name = re.sub(r"[^A-Z0-9\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _name_match_score(vendor_name: str, sec_name: str) -> float:
    """
    Score how well a SEC-registered name matches the vendor being assessed.
    Returns 0.0-1.0. Threshold for acceptance is 0.65.
    """
    v = _normalize_for_match(vendor_name)
    s = _normalize_for_match(sec_name)

    if not v or not s:
        return 0.0

    # Exact normalized match
    if v == s:
        return 1.0

    # One contains the other (e.g., "LOCKHEED MARTIN" in "LOCKHEED MARTIN CORPORATION")
    if v in s or s in v:
        return 0.95

    # SequenceMatcher ratio
    return SequenceMatcher(None, v, s).ratio()


def _get(url: str) -> dict | list | None:
    """GET request with proper headers.

    Note: SEC EDGAR sometimes serves valid JSON with Content-Type: text/html
    (e.g. index.json endpoints).  We therefore try JSON parsing first and only
    reject as HTML if the body genuinely starts with an HTML doctype.
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            # Reject actual HTML pages (starts with DOCTYPE or <html)
            if raw[:20].lstrip().startswith(b"<!DOCTYPE") or raw[:20].lstrip().startswith(b"<html"):
                return None
            return json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _normalize_financing_entity(name: str) -> str:
    cleaned = str(name or "").strip(" ,;:-")
    cleaned = re.split(r"\s+(?:and|with|together with|including)\b", cleaned, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,;:-")
    cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned, flags=re.IGNORECASE)
    if cleaned.endswith(".") and not re.search(r"\b[A-Z]\.[A-Z]\.$", cleaned):
        cleaned = cleaned[:-1]
    return cleaned


def _looks_like_financing_entity(name: str, vendor_name: str) -> bool:
    cleaned = _normalize_financing_entity(name)
    if len(cleaned) < 3:
        return False
    if _name_match_score(cleaned, vendor_name) >= 0.78:
        return False
    if not re.search(r"[A-Za-z]", cleaned):
        return False
    if len(cleaned.split()) > 10:
        return False
    lowered = cleaned.lower()
    if any(
        token in lowered
        for token in (
            "credit agreement",
            "term loan",
            "revolving credit facility",
            "guarantee",
            "secured party",
            "borrower",
            "company",
        )
    ):
        return False
    return True


def _strip_sec_document_markup(text: str) -> str:
    payload = re.sub(r"</TEXT>\s*</DOCUMENT>\s*$", "", text or "", flags=re.IGNORECASE)
    text_marker = re.search(r"<TEXT>\s*", payload, re.IGNORECASE)
    if text_marker:
        payload = payload[text_marker.end():]
    payload = re.sub(r"<br\s*/?>", "\n", payload, flags=re.IGNORECASE)
    payload = re.sub(r"</?(?:td|th|tr|p|div|span|li|ul|ol|table)[^>]*>", "\n", payload, flags=re.IGNORECASE)
    payload = re.sub(r"<[^>]+>", " ", payload)
    payload = html.unescape(payload)
    payload = re.sub(r"\s+", " ", payload)
    return payload.strip()


def _parse_financing_document(text: str, vendor_name: str) -> list[dict]:
    normalized_text = _strip_sec_document_markup(text)
    if not normalized_text:
        return []
    relationships: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for pattern, role, confidence, rel_type in _FINANCING_PATTERNS:
        for hit in pattern.finditer(normalized_text):
            entity_name = _normalize_financing_entity(hit.group(1))
            if not _looks_like_financing_entity(entity_name, vendor_name):
                continue
            dedupe_key = (rel_type, entity_name.upper())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            snippet_start = max(hit.start() - 120, 0)
            snippet_end = min(hit.end() + 120, len(normalized_text))
            relationships.append(
                {
                    "type": rel_type,
                    "target_entity": entity_name,
                    "sec_role": role,
                    "confidence": confidence,
                    "snippet": normalized_text[snippet_start:snippet_end].strip(),
                }
            )
    return relationships


def _extract_financing_relationships(
    cik: str,
    padded_cik: str,
    forms: list,
    accessions: list,
    dates: list,
    vendor_name: str,
    result: EnrichmentResult,
) -> None:
    financing_candidates = [
        (form_type, filing_date, accession.replace("-", ""))
        for form_type, filing_date, accession in zip(forms, dates, accessions)
        if form_type in {"8-K", "10-Q", "10-K"}
    ][:4]
    if not financing_candidates:
        return

    extracted_relationships: list[dict] = []
    for form_type, filing_date, accession_clean in financing_candidates:
        index_url = f"https://www.sec.gov/Archives/edgar/data/{padded_cik}/{accession_clean}/index.json"
        time.sleep(0.25)
        index_data = _get(index_url)
        if not isinstance(index_data, dict):
            continue
        items = ((index_data.get("directory") or {}).get("item") or [])
        if not isinstance(items, list):
            continue
        document_candidates = [
            str(item.get("name") or "")
            for item in items
            if isinstance(item, dict)
            and any(hint in str(item.get("name") or "").lower() for hint in _FINANCING_DOC_NAME_HINTS)
        ][:3]
        for document_name in document_candidates:
            document_url = f"https://www.sec.gov/Archives/edgar/data/{padded_cik}/{accession_clean}/{document_name}"
            time.sleep(0.25)
            document_text = _fetch_text(document_url)
            parsed = _parse_financing_document(document_text, vendor_name)
            if not parsed:
                continue
            for relationship in parsed:
                relationship["document_url"] = document_url
                relationship["filing_date"] = filing_date
                relationship["form_type"] = form_type
            extracted_relationships.extend(parsed)

    if not extracted_relationships:
        return

    seen_targets: set[tuple[str, str]] = set()
    for relationship in extracted_relationships:
        dedupe_key = (relationship["type"], relationship["target_entity"].upper())
        if dedupe_key in seen_targets:
            continue
        seen_targets.add(dedupe_key)
        rel_type = relationship["type"]
        target_entity_type = "bank" if rel_type in {"backed_by", "routes_payment_through"} else "company"
        result.relationships.append(
            {
                "type": rel_type,
                "source_entity": vendor_name,
                "source_entity_type": "company",
                "source_identifiers": {"cik": cik},
                "target_entity": relationship["target_entity"],
                "target_entity_type": target_entity_type,
                "target_identifiers": {},
                "country": "",
                "data_source": "sec_edgar_ex10",
                "confidence": relationship["confidence"],
                "evidence": relationship["snippet"],
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "artifact_ref": relationship["document_url"],
                "evidence_url": relationship["document_url"],
                "evidence_title": "SEC financing filing",
                "structured_fields": {
                    "relationship_scope": "sec_credit_agreement",
                    "sec_role": relationship["sec_role"],
                    "filing_date": relationship["filing_date"],
                    "form_type": relationship["form_type"],
                },
                "source_class": "official_regulatory",
                "authority_level": "official_regulatory",
                "access_model": "public_api",
            }
        )

    summary_lines = [
        f"  {relationship['target_entity']} ({relationship['sec_role']}, {relationship['form_type']} {relationship['filing_date']})"
        for relationship in extracted_relationships[:12]
    ]
    result.findings.append(
        Finding(
            source="sec_edgar",
            category="finance",
            title=f"SEC financing counterparties: {len(seen_targets)} entities identified",
            detail=(
                "Credit and financing filings named the following counterparties:\n"
                + "\n".join(summary_lines)
                + (f"\n  ... and {len(extracted_relationships) - 12} more" if len(extracted_relationships) > 12 else "")
            ),
            severity="info",
            confidence=0.82,
            raw_data={"relationship_count": len(seen_targets)},
        )
    )


def _deep_parse_company(cik: str, vendor_name: str, result: EnrichmentResult):
    """
    Deep parse SEC EDGAR company data to extract:
    - Officers and directors (from company submissions API)
    - Recent insider transactions (Forms 3, 4, 5)
    - Beneficial ownership (Schedule 13D/13G)
    - Subsidiaries and relationships

    Includes CIK validation: confirms the SEC-registered entity name matches
    the vendor being assessed before extracting identifiers.
    """
    try:
        # 1. Fetch company submissions (officers, filings, metadata)
        padded_cik = cik.zfill(10)
        company_url = f"https://data.sec.gov/submissions/CIK{padded_cik}.json"
        company_data = _get(company_url)

        if not company_data:
            return

        # ---- CIK VALIDATION ----
        # Confirm the SEC-registered name actually matches our vendor.
        # This prevents the Lockheed/Leidos problem where a search for
        # "Lockheed Martin" returns CIK for Leidos (a former subsidiary).
        sec_registered_name = company_data.get("name", "")
        match_score = _name_match_score(vendor_name, sec_registered_name)

        if match_score < 0.65:
            # Check former names as fallback (entity may have been renamed)
            former_names = company_data.get("formerNames", [])
            best_former_score = 0.0
            best_former_name = ""
            for fn in former_names:
                fn_name = fn.get("name", "")
                fn_score = _name_match_score(vendor_name, fn_name)
                if fn_score > best_former_score:
                    best_former_score = fn_score
                    best_former_name = fn_name

            if best_former_score >= 0.65:
                logger.info(
                    "CIK %s: current name '%s' doesn't match vendor '%s' (%.0f%%), "
                    "but former name '%s' matches (%.0f%%). Proceeding with caution.",
                    cik, sec_registered_name, vendor_name,
                    match_score * 100, best_former_name, best_former_score * 100,
                )
                # Store the relationship but proceed
                result.relationships.append({
                    "type": "former_name_match",
                    "entity": sec_registered_name,
                    "former_name": best_former_name,
                    "match_score": round(best_former_score, 2),
                })
            else:
                # CIK does NOT belong to this vendor. Log and skip.
                logger.warning(
                    "CIK MISMATCH: CIK %s is registered to '%s', not '%s' (score: %.0f%%). "
                    "Skipping deep parse to avoid cross-contamination.",
                    cik, sec_registered_name, vendor_name, match_score * 100,
                )
                result.findings.append(Finding(
                    source="sec_edgar", category="identity",
                    title=f"CIK mismatch: {sec_registered_name} (CIK {cik}) is a different entity",
                    detail=(
                        f"SEC EDGAR search returned CIK {cik} which is registered to "
                        f"'{sec_registered_name}', not '{vendor_name}' "
                        f"(name similarity: {match_score:.0%}). "
                        f"This may be a subsidiary, spin-off, or coincidental name match. "
                        f"Identifiers from this CIK have NOT been applied to avoid data contamination."
                    ),
                    severity="low", confidence=0.85,
                    url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
                ))
                # Clear the CIK from identifiers since it's wrong
                result.identifiers.pop("cik", None)
                return

        logger.info(
            "CIK %s validated: SEC name '%s' matches vendor '%s' (score: %.0f%%)",
            cik, sec_registered_name, vendor_name, match_score * 100,
        )
        result.identifiers["sec_registered_name"] = sec_registered_name
        # ---- END CIK VALIDATION ----

        # Extract company metadata
        sic = company_data.get("sic", "")
        sic_desc = company_data.get("sicDescription", "")
        state = company_data.get("stateOfIncorporation", "")
        fiscal_year = company_data.get("fiscalYearEnd", "")
        exchanges = company_data.get("exchanges", [])
        tickers = company_data.get("tickers", [])
        ein = company_data.get("ein", "")

        # Store discovered identifiers (safe now -- CIK is validated)
        if ein:
            result.identifiers["ein"] = ein
        if tickers:
            result.identifiers["tickers"] = tickers
        if exchanges:
            result.identifiers["exchanges"] = exchanges
        if sic:
            result.identifiers["sic_code"] = sic
            result.identifiers["sic_description"] = sic_desc
        if state:
            result.identifiers["state_of_incorporation"] = state

        # Extract officers/directors from former names or addresses
        officers = company_data.get("officers", [])
        if not officers:
            # Try the 'formerNames' array for historical data
            former_names = company_data.get("formerNames", [])
            if former_names:
                for fn in former_names[:5]:
                    result.relationships.append({
                        "type": "former_name",
                        "entity": fn.get("name", ""),
                        "date_from": fn.get("from", ""),
                        "date_to": fn.get("to", ""),
                    })

        # Parse recent filings to detect key patterns
        recent = company_data.get("filings", {}).get("recent", {})
        if recent:
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])

            # Count insider transaction filings (Forms 3, 4, 5)
            insider_forms = [(f, d) for f, d in zip(forms, dates) if f in ("3", "4", "5")]
            if insider_forms:
                recent_insider = [d for _, d in insider_forms if d >= "2024-01-01"]
                result.structured_fields["insider_filing_count"] = len(insider_forms)
                result.structured_fields["recent_insider_filing_count"] = len(recent_insider)
                if len(recent_insider) >= 10:
                    result.risk_signals.append({
                        "signal": "sec_high_insider_activity",
                        "severity": "low",
                        "detail": f"{len(recent_insider)} insider transaction filings since 2024. "
                                  "High volume may indicate significant ownership changes.",
                    })
                result.findings.append(Finding(
                    source="sec_edgar", category="ownership",
                    title=f"SEC insider filings: {len(insider_forms)} transactions on record",
                    detail=(
                        f"Found {len(insider_forms)} insider transaction filings (Forms 3/4/5). "
                        f"{len(recent_insider)} filed since 2024-01-01. "
                        "These disclose officer/director equity transactions."
                    ),
                    severity="info", confidence=0.95,
                    url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=40",
                ))

            # Check for Schedule 13D/13G (beneficial ownership > 5%)
            ownership_forms = [(f, d, a) for f, d, a in zip(forms, dates, accessions) if "SC 13" in f]
            if ownership_forms:
                result.structured_fields["beneficial_ownership_filing_count"] = len(ownership_forms)
                result.structured_fields["most_recent_beneficial_ownership_filing"] = ownership_forms[0][1]
                result.findings.append(Finding(
                    source="sec_edgar", category="ownership",
                    title=f"Beneficial ownership disclosures: {len(ownership_forms)} filings",
                    detail=(
                        f"Found {len(ownership_forms)} Schedule 13D/13G filings indicating investors "
                        f"with >5% beneficial ownership stakes. Most recent: {ownership_forms[0][1]}. "
                        "Review for concentrated ownership risk or activist investor activity."
                    ),
                    severity="low", confidence=0.9,
                    url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=SC+13&dateb=&owner=include&count=10",
                ))
                result.risk_signals.append({
                    "signal": "sec_beneficial_ownership",
                    "severity": "info",
                    "detail": f"{len(ownership_forms)} beneficial ownership (>5%) disclosures on file",
                })

            # Check for enforcement actions (litigation releases)
            enforcement = [f for f in forms if any(k in f.upper() for k in ["ADMIN", "ORDER", "JUDGMENT"])]
            if enforcement:
                result.findings.append(Finding(
                    source="sec_edgar", category="enforcement",
                    title=f"SEC enforcement: {len(enforcement)} administrative filings detected",
                    detail=f"Found {len(enforcement)} filings that may indicate SEC enforcement actions.",
                    severity="high", confidence=0.7,
                ))

            # --- Layer 3: Exhibit 21 subsidiary extraction ---
            # Exhibit 21 lists all subsidiaries of a registrant. We look for the
            # most recent 10-K that has an EX-21 attachment and fetch the XBRL
            # subsidiary data from the SEC's companion files API.
            try:
                _extract_subsidiaries(cik, padded_cik, forms, accessions, dates, vendor_name, result)
            except Exception as ex21_err:
                logger.debug("Exhibit 21 extraction failed for CIK %s: %s", cik, ex21_err)

            try:
                _extract_financing_relationships(cik, padded_cik, forms, accessions, dates, vendor_name, result)
            except Exception as financing_err:
                logger.debug("SEC financing extraction failed for CIK %s: %s", cik, financing_err)

        # Company metadata finding
        meta_parts = [f"SIC: {sic} ({sic_desc})"] if sic else []
        if state:
            meta_parts.append(f"Incorporated: {state}")
        if fiscal_year:
            meta_parts.append(f"Fiscal year ends: {fiscal_year}")
        if tickers:
            meta_parts.append(f"Tickers: {', '.join(tickers)}")
        if exchanges:
            meta_parts.append(f"Exchanges: {', '.join(exchanges)}")
        if ein:
            meta_parts.append(f"EIN: {ein}")

        if meta_parts:
            result.findings.append(Finding(
                source="sec_edgar", category="identity",
                title=f"SEC corporate profile: {vendor_name}",
                detail="\n".join(meta_parts),
                severity="info", confidence=0.95,
                url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
            ))

    except Exception as e:
        logger.debug("SEC EDGAR deep parse error for CIK %s: %s", cik, e)


def _extract_subsidiaries(cik: str, padded_cik: str, forms: list, accessions: list,
                           dates: list, vendor_name: str, result: EnrichmentResult):
    """
    Layer 3: Extract subsidiary list from Exhibit 21 filings.

    SEC rules require public companies to list significant subsidiaries in
    Exhibit 21 of their annual 10-K filing. This data is the authoritative
    source for corporate parent/subsidiary relationships.

    Strategy:
      1. Find the most recent 10-K filing in the recent filings list
      2. Fetch the filing index to find EX-21 attachment
      3. Parse the EX-21 document for subsidiary names and jurisdictions
    """
    # Find the most recent 10-K filing
    annual_filings = [
        (f, d, a.replace("-", "")) for f, d, a in zip(forms, dates, accessions)
        if f == "10-K"
    ]
    if not annual_filings:
        return

    _, filing_date, accession_clean = annual_filings[0]  # Most recent

    # Fetch the filing index to find Exhibit 21
    # Format: https://www.sec.gov/Archives/edgar/data/{CIK}/{accession}/
    index_url = f"https://www.sec.gov/Archives/edgar/data/{padded_cik}/{accession_clean}/"

    import time as _time
    _time.sleep(0.3)  # Rate limit

    index_data = _get(f"{index_url}index.json")
    if not index_data:
        return

    # Look for EX-21 in the filing directory
    directory = index_data.get("directory", {})
    items = directory.get("item", [])

    ex21_doc = None
    for item in items:
        name = item.get("name", "").lower()
        if "ex-21" in name or "ex21" in name or "exhibit21" in name:
            ex21_doc = item.get("name", "")
            break

    if not ex21_doc:
        # Try the companion files API for structured data
        # We already have this data from the main deep parse, so just check
        # recent filings for EX-21 form types
        ex21_filings = [
            (f, d) for f, d in zip(forms, dates) if "EX-21" in f.upper()
        ]
        if not ex21_filings:
            return
        # We found an EX-21 reference but can't get the document directly
        result.findings.append(Finding(
            source="sec_edgar", category="subsidiaries",
            title=f"Exhibit 21 subsidiary filing detected (filed {ex21_filings[0][1]})",
            detail=(
                f"SEC annual filing includes Exhibit 21 (subsidiary list). "
                f"Most recent: {ex21_filings[0][1]}. "
                "Subsidiary extraction requires full-text parse of filing document."
            ),
            severity="info", confidence=0.8,
            raw_data={"has_exhibit_21": True, "filing_date": ex21_filings[0][1]},
        ))
        return

    # Fetch the Exhibit 21 document
    _time.sleep(0.3)
    ex21_url = f"{index_url}{ex21_doc}"

    try:
        req = urllib.request.Request(ex21_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            ex21_text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return

    # Parse subsidiaries from EX-21 text
    # Format varies but typically: "Subsidiary Name    State/Jurisdiction"
    # or HTML tables with subsidiary name and jurisdiction columns
    subsidiaries = _parse_exhibit_21(ex21_text, vendor_name)

    if subsidiaries:
        result.structured_fields["subsidiary_count"] = len(subsidiaries)
        sub_lines = [
            f"  {s['name']} ({s.get('jurisdiction', 'Unknown')})"
            for s in subsidiaries[:20]
        ]
        result.findings.append(Finding(
            source="sec_edgar", category="subsidiaries",
            title=f"Exhibit 21: {len(subsidiaries)} subsidiary/ies identified",
            detail=(
                f"SEC 10-K Exhibit 21 (filed {filing_date}) lists the following subsidiaries:\n"
                + "\n".join(sub_lines)
                + (f"\n  ... and {len(subsidiaries) - 20} more" if len(subsidiaries) > 20 else "")
            ),
            severity="info", confidence=0.9,
            raw_data={
                "subsidiaries": subsidiaries[:50],
                "filing_date": filing_date,
                "total_count": len(subsidiaries),
            },
        ))

        # Store subsidiary relationships for graph ingestion
        for sub in subsidiaries[:30]:
            result.relationships.append({
                "type": "subsidiary_of",
                "entity": sub["name"],
                "jurisdiction": sub.get("jurisdiction", ""),
                "data_source": "sec_edgar_ex21",
                "confidence": 0.9,
            })

        logger.info("Exhibit 21: found %d subsidiaries for %s (CIK %s)", len(subsidiaries), vendor_name, cik)


def _normalize_geo_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _looks_like_exhibit_reference(name: str) -> bool:
    normalized = str(name or "").strip()
    return bool(re.match(r"^EX[-.\s]*21(?:\.\d+)?$", normalized, re.IGNORECASE))


def _looks_like_jurisdiction_label(name: str, jurisdictions: set[str]) -> bool:
    normalized = _normalize_geo_label(name)
    if not normalized:
        return False
    if normalized in jurisdictions:
        return True
    if any(
        phrase in normalized
        for phrase in (
            "republic of",
            "province of",
            "state of",
            "kingdom of",
            "territory of",
        )
    ):
        return True
    return False


def _looks_like_exhibit_21_noise(name: str, jurisdictions: set[str]) -> bool:
    normalized = str(name or "").strip()
    if not normalized:
        return True
    if _looks_like_exhibit_reference(normalized):
        return True
    if _looks_like_jurisdiction_label(normalized, jurisdictions):
        return True
    if re.match(r"^(?:schedule|exhibit|appendix|table)\b", normalized, re.IGNORECASE):
        return True
    return False


def _parse_exhibit_21(text: str, vendor_name: str) -> list[dict]:
    """Parse subsidiary names and jurisdictions from Exhibit 21 text.

    Handles both plain text and HTML formats. Returns list of
    {name, jurisdiction} dicts.

    SEC EDGAR wraps Exhibit 21 in an SGML envelope like:
        <DOCUMENT><TYPE>EX-21<SEQUENCE>7<FILENAME>ex21q42025.htm
        <DESCRIPTION>EX-21<TEXT> ... actual HTML ...
    The parser strips this preamble before processing.
    """
    import html as _html

    placeholder_names = {
        "entity",
        "entity name",
        "name",
        "name of entity",
        "name of subsidiary",
        "subsidiary name",
        "subsidiary",
        "legal entity name",
    }

    # ---- Strip SGML envelope ----
    # Find the <TEXT> marker that precedes actual content
    text_marker = re.search(r"<TEXT>\s*", text, re.IGNORECASE)
    if text_marker:
        text = text[text_marker.end():]
    # Also strip trailing </TEXT></DOCUMENT>
    text = re.sub(r"</TEXT>\s*</DOCUMENT>\s*$", "", text, flags=re.IGNORECASE)

    # ---- Strip HTML tags if present ----
    if "<html" in text.lower() or "<table" in text.lower():
        clean = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        clean = re.sub(r"</?(?:td|th|tr|p|div|span)[^>]*>", "\n", clean, flags=re.IGNORECASE)
        clean = re.sub(r"<[^>]+>", "", clean)
        clean = _html.unescape(clean)
    else:
        clean = text

    # Normalize whitespace artifacts
    clean = clean.replace("\xa0", " ")  # non-breaking space
    clean = re.sub(r"&#160;", " ", clean)

    lines = clean.split("\n")
    subsidiaries = []
    seen_names = set()
    vendor_upper = vendor_name.upper()

    # Known jurisdiction values for matching standalone jurisdiction lines
    _JURISDICTIONS = {
        "delaware", "nevada", "california", "new york", "texas", "maryland",
        "virginia", "florida", "illinois", "ohio", "pennsylvania", "georgia",
        "new jersey", "massachusetts", "north carolina", "washington",
        "colorado", "connecticut", "michigan", "minnesota", "missouri",
        "wisconsin", "arizona", "indiana", "oregon", "tennessee", "utah",
        "district of columbia", "ontario",
        "united kingdom", "uk", "england", "canada", "germany", "france",
        "japan", "australia", "india", "ireland", "netherlands", "singapore",
        "switzerland", "cayman islands", "british virgin islands", "bermuda",
        "brazil", "china", "south korea", "israel", "italy", "poland",
        "spain", "sweden", "mexico", "hong kong", "taiwan",
    }

    jurisdiction_labels = {_normalize_geo_label(item) for item in _JURISDICTIONS}

    # First pass: collect candidate lines (skip obvious non-data lines)
    candidate_lines = []
    for line in lines:
        line = line.strip()
        if not line or len(line) < 3 or len(line) > 200:
            continue
        # Skip header/footer lines
        if any(h in line.lower() for h in (
            "exhibit", "subsidiaries of", "name of", "jurisdiction",
            "state of", "place of", "------", "======",
            "significant", "registrant", "regulation s-k",
            "consolidated", "financial statements", "item 601",
            "rule 1-02", "document", "in accordance", "entity name",
        )):
            continue
        # Skip lines that are just the parent company
        if line.upper().startswith(vendor_upper[:20]):
            continue
        # Skip filenames and purely numeric lines
        if re.match(r"^[\d.]+$", line) or re.match(r"^.+\.(htm|html|txt|xml)$", line, re.I):
            continue
        if _looks_like_exhibit_reference(line):
            continue
        if re.match(r"^(?:schedule|appendix|table)\b", line, re.IGNORECASE):
            continue
        candidate_lines.append(line)

    # Second pass: pair names with jurisdictions
    # SEC Exhibit 21 often alternates: subsidiary name, then jurisdiction on next line
    i = 0
    while i < len(candidate_lines):
        line = candidate_lines[i]

        # Check if this line is itself a standalone jurisdiction
        if _looks_like_jurisdiction_label(line, jurisdiction_labels):
            i += 1
            continue

        # Try to split inline: name   jurisdiction (tab or multi-space separated)
        parts = re.split(r"\s{3,}|\t|\|", line, maxsplit=1)
        name = parts[0].strip().rstrip(",").rstrip(".")
        jurisdiction = ""

        if len(parts) > 1:
            jurisdiction = parts[1].strip().rstrip(",").rstrip(".")
        else:
            # Check parenthesized jurisdiction: "Name (Delaware)"
            j_match = re.search(r"\(([^)]+)\)\s*$", name)
            if j_match:
                jurisdiction = j_match.group(1)
                name = name[:j_match.start()].strip()

        # If no jurisdiction found inline, peek at next line
        if not jurisdiction and i + 1 < len(candidate_lines):
            next_line = candidate_lines[i + 1].strip()
            if _looks_like_jurisdiction_label(next_line, jurisdiction_labels):
                jurisdiction = next_line
                i += 1  # consume the jurisdiction line

        # Validate entity name
        if not name or len(name) < 3:
            i += 1
            continue
        if not re.search(r"[A-Za-z]", name):
            i += 1
            continue
        if name.lower() in ("none", "n/a", "not applicable", "total", "end"):
            i += 1
            continue
        if name.lower() in placeholder_names:
            i += 1
            continue
        if _looks_like_exhibit_21_noise(name, jurisdiction_labels):
            i += 1
            continue

        name_upper = name.upper()
        if name_upper not in seen_names:
            seen_names.add(name_upper)
            subsidiaries.append({
                "name": name,
                "jurisdiction": jurisdiction or "Unknown",
            })

        i += 1

    return subsidiaries


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query SEC EDGAR full-text search API for company intelligence."""
    t0 = time.time()
    result = EnrichmentResult(source="sec_edgar", vendor_name=vendor_name)

    try:
        # LIVE API call: Full-text search for filings
        encoded_name = urllib.parse.quote(f'"{vendor_name}"')
        url = (
            f"{EFTS}/search-index"
            f"?q={encoded_name}"
            f"&forms=10-K,10-Q,8-K,DEF+14A"
            f"&from=0"
            f"&size=5"
        )

        data = _get(url)

        if not data or "hits" not in data:
            result.findings.append(Finding(
                source="sec_edgar", category="identity",
                title="No SEC filings found",
                detail=f"No EDGAR filings found for '{vendor_name}'. Entity may be private, foreign, or non-reporting.",
                severity="medium", confidence=0.8,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        hits = data.get("hits", {}).get("hits", [])

        if not hits:
            result.findings.append(Finding(
                source="sec_edgar", category="identity",
                title="No SEC filings found",
                detail=f"No EDGAR filings found for '{vendor_name}'.",
                severity="medium", confidence=0.7,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Process results -- validate CIK ownership before accepting
        seen_ciks = set()
        best_cik = None
        best_cik_score = 0.0
        best_cik_name = ""
        matched_form_types: list[str] = []

        for hit in hits:
            src = hit.get("_source", {})
            ciks = src.get("ciks", [])
            display_names = src.get("display_names", [])
            file_date = src.get("file_date", "")
            form_type = src.get("form", "")
            company_name = src.get("company_name", "")
            file_num = src.get("file_num", "")

            cik = ciks[0].lstrip("0") if ciks else ""

            if not cik or cik in seen_ciks:
                continue

            seen_ciks.add(cik)

            # Validate CIK belongs to the vendor we're assessing
            filing_entity = company_name or (display_names[0] if display_names else "")
            name_score = _name_match_score(vendor_name, filing_entity) if filing_entity else 0.0

            # Track the best-matching CIK
            if name_score > best_cik_score:
                best_cik_score = name_score
                best_cik = cik
                best_cik_name = filing_entity

            # Only set as primary CIK if name match is strong enough
            if not result.identifiers.get("cik") and name_score >= 0.65:
                result.identifiers["cik"] = cik
                result.identifiers["cik_confidence"] = "high"
                logger.info("SEC EDGAR: accepted CIK %s for '%s' (filing entity: '%s', score: %.0f%%)",
                           cik, vendor_name, filing_entity, name_score * 100)
            if name_score >= 0.65:
                matched_form_types.append(form_type)

            # Create finding for company/filing
            display_name = company_name or (display_names[0] if display_names else "") or vendor_name
            title_text = f"{display_name} - {form_type} ({file_date})"
            detail_parts = [
                f"CIK: {cik}",
                f"Company: {company_name}",
                f"Form: {form_type}",
                f"Filing Date: {file_date}",
                f"File Number: {file_num}",
            ]

            severity_map = {
                "10-K": "info",
                "10-Q": "info",
                "8-K": "low",
                "DEF 14A": "info",
            }
            severity = severity_map.get(form_type, "info")

            result.findings.append(Finding(
                source="sec_edgar", category="identity",
                title=title_text,
                detail="\n".join(detail_parts),
                severity=severity, confidence=0.95,
                url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
                raw_data={"cik": cik, "form": form_type, "date": file_date},
            ))

        # Treat SEC public-company evidence as valid only when the filings belong
        # to the matched vendor, not merely some related counterparty in search hits.
        form_types_found = matched_form_types
        if "10-K" in form_types_found or "10-Q" in form_types_found or "DEF 14A" in form_types_found:
            result.identifiers["publicly_traded"] = True

        # Risk signal: 8-K filings (material events)
        if "8-K" in form_types_found:
            result.risk_signals.append({
                "signal": "sec_8k_filing",
                "severity": "low",
                "detail": "Entity has recent 8-K material event disclosure(s)",
            })

        # Risk signal: DEF 14A (proxy statements indicate public company)
        if "DEF 14A" in form_types_found:
            result.risk_signals.append({
                "signal": "sec_def14a_proxy",
                "severity": "info",
                "detail": "Entity has proxy statement (DEF 14A) on file",
            })

        # If no CIK passed validation, use best match with a warning
        if not result.identifiers.get("cik") and best_cik:
            if best_cik_score >= 0.5:
                logger.warning(
                    "SEC EDGAR: no strong CIK match for '%s'. Best: CIK %s ('%s', score: %.0f%%). Using with caution.",
                    vendor_name, best_cik, best_cik_name, best_cik_score * 100,
                )
                result.identifiers["cik"] = best_cik
                result.identifiers["cik_confidence"] = "low"
            else:
                logger.info("SEC EDGAR: no CIK match for '%s' above threshold. Best was %.0f%%.",
                           vendor_name, best_cik_score * 100)

        # Deep parsing: extract officers/executives from company data
        cik = result.identifiers.get("cik")
        if cik and result.identifiers.get("cik_confidence") != "low":
            _deep_parse_company(cik, vendor_name, result)

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
