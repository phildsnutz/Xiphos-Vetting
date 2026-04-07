"""Seeded public GAO bid protest collector using browser-render capture."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import EnrichmentResult, Finding
from .browser_render import capture_rendered_html


SOURCE_NAME = "gao_bid_protests_public"
REPO_ROOT = Path(__file__).resolve().parents[2]
URL_KEYS = (
    "gao_public_url",
    "gao_public_urls",
    "gao_docket_url",
    "gao_docket_urls",
    "gao_decision_url",
    "gao_decision_urls",
    "gao_bid_protest_url",
    "gao_bid_protest_urls",
    "gao_public_html_fixture_page",
    "gao_public_html_fixture_pages",
)
FIELD_LABELS = (
    "Protester",
    "Solicitation Number",
    "Agency",
    "File number",
    "Outcome",
    "Decision Date",
    "Filed Date",
    "Due Date",
    "Case Type",
    "GAO Attorney",
)
OUTCOME_MAP = (
    ("corrective action", "corrective_action"),
    ("sustain", "sustained"),
    ("deny", "denied"),
    ("dismiss", "dismissed"),
)
_ENABLE_VALUES = {"1", "true", "yes", "on"}


def _live_capture_enabled() -> bool:
    raw = str(os.environ.get("XIPHOS_ENABLE_GAO_BROWSER_CAPTURE") or "").strip().lower()
    return raw in _ENABLE_VALUES


def _resolve_urls(ids: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in URL_KEYS:
        raw = ids.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, (list, tuple, set)):
            values.extend(str(item or "") for item in raw)
    urls: list[str] = []
    seen: set[str] = set()
    for raw in values:
        candidate = str(raw or "").strip()
        if not candidate:
            continue
        if "://" not in candidate and not candidate.startswith("file:"):
            path = Path(candidate)
            if not path.is_absolute():
                path = (REPO_ROOT / candidate).resolve()
            if path.exists():
                candidate = path.as_uri()
        if candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _main_text(soup: BeautifulSoup) -> str:
    main = soup.find("main") or soup
    return _normalize_text(main.get_text(" ", strip=True))


def _page_title(soup: BeautifulSoup) -> str:
    node = soup.find("h1") or soup.find("title")
    if node is None:
        return ""
    return _normalize_text(node.get_text(" ", strip=True))


def _extract_labeled_value(text: str, label: str, next_labels: list[str]) -> str:
    lookahead = "|".join(re.escape(item) for item in next_labels if item)
    pattern = re.compile(
        rf"{re.escape(label)}\s+(?P<value>.*?)(?=\s+(?:{lookahead})\s+|$)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    return _normalize_text(match.group("value")) if match else ""


def _classify_outcome(text: str) -> str:
    lowered = text.lower()
    for needle, label in OUTCOME_MAP:
        if needle in lowered:
            return label
    return "observed"


def _parse_docket(soup: BeautifulSoup, page_url: str) -> dict[str, Any]:
    text = _main_text(soup)
    title = _page_title(soup)
    data: dict[str, str] = {}
    ordered = list(FIELD_LABELS)
    for index, label in enumerate(ordered):
        data[label] = _extract_labeled_value(text, label, ordered[index + 1 :])

    file_number = data.get("File number") or ""
    outcome_text = data.get("Outcome") or ""
    decision_date = data.get("Decision Date") or ""
    filed_date = data.get("Filed Date") or ""
    agency = data.get("Agency") or ""
    protester = data.get("Protester") or title or "GAO protester"
    solicitation_number = data.get("Solicitation Number") or ""
    status = _classify_outcome(outcome_text)
    detail_bits = [
        f"GAO docket lists {protester}" if protester else "GAO docket captured",
        f"against {agency}" if agency else "",
        f"under solicitation {solicitation_number}" if solicitation_number else "",
        f"with outcome {outcome_text}" if outcome_text else "",
    ]
    detail = " ".join(bit for bit in detail_bits if bit).strip()
    return {
        "title": title or f"GAO docket {file_number or protester}",
        "detail": detail,
        "status": status,
        "forum": "GAO",
        "event_id": file_number,
        "protester": protester,
        "agency": agency,
        "solicitation_number": solicitation_number,
        "decision_date": decision_date,
        "filed_date": filed_date,
        "due_date": data.get("Due Date") or "",
        "case_type": data.get("Case Type") or "",
        "gao_attorney": data.get("GAO Attorney") or "",
        "page_type": "docket",
        "url": page_url,
    }


def _decision_paragraphs(soup: BeautifulSoup) -> list[str]:
    main = soup.find("main") or soup
    return [
        _normalize_text(node.get_text(" ", strip=True))
        for node in main.find_all(["p", "li"])
        if _normalize_text(node.get_text(" ", strip=True))
    ]


def _first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    return _normalize_text(match.group(1)) if match else ""


def _extract_solicitation_number(text: str) -> str:
    patterns = (
        r"request for proposals\s*\(RFP\)\s*No\.?\s*([A-Z0-9][A-Z0-9\-]{5,})",
        r"(?:RFP|RFQ|IFB)\s+No\.?\s*([A-Z0-9][A-Z0-9\-]{5,})",
        r"under\s+solicitation\s+No\.?\s*([A-Z0-9][A-Z0-9\-]{5,})",
        r"solicitation\s+No\.?\s*([A-Z0-9][A-Z0-9\-]{5,})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return _normalize_text(match.group(1))
    return ""


def _decision_outcome(paragraphs: list[str]) -> tuple[str, str]:
    joined = " ".join(paragraphs[:40])
    for phrase, label in (
        ("We sustain the protest.", "sustained"),
        ("We deny the protest.", "denied"),
        ("We dismiss the protest.", "dismissed"),
        ("The protest is sustained.", "sustained"),
        ("The protest is denied.", "denied"),
        ("The protest is dismissed.", "dismissed"),
        ("We dismiss in part and deny in part the protest.", "dismissed_in_part_denied_in_part"),
        ("We sustain in part and deny in part the protest.", "sustained_in_part_denied_in_part"),
    ):
        if phrase.lower() in joined.lower():
            return label, phrase
    return "observed", ""


def _parse_decision(soup: BeautifulSoup, page_url: str) -> dict[str, Any]:
    paragraphs = _decision_paragraphs(soup)
    joined = " ".join(paragraphs[:120])
    title = _page_title(soup)
    protester = _first_match(r"Matter of:\s*(.*?)\s+File:", joined) or title
    file_number = _first_match(r"File:\s*(B-[A-Za-z0-9.\-]+)", joined)
    decision_date = _first_match(r"Date:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})", joined)
    solicitation_number = _extract_solicitation_number(joined)
    agency = _first_match(r"issued by the ([A-Z][A-Za-z0-9,&() .:\-]{3,140}?)(?:,|\s+for\b)", joined)
    if not agency:
        agency = _first_match(r"issued by ([A-Z][A-Za-z0-9,&() .:\-]{3,140}?)(?:,|\s+for\b)", joined)
    status, outcome_sentence = _decision_outcome(paragraphs)
    digest = ""
    if "DIGEST" in paragraphs:
        idx = paragraphs.index("DIGEST")
        digest = " ".join(paragraphs[idx + 1 : idx + 3]).strip()
    decision_summary = ""
    if "DECISION" in paragraphs:
        idx = paragraphs.index("DECISION")
        decision_summary = " ".join(paragraphs[idx + 1 : idx + 3]).strip()
    detail = digest or decision_summary or outcome_sentence or _normalize_text(" ".join(paragraphs[:3]))
    return {
        "title": title or protester or file_number or "GAO protest decision",
        "detail": detail,
        "status": status,
        "forum": "GAO",
        "event_id": file_number,
        "protester": protester,
        "agency": agency,
        "solicitation_number": solicitation_number,
        "decision_date": decision_date,
        "filed_date": "",
        "due_date": "",
        "case_type": "Bid Protest",
        "gao_attorney": "",
        "page_type": "decision",
        "url": page_url,
    }


def _parse_page(html_text: str, page_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html_text, "html.parser")
    parsed = urlparse(page_url)
    text = _main_text(soup)
    is_docket = "/docket/" in parsed.path or all(label in text for label in ("Protester", "Outcome", "Filed Date"))
    if is_docket:
        return _parse_docket(soup, page_url)
    return _parse_decision(soup, page_url)


def enrich(vendor_name: str, **ids) -> EnrichmentResult:
    started = time.perf_counter()
    urls = _resolve_urls(ids)
    result = EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        source_class="public_connector",
        authority_level="official_program_system",
        access_model="browser_rendered_public_html",
    )
    if not urls:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    findings: list[Finding] = []
    partial_errors: list[str] = []
    artifact_refs: list[str] = []
    for url in urls:
        try:
            is_file = urlparse(url).scheme == "file"
            if not is_file and not _live_capture_enabled():
                partial_errors.append(
                    f"{url}: live GAO browser capture is disabled. "
                    "Provide gao_public_html_fixture_pages or set XIPHOS_ENABLE_GAO_BROWSER_CAPTURE=1 for local operator capture."
                )
                continue
            html_text, final_url = capture_rendered_html(url)
            artifact_refs.append(final_url)
            event = _parse_page(html_text, final_url)
            findings.append(
                Finding(
                    source=SOURCE_NAME,
                    category="bid_protest",
                    title=str(event.get("title") or "GAO bid protest"),
                    detail=str(event.get("detail") or ""),
                    severity="medium",
                    confidence=0.82 if event.get("page_type") == "decision" else 0.76,
                    url=final_url,
                    raw_data={
                        "vehicle_name": vendor_name,
                        "event_id": event.get("event_id", ""),
                        "status": event.get("status", ""),
                        "forum": event.get("forum", "GAO"),
                        "protester": event.get("protester", ""),
                        "agency": event.get("agency", ""),
                        "solicitation_number": event.get("solicitation_number", ""),
                        "decision_date": event.get("decision_date", ""),
                        "filed_date": event.get("filed_date", ""),
                        "due_date": event.get("due_date", ""),
                        "case_type": event.get("case_type", ""),
                        "gao_attorney": event.get("gao_attorney", ""),
                        "page_type": event.get("page_type", ""),
                        "assessment": event.get("detail", ""),
                    },
                    source_class="public_connector",
                    authority_level="official_program_system",
                    access_model="browser_rendered_public_html" if urlparse(final_url).scheme != "file" else "local_html_fixture",
                    artifact_ref=final_url,
                    structured_fields={
                        "vehicle_name": vendor_name,
                        "event_id": event.get("event_id", ""),
                        "status": event.get("status", ""),
                        "page_type": event.get("page_type", ""),
                    },
                )
            )
        except Exception as exc:
            partial_errors.append(f"{url}: {exc}")

    result.findings = findings
    result.artifact_refs = list(dict.fromkeys(artifact_refs))
    if partial_errors and not findings:
        result.error = partial_errors[0][:400]
    elif partial_errors:
        result.structured_fields["partial_errors"] = partial_errors[:4]
    result.structured_fields["page_count"] = len(urls)
    result.structured_fields["successful_pages"] = len(findings)
    result.structured_fields["live_capture_enabled"] = _live_capture_enabled()
    result.structured_fields["capture_mode"] = "artifact_first_browser_helper"
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
