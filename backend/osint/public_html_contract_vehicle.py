"""Public HTML contract-vehicle lineage connector.

This connector is deliberately narrow:
  - only reads analyst-provided public or archived pages
  - does not perform discovery, search automation, or crawling
  - extracts lineage and customer signals with deterministic patterns

It is meant to be a cheap, local-first bridge from replayable fixtures to live
public-page collection while preserving the existing provider-neutral import
contract.
"""

from __future__ import annotations

import html
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from requests import exceptions as requests_exceptions

from http_trust import resolve_verify_target

from . import EnrichmentResult, Finding


SOURCE_NAME = "public_html_contract_vehicle"
REPO_ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 12
MAX_PAGES = 8
USER_AGENT = "Helios/5.2 (+https://xiphosllc.com)"
PAGE_KEYS = (
    "contract_vehicle_page",
    "contract_vehicle_pages",
    "contract_vehicle_public_html_page",
    "contract_vehicle_public_html_pages",
    "contract_vehicle_public_html_fixture_page",
    "contract_vehicle_public_html_fixture_pages",
)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
SCRIPT_STYLE = re.compile(r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>", re.IGNORECASE | re.DOTALL)
TAGS = re.compile(r"<[^>]+>")
WHITESPACE = re.compile(r"\s+")
TITLE_PATTERN = re.compile(r"<title[^>]*>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)

_ENTITY_PATTERN = r"(?P<entity>[A-Z][A-Za-z0-9/&().,' -]{2,120}?)"
_SIGNALS: tuple[tuple[re.Pattern[str], str, float, str], ...] = (
    (
        re.compile(
            rf"\b(?:awarded|issued|placed)\s+under\s+{_ENTITY_PATTERN}(?=[.;,]|\s+(?:for|to|with|at|and)\b|$)",
            re.IGNORECASE,
        ),
        "awarded_under",
        0.78,
        "Awarded under",
    ),
    (
        re.compile(
            rf"\b(?:contract|vehicle)\s+family\s*[:\-]\s*{_ENTITY_PATTERN}(?=[.;,]|$)",
            re.IGNORECASE,
        ),
        "awarded_under",
        0.72,
        "Contract vehicle family",
    ),
    (
        re.compile(
            rf"\b(?:follow[- ]on to|recompete of|bridge from|predecessor)\s*[:\-]?\s*{_ENTITY_PATTERN}(?=[.;,]|\s+(?:for|with|supporting|at|and)\b|$)",
            re.IGNORECASE,
        ),
        "predecessor_of",
        0.82,
        "Predecessor signal",
    ),
    (
        re.compile(
            rf"\b(?:succeeded by|followed by|replacement vehicle)\s*[:\-]?\s*{_ENTITY_PATTERN}(?=[.;,]|$)",
            re.IGNORECASE,
        ),
        "successor_of",
        0.80,
        "Successor signal",
    ),
    (
        re.compile(
            rf"\b(?:customer|sponsor|requiring activity|program office|mission owner)\s*[:\-]\s*{_ENTITY_PATTERN}(?=[.;,]|$)",
            re.IGNORECASE,
        ),
        "funded_by",
        0.74,
        "Customer signal",
    ),
    (
        re.compile(
            rf"\b(?:place of performance|performance location|performed at)\s*[:\-]\s*{_ENTITY_PATTERN}(?=[.;,]|$)",
            re.IGNORECASE,
        ),
        "performed_at",
        0.70,
        "Performance signal",
    ),
)


def _verify_ssl() -> bool | str:
    return resolve_verify_target(
        verify_env="XIPHOS_PUBLIC_HTML_VERIFY_SSL",
        bundle_envs=("XIPHOS_PUBLIC_HTML_CA_BUNDLE",),
    )


def _normalize_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _normalize_page(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    if "://" not in candidate and not candidate.startswith("file:"):
        resolved = (REPO_ROOT / candidate).resolve()
        if resolved.exists():
            return resolved.as_uri()
        if candidate.startswith("www."):
            return f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https", "file"}:
        return candidate
    return ""


def _resolve_pages(ids: dict[str, Any]) -> list[str]:
    raw_values: list[str] = []
    for key in PAGE_KEYS:
        raw = ids.get(key)
        if isinstance(raw, str):
            raw_values.append(raw)
        elif isinstance(raw, (list, tuple, set)):
            raw_values.extend(str(item or "") for item in raw)

    pages: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        normalized = _normalize_page(raw)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        pages.append(normalized)
    return pages[:MAX_PAGES]


def _authority_for_page(page_url: str) -> tuple[str, str]:
    parsed = urlparse(page_url)
    if parsed.scheme == "file":
        return "analyst_curated_fixture", "local_html_fixture"
    host = (parsed.netloc or "").lower()
    if host.endswith(".gov") or host == "sam.gov":
        return "official_program_system", "public_html"
    if "web.archive.org" in host:
        return "third_party_public", "public_archive"
    return "third_party_public", "public_html"


def _fetch_page(page_url: str) -> tuple[str, str]:
    parsed = urlparse(page_url)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
        return path.read_text(encoding="utf-8"), page_url

    response = requests.get(
        page_url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=TIMEOUT,
        verify=_verify_ssl(),
    )
    response.raise_for_status()
    return response.text, str(response.url)


def _extract_text(markup: str) -> str:
    if not markup:
        return ""
    cleaned = HTML_COMMENT.sub(" ", markup)
    cleaned = SCRIPT_STYLE.sub(" ", cleaned)
    cleaned = TAGS.sub(" ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = WHITESPACE.sub(" ", cleaned)
    return cleaned.strip()


def _extract_title(markup: str) -> str:
    match = TITLE_PATTERN.search(markup or "")
    if not match:
        return ""
    return WHITESPACE.sub(" ", html.unescape(match.group("title") or "")).strip()


def _clean_entity_name(raw_name: str) -> str:
    text = str(raw_name or "").strip(" ,.;:-")
    text = re.split(r"\s+(?:for|to|with|under|at|and|which|that)\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.split(r"[|•·]", text, maxsplit=1)[0]
    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")
    return text


def _extract_sentence(text: str, start: int, end: int) -> str:
    left = text.rfind(".", 0, start)
    right_candidates = [text.find(".", end), text.find(";", end)]
    right = min((idx for idx in right_candidates if idx != -1), default=-1)
    snippet_start = 0 if left == -1 else left + 1
    snippet_end = len(text) if right == -1 else right + 1
    snippet = text[snippet_start:snippet_end].strip()
    return snippet or text[max(0, start - 80): min(len(text), end + 120)].strip()


def _relationship_orientation(rel_type: str, vehicle_name: str, entity_name: str) -> tuple[str, str]:
    if rel_type == "successor_of":
        return vehicle_name, entity_name
    return entity_name, vehicle_name


def enrich(vendor_name: str, **ids) -> EnrichmentResult:
    started = time.perf_counter()
    pages = _resolve_pages(ids)
    result = EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        source_class="public_connector",
        authority_level="third_party_public",
        access_model="public_html",
    )
    if not pages:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    relationships_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    findings: list[Finding] = []
    artifact_refs: list[str] = []
    successful_pages = 0
    errors: list[str] = []

    for page_url in pages:
        try:
            markup, resolved_page_url = _fetch_page(page_url)
        except requests_exceptions.SSLError as exc:
            errors.append(
                f"{page_url}: {exc}. Set XIPHOS_PUBLIC_HTML_CA_BUNDLE, REQUESTS_CA_BUNDLE, or SSL_CERT_FILE if your network uses a custom trust chain."
            )
            continue
        except (OSError, requests.RequestException) as exc:
            errors.append(f"{page_url}: {exc}")
            continue

        successful_pages += 1
        artifact_refs.append(resolved_page_url)
        page_title = _extract_title(markup)
        text = _extract_text(markup)
        authority_level, access_model = _authority_for_page(resolved_page_url)

        if not text:
            continue

        for pattern, rel_type, confidence, label in _SIGNALS:
            for match in pattern.finditer(text):
                entity_name = _clean_entity_name(match.group("entity"))
                if not entity_name:
                    continue
                normalized_entity = _normalize_name(entity_name)
                normalized_vehicle = _normalize_name(vendor_name)
                if not normalized_entity or normalized_entity == normalized_vehicle:
                    continue
                source_name, target_name = _relationship_orientation(rel_type, vendor_name, entity_name)
                sentence = _extract_sentence(text, match.start(), match.end())
                key = (rel_type, _normalize_name(source_name), _normalize_name(target_name))
                record = relationships_by_key.get(key)
                if record is None:
                    record = {
                        "rel_type": rel_type,
                        "source_name": source_name,
                        "target_name": target_name,
                        "data_source": SOURCE_NAME,
                        "data_sources": [SOURCE_NAME],
                        "corroboration_count": 0,
                        "intelligence_tier": "supported" if confidence >= 0.72 else "tentative",
                        "evidence": sentence,
                        "evidence_summary": sentence,
                        "observed_at": "",
                        "source_urls": [],
                        "source_notes": [],
                        "source_class": "public_connector",
                        "authority_level": authority_level,
                        "access_model": access_model,
                    }
                    relationships_by_key[key] = record
                record["corroboration_count"] += 1
                if resolved_page_url not in record["source_urls"]:
                    record["source_urls"].append(resolved_page_url)
                note_parts = [label]
                if page_title:
                    note_parts.append(page_title)
                note = " | ".join(note_parts)
                if note not in record["source_notes"]:
                    record["source_notes"].append(note)
                if len(sentence) > len(str(record.get("evidence_summary") or "")):
                    record["evidence"] = sentence
                    record["evidence_summary"] = sentence
                record["authority_level"] = authority_level
                record["access_model"] = access_model

    for relationship in relationships_by_key.values():
        artifact_ref = next(iter(relationship.get("source_urls") or []), "")
        counterpart = relationship["source_name"] if _normalize_name(relationship["target_name"]) == _normalize_name(vendor_name) else relationship["target_name"]
        signal = relationship["rel_type"].replace("_", " ")
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category="vehicle_lineage",
                title=f"Public vehicle signal: {signal} {counterpart}",
                detail=str(relationship.get("evidence_summary") or ""),
                severity="info",
                confidence=0.72 if relationship["intelligence_tier"] == "supported" else 0.58,
                url=artifact_ref,
                raw_data={
                    "relationship_type": relationship["rel_type"],
                    "vehicle_name": vendor_name,
                    "source_name": relationship["source_name"],
                    "target_name": relationship["target_name"],
                    "corroboration_count": relationship["corroboration_count"],
                },
                source_class="public_connector",
                authority_level=str(relationship.get("authority_level") or "third_party_public"),
                access_model=str(relationship.get("access_model") or "public_html"),
                artifact_ref=artifact_ref,
                structured_fields={
                    "relationship_type": relationship["rel_type"],
                    "vehicle_name": vendor_name,
                    "corroboration_count": relationship["corroboration_count"],
                },
            )
        )

    if successful_pages == 0 and errors:
        result.error = errors[0][:400]
    elif errors:
        result.structured_fields["partial_errors"] = errors[:4]

    result.relationships = list(relationships_by_key.values())
    result.findings = findings
    result.artifact_refs = list(dict.fromkeys(artifact_refs))
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    if result.relationships:
        max_authority = next(
            (
                rel.get("authority_level")
                for rel in result.relationships
                if rel.get("authority_level") in {"official_program_system", "analyst_curated_fixture"}
            ),
            "third_party_public",
        )
        result.authority_level = str(max_authority)
        result.access_model = str(result.relationships[0].get("access_model") or "public_html")
    result.structured_fields.update(
        {
            "page_count": len(pages),
            "successful_pages": successful_pages,
        }
    )
    return result
