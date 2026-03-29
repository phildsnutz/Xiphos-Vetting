"""
Public HTML Ownership Connector

Cheap ownership/control hints from a company's public website.
This connector is deliberately narrow:
  - only uses analyst-provided or previously discovered website/domain hints
  - fetches a small set of first-party pages
  - extracts ownership phrases with deterministic pattern matching

It avoids search automation, anti-bot workarounds, or broad crawling.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests

from . import EnrichmentResult, Finding


SOURCE_NAME = "public_html_ownership"
TIMEOUT = 12
MAX_PAGES = 16
MAX_DISCOVERED_LINKS = 3
DEFAULT_PATHS = (
    "",
    "/about",
    "/about-us",
    "/who-we-are",
    "/history",
    "/company",
    "/the-company",
    "/en/the-company",
    "/leadership",
    "/ysgleadership",
    "/news",
    "/blog",
    "/newsroom",
)
USER_AGENT = "Helios/5.2 (+https://xiphosllc.com)"

SIGNAL_PATTERNS: tuple[tuple[re.Pattern[str], str, float, str], ...] = (
    (
        re.compile(r"\b(?:is|was)\s+(?:a\s+)?subsidiary of\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "owned_by",
        0.78,
        "subsidiary_of_phrase",
    ),
    (
        re.compile(r"\bowned by\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "owned_by",
        0.76,
        "owned_by_phrase",
    ),
    (
        re.compile(r"\bpart of\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'()/ -]{2,90})(?:\s+group|\s+family|\s+portfolio)?", re.IGNORECASE),
        "owned_by",
        0.70,
        "part_of_phrase",
    ),
    (
        re.compile(
            r"\bmember of\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'()/ -]{2,90}\s+(?:group|family|portfolio|holdings|network|alliance))",
            re.IGNORECASE,
        ),
        "owned_by",
        0.68,
        "member_of_phrase",
    ),
    (
        re.compile(r"\bacquired by\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "owned_by",
        0.64,
        "acquired_by_phrase",
    ),
    (
        re.compile(r"\bdivision of\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "owned_by",
        0.72,
        "division_of_phrase",
    ),
    (
        re.compile(
            r"\b(?:main|majority|principal)\s+shareholder\s+(?:is\s+|the\s+)?([A-Z][A-Za-z0-9&.,'()/ -]{2,120})",
            re.IGNORECASE,
        ),
        "owned_by",
        0.74,
        "main_shareholder_phrase",
    ),
    (
        re.compile(r"\bowner\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "owned_by",
        0.62,
        "owner_phrase",
    ),
    (
        re.compile(r"\b(?:funding round|investment round)[^.]{0,120}?led by\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "backed_by",
        0.64,
        "funding_round_led_by_phrase",
    ),
    (
        re.compile(
            r"\b(?:investment|financing|funding|seed(?:\s+round)?|series\s+[a-z]+|raised)\b.{0,180}?led by\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})",
            re.IGNORECASE,
        ),
        "backed_by",
        0.66,
        "investment_led_by_phrase",
    ),
    (
        re.compile(r"\bbacked by\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "backed_by",
        0.62,
        "backed_by_phrase",
    ),
    (
        re.compile(r"\bportfolio company of\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "backed_by",
        0.60,
        "portfolio_company_phrase",
    ),
    (
        re.compile(
            r"\binvestors?\s+of\s+[A-Z][A-Za-z0-9&.,'()/ -]{2,90}\s+(?:include|are)\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,120}?)(?:\s*[?.!]|$)",
            re.IGNORECASE,
        ),
        "backed_by",
        0.58,
        "investors_include_phrase",
    ),
    (
        re.compile(r"\binvestment from\s+([A-Z][A-Za-z0-9&.,'()/ -]{2,90})", re.IGNORECASE),
        "backed_by",
        0.60,
        "investment_from_phrase",
    ),
)

TRAILING_GENERIC = re.compile(
    r"\s+(?:group|family|portfolio|company|companies|corporation|corp\.?|inc\.?|llc|ltd\.?|plc|gmbh)\s*$",
    re.IGNORECASE,
)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TAGS = re.compile(r"<[^>]+>")
WHITESPACE = re.compile(r"\s+")
ANCHOR_TAG = re.compile(r"<a\b[^>]*href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<label>.*?)</a>", re.IGNORECASE | re.DOTALL)
DISCOVERY_KEYWORDS = (
    "fund",
    "invest",
    "back",
    "acquir",
    "news",
    "press",
    "growth",
    "history",
    "leadership",
    "about",
    "company",
    "corporate",
)
RAW_CTA_NOISE_PHRASES = (
    "let's ",
    "let’s ",
    "get a quote",
    "order equipment",
    "find a power solution",
    "power problems",
)
ENTITY_NOISE_PHRASES = (
    "proven in the field",
    "years of experience",
    "building solutions",
    "broad product line",
    "industry recognized benchmarks",
    "iso 9001",
    "cmmi",
    "lean six sigma",
    "quality auditing",
)
DESCRIPTOR_OWNER_PHRASES = (
    "service disabled veteran",
    "service-disabled veteran",
    "veteran owned",
    "veteran-owned",
    "small business",
    "woman owned",
    "woman-owned",
    "minority owned",
    "minority-owned",
    "hubzone",
    "sdb",
    "sdvosb",
    "vosb",
    "wosb",
    "edwosb",
    "8(a)",
)
CONTROL_BODY_NOISE_PHRASES = (
    "executive management team",
    "management team",
    "leadership team",
    "board of directors",
    "advisory board",
    "executive committee",
    "steering committee",
)
IDENTIFIER_PATTERNS: tuple[tuple[str, str, re.Pattern[str], float], ...] = (
    (
        "cage",
        "CAGE",
        re.compile(
            r"\b(?:CAGE(?:\s+Code)?|Commercial and Government Entity(?:\s+Code)?)\s*[:#]?\s*([A-Z0-9]{5})\b",
            re.IGNORECASE,
        ),
        0.72,
    ),
    (
        "uei",
        "UEI",
        re.compile(
            r"\b(?:UEI|Unique Entity ID(?:entifier)?)\s*(?:Number|Code|#)?\s*[:#]?\s*([A-Z0-9]{12})\b",
            re.IGNORECASE,
        ),
        0.70,
    ),
    (
        "duns",
        "DUNS",
        re.compile(
            r"\b(?:D[- ]?U[- ]?N[- ]?S(?:\s+Number)?|DUNS(?:\s+Number)?)\s*[:#]?\s*([0-9]{9})\b",
            re.IGNORECASE,
        ),
        0.68,
    ),
    (
        "ncage",
        "NCAGE",
        re.compile(
            r"\b(?:N[- ]?CAGE(?:\s+Code)?|NCAGE(?:\s+Code)?)\s*[:#]?\s*([A-Z0-9]{5})\b",
            re.IGNORECASE,
        ),
        0.66,
    ),
)
INVALID_IDENTIFIER_VALUES: dict[str, set[str]] = {
    "cage": {"CAGE", "CODES", "CODE", "ENTITY"},
    "uei": {"REGISTRATION", "IDENTIFIER", "ENTITY", "NUMBER", "UNIQUE"},
    "ncage": {"NCAGE", "CODES", "CODE", "ENTITY"},
}
IDENTIFIER_CONTEXT_BONUSES: tuple[tuple[str, float], ...] = (
    ("legal name", 0.18),
    ("active registration", 0.14),
    ("registration information", 0.14),
    ("registered in the system for award management", 0.12),
    ("registered with sam", 0.12),
    ("showing registration information", 0.12),
    ("headquartered", 0.04),
)
IDENTIFIER_CONTEXT_PENALTIES: tuple[tuple[str, float], ...] = (
    ("copy url email tweet", 0.16),
    ("search awardees", 0.14),
    ("people - schedules", 0.10),
    ("vehicles - idvs - contracts", 0.10),
    ("overview analysis registration people", 0.08),
)
IDENTIFIER_VENDOR_TOKEN_STOPWORDS = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "llc",
    "ltd",
    "limited",
    "plc",
    "gmbh",
    "sa",
    "systems",
    "group",
    "solutions",
    "services",
    "technologies",
    "technology",
    "defense",
    "holdings",
    "holding",
}
FOUNDED_YEAR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:in\s+)?((?:19|20)\d{2})\b[^.]{0,80}\b(?:was\s+founded|founded|began|established|started|launched)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:founded|began|established|started|launched)\b[^.]{0,80}\b((?:19|20)\d{2})\b",
        re.IGNORECASE,
    ),
)


def _normalize_website(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value.lstrip('/')}"
    parsed = urlparse(value)
    if not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    normalized = f"{parsed.scheme or 'https'}://{parsed.netloc}{path}"
    return normalized.rstrip("/")


def _candidate_urls(website: str) -> list[str]:
    base = _normalize_website(website)
    if not base:
        return []
    seen: set[str] = set()
    urls: list[str] = []
    for path in DEFAULT_PATHS:
        candidate = urljoin(f"{base}/", path.lstrip("/"))
        candidate = candidate.rstrip("/") if path else candidate.rstrip("/")
        if candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
        if len(urls) >= MAX_PAGES:
            break
    return urls


def _extract_text(markup: str) -> str:
    if not markup:
        return ""
    cleaned = HTML_COMMENT.sub(" ", markup)
    cleaned = SCRIPT_STYLE.sub(" ", cleaned)
    cleaned = TAGS.sub(" ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = WHITESPACE.sub(" ", cleaned)
    return cleaned.strip()


def _clean_parent_name(raw_name: str) -> str:
    text = (raw_name or "").strip(" ,.;:-")
    text = re.split(r"\.\s+(?:the|our|its|their|in|at|as|with|for)\b", text, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,.;:-")
    text = re.split(r"['’]s\b", text, maxsplit=1)[0].strip(" ,.;:-")
    text = re.split(r"[|•·]", text, maxsplit=1)[0].strip()
    text = re.split(r",\s+(?:part of|boasting)\b", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    text = re.split(
        r",\s+(?:boosting|bringing|driving|giving|making|positioning|raising|lifting)\b",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    text = re.split(r",\s+(?:the|which|with|that)\b", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    text = re.split(r"\s+(?:and|which|with|that)\b", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.IGNORECASE)
    text = TRAILING_GENERIC.sub("", text).strip(" ,.;:-")
    return text


def _looks_like_vendor(parent_name: str, vendor_name: str) -> bool:
    norm_parent = re.sub(r"[^A-Z0-9]+", " ", parent_name.upper()).strip()
    norm_vendor = re.sub(r"[^A-Z0-9]+", " ", vendor_name.upper()).strip()
    return bool(norm_parent and norm_vendor and (norm_parent == norm_vendor or norm_parent in norm_vendor or norm_vendor in norm_parent))


def _looks_like_entity_name(raw_name: str, parent_name: str) -> bool:
    raw = str(raw_name or "").strip()
    cleaned = str(parent_name or "").strip()
    if len(cleaned) < 3:
        return False
    lowered = cleaned.lower()
    raw_lowered = raw.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
    if any(
        token in lowered
        for token in (
            "vice president",
            "engineer other",
            "leave this field empty",
            "free subscription",
            "email",
            "select title",
        )
    ):
        return False
    if any(fragment in raw_lowered for fragment in RAW_CTA_NOISE_PHRASES):
        return False
    if any(fragment in lowered for fragment in ENTITY_NOISE_PHRASES):
        return False
    if any(phrase in lowered or phrase in normalized for phrase in DESCRIPTOR_OWNER_PHRASES):
        return False
    if len(cleaned.split()) > 8:
        return False
    candidate_for_case = cleaned if cleaned and raw[:1].lower() == raw[:1] else raw
    first_alpha = re.search(r"[A-Za-z]", candidate_for_case)
    if not first_alpha or candidate_for_case[first_alpha.start()] != candidate_for_case[first_alpha.start()].upper():
        return False
    if re.search(r"\b\d{1,2}\.\s*[A-Za-z]{2,}\b", cleaned):
        return False
    return True


def _is_news_like_page(page_url: str) -> bool:
    path = urlparse(page_url).path.lower()
    return any(segment in path for segment in ("/news", "/press", "/blog", "/article"))


def _extract_candidates(text: str, vendor_name: str, page_url: str) -> list[dict]:
    matches: list[dict] = []
    news_like_page = _is_news_like_page(page_url)
    for pattern, rel_type, confidence, scope in SIGNAL_PATTERNS:
        for hit in pattern.finditer(text):
            if news_like_page and scope in {"part_of_phrase", "member_of_phrase"}:
                continue
            raw_parent_name = hit.group(1)
            parent_name = _clean_parent_name(raw_parent_name)
            if not _looks_like_entity_name(raw_parent_name, parent_name):
                continue
            if _looks_like_vendor(parent_name, vendor_name):
                continue
            snippet_start = max(hit.start() - 80, 0)
            snippet_end = min(hit.end() + 80, len(text))
            snippet = text[snippet_start:snippet_end].strip()
            parent_lower = parent_name.lower()
            snippet_lower = snippet.lower()
            if rel_type == "owned_by":
                if any(phrase in parent_lower for phrase in CONTROL_BODY_NOISE_PHRASES):
                    continue
                if any(phrase in snippet_lower for phrase in CONTROL_BODY_NOISE_PHRASES):
                    continue
                if "minority member of" in snippet_lower:
                    continue
            if rel_type == "backed_by":
                if any(phrase in parent_lower for phrase in ENTITY_NOISE_PHRASES):
                    continue
                if "performance is backed by" in snippet_lower:
                    continue
            matches.append(
                {
                    "target_entity": parent_name,
                    "rel_type": rel_type,
                    "confidence": confidence,
                    "scope": scope,
                    "snippet": snippet,
                }
            )
    return matches


def _identifier_hint_bonus(key: str, snippet: str) -> float:
    context = re.sub(r"\s+", " ", (snippet or "").lower())
    bonus = 0.0
    for phrase, weight in IDENTIFIER_CONTEXT_BONUSES:
        if phrase in context:
            bonus += weight
    for phrase, weight in IDENTIFIER_CONTEXT_PENALTIES:
        if phrase in context:
            bonus -= weight
    if key == "uei" and "cage" in context:
        bonus += 0.06
    if key == "duns" and "cage" in context:
        bonus += 0.04
    if key in {"uei", "cage", "duns"} and "instead" in context:
        bonus += 0.08
    return bonus


def _identifier_vendor_tokens(vendor_name: str) -> list[str]:
    raw = str(vendor_name or "").strip().lower().replace("&", " and ")
    tokens = re.split(r"[^a-z0-9]+", raw)
    return [token for token in tokens if token and token not in IDENTIFIER_VENDOR_TOKEN_STOPWORDS][:4]


def _identifier_vendor_bonus(
    key: str,
    haystack: str,
    hit_start: int,
    hit_end: int,
    vendor_tokens: list[str],
) -> float:
    if not vendor_tokens:
        return 0.0
    before = re.sub(r"[^a-z0-9]+", " ", (haystack[max(0, hit_start - 120):hit_start] or "").lower()).strip()
    after = re.sub(r"[^a-z0-9]+", " ", (haystack[hit_end:min(len(haystack), hit_end + 120)] or "").lower()).strip()
    if not before and not after:
        return -0.22 if key in {"cage", "uei", "duns", "ncage"} else -0.12
    before_haystack = f" {before} " if before else ""
    after_haystack = f" {after} " if after else ""
    before_hits = sum(1 for token in vendor_tokens if before_haystack and f" {token} " in before_haystack)
    after_hits = sum(1 for token in vendor_tokens if after_haystack and f" {token} " in after_haystack)
    if before_hits >= min(2, len(vendor_tokens)):
        return 0.16
    if before_hits >= 1:
        return 0.11
    if after_hits >= 1:
        return -0.10 if key in {"cage", "uei", "duns", "ncage"} else -0.04
    return -0.22 if key in {"cage", "uei", "duns", "ncage"} else -0.12


def _extract_identifier_hints(text: str, *, vendor_name: str = "") -> dict[str, dict[str, str | float]]:
    hints: dict[str, dict[str, str | float]] = {}
    haystack = text or ""
    vendor_tokens = _identifier_vendor_tokens(vendor_name)
    for key, label, pattern, confidence in IDENTIFIER_PATTERNS:
        best_hint: dict[str, str | float] | None = None
        for hit in pattern.finditer(haystack):
            value = str(hit.group(1) or "").strip().upper()
            if not value:
                continue
            snippet_start = max(hit.start() - 80, 0)
            snippet_end = min(hit.end() + 80, len(haystack))
            snippet = haystack[snippet_start:snippet_end].strip()
            if value in INVALID_IDENTIFIER_VALUES.get(key, set()):
                continue
            if key == "uei" and not any(ch.isdigit() for ch in value):
                continue
            adjusted_confidence = max(
                0.30,
                min(
                    confidence
                    + _identifier_hint_bonus(key, snippet)
                    + _identifier_vendor_bonus(key, haystack, hit.start(), hit.end(), vendor_tokens),
                    0.92,
                ),
            )
            candidate_hint = {
                "label": label,
                "value": value,
                "confidence": adjusted_confidence,
                "snippet": snippet,
            }
            if best_hint is None:
                best_hint = candidate_hint
                continue
            current_confidence = float(best_hint["confidence"])
            if adjusted_confidence > current_confidence + 1e-9:
                best_hint = candidate_hint
                continue
            if abs(adjusted_confidence - current_confidence) <= 1e-9 and len(snippet) > len(str(best_hint["snippet"])):
                best_hint = candidate_hint
        if best_hint is not None:
            hints[key] = best_hint
    return hints


def _extract_profile_hints(text: str) -> dict[str, dict[str, str | float]]:
    hints: dict[str, dict[str, str | float]] = {}
    haystack = text or ""
    for pattern in FOUNDED_YEAR_PATTERNS:
        hit = pattern.search(haystack)
        if not hit:
            continue
        year = str(hit.group(1)).strip()
        if not year:
            continue
        snippet_start = max(hit.start() - 100, 0)
        snippet_end = min(hit.end() + 100, len(haystack))
        hints["founded_year"] = {
            "label": "Founded",
            "value": year,
            "confidence": 0.72,
            "snippet": haystack[snippet_start:snippet_end].strip(),
        }
        break
    return hints


def _extract_internal_candidate_links(markup: str, page_url: str, website: str) -> list[str]:
    base = _normalize_website(website)
    parsed_base = urlparse(base)
    normalized_page_url = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}{urlparse(page_url).path}".rstrip("/")
    discovered: list[tuple[int, str]] = []
    seen: set[str] = set()
    for match in ANCHOR_TAG.finditer(markup or ""):
        href = match.group("href") or ""
        label = _extract_text(match.group("label") or "")
        candidate = urljoin(page_url, href)
        parsed_candidate = urlparse(candidate)
        if parsed_candidate.scheme not in {"http", "https"}:
            continue
        if parsed_candidate.netloc != parsed_base.netloc:
            continue
        lowered = f"{candidate} {label}".lower()
        if not any(keyword in lowered for keyword in DISCOVERY_KEYWORDS):
            continue
        normalized = f"{parsed_candidate.scheme}://{parsed_candidate.netloc}{parsed_candidate.path}".rstrip("/")
        if not normalized or normalized == normalized_page_url:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        score = 0
        if any(keyword in lowered for keyword in ("fund", "invest", "back", "acquir")):
            score += 50
        if any(keyword in lowered for keyword in ("history", "leadership", "about")):
            score += 25
        if any(keyword in lowered for keyword in ("company", "corporate")):
            score += 22
        if "growth" in lowered:
            score += 20
        if any(keyword in lowered for keyword in ("news", "press")):
            score += 5
        if parsed_candidate.path.lower().endswith("/news"):
            score -= 10
        discovered.append((score, normalized))
    discovered.sort(key=lambda item: (-item[0], item[1]))
    return [url for _score, url in discovered[:MAX_DISCOVERED_LINKS]]


def _fetch_page(url: str) -> tuple[str, str]:
    response = requests.get(
        url,
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type and response.text.lstrip()[:1] != "<":
        return "", content_type
    return response.text, content_type


def _build_relationship(
    *,
    vendor_name: str,
    country: str,
    website: str,
    rel_type: str,
    parent_name: str,
    page_url: str,
    confidence: float,
    scope: str,
    snippet: str,
) -> dict:
    return {
        "type": rel_type,
        "source_entity": vendor_name,
        "source_entity_type": "company",
        "source_identifiers": {"website": website} if website else {},
        "target_entity": parent_name,
        "target_entity_type": "holding_company",
        "target_identifiers": {},
        "country": country,
        "data_source": SOURCE_NAME,
        "confidence": confidence,
        "evidence": snippet,
        "observed_at": datetime.utcnow().isoformat() + "Z",
        "artifact_ref": page_url,
        "evidence_url": page_url,
        "evidence_title": "Public company website ownership statement",
        "structured_fields": {
            "relationship_scope": scope if rel_type == "owned_by" else "first_party_financing",
            "extraction_method": "public_html_pattern",
            "source_page": page_url,
            "website": website,
        },
        "source_class": "public_connector",
        "authority_level": "first_party_self_disclosed",
        "access_model": "public_html",
        "raw_data": {
            "snippet": snippet,
            "website": website,
            "page_url": page_url,
        },
    }


def _resolve_website(ids: dict) -> str:
    for key in ("website", "official_website", "domain"):
        value = ids.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_website(value)
    return ""


def extract_page(
    vendor_name: str,
    country: str = "",
    *,
    website: str,
    page_url: str,
    discover_links: bool = False,
) -> tuple[EnrichmentResult, list[str]]:
    result = EnrichmentResult(source=SOURCE_NAME, vendor_name=vendor_name)
    started = datetime.utcnow()
    normalized_website = _normalize_website(website)
    normalized_page_url = _normalize_website(page_url)
    result.source_class = "public_connector"
    result.authority_level = "first_party_self_disclosed"
    result.access_model = "public_html"

    if not normalized_website or not normalized_page_url:
        result.elapsed_ms = 0
        return result, []

    discovered_links: list[str] = []
    try:
        html_text, _content_type = _fetch_page(normalized_page_url)
        text = _extract_text(html_text)
        if not text:
            result.identifiers["website"] = normalized_website
            result.elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
            return result, discovered_links

        for key, hint in _extract_identifier_hints(text).items():
            value = str(hint["value"])
            result.identifiers.setdefault(key, value)
            result.findings.append(
                Finding(
                    source=SOURCE_NAME,
                    category="identity",
                    title=f"Public site identifier hint: {hint['label']} {value}",
                    detail=f"{hint['snippet']} | Source page: {normalized_page_url}",
                    severity="info",
                    confidence=float(hint["confidence"]),
                    url=normalized_page_url,
                    artifact_ref=normalized_page_url,
                    structured_fields={
                        "identifier_type": key,
                        "identifier_value": value,
                        "source_page": normalized_page_url,
                        "website": normalized_website,
                    },
                    source_class="public_connector",
                    authority_level="first_party_self_disclosed",
                    access_model="public_html",
                )
            )
        for key, hint in _extract_profile_hints(text).items():
            value = str(hint["value"])
            result.identifiers.setdefault(key, value)
            result.findings.append(
                Finding(
                    source=SOURCE_NAME,
                    category="profile",
                    title=f"Public site operating history hint: founded in {value}",
                    detail=f"{hint['snippet']} | Source page: {normalized_page_url}",
                    severity="info",
                    confidence=float(hint["confidence"]),
                    url=normalized_page_url,
                    artifact_ref=normalized_page_url,
                    structured_fields={
                        "identifier_type": key,
                        "identifier_value": value,
                        "source_page": normalized_page_url,
                        "website": normalized_website,
                    },
                    source_class="public_connector",
                    authority_level="first_party_self_disclosed",
                    access_model="public_html",
                )
            )
        for candidate in _extract_candidates(text, vendor_name, normalized_page_url):
            result.relationships.append(
                _build_relationship(
                    vendor_name=vendor_name,
                    country=country,
                    website=normalized_website,
                    rel_type=candidate["rel_type"],
                    parent_name=candidate["target_entity"],
                    page_url=normalized_page_url,
                    confidence=candidate["confidence"],
                    scope=candidate["scope"],
                    snippet=candidate["snippet"],
                )
            )
            result.findings.append(
                Finding(
                    source=SOURCE_NAME,
                    category="ownership" if candidate["rel_type"] == "owned_by" else "finance",
                    title=(
                        f"Public site ownership hint: {candidate['target_entity']}"
                        if candidate["rel_type"] == "owned_by"
                        else f"Public site financial backer hint: {candidate['target_entity']}"
                    ),
                    detail=f"{candidate['snippet']} | Source page: {normalized_page_url}",
                    severity="info",
                    confidence=candidate["confidence"],
                    url=normalized_page_url,
                    artifact_ref=normalized_page_url,
                    structured_fields={
                        "relationship_scope": candidate["scope"] if candidate["rel_type"] == "owned_by" else "first_party_financing",
                        "relationship_type": candidate["rel_type"],
                        "target_entity": candidate["target_entity"],
                        "website": normalized_website,
                    },
                    source_class="public_connector",
                    authority_level="first_party_self_disclosed",
                    access_model="public_html",
                )
            )
        if discover_links:
            discovered_links = _extract_internal_candidate_links(html_text, normalized_page_url, normalized_website)
    except Exception as exc:
        result.error = str(exc)

    result.identifiers["website"] = normalized_website
    result.artifact_refs = list(
        dict.fromkeys(
            [
                *(rel["artifact_ref"] for rel in result.relationships if rel.get("artifact_ref")),
                *(finding.artifact_ref for finding in result.findings if finding.artifact_ref),
            ]
        )
    )
    result.elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
    if result.relationships:
        result.risk_signals.append(
            {
                "signal": "ownership_self_disclosed",
                "source": SOURCE_NAME,
                "severity": "info",
                "confidence": max((rel["confidence"] for rel in result.relationships), default=0.0),
                "summary": f"Public website ownership hint found for {vendor_name}",
                "website": normalized_website,
            }
        )
    return result, discovered_links


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    result = EnrichmentResult(source=SOURCE_NAME, vendor_name=vendor_name)
    started = datetime.utcnow()
    website = _resolve_website(ids)
    result.source_class = "public_connector"
    result.authority_level = "first_party_self_disclosed"
    result.access_model = "public_html"

    if not website:
        result.elapsed_ms = 0
        return result

    relationships: list[dict] = []
    findings: list[Finding] = []
    seen_targets: set[tuple[str, str]] = set()
    seen_identifiers: set[tuple[str, str]] = set()
    identifier_artifact_refs: list[str] = []
    seen_page_findings: set[tuple[str, str, str]] = set()
    queue = _candidate_urls(website)
    visited: set[str] = set()

    try:
        while queue and len(visited) < MAX_PAGES:
            page_url = queue.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            page_result, discovered_links = extract_page(
                vendor_name,
                country,
                website=website,
                page_url=page_url,
                discover_links=True,
            )
            if page_result.error:
                continue
            for key, value in page_result.identifiers.items():
                if key == "website":
                    continue
                dedupe_key = (key, value)
                if dedupe_key in seen_identifiers:
                    continue
                seen_identifiers.add(dedupe_key)
                result.identifiers.setdefault(key, value)
            for finding in page_result.findings:
                artifact_ref = finding.artifact_ref or page_url
                if finding.category not in {"identity", "profile"}:
                    continue
                dedupe_key = (finding.category, finding.title, artifact_ref)
                if dedupe_key in seen_page_findings:
                    continue
                seen_page_findings.add(dedupe_key)
                if artifact_ref:
                    identifier_artifact_refs.append(artifact_ref)
                findings.append(finding)
            relationship_findings = {
                (
                    str(finding.structured_fields.get("relationship_type") or ""),
                    str(finding.structured_fields.get("target_entity") or "").upper(),
                ): finding
                for finding in page_result.findings
                if finding.category in {"ownership", "finance"}
            }
            for relationship in page_result.relationships:
                dedupe_key = (relationship["type"], relationship["target_entity"].upper())
                if dedupe_key in seen_targets:
                    continue
                seen_targets.add(dedupe_key)
                relationships.append(relationship)
                relationship_finding = relationship_findings.get(dedupe_key)
                if relationship_finding:
                    findings.append(relationship_finding)
            for discovered in discovered_links:
                if discovered not in visited and discovered not in queue:
                    queue.append(discovered)
    except Exception as exc:
        result.error = str(exc)

    result.identifiers["website"] = website
    result.relationships = relationships
    result.findings = findings
    result.artifact_refs = list(
        dict.fromkeys(
            [rel["artifact_ref"] for rel in relationships if rel.get("artifact_ref")] + identifier_artifact_refs
        )
    )
    result.elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
    result.structured_fields["visited_pages"] = list(visited)
    if relationships:
        result.risk_signals.append(
            {
                "signal": "ownership_self_disclosed",
                "source": SOURCE_NAME,
                "severity": "info",
                "confidence": max((rel["confidence"] for rel in relationships), default=0.0),
                "summary": f"Public website ownership hint found for {vendor_name}",
                "website": website,
            }
        )
    return result
