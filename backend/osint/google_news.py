"""
Google News RSS Connector

Free RSS feed, no auth required.
Fetches recent news articles about a vendor from Google News.
Complements GDELT with more consumer-facing coverage.

Source: https://news.google.com/rss
"""

from datetime import datetime
import re
from urllib.parse import quote

import requests
import xml.etree.ElementTree as ET

from . import EnrichmentResult, Finding

TIMEOUT = 20
MAX_QUERY_VARIANTS = 5
LEGAL_SUFFIXES = (
    " Inc",
    " Inc.",
    " LLC",
    " L.L.C.",
    " Corp",
    " Corp.",
    " Ltd",
    " Ltd.",
    " PLC",
    " SA",
    " AG",
    " GmbH",
    " Company",
)
TRAILING_JURISDICTION_SUFFIXES = (
    " US",
    " U.S.",
    " U.S.A.",
    " USA",
    " UK",
    " U.K.",
    " EU",
)

# Try to load ML classifier (graceful fallback to keyword matching if unavailable)
_ml_available = False
_ml_classify = None
try:
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from ml.inference import is_model_available, classify_finding
    if is_model_available():
        _ml_available = True
        _ml_classify = classify_finding
except Exception:
    pass


def _clean_entity_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" -|,:;.")
    text = re.sub(
        r".*\b(?:joins?|joined|appoints?|appointed|names?|named|adds?|added|hires?|hired)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.split(r"\s+(?:for|to|in|after|amid|as)\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    return text.strip(" -|,:;.")


def _query_variants(vendor_name: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = _clean_entity_name(value)
        if len(text) < 3:
            return
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        candidates.append(text)

    raw_name = str(vendor_name or "").strip()
    add(raw_name)
    for segment in re.split(r"\s*[|/]\s*", raw_name):
        add(segment)

    snapshot = list(candidates)
    for candidate in snapshot:
        simplified = candidate
        for suffix in LEGAL_SUFFIXES:
            simplified = re.sub(rf"{re.escape(suffix)}$", "", simplified, flags=re.IGNORECASE).strip()
        for suffix in TRAILING_JURISDICTION_SUFFIXES:
            simplified = re.sub(rf"{re.escape(suffix)}$", "", simplified, flags=re.IGNORECASE).strip()
        add(simplified)

        if candidate.endswith("Laboratories"):
            add(candidate.replace("Laboratories", "Labs"))
        if candidate.endswith("Labs"):
            add(candidate.replace("Labs", "Laboratories"))

    ranked = sorted(
        candidates,
        key=lambda value: (
            "/" in value or "|" in value,
            len(value) <= 4 and " " not in value,
            -len(value),
            value.casefold(),
        ),
    )
    return ranked[:MAX_QUERY_VARIANTS]


def _title_relevance(title: str, vendor_names: list[str]) -> int:
    lowered = str(title or "").casefold()
    best = 0
    for vendor_name in vendor_names:
        candidate = vendor_name.casefold()
        if candidate and candidate in lowered:
            best = max(best, len(candidate))
    return best


def _build_media_ownership_relationship(
    *,
    vendor_name: str,
    target_name: str,
    rel_type: str,
    confidence: float,
    title: str,
    link: str,
    source_name: str,
    detection_method: str,
) -> dict:
    return {
        "type": rel_type,
        "source_entity": vendor_name,
        "source_entity_type": "company",
        "source_identifiers": {},
        "target_entity": target_name,
        "target_entity_type": "holding_company",
        "target_identifiers": {},
        "country": "",
        "data_source": "google_news",
        "confidence": confidence,
        "evidence": title,
        "observed_at": datetime.utcnow().isoformat() + "Z",
        "artifact_ref": f"google-news://{vendor_name}/{detection_method}/{target_name}",
        "evidence_url": link,
        "evidence_title": title,
        "structured_fields": {
            "relationship_scope": "media_reported_control" if rel_type == "owned_by" else "media_reported_financing",
            "detection_method": detection_method,
            "source_name": source_name,
        },
        "source_class": "public_connector",
        "authority_level": "third_party_public",
        "access_model": "rss_public",
    }


def _extract_control_signal(vendor_names: list[str], title: str) -> tuple[str, str, float, str] | None:
    title_clean = " ".join(str(title or "").split())

    for vendor_name in vendor_names:
        escaped_vendor = re.escape(vendor_name)
        patterns = [
            (
                rf"^(?P<owner>.+?)\s+(?:(?:to|will|plans?\s+to)\s+)?acquires?\s+(?:(?:[A-Za-z][A-Za-z-]*|[A-Za-z]+-based)\s+){{0,4}}{escaped_vendor}\b",
                "owned_by",
                0.66,
                "rss_title_acquires_vendor",
            ),
            (
                rf"\b{escaped_vendor}\b\s+acquired by\s+(?P<owner>.+)$",
                "owned_by",
                0.70,
                "rss_title_acquired_by",
            ),
            (
                rf"\b{escaped_vendor}\b,\s+a subsidiary of\s+(?P<owner>.+)$",
                "owned_by",
                0.72,
                "rss_title_subsidiary_of",
            ),
            (
                rf"\b{escaped_vendor}\b\s+is part of\s+(?P<owner>.+)$",
                "owned_by",
                0.68,
                "rss_title_part_of",
            ),
            (
                rf"(?:^|\b(?:joins?|joined|appoints?|appointed|names?|named|adds?|added|hires?|hired)\s+)(?P<owner>[A-Z][A-Za-z0-9&.,'()/ -]{{2,90}})-backed\s+{escaped_vendor}\b",
                "backed_by",
                0.62,
                "rss_title_backed_vendor",
            ),
            (
                rf"(?P<owner>[A-Z][A-Za-z0-9&.,'()/ -]{{2,90}})\s+invests? in(?:.+?)\b{escaped_vendor}\b",
                "backed_by",
                0.64,
                "rss_title_invests_in_vendor",
            ),
            (
                rf"\b{escaped_vendor}\b(?:.+?)\bbacked by\s+(?P<owner>[A-Z][A-Za-z0-9&.,'()/ -]{{2,90}})",
                "backed_by",
                0.60,
                "rss_title_vendor_backed_by",
            ),
        ]

        for pattern, rel_type, confidence, detection_method in patterns:
            match = re.search(pattern, title_clean, re.IGNORECASE)
            if not match:
                continue
            owner_name = _clean_entity_name(match.group("owner"))
            if owner_name and owner_name.casefold() != vendor_name.casefold():
                return owner_name, rel_type, confidence, detection_method
    return None


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    result = EnrichmentResult(source="google_news", vendor_name=vendor_name)
    start = datetime.now()

    try:
        items = []
        seen_items: set[tuple[str, str]] = set()
        query_variants = _query_variants(vendor_name)
        for query_name in query_variants:
            encoded = quote(f'"{query_name}"')
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Xiphos/5.0"})
            resp.raise_for_status()

            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                dedupe_key = (title, link)
                if dedupe_key in seen_items:
                    continue
                seen_items.add(dedupe_key)
                items.append(item)
        items.sort(
            key=lambda item: (
                -_title_relevance(item.findtext("title", ""), query_variants),
                item.findtext("pubDate", ""),
            )
        )

        # Keyword fallback: only used when ML model is not available
        adverse_kw = {"sanction", "sanctioned", "fraud", "lawsuit", "indictment", "indicted",
                      "penalty", "scandal", "bankruptcy", "subpoena", "convicted", "debarred",
                      "money laundering", "bribery", "corruption", "embezzlement", "insider trading"}
        vendor_words = [w.lower() for w in vendor_name.split() if len(w) >= 3]

        article_count = 0
        adverse_count = 0

        for item in items[:15]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            source_name = item.findtext("source", "")

            if not title:
                continue

            # ML-based classification (preferred) or keyword fallback
            if _ml_available and _ml_classify:
                ml_result = _ml_classify(f"{title}. Source: {source_name}")
                is_adverse = ml_result["adverse"] and ml_result["confidence"] > 0.65
                detection_method = "ml"
                ml_confidence = ml_result["confidence"]
            else:
                title_lower = title.lower()
                vendor_in_title = any(vw in title_lower for vw in vendor_words)
                has_adverse_kw = any(kw in title_lower for kw in adverse_kw)
                is_adverse = has_adverse_kw and vendor_in_title
                detection_method = "keyword"
                ml_confidence = 0.50 if is_adverse else 0.30

            if is_adverse:
                adverse_count += 1

            control_signal = _extract_control_signal(query_variants, title)
            if control_signal:
                owner_name, rel_type, ownership_confidence, detection_method = control_signal
                result.relationships.append(
                    _build_media_ownership_relationship(
                        vendor_name=vendor_name,
                        target_name=owner_name,
                        rel_type=rel_type,
                        confidence=ownership_confidence,
                        title=title,
                        link=link,
                        source_name=source_name,
                        detection_method=detection_method,
                    )
                )
                result.findings.append(Finding(
                    source="google_news",
                    category="ownership" if rel_type == "owned_by" else "finance",
                    title=(
                        f"Media-reported ownership link: {owner_name}"
                        if rel_type == "owned_by"
                        else f"Media-reported financial backer: {owner_name}"
                    ),
                    detail=(
                        f"Article title suggests {vendor_name} is linked to {owner_name} via {rel_type}. "
                        f"Source: {source_name} | Detection: {detection_method}\nURL: {link}"
                    ),
                    severity="info",
                    confidence=ownership_confidence,
                    url=link,
                    source_class="public_connector",
                    authority_level="third_party_public",
                    access_model="rss_public",
                    structured_fields={
                        "relationship_scope": "media_reported_control" if rel_type == "owned_by" else "media_reported_financing",
                        "detection_method": detection_method,
                        "source_name": source_name,
                    },
                ))

            severity = "medium" if is_adverse else "info"
            article_count += 1

            result.findings.append(Finding(
                source="google_news", category="adverse_media" if is_adverse else "media",
                title=f"{'[ADVERSE] ' if is_adverse else ''}{title[:80]}",
                detail=f"Source: {source_name} | Published: {pub_date} | Detection: {detection_method}\nURL: {link}",
                severity=severity,
                confidence=ml_confidence if detection_method == "ml" else (0.50 if is_adverse else 0.30),
                url=link,
            ))

        result.identifiers["news_article_count"] = article_count
        result.identifiers["adverse_article_count"] = adverse_count

        if adverse_count > 0:
            result.risk_signals.append({
                "signal": "adverse_news_coverage",
                "severity": "high" if adverse_count >= 3 else "medium",
                "detail": f"{adverse_count} adverse news articles found for '{vendor_name}'",
            })

        if article_count == 0:
            result.findings.append(Finding(
                source="google_news", category="media",
                title=f"Google News: No recent articles found for '{vendor_name}'",
                detail="No news coverage found. Entity may be private, recently renamed, or low-profile.",
                severity="info", confidence=0.3,
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
    return result
