"""
Public Search Ownership Connector

Cheap public-search discovery that finds a likely official company website,
then routes that website through the first-party HTML ownership extractor.

This stays within the collector-lab rules:
  - public search result HTML only
  - no login, captcha workarounds, or anti-bot evasion
  - no broad crawling beyond the discovered first-party website
"""

from __future__ import annotations

import base64
import html
import re
import time
from datetime import datetime
from typing import Iterable
from urllib.parse import parse_qs, urlparse

import requests

from . import EnrichmentResult, Finding
from . import public_html_ownership


SOURCE_NAME = "public_search_ownership"
SEARCH_URL = "https://html.duckduckgo.com/html/"
SEARCH_LITE_URL = "https://lite.duckduckgo.com/lite/"
YAHOO_SEARCH_URL = "https://search.yahoo.com/search"
BING_SEARCH_URL = "https://www.bing.com/search"
BRAVE_SEARCH_URL = "https://search.brave.com/search"
SEARCH_TIMEOUT = 4
TIMEOUT = SEARCH_TIMEOUT
USER_AGENT = "Helios/5.2 (+https://xiphosllc.com)"
MAX_RESULTS = 5
SEARCH_RESULT_WINDOW = 12
IDENTIFIER_MAX_RESULTS = 12
MAX_EXTERNAL_PAGES = 3
CONNECTOR_BUDGET_SECONDS = 35
MAX_OWNERSHIP_QUERIES = 4
MAX_FINANCE_QUERIES = 4
MAX_IDENTIFIER_QUERIES = 4
IDENTIFIER_PHASE_MIN_REMAINING_SECONDS = 8
SNIPPET_IDENTIFIER_MIN_CONFIDENCE = 0.52
EXTERNAL_IDENTIFIER_MIN_CONFIDENCE = 0.60
EXTERNAL_IDENTIFIER_ACCESS_BONUS = 0.05
MAX_SYNTHETIC_FINANCE_PAGES = 4
OWNERSHIP_SEARCH_SUFFIX = " owner investor shareholder acquired backed by"
LEADERSHIP_OWNERSHIP_SEARCH_SUFFIX = " founder president CEO owner"
FINANCING_SEARCH_SUFFIX = " portfolio capital funding investors"
LEGACY_CORPORATE_SUFFIXES = ("Systems", "Technologies", "Solutions", "Laboratories", "Labs")
SYNTHETIC_FINANCE_PROFILE_TEMPLATES = (
    "https://www.freshtrackscap.com/portfolio/{slug}/",
    "https://www.cbinsights.com/company/{slug}/financials",
    "https://www.cbinsights.com/company/{slug}",
)
IDENTIFIER_QUERY_TERMS = {
    "cage": " CAGE Code",
    "uei": " UEI Unique Entity ID",
    "duns": " DUNS Number",
    "ncage": " NCAGE Code",
}

ANCHOR_RE = re.compile(
    r'<a\b[^>]*class="[^"]*result__a[^"]*"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
SNIPPET_RE = re.compile(
    r'<a\b[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_CLEAN_SPLIT_RE = re.compile(
    r"\s+(?:a unified vision|under a new brand|launches|launched|announces|announced|awarded|merges|merged)\b",
    re.IGNORECASE,
)
LITE_LINK_RE = re.compile(
    r"<a\b(?P<attrs>[^>]*)>(?P<title>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
LITE_SNIPPET_RE = re.compile(
    r"<td\b[^>]*class=['\"]result-snippet['\"][^>]*>(?P<snippet>.*?)</td>",
    re.IGNORECASE | re.DOTALL,
)
BRAVE_BLOCK_START_RE = re.compile(
    r'<div class="snippet[^"]*"[^>]*data-type="web"[^>]*>',
    re.IGNORECASE,
)
BING_BLOCK_START_RE = re.compile(
    r'<li class="b_algo"[^>]*>',
    re.IGNORECASE,
)
YAHOO_BLOCK_START_RE = re.compile(
    r'<div class="dd\b[^"]*"',
    re.IGNORECASE,
)
YAHOO_HREF_RE = re.compile(
    r'<div class="compTitle[^"]*"[^>]*>.*?<a[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
YAHOO_SNIPPET_RE = re.compile(
    r'<div class="compText[^"]*"[^>]*>.*?<p[^>]*>(?P<snippet>.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)
BING_HREF_RE = re.compile(
    r'<h2[^>]*>\s*<a[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>\s*</h2>',
    re.IGNORECASE | re.DOTALL,
)
BING_SNIPPET_RE = re.compile(
    r'<div class="b_caption"[^>]*>.*?<p[^>]*>(?P<snippet>.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)
BRAVE_HREF_RE = re.compile(
    r'<a href="(?P<href>https?://[^"]+)"[^>]*class="[^"]*\bl1\b[^"]*"',
    re.IGNORECASE | re.DOTALL,
)
BRAVE_TITLE_RE = re.compile(
    r'<div class="title[^"]*"[^>]*>(?P<title>.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
BRAVE_SNIPPET_TEXT_RE = re.compile(
    r'<div class="content[^"]*"[^>]*>(?P<snippet>.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
HTML_ATTR_RE = re.compile(r"(?P<name>[a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(['\"])(?P<value>.*?)\2", re.DOTALL)
BAD_HOST_PATTERNS = (
    "duckduckgo.com",
    "news.google.com",
    "google.com",
    "search.yahoo.com",
    "images.search.yahoo.com",
    "bing.com",
    "rippling.com",
    "myworkdayjobs.com",
    "greenhouse.io",
    "smartrecruiters.com",
    "lever.co",
    "ashbyhq.com",
    "workable.com",
    "jobvite.com",
    "icims.com",
    "linkedin.com",
    "crunchbase.com",
    "contactout.com",
    "craft.co",
    "bloomberg.com",
    "cbinsights.com",
    "pitchbook.com",
    "rocketreach.co",
    "theorg.com",
    "tracxn.com",
    "wikipedia.org",
    "wikidata.org",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "zoominfo.com",
    "youtube.com",
    "rssi.org",
    "federalcompass.com",
    "trendlyne.com",
    "marketscreener.com",
    "edgar-online.com",
)
OFFICIAL_HOST_EXCLUDE_PATTERNS = (
    "army-technology.com",
    "criticalcommunicationsreview.com",
    "defenceconnect.com.au",
    "prnewswire.com",
    "virginiabusiness.com",
    "eida.asn.au",
    "adsgroup.org.uk",
    "industry.ausa.org",
    "govtribe.com",
    "marketscreener.com",
    "unmanned-network.com",
    "everythingrf.com",
    "aerospacedefensereview.com",
    "defenseadvancement.com",
    "grokipedia.com",
)
BAD_TITLE_PATTERNS = (
    "dun & bradstreet",
    "company profile",
    "management and employees",
    "directory",
    "sourcehere",
    "cb insights",
    "defense guide",
    "defense-guide",
    "datanyze",
    "portfolio and holdings",
    "award |",
    "company details",
)
OFFICIAL_TITLE_POSITIVE_PATTERNS = (
    "official website",
    "official site",
    "corporate website",
)
OFFICIAL_SNIPPET_POSITIVE_PATTERNS = (
    "official corporate site",
    "official website",
    "corporate website",
)
OFFICIAL_HOST_NEGATIVE_PATTERNS = (
    "mediaroom.",
    "newsroom.",
    "suppliers.",
)
OFFICIAL_PATH_NEGATIVE_PATTERNS = (
    "/newsroom",
    "/supplier",
    "/suppliers",
    "/procurement",
    "/companies/",
    "/company/",
    "/members/",
    "/member/",
    "/directory/",
    "/tour",
    "/tickets",
)
OFFICIAL_TITLE_NEGATIVE_PATTERNS = (
    "newsroom",
    "supplier portal",
    "procurement portal",
    "factory tour",
    "profile on",
    "top maritime solutions company",
    " archives",
)
SNIPPET_ONLY_HOST_PATTERNS = (
    "cbinsights.com",
    "pitchbook.com",
    "crunchbase.com",
    "tracxn.com",
    "craft.co",
)
SEARCH_KEYWORDS = ("official", "company", "marine", "defense", "technology", "laboratories", "labs")
EXTERNAL_SIGNAL_KEYWORDS = (
    "investor",
    "investment",
    "fund",
    "funding",
    "backed",
    "owned",
    "acquire",
    "acquired",
    "acquisition",
    "owner",
    "shareholder",
    "portfolio",
)
LEADERSHIP_SIGNAL_KEYWORDS = (
    " president ",
    " ceo ",
    " chief executive officer ",
    " founder ",
    " chair ",
    " chairman ",
)
IDENTIFIER_SIGNAL_KEYWORDS = (
    " cage ",
    " uei ",
    " duns ",
    " ncage ",
    " unique entity",
    "commercial and government entity",
)
INVESTOR_SITE_KEYWORDS = ("capital", "ventures", "venture", "partners", "equity", "holdings", "portfolio", "fund")
INVESTOR_TITLE_INFERENCE_PATTERNS = (
    " portfolio ",
    " portfolio company ",
    " investor ",
    " investors ",
    " venture capital ",
    " private equity ",
    " growth equity ",
    " backed by ",
)

SNIPPET_SEARCH_SUFFIXES = (
    OWNERSHIP_SEARCH_SUFFIX,
    LEADERSHIP_OWNERSHIP_SEARCH_SUFFIX,
)

SEARCH_PROVIDER_NAMES = (
    "duckduckgo_html",
    "duckduckgo_lite",
    "yahoo",
    "bing",
    "brave",
)
COUNTRY_TLD_HINTS = {
    "AU": (".au",),
    "CA": (".ca",),
    "DE": (".de",),
    "FR": (".fr",),
    "GB": (".uk", ".co.uk"),
    "GR": (".gr",),
    "IL": (".il",),
    "JP": (".jp",),
    "KR": (".kr",),
    "TW": (".tw",),
    "US": (".us", ".gov", ".mil"),
}
SYNTHETIC_DOMAIN_SUFFIXES = {
    "AU": (".com.au", ".au", ".com"),
    "CA": (".ca", ".com"),
    "DE": (".de", ".com"),
    "FR": (".fr", ".com"),
    "GB": (".co.uk", ".uk", ".com"),
    "GR": (".gr", ".com"),
    "IL": (".co.il", ".il", ".com"),
    "JP": (".co.jp", ".jp", ".com"),
    "KR": (".co.kr", ".kr", ".com"),
    "TW": (".com.tw", ".tw", ".com"),
    "US": (".com", ".us"),
}
DEFAULT_SYNTHETIC_DOMAIN_SUFFIXES = (".com",)
COUNTRY_MISMATCH_TERMS = {
    "US": (
        " canada ",
        " canadian ",
        " british columbia ",
        " alberta ",
        " ontario ",
        " quebec ",
        " kootenay ",
        " nelson, bc ",
        " vancouver ",
    ),
}
DOMAIN_LABEL_STOPWORDS = {
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
    "group",
    "holdings",
    "holding",
    "systems",
    "solutions",
    "services",
}
FINANCE_SLUG_STOPWORDS = {
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
}
TITLE_RE = re.compile(r"<title[^>]*>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
ALIAS_TRANSITION_PATTERNS = (
    re.compile(
        r"(?P<alias>[A-Z][A-Za-z0-9&.,'()/ -]{2,120})\s+transforms into\s+(?P<current>[A-Z][A-Za-z0-9&.,'()/ -]{2,120})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<alias>[A-Z][A-Za-z0-9&.,'()/ -]{2,120})\s+rebrands?\s+(?:as|to)\s+(?P<current>[A-Z][A-Za-z0-9&.,'()/ -]{2,120})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<alias>[A-Z][A-Za-z0-9&.,'()/ -]{2,120})\s*,?\s*d\.b\.a\.\s+(?P<current>[A-Z][A-Za-z0-9&.,'()/ -]{2,120})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<current>[A-Z][A-Za-z0-9&.,'()/ -]{2,120})\s*\((?:formerly|formerly known as)\s+(?P<alias>[A-Z][A-Za-z0-9&.,'()/ -]{2,120})\)",
        re.IGNORECASE,
    ),
)

RECRUITING_HOST_PATTERNS = (
    "appone.com",
    "rippling.com",
    "myworkdayjobs.com",
    "greenhouse.io",
    "smartrecruiters.com",
    "lever.co",
    "ashbyhq.com",
    "workable.com",
    "jobvite.com",
    "icims.com",
)

RECRUITING_PATH_HINTS = (
    "/jobs",
    "/job",
    "/careers",
    "/career",
    "/positions",
    "/openings",
    "/apply",
)


def _is_recruiting_host(host: str, path: str, title: str = "", snippet: str = "") -> bool:
    normalized_host = host.lower()
    normalized_path = path.lower()
    normalized_text = f"{title.lower()} {snippet.lower()}"
    if any(pattern in normalized_host for pattern in RECRUITING_HOST_PATTERNS):
        return True
    if normalized_host.startswith(("jobs.", "careers.", "apply.", "ats.")):
        return True
    if any(token in normalized_path for token in RECRUITING_PATH_HINTS):
        if any(keyword in normalized_text for keyword in ("job", "jobs", "career", "hiring", "apply", "position", "opening")):
            return True
    return False


def _clean_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", TAG_RE.sub(" ", html.unescape(value or ""))).strip()


def _extract_html_attrs(raw_attrs: str) -> dict[str, str]:
    return {match.group("name").lower(): html.unescape(match.group("value") or "") for match in HTML_ATTR_RE.finditer(raw_attrs or "")}


def _normalize_name_tokens(vendor_name: str) -> list[str]:
    raw = str(vendor_name or "").strip().lower()
    raw = raw.replace("&", " and ")
    tokens = re.split(r"[^a-z0-9]+", raw)
    filtered = [
        token for token in tokens
        if token
        and token not in {
            "inc", "incorporated", "corp", "corporation", "co", "company", "llc",
            "ltd", "plc", "sa", "ag", "gmbh", "marine", "technologies",
        }
    ]
    return filtered[:4]


def _search_queries(vendor_name: str) -> list[str]:
    raw = str(vendor_name or "").strip()
    variants: list[str] = []
    primary = re.split(r"\s*[|/]\s*", raw, maxsplit=1)[0].strip()
    jurisdiction_trimmed = re.sub(r"\b(?:US|USA|U\.S\.|UK|U\.K\.)\b\s*$", "", primary, flags=re.IGNORECASE).strip(" ,-/")
    short_brand_trimmed = ""
    primary_tokens = jurisdiction_trimmed.split()
    if len(primary_tokens) >= 2:
        trailing = re.sub(r"[^A-Za-z0-9]", "", primary_tokens[-1])
        if 1 < len(trailing) <= 3 and trailing.upper() == trailing and any(ch.isalpha() for ch in trailing):
            short_brand_trimmed = " ".join(primary_tokens[:-1]).strip()
    for candidate in (
        jurisdiction_trimmed,
        short_brand_trimmed,
        primary,
        raw,
    ):
        if candidate and candidate not in variants:
            variants.append(candidate)
    return variants or [raw]


def _quote_vendor_phrase(query: str, vendor_name: str) -> str:
    normalized_query = str(query or "").strip()
    vendor = str(vendor_name or "").strip()
    if not normalized_query or not vendor or f'"{vendor}"' in normalized_query:
        return normalized_query
    if vendor not in normalized_query:
        return normalized_query
    if " " not in vendor and "-" not in vendor:
        return normalized_query
    return normalized_query.replace(vendor, f'"{vendor}"', 1)


def _expanded_search_queries(vendor_name: str, aliases: Iterable[str] | None = None) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    for name in [vendor_name, *(aliases or [])]:
        for query in _search_queries(name):
            if query in seen:
                continue
            seen.add(query)
            queries.append(query)
    return queries


def _legacy_corporate_query_variants(vendor_name: str) -> list[str]:
    raw = str(vendor_name or "").strip()
    primary = re.split(r"\s*[|/]\s*", raw, maxsplit=1)[0].strip()
    tokens = primary.split()
    if len(tokens) < 2:
        return []
    trailing = re.sub(r"[^A-Za-z0-9]", "", tokens[-1])
    if not (1 < len(trailing) <= 3 and trailing.upper() == trailing and any(ch.isalpha() for ch in trailing)):
        return []
    base = " ".join(tokens[:-1]).strip(" ,-/")
    if not base:
        return []
    variants: list[str] = []
    seen: set[str] = set()
    for suffix in LEGACY_CORPORATE_SUFFIXES:
        candidate = f"{base} {suffix}".strip()
        if candidate in seen:
            continue
        seen.add(candidate)
        variants.append(candidate)
    return variants


def _finance_profile_slug_candidates(names: Iterable[str]) -> list[str]:
    slugs: list[str] = []
    seen: set[str] = set()
    for name in names:
        tokens = [
            token
            for token in re.split(r"[^a-z0-9]+", str(name or "").lower())
            if token and token not in FINANCE_SLUG_STOPWORDS
        ]
        if not tokens:
            continue
        slug = "-".join(tokens).strip("-")
        if len(slug) < 4 or slug in seen:
            continue
        seen.add(slug)
        slugs.append(slug)
    return slugs


def _domain_label_candidates(vendor_name: str) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for variant in _search_queries(vendor_name):
        tokens = [
            token
            for token in re.split(r"[^a-z0-9]+", variant.lower())
            if token and token not in DOMAIN_LABEL_STOPWORDS
        ]
        if not tokens:
            continue
        for label in ("".join(tokens), "-".join(tokens)):
            normalized = label.strip("-")
            if len(normalized) < 4 or len(normalized) > 40:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            labels.append(normalized)
    return labels


def _synthetic_domain_urls(vendor_name: str, country: str = "") -> list[str]:
    cc = str(country or "").strip().upper()
    suffixes = SYNTHETIC_DOMAIN_SUFFIXES.get(cc, DEFAULT_SYNTHETIC_DOMAIN_SUFFIXES)
    urls: list[str] = []
    seen: set[str] = set()
    for label in _domain_label_candidates(vendor_name):
        for suffix in suffixes:
            for prefix in ("https://", "https://www."):
                url = f"{prefix}{label}{suffix}".rstrip("/")
                if url in seen:
                    continue
                seen.add(url)
                urls.append(url)
    return urls


def _extract_html_title(markup: str) -> str:
    match = TITLE_RE.search(markup or "")
    if not match:
        return ""
    return _clean_text(match.group("title") or "")


def _matches_vendor_name(candidate: str, vendor_name: str) -> bool:
    candidate_tokens = set(_normalize_name_tokens(candidate))
    vendor_tokens = set(_normalize_name_tokens(vendor_name))
    if not candidate_tokens or not vendor_tokens:
        return False
    shared = candidate_tokens & vendor_tokens
    return len(shared) >= min(2, len(vendor_tokens))


def _clean_alias_name(value: str) -> str:
    cleaned = _clean_text(value)
    cleaned = re.split(r"[:;|]", cleaned, maxsplit=1)[0].strip(" ,.;:-")
    cleaned = SENTENCE_CLEAN_SPLIT_RE.split(cleaned, maxsplit=1)[0].strip(" ,.;:-")
    return cleaned


def _search_snippet_vendor_pattern(vendor_variant: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", str(vendor_variant or "")) if part]
    if not parts:
        return re.escape(str(vendor_variant or ""))
    if len(parts) == 1:
        return re.escape(parts[0])
    joiner = r"(?:\s*[-/&.,'()]+\s*|\s+)"
    return joiner.join(re.escape(part) for part in parts)


def _extract_legacy_aliases(vendor_name: str, candidates: Iterable[dict]) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    vendor_tokens = set(_normalize_name_tokens(vendor_name))
    if not vendor_tokens:
        return aliases

    for candidate in candidates:
        for raw_text in (candidate.get("title") or "", candidate.get("snippet") or ""):
            text = _clean_text(str(raw_text or ""))
            if not text:
                continue
            for pattern in ALIAS_TRANSITION_PATTERNS:
                for match in pattern.finditer(text):
                    current = _clean_alias_name(match.group("current") or "")
                    alias = _clean_alias_name(match.group("alias") or "")
                    if not current or not alias:
                        continue
                    if not _matches_vendor_name(current, vendor_name):
                        continue
                    alias_tokens = set(_normalize_name_tokens(alias))
                    if not alias_tokens or alias_tokens == vendor_tokens:
                        continue
                    if not (alias_tokens & vendor_tokens):
                        continue
                    normalized_alias = alias.strip()
                    normalized_key = normalized_alias.upper()
                    if normalized_key in seen:
                        continue
                    seen.add(normalized_key)
                    aliases.append(normalized_alias)
    return aliases


def _synthetic_official_candidates(vendor_name: str, country: str = "") -> list[dict]:
    candidates: list[dict] = []
    vendor_tokens = _normalize_name_tokens(vendor_name)
    if not vendor_tokens:
        return candidates

    for url in _synthetic_domain_urls(vendor_name, country):
        try:
            markup, _content_type = public_html_ownership._fetch_page(url)
        except Exception:
            continue
        title = _extract_html_title(markup)
        text = public_html_ownership._extract_text(markup)
        corpus = f" {title.lower()} {text.lower()} "
        host = urlparse(url).netloc.lower()
        body_token_matches = sum(1 for token in vendor_tokens if f" {token} " in corpus or token in host)
        if body_token_matches < min(2, len(vendor_tokens)):
            continue
        snippet = text[:280]
        score = _score_candidate(url, title or vendor_name, vendor_name, snippet, country=country) + (body_token_matches * 6)
        if score < 18:
            continue
        candidate = {
            "url": url,
            "title": title or vendor_name,
            "snippet": snippet,
            "score": score,
            "blocked_host": False,
            "search_provider": "synthetic_domain",
        }
        candidates.append(candidate)
        if score >= 32 and not host.startswith("www."):
            return [candidate]

    candidates.sort(key=lambda item: (-item["score"], item["url"]))
    return candidates[:SEARCH_RESULT_WINDOW]


def _site_scoped_queries(vendor_name: str, website: str) -> list[str]:
    host = urlparse(website).netloc.lower()
    if not host:
        return []
    host_label = host.removeprefix("www.").split(".", 1)[0].replace("-", " ").strip()
    queries: list[str] = []
    seen: set[str] = set()
    for variant in _search_queries(vendor_name):
        query = f"site:{host} {variant}{OWNERSHIP_SEARCH_SUFFIX}".strip()
        if query not in seen:
            seen.add(query)
            queries.append(query)
    if host_label:
        query = f"site:{host} {host_label}{OWNERSHIP_SEARCH_SUFFIX}".strip()
        if query not in seen:
            seen.add(query)
            queries.append(query)
    generic_query = f"site:{host}{OWNERSHIP_SEARCH_SUFFIX}".strip()
    if generic_query not in seen:
        queries.append(generic_query)
    return queries


def _identifier_search_queries(vendor_name: str, missing_keys: Iterable[str] | None = None) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    keys = [key for key in (missing_keys or IDENTIFIER_QUERY_TERMS.keys()) if key in IDENTIFIER_QUERY_TERMS]
    for key in keys:
        suffix = IDENTIFIER_QUERY_TERMS[key]
        for variant in _search_queries(vendor_name):
            query = f"{variant}{suffix}".strip()
            if query in seen:
                continue
            seen.add(query)
            queries.append(query)
    return queries


def _unwrap_result_url(href: str) -> str:
    href = html.unescape(href or "").strip()
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    uddg = query.get("uddg")
    if uddg:
        return uddg[0]
    if "bing.com" in parsed.netloc.lower():
        bing_u = query.get("u")
        if bing_u:
            encoded = str(bing_u[0] or "")
            if encoded.startswith("a1"):
                encoded = encoded[2:]
            if encoded:
                try:
                    padded = encoded + "=" * (-len(encoded) % 4)
                    decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
                    if decoded.startswith(("http://", "https://")):
                        return decoded
                except Exception:
                    pass
        if parsed.path.startswith("/ck/"):
            return ""
    return href


def _official_site_root(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{parsed.scheme}://{host}"


def _same_host_candidate_pages(candidates: list[dict], website_root: str) -> list[str]:
    parsed_root = urlparse(website_root)
    selected: list[tuple[int, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = str(candidate.get("url") or "").strip()
        title = _clean_text(str(candidate.get("title") or "")).lower()
        snippet = _clean_text(str(candidate.get("snippet") or "")).lower()
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc or parsed.netloc != parsed_root.netloc:
            continue
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        path = parsed.path.lower()
        score = 0
        if normalized == website_root.rstrip("/"):
            score += 100
        if any(token in path for token in ("/about", "/company", "/the-company", "/who-we-are", "/about-us")):
            score += 40
        if any(token in title for token in ("about", "company", "the company", "who we are")):
            score += 25
        if any(token in path for token in ("/fund", "/invest", "/acquir")):
            score += 30
        if any(token in title for token in ("fund", "investment", "backed", "acquired", "led by")):
            score += 20
        strong_signal = any(
            token in f"{title} {snippet}"
            for token in ("fund", "investment", "backed", "investor", "series a", "series b", "series c", "acquired", "led by")
        )
        if strong_signal:
            score += 18
        if "/news/" in path and score < 25 and not strong_signal:
            score -= 30
        selected.append((score, normalized))
    selected.sort(key=lambda item: (-item[0], item[1]))
    return [url for score, url in selected if score > 0][:3]


def _country_mismatch_penalty(host: str, title: str, snippet: str, country: str) -> int:
    cc = str(country or "").strip().upper()
    if not cc:
        return 0

    penalty = 0
    for foreign_cc, tlds in COUNTRY_TLD_HINTS.items():
        if foreign_cc == cc:
            continue
        if any(host.endswith(tld) for tld in tlds):
            penalty += 18
            break
    if cc == "US" and host.endswith(".com"):
        penalty -= 2

    haystack = f" {title.lower()} {snippet.lower()} "
    if any(term in haystack for term in COUNTRY_MISMATCH_TERMS.get(cc, ())):
        penalty += 15
    return penalty


def _pick_official_candidate(candidates: list[dict], country: str = "") -> dict | None:
    ranked: list[tuple[int, dict]] = []
    for candidate in candidates:
        url = str(candidate.get("url") or "").strip()
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        score = int(candidate.get("score") or 0)
        title = _clean_text(str(candidate.get("title") or ""))
        snippet = _clean_text(str(candidate.get("snippet") or ""))
        title_lower = title.lower()
        snippet_lower = snippet.lower()
        if not host:
            continue
        if _is_recruiting_host(host, parsed.path, title, snippet):
            score -= 50
        if any(pattern in host for pattern in OFFICIAL_HOST_EXCLUDE_PATTERNS):
            score -= 30
        if any(pattern in title_lower for pattern in OFFICIAL_TITLE_POSITIVE_PATTERNS):
            score += 18
        if any(pattern in snippet_lower for pattern in OFFICIAL_SNIPPET_POSITIVE_PATTERNS):
            score += 10
        if any(pattern in host for pattern in OFFICIAL_HOST_NEGATIVE_PATTERNS):
            score -= 18
        if any(pattern in path for pattern in OFFICIAL_PATH_NEGATIVE_PATTERNS):
            score -= 16
        if any(pattern in title_lower for pattern in OFFICIAL_TITLE_NEGATIVE_PATTERNS):
            score -= 14
        if parsed.path in {"", "/"}:
            score += 8
        if candidate.get("blocked_host"):
            score -= 10
        host_label = host.removeprefix("www.").split(".", 1)[0].strip()
        combined = f"{title} {snippet}"
        combined_tokens = set(_normalize_name_tokens(combined))
        if (
            2 <= len(host_label) <= 5
            and re.search(rf"\(\s*{re.escape(host_label)}\s*\)", combined, re.IGNORECASE)
            and len(combined_tokens) >= 3
        ):
            score += 18
        score -= _country_mismatch_penalty(host, title, snippet, country)
        ranked.append((score, candidate))

    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("url") or "")))
    return ranked[0][1]


def _external_candidate_pages(candidates: list[dict], website_root: str) -> list[dict]:
    parsed_root = urlparse(website_root)
    selected: list[tuple[int, dict]] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = str(candidate.get("url") or "").strip()
        if not url or url in seen:
            continue
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            continue
        if parsed.netloc == parsed_root.netloc:
            continue
        title = _clean_text(str(candidate.get("title") or "")).lower()
        snippet = _clean_text(str(candidate.get("snippet") or "")).lower()
        score = int(candidate.get("score") or 0)
        if any(keyword in title for keyword in EXTERNAL_SIGNAL_KEYWORDS):
            score += 14
        if any(keyword in snippet for keyword in EXTERNAL_SIGNAL_KEYWORDS):
            score += 8
        if "/news/" in parsed.path.lower():
            score += 3
        if score < 10:
            continue
        seen.add(url)
        selected.append((score, candidate))
    selected.sort(key=lambda item: (-item[0], str(item[1].get("url") or "")))
    return [candidate for score, candidate in selected[:MAX_EXTERNAL_PAGES]]


def _score_candidate(
    url: str,
    title: str,
    vendor_name: str,
    snippet: str = "",
    *,
    allow_blocked: bool = False,
    country: str = "",
) -> int:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not host:
        return -100
    if _is_recruiting_host(host, parsed.path, title, snippet):
        return -100
    blocked_host = any(pattern in host for pattern in BAD_HOST_PATTERNS)
    if blocked_host and not allow_blocked:
        return -100

    vendor_tokens = _normalize_name_tokens(vendor_name)
    title_lower = _clean_text(title).lower()
    snippet_lower = _clean_text(snippet).lower()
    if any(pattern in title_lower for pattern in BAD_TITLE_PATTERNS):
        if not (allow_blocked and any(pattern in host for pattern in SNIPPET_ONLY_HOST_PATTERNS)):
            return -50
    score = 0
    for token in vendor_tokens:
        if token in host:
            score += 15
        if token in title_lower:
            score += 6
        if token in snippet_lower:
            score += 4
    if "." not in host:
        score -= 5
    if any(host.startswith(prefix) for prefix in ("www.", "en.")):
        score += 2
    if title_lower.startswith(vendor_name.lower()):
        score += 10
    if any(keyword in title_lower for keyword in SEARCH_KEYWORDS):
        score += 2
    if any(keyword in snippet_lower for keyword in EXTERNAL_SIGNAL_KEYWORDS):
        score += 6
    if parsed.path not in {"", "/"}:
        score -= 2
    if blocked_host:
        score -= 4
    score -= _country_mismatch_penalty(host, title_lower, snippet_lower, country)
    return score


def _search_providers_available(provider_state: dict[str, bool] | None) -> bool:
    if provider_state is None:
        return True
    return any(provider_state.get(name, True) for name in SEARCH_PROVIDER_NAMES)


def _query_requires_high_signal_results(query: str) -> bool:
    normalized = f" {_clean_text(query).lower()} "
    if any(keyword in normalized for keyword in IDENTIFIER_SIGNAL_KEYWORDS):
        return True
    if any(f" {keyword} " in normalized for keyword in EXTERNAL_SIGNAL_KEYWORDS):
        return True
    return any(keyword in normalized for keyword in LEADERSHIP_SIGNAL_KEYWORDS)


def _candidate_has_required_signal(candidate: dict, vendor_name: str, query: str) -> bool:
    title = _clean_text(str(candidate.get("title") or "")).lower()
    snippet = _clean_text(str(candidate.get("snippet") or "")).lower()
    url = str(candidate.get("url") or "").strip().lower()
    combined = f" {title} {snippet} {url} "
    normalized_query = f" {_clean_text(query).lower()} "

    if any(keyword in normalized_query for keyword in IDENTIFIER_SIGNAL_KEYWORDS):
        return any(keyword in combined for keyword in IDENTIFIER_SIGNAL_KEYWORDS)

    vendor_tokens = _normalize_name_tokens(vendor_name)
    required_token_hits = 1 if len(vendor_tokens) <= 2 else 2
    token_hits = sum(1 for token in vendor_tokens if token and f" {token} " in combined)
    if vendor_tokens and token_hits < required_token_hits:
        return False
    if any(f" {keyword} " in combined for keyword in EXTERNAL_SIGNAL_KEYWORDS):
        return True
    return any(keyword in combined for keyword in LEADERSHIP_SIGNAL_KEYWORDS)


def _search(query: str, vendor_name: str, *, allow_blocked: bool = False, country: str = "") -> list[dict]:
    response = requests.get(
        SEARCH_URL,
        params={"q": query},
        timeout=SEARCH_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    response.raise_for_status()

    candidates: list[dict] = []
    seen: set[str] = set()
    snippets = [_clean_text(match.group("snippet") or "") for match in SNIPPET_RE.finditer(response.text)]
    for idx, match in enumerate(ANCHOR_RE.finditer(response.text)):
        href = _unwrap_result_url(match.group("href") or "")
        title = _clean_text(match.group("title") or "")
        snippet = snippets[idx] if idx < len(snippets) else ""
        if not href or not title:
            continue
        normalized_url = href.strip()
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        score = _score_candidate(
            normalized_url,
            title,
            vendor_name,
            snippet,
            allow_blocked=allow_blocked,
            country=country,
        )
        if score < 0:
            continue
        host = urlparse(normalized_url).netloc.lower()
        candidates.append(
            {
                "url": normalized_url,
                "title": title,
                "snippet": snippet,
                "score": score,
                "blocked_host": any(pattern in host for pattern in BAD_HOST_PATTERNS),
            }
        )

    candidates.sort(key=lambda item: (-item["score"], item["url"]))
    return candidates[:SEARCH_RESULT_WINDOW]


def _search_lite(query: str, vendor_name: str, *, allow_blocked: bool = False, country: str = "") -> list[dict]:
    response = requests.get(
        SEARCH_LITE_URL,
        params={"q": query},
        timeout=SEARCH_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    response.raise_for_status()

    candidates: list[dict] = []
    seen: set[str] = set()
    snippets = [_clean_text(match.group("snippet") or "") for match in LITE_SNIPPET_RE.finditer(response.text)]
    result_idx = 0
    for match in LITE_LINK_RE.finditer(response.text):
        attrs = _extract_html_attrs(match.group("attrs") or "")
        classes = attrs.get("class", "")
        if "result-link" not in classes.split():
            continue
        href = _unwrap_result_url(attrs.get("href", ""))
        title = _clean_text(match.group("title") or "")
        snippet = snippets[result_idx] if result_idx < len(snippets) else ""
        result_idx += 1
        if not href or not title:
            continue
        normalized_url = href.strip()
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        score = _score_candidate(
            normalized_url,
            title,
            vendor_name,
            snippet,
            allow_blocked=allow_blocked,
            country=country,
        )
        if score < 0:
            continue
        host = urlparse(normalized_url).netloc.lower()
        candidates.append(
            {
                "url": normalized_url,
                "title": title,
                "snippet": snippet,
                "score": score,
                "blocked_host": any(pattern in host for pattern in BAD_HOST_PATTERNS),
                "search_provider": "duckduckgo_lite",
            }
        )

    candidates.sort(key=lambda item: (-item["score"], item["url"]))
    return candidates[:SEARCH_RESULT_WINDOW]


def _search_brave(query: str, vendor_name: str, *, allow_blocked: bool = False, country: str = "") -> list[dict]:
    response = requests.get(
        BRAVE_SEARCH_URL,
        params={"q": query, "source": "web"},
        timeout=SEARCH_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    response.raise_for_status()

    candidates: list[dict] = []
    seen: set[str] = set()
    starts = [match.start() for match in BRAVE_BLOCK_START_RE.finditer(response.text)]
    starts.append(len(response.text))
    for idx, start in enumerate(starts[:-1]):
        block = response.text[start:starts[idx + 1]]
        href_match = BRAVE_HREF_RE.search(block)
        title_match = BRAVE_TITLE_RE.search(block)
        if not href_match or not title_match:
            continue
        href = _unwrap_result_url(href_match.group("href") or "")
        title = _clean_text(title_match.group("title") or "")
        snippet_match = BRAVE_SNIPPET_TEXT_RE.search(block)
        snippet = _clean_text(snippet_match.group("snippet") or "") if snippet_match else ""
        if not href or not title:
            continue
        normalized_url = href.strip()
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        score = _score_candidate(
            normalized_url,
            title,
            vendor_name,
            snippet,
            allow_blocked=allow_blocked,
            country=country,
        )
        if score < 0:
            continue
        host = urlparse(normalized_url).netloc.lower()
        candidates.append(
            {
                "url": normalized_url,
                "title": title,
                "snippet": snippet,
                "score": score,
                "blocked_host": any(pattern in host for pattern in BAD_HOST_PATTERNS),
                "search_provider": "brave",
            }
        )

    candidates.sort(key=lambda item: (-item["score"], item["url"]))
    return candidates[:MAX_RESULTS]


def _search_yahoo(query: str, vendor_name: str, *, allow_blocked: bool = False, country: str = "") -> list[dict]:
    provider_query = _quote_vendor_phrase(query, vendor_name)
    response = requests.get(
        YAHOO_SEARCH_URL,
        params={"p": provider_query},
        timeout=SEARCH_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    response.raise_for_status()

    candidates: list[dict] = []
    seen: set[str] = set()
    starts = [match.start() for match in YAHOO_BLOCK_START_RE.finditer(response.text)]
    starts.append(len(response.text))
    for idx, start in enumerate(starts[:-1]):
        block = response.text[start:starts[idx + 1]]
        href_match = YAHOO_HREF_RE.search(block)
        if not href_match:
            continue
        href = _unwrap_result_url(href_match.group("href") or "")
        title = _clean_text(href_match.group("title") or "")
        snippet_match = YAHOO_SNIPPET_RE.search(block)
        snippet = _clean_text(snippet_match.group("snippet") or "") if snippet_match else ""
        if not href or not title:
            continue
        normalized_url = href.strip()
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        score = _score_candidate(
            normalized_url,
            title,
            vendor_name,
            snippet,
            allow_blocked=allow_blocked,
            country=country,
        )
        if score < 0:
            continue
        host = urlparse(normalized_url).netloc.lower()
        candidates.append(
            {
                "url": normalized_url,
                "title": title,
                "snippet": snippet,
                "score": score,
                "blocked_host": any(pattern in host for pattern in BAD_HOST_PATTERNS),
                "search_provider": "yahoo",
            }
        )

    candidates.sort(key=lambda item: (-item["score"], item["url"]))
    return candidates[:SEARCH_RESULT_WINDOW]


def _search_bing(query: str, vendor_name: str, *, allow_blocked: bool = False, country: str = "") -> list[dict]:
    response = requests.get(
        BING_SEARCH_URL,
        params={"q": query},
        timeout=SEARCH_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    response.raise_for_status()

    candidates: list[dict] = []
    seen: set[str] = set()
    starts = [match.start() for match in BING_BLOCK_START_RE.finditer(response.text)]
    starts.append(len(response.text))
    for idx, start in enumerate(starts[:-1]):
        block = response.text[start:starts[idx + 1]]
        href_match = BING_HREF_RE.search(block)
        if not href_match:
            continue
        href = _unwrap_result_url(href_match.group("href") or "")
        title = _clean_text(href_match.group("title") or "")
        snippet_match = BING_SNIPPET_RE.search(block)
        snippet = _clean_text(snippet_match.group("snippet") or "") if snippet_match else ""
        if not href or not title:
            continue
        normalized_url = href.strip()
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        score = _score_candidate(
            normalized_url,
            title,
            vendor_name,
            snippet,
            allow_blocked=allow_blocked,
            country=country,
        )
        if score < 0:
            continue
        host = urlparse(normalized_url).netloc.lower()
        candidates.append(
            {
                "url": normalized_url,
                "title": title,
                "snippet": snippet,
                "score": score,
                "blocked_host": any(pattern in host for pattern in BAD_HOST_PATTERNS),
                "search_provider": "bing",
            }
        )

    candidates.sort(key=lambda item: (-item["score"], item["url"]))
    return candidates[:SEARCH_RESULT_WINDOW]


def _search_with_fallbacks(
    query: str,
    vendor_name: str,
    *,
    allow_blocked: bool = False,
    country: str = "",
    provider_state: dict[str, bool] | None = None,
) -> list[dict]:
    search_chain = (
        ("duckduckgo_html", _search),
        ("duckduckgo_lite", _search_lite),
        ("yahoo", _search_yahoo),
        ("brave", _search_brave),
        ("bing", _search_bing),
    )
    require_high_signal = _query_requires_high_signal_results(query)
    merged: list[dict] = []
    seen_urls: set[str] = set()
    for provider_name, search_fn in search_chain:
        if provider_state is not None and not provider_state.get(provider_name, True):
            continue
        try:
            candidates = search_fn(query, vendor_name, allow_blocked=allow_blocked, country=country)
        except Exception:
            if provider_state is not None:
                provider_state[provider_name] = False
            continue
        if provider_state is not None:
            provider_state[provider_name] = True
        if not candidates:
            continue
        for candidate in candidates:
            normalized = dict(candidate)
            normalized.setdefault("search_provider", provider_name)
            url = str(normalized.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(normalized)
        if not require_high_signal:
            break
        if any(_candidate_has_required_signal(candidate, vendor_name, query) for candidate in merged):
            break

    merged.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("url") or "")))
    return merged[:SEARCH_RESULT_WINDOW]


def _merge_unique_relationships(relationships: Iterable[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for relationship in relationships:
        key = (
            str(relationship.get("type") or ""),
            str(relationship.get("source_entity") or "").upper(),
            str(relationship.get("target_entity") or "").upper(),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(relationship)
    return merged


def _merge_identifier_values(
    target: dict,
    incoming: dict,
    *,
    identifier_ranks: dict[str, int] | None = None,
    incoming_rank: int = 0,
    incoming_ranks: dict[str, float] | None = None,
) -> None:
    target_cage = str(target.get("cage") or target.get("ncage") or "").strip().upper()
    incoming_cage = str((incoming or {}).get("cage") or (incoming or {}).get("ncage") or "").strip().upper()
    if target_cage and incoming_cage and target_cage != incoming_cage:
        return
    for key, value in (incoming or {}).items():
        if value in (None, "", []):
            continue
        effective_rank = float((incoming_ranks or {}).get(str(key), incoming_rank))
        if key not in target or target.get(key) in (None, "", []):
            target[key] = value
            if identifier_ranks is not None:
                identifier_ranks[str(key)] = effective_rank
            continue
        if identifier_ranks is not None and effective_rank > float(identifier_ranks.get(str(key), 0) or 0):
            target[key] = value
            identifier_ranks[str(key)] = effective_rank


def _identifier_ranks_from_findings(findings: list[Finding], *, access_bonus: float = 0.0) -> dict[str, float]:
    ranks: dict[str, float] = {}
    for finding in findings:
        structured = finding.structured_fields or {}
        key = str(structured.get("identifier_type") or "").strip()
        if not key:
            continue
        rank = float(finding.confidence or 0.0) + access_bonus
        if rank > float(ranks.get(key, 0.0)):
            ranks[key] = rank
    return ranks


def _merge_enrichment_result(
    result: EnrichmentResult,
    incoming: EnrichmentResult,
    *,
    relationships: list[dict],
    findings: list[Finding],
    risk_signals: list[dict],
    artifact_refs: list[str],
    seen_finding_keys: set[tuple[str, str, str]],
) -> None:
    _merge_identifier_values(result.identifiers, incoming.identifiers)
    relationships.extend(incoming.relationships)
    for finding in incoming.findings:
        artifact_ref = str(finding.artifact_ref or finding.url or "")
        key = (finding.category, finding.title, artifact_ref)
        if key in seen_finding_keys:
            continue
        seen_finding_keys.add(key)
        findings.append(finding)
    risk_signals.extend(incoming.risk_signals)
    artifact_refs.extend([ref for ref in incoming.artifact_refs if ref])


def _within_budget(deadline: float, *, reserve_seconds: float = 0.0) -> bool:
    return time.monotonic() + reserve_seconds < deadline


def _extract_external_relationships(
    vendor_name: str,
    country: str,
    website: str,
    candidate: dict,
    *,
    vendor_variants: Iterable[str] | None = None,
) -> tuple[list[dict], list[Finding], list[dict], list[str], dict[str, str]]:
    url = str(candidate.get("url") or "").strip()
    title = _clean_text(str(candidate.get("title") or "")).strip()
    if not url:
        return [], [], [], [], {}
    try:
        html_text, _content_type = public_html_ownership._fetch_page(url)
    except Exception:
        return [], [], [], [], {}
    text = public_html_ownership._extract_text(html_text)
    if not text:
        return [], [], [], [], {}

    relationships: list[dict] = []
    findings: list[Finding] = []
    risk_signals: list[dict] = []
    artifact_refs: list[str] = [url]
    identifiers: dict[str, str] = {}
    for key, hint in public_html_ownership._extract_identifier_hints(text).items():
        value = str(hint["value"])
        identifiers[key] = value
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category="identity",
                title=f"Public search identifier hint: {hint['label']} {value}",
                detail=f"{hint['snippet']} | Search result: {title} | Source page: {url}",
                severity="info",
                confidence=max(0.54, min(float(hint["confidence"]) - 0.06, 0.74)),
                url=url,
                artifact_ref=url,
                source_class="public_connector",
                authority_level="third_party_public",
                access_model="search_public_html",
                structured_fields={
                    "identifier_type": key,
                    "identifier_value": value,
                    "search_result_title": title,
                    "search_result_url": url,
                    "search_score": int(candidate.get("score") or 0),
                    "source_page": url,
                    "website": website,
                },
            )
        )
    host = urlparse(url).netloc.lower()
    allows_broad_html_patterns = not (
        candidate.get("blocked_host") or any(pattern in host for pattern in SNIPPET_ONLY_HOST_PATTERNS)
    )
    extracted_candidates: list[dict] = []
    if allows_broad_html_patterns:
        extracted_candidates.extend(public_html_ownership._extract_candidates(text, vendor_name, url))
    if not extracted_candidates:
        extracted_candidates.extend(
            _extract_search_pattern_candidates(vendor_name, text, vendor_variants=vendor_variants)
        )
    for extracted in extracted_candidates:
        rel_type = str(extracted["rel_type"])
        confidence = max(0.52, min(float(extracted["confidence"]) - 0.08, 0.74))
        if rel_type == "led_by":
            relationship = {
                "type": rel_type,
                "source_entity": vendor_name,
                "source_entity_type": "company",
                "source_identifiers": {"website": website} if website else {},
                "target_entity": str(extracted["target_entity"]),
                "target_entity_type": "person",
                "target_identifiers": {},
                "country": country,
                "data_source": SOURCE_NAME,
                "confidence": confidence,
                "evidence": str(extracted["snippet"]),
                "observed_at": datetime.utcnow().isoformat() + "Z",
                "artifact_ref": url,
                "evidence_url": url,
                "evidence_title": "Public search leadership/control signal",
                "structured_fields": {
                    "relationship_scope": str(extracted["scope"]),
                    "extraction_method": "search_leadership_pattern",
                    "search_result_title": title,
                    "search_result_url": url,
                    "search_score": int(candidate.get("score") or 0),
                    "source_page": url,
                    "website": website,
                },
                "source_class": "public_connector",
                "authority_level": "third_party_public",
                "access_model": "search_public_html",
                "raw_data": {
                    "snippet": str(extracted["snippet"]),
                    "website": website,
                    "page_url": url,
                },
            }
        else:
            relationship = public_html_ownership._build_relationship(
                vendor_name=vendor_name,
                country=country,
                website=website,
                rel_type=rel_type,
                parent_name=str(extracted["target_entity"]),
                page_url=url,
                confidence=confidence,
                scope=str(extracted["scope"]),
                snippet=str(extracted["snippet"]),
            )
            relationship["data_source"] = SOURCE_NAME
            relationship["evidence_title"] = "Public search ownership/control signal"
            relationship["source_class"] = "public_connector"
            relationship["authority_level"] = "third_party_public"
            relationship["access_model"] = "search_public_html"
            structured_fields = dict(relationship.get("structured_fields") or {})
            structured_fields.update(
                {
                    "search_result_title": title,
                    "search_result_url": url,
                    "search_score": int(candidate.get("score") or 0),
                    "source_page": url,
                }
            )
            relationship["structured_fields"] = structured_fields
        relationships.append(relationship)

        finding_category = "ownership" if rel_type == "owned_by" else "governance" if rel_type == "led_by" else "finance"
        finding_title = (
            f"Public search ownership hint: {extracted['target_entity']}"
            if rel_type == "owned_by"
            else f"Public search leadership-control hint: {extracted['target_entity']}"
            if rel_type == "led_by"
            else f"Public search financial backer hint: {extracted['target_entity']}"
        )
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category=finding_category,
                title=finding_title,
                detail=f"{extracted['snippet']} | Search result: {title} | Source page: {url}",
                severity="info",
                confidence=confidence,
                url=url,
                artifact_ref=url,
                source_class="public_connector",
                authority_level="third_party_public",
                access_model="search_public_html",
                structured_fields={
                    "search_result_title": title,
                    "search_result_url": url,
                    "search_score": int(candidate.get("score") or 0),
                    "relationship_scope": str(extracted["scope"]),
                    "website": website,
                },
            )
        )
        risk_signals.append(
            {
                "signal": "search_reported_control" if rel_type in {"owned_by", "led_by"} else "search_reported_financing",
                "source": SOURCE_NAME,
                "severity": "info",
                "confidence": confidence,
                "summary": f"Public search surfaced {rel_type} hint for {vendor_name}",
                "website": website,
                "search_result_title": title,
                "url": url,
            }
        )

    if not relationships:
        title_text = _clean_text(title)
        snippet_text = _clean_text(str(candidate.get("snippet") or ""))
        normalized_vendor_variants = [
            re.sub(r"[^a-z0-9]+", " ", variant.lower()).strip()
            for variant in (vendor_variants or _search_queries(vendor_name))
            if variant
        ]
        normalized_title = re.sub(r"[^a-z0-9]+", " ", title_text.lower()).strip()
        normalized_title_haystack = f" {title_text.lower()} "
        investor_like_site = any(keyword in host for keyword in INVESTOR_SITE_KEYWORDS)
        investor_like_title = any(pattern in normalized_title_haystack for pattern in INVESTOR_TITLE_INFERENCE_PATTERNS)
        pieces = [piece.strip() for piece in re.split(r"\s+[|—-]\s+", title_text) if piece.strip()]
        inferred_parent = pieces[-1] if len(pieces) >= 2 else ""
        inferred_parent = public_html_ownership._clean_parent_name(inferred_parent)
        inferred_parent_lower = inferred_parent.lower()
        inferred_parent_investor_like = any(keyword in inferred_parent_lower for keyword in INVESTOR_SITE_KEYWORDS)
        allows_title_inference = investor_like_site or investor_like_title or inferred_parent_investor_like
        if allows_title_inference and any(
            normalized_variant and normalized_variant in normalized_title
            for normalized_variant in normalized_vendor_variants
        ):
            if (
                inferred_parent
                and public_html_ownership._looks_like_entity_name(inferred_parent, inferred_parent)
                and not public_html_ownership._looks_like_vendor(inferred_parent, vendor_name)
            ):
                confidence = 0.48
                evidence = snippet_text or title_text
                relationships.append(
                    {
                        "type": "backed_by",
                        "source_entity": vendor_name,
                        "source_entity_type": "company",
                        "source_identifiers": {"website": website} if website else {},
                        "target_entity": inferred_parent,
                        "target_entity_type": "holding_company",
                        "target_identifiers": {},
                        "country": country,
                        "data_source": SOURCE_NAME,
                        "confidence": confidence,
                        "evidence": evidence,
                        "observed_at": datetime.utcnow().isoformat() + "Z",
                        "artifact_ref": url,
                        "evidence_url": url,
                        "evidence_title": "Public search investor page hint",
                        "structured_fields": {
                            "relationship_scope": "portfolio_title_inference",
                            "extraction_method": "search_title_inference",
                            "search_result_title": title_text,
                            "search_result_url": url,
                            "search_score": int(candidate.get("score") or 0),
                            "source_page": url,
                        },
                        "source_class": "public_connector",
                        "authority_level": "third_party_public",
                        "access_model": "search_public_html",
                        "raw_data": {
                            "title": title_text,
                            "snippet": snippet_text,
                            "website": website,
                            "page_url": url,
                        },
                    }
                )
                findings.append(
                    Finding(
                        source=SOURCE_NAME,
                        category="finance",
                        title=f"Public search financial backer hint: {inferred_parent}",
                        detail=f"{evidence} | Search result: {title_text} | Source page: {url}",
                        severity="info",
                        confidence=confidence,
                        url=url,
                        artifact_ref=url,
                        source_class="public_connector",
                        authority_level="third_party_public",
                        access_model="search_public_html",
                        structured_fields={
                            "search_result_title": title_text,
                            "search_result_url": url,
                            "search_score": int(candidate.get("score") or 0),
                            "relationship_scope": "portfolio_title_inference",
                            "website": website,
                        },
                    )
                )
                risk_signals.append(
                    {
                        "signal": "search_reported_financing",
                        "source": SOURCE_NAME,
                        "severity": "info",
                        "confidence": confidence,
                        "summary": f"Investor-site portfolio page surfaced backing hint for {vendor_name}",
                        "website": website,
                        "search_result_title": title_text,
                        "url": url,
                    }
                )

    return relationships, findings, risk_signals, artifact_refs, identifiers


def _synthetic_finance_profile_candidates(
    vendor_name: str,
    aliases: Iterable[str] | None = None,
) -> list[dict]:
    candidate_names = [
        *_legacy_corporate_query_variants(vendor_name),
        *_expanded_search_queries(vendor_name, aliases),
    ]
    vendor_tokens = set(_normalize_name_tokens(vendor_name))
    candidates: list[dict] = []
    seen_urls: set[str] = set()
    for slug in _finance_profile_slug_candidates(candidate_names):
        for template in SYNTHETIC_FINANCE_PROFILE_TEMPLATES:
            url = template.format(slug=slug)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                html_text, _content_type = public_html_ownership._fetch_page(url)
            except Exception:
                continue
            text = public_html_ownership._extract_text(html_text)
            title = _extract_html_title(html_text)
            corpus = f" {title.lower()} {text.lower()} "
            if vendor_tokens and not any(token in corpus for token in vendor_tokens):
                continue
            score = 28 + (8 if "/financials" in url else 0)
            candidates.append(
                {
                    "url": url,
                    "title": title or slug.replace("-", " ").title(),
                    "snippet": text[:280],
                    "score": score,
                    "blocked_host": True,
                    "search_provider": "synthetic_finance_profile",
                }
            )
            if len(candidates) >= MAX_SYNTHETIC_FINANCE_PAGES:
                return candidates
    return candidates


def _snippet_signal_candidates(candidates: list[dict], website: str, vendor_name: str) -> list[dict]:
    official_host = urlparse(website).netloc.lower()
    vendor_tokens = _normalize_name_tokens(vendor_name)
    required_token_hits = 1 if len(vendor_tokens) <= 2 else 2
    selected: list[tuple[int, dict]] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = str(candidate.get("url") or "").strip()
        if not url or url in seen:
            continue
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if not host:
            continue
        same_host = host == official_host
        if same_host and parsed.path in {"", "/"}:
            continue
        snippet = _clean_text(str(candidate.get("snippet") or "")).lower()
        title = _clean_text(str(candidate.get("title") or "")).lower()
        vendor_haystack = re.sub(r"[^a-z0-9]+", " ", f"{host} {title} {snippet}".lower()).strip()
        vendor_haystack = f" {vendor_haystack} "
        token_hits = sum(1 for token in vendor_tokens if token and f" {token} " in vendor_haystack)
        if vendor_tokens and token_hits < required_token_hits:
            continue
        if not snippet:
            continue
        combined = f" {title} {snippet} "
        has_external_signal = any(f" {keyword} " in combined for keyword in EXTERNAL_SIGNAL_KEYWORDS)
        has_leadership_signal = any(keyword in combined for keyword in LEADERSHIP_SIGNAL_KEYWORDS)
        if not has_external_signal and not has_leadership_signal:
            continue
        if candidate.get("blocked_host") and not any(pattern in host for pattern in SNIPPET_ONLY_HOST_PATTERNS):
            continue
        score = int(candidate.get("score") or 0)
        if any(keyword in snippet for keyword in ("investors of", "portfolio company of", "invested in", "backed by")):
            score += 12
        if any(keyword in title for keyword in ("funding", "investors", "valuation")):
            score += 4
        if any(keyword in f"{title} {snippet}" for keyword in ("to acquire", "acquires", "acquired by", "acquisition of")):
            score += 10
        if has_leadership_signal:
            score += 8
        if same_host:
            score += 3
        seen.add(url)
        selected.append((score, candidate))
    selected.sort(key=lambda item: (-item[0], str(item[1].get("url") or "")))
    return [candidate for score, candidate in selected[:MAX_RESULTS]]


def _identifier_signal_candidates(candidates: list[dict], website: str, vendor_name: str) -> list[dict]:
    official_host = urlparse(website).netloc.lower()
    vendor_tokens = _normalize_name_tokens(vendor_name)
    required_title_hits = 1 if len(vendor_tokens) <= 2 else 2
    selected: list[tuple[int, dict]] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = str(candidate.get("url") or "").strip()
        if not url or url in seen:
            continue
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if not host:
            continue
        title = _clean_text(str(candidate.get("title") or "")).lower()
        snippet = _clean_text(str(candidate.get("snippet") or "")).lower()
        vendor_title_haystack = re.sub(r"[^a-z0-9]+", " ", f"{host} {title}".lower()).strip()
        vendor_title_haystack = f" {vendor_title_haystack} "
        title_token_hits = sum(1 for token in vendor_tokens if token and f" {token} " in vendor_title_haystack)
        combined = f" {title} {snippet} "
        identifier_query = bool(candidate.get("identifier_query"))
        if not identifier_query and not any(keyword in combined for keyword in IDENTIFIER_SIGNAL_KEYWORDS):
            continue
        if vendor_tokens and host != official_host and title_token_hits < required_title_hits:
            continue
        score = int(candidate.get("score") or 0)
        if identifier_query:
            score += 8
        if host == official_host:
            score += 10
        if title_token_hits:
            score += title_token_hits * 8
        if any(keyword in combined for keyword in (" cage ", " uei ", " duns ", " ncage ")):
            score += 12
        if any(keyword in combined for keyword in ("cage code", "unique entity id", "company type", "duns number", "ncage code")):
            score += 8
        seen.add(url)
        selected.append((score, candidate))
    selected.sort(key=lambda item: (-item[0], str(item[1].get("url") or "")))
    return [candidate for score, candidate in selected[:IDENTIFIER_MAX_RESULTS]]


def _extract_snippet_relationships(
    vendor_name: str,
    country: str,
    website: str,
    candidate: dict,
    *,
    vendor_variants: Iterable[str] | None = None,
) -> tuple[list[dict], list[Finding], list[dict], list[str]]:
    url = str(candidate.get("url") or "").strip()
    title = _clean_text(str(candidate.get("title") or "")).strip()
    snippet = _clean_text(str(candidate.get("snippet") or "")).strip()
    if not url or not snippet:
        return [], [], [], []

    snippet_text = f"{title}. {snippet}".strip()
    extracted_candidates = public_html_ownership._extract_candidates(snippet_text, vendor_name, url)
    if not extracted_candidates:
        extracted_candidates = _extract_search_pattern_candidates(
            vendor_name,
            snippet_text,
            vendor_variants=vendor_variants,
        )
    relationships: list[dict] = []
    findings: list[Finding] = []
    risk_signals: list[dict] = []
    artifact_refs: list[str] = [url]
    for extracted in extracted_candidates:
        rel_type = str(extracted["rel_type"])
        confidence = max(0.46, min(float(extracted["confidence"]) - 0.12, 0.60))
        relationship = {
            "type": rel_type,
            "source_entity": vendor_name,
            "source_entity_type": "company",
            "source_identifiers": {"website": website} if website else {},
            "target_entity": str(extracted["target_entity"]),
            "target_entity_type": "person" if rel_type == "led_by" else "holding_company",
            "target_identifiers": {},
            "country": country,
            "data_source": SOURCE_NAME,
            "confidence": confidence,
            "evidence": snippet,
            "observed_at": datetime.utcnow().isoformat() + "Z",
            "artifact_ref": url,
            "evidence_url": url,
            "evidence_title": "Public search leadership/control snippet" if rel_type == "led_by" else "Public search ownership/control snippet",
            "structured_fields": {
                "relationship_scope": (
                    str(extracted["scope"])
                    if rel_type in {"owned_by", "led_by"}
                    else "search_snippet_financing"
                ),
                "extraction_method": "search_leadership_pattern" if rel_type == "led_by" else "search_snippet_pattern",
                "search_result_title": title,
                "search_result_url": url,
                "search_score": int(candidate.get("score") or 0),
                "snippet_only": True,
                "website": website,
            },
            "source_class": "public_connector",
            "authority_level": "third_party_public",
            "access_model": "search_snippet_only",
            "raw_data": {
                "snippet": snippet,
                "title": title,
                "website": website,
            },
        }
        relationships.append(relationship)
        finding_category = "ownership" if rel_type == "owned_by" else "governance" if rel_type == "led_by" else "finance"
        finding_title = (
            f"Public search ownership hint: {extracted['target_entity']}"
            if rel_type == "owned_by"
            else f"Public search leadership-control hint: {extracted['target_entity']}"
            if rel_type == "led_by"
            else f"Public search financial backer hint: {extracted['target_entity']}"
        )
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category=finding_category,
                title=finding_title,
                detail=f"{snippet} | Search result: {title} | Source page: {url}",
                severity="info",
                confidence=confidence,
                url=url,
                artifact_ref=url,
                source_class="public_connector",
                authority_level="third_party_public",
                access_model="search_snippet_only",
                structured_fields={
                    "search_result_title": title,
                    "search_result_url": url,
                    "search_score": int(candidate.get("score") or 0),
                    "relationship_scope": (
                        str(extracted["scope"])
                        if rel_type in {"owned_by", "led_by"}
                        else "search_snippet_financing"
                    ),
                    "snippet_only": True,
                    "website": website,
                },
            )
        )
        risk_signals.append(
            {
                "signal": "search_reported_control" if rel_type in {"owned_by", "led_by"} else "search_reported_financing",
                "source": SOURCE_NAME,
                "severity": "info",
                "confidence": confidence,
                "summary": f"Public search snippet surfaced {rel_type} hint for {vendor_name}",
                "website": website,
                "search_result_title": title,
                "url": url,
            }
        )
    return relationships, findings, risk_signals, artifact_refs


def _extract_search_pattern_candidates(
    vendor_name: str,
    text: str,
    *,
    vendor_variants: Iterable[str] | None = None,
) -> list[dict]:
    if not text:
        return []
    extracted_candidates: list[dict] = []
    search_vendor_variants = sorted(
        {variant for variant in (vendor_variants or _search_queries(vendor_name)) if variant},
        key=len,
        reverse=True,
    )
    for vendor_variant in search_vendor_variants:
        vendor_pattern = _search_snippet_vendor_pattern(vendor_variant)
        snippet_patterns: tuple[tuple[re.Pattern[str], str, float, str], ...] = (
            (
                re.compile(
                    rf"([A-Z][A-Za-z0-9&.,'()/ -]{{2,120}}?)\s+(?:completes?|completed)\s+acquisition of\s+{vendor_pattern}",
                    re.IGNORECASE,
                ),
                "owned_by",
                0.62,
                "acquisition_complete_snippet",
            ),
            (
                re.compile(
                    rf"([A-Z][A-Za-z0-9&.,'()/ -]{{2,120}}?)\s+(?:to\s+)?acquire(?:s|d)?\s+{vendor_pattern}",
                    re.IGNORECASE,
                ),
                "owned_by",
                0.58,
                "acquisition_snippet",
            ),
            (
                re.compile(
                    rf"\binvestors?\s+of\s+{vendor_pattern}\s*(?:[?.!]+\s*)?(?:investors?\s+of\s+{vendor_pattern}\s+)?(?:include|are)\s+([A-Z][A-Za-z0-9&.,'()/ -]{{2,120}}?)(?:\s*[?.!]|$)",
                    re.IGNORECASE,
                ),
                "backed_by",
                0.58,
                "investors_include_snippet",
            ),
            (
                re.compile(
                    rf"(?:^|[.!?]\s+)([A-Z][A-Za-z0-9&,'()/ -]{{2,120}}?)\s+invested in\s+{vendor_pattern}(?:\s*['’]\s*s)?(?:\s+[A-Za-z][A-Za-z0-9&.-]*){{0,3}}\s+(?:unattributed\s+vc\s+)?(?:funding|investment)\s+round",
                    re.IGNORECASE,
                ),
                "backed_by",
                0.58,
                "invested_in_round_snippet",
            ),
            (
                re.compile(
                    rf"{vendor_pattern}(?:\s*['’]\s*s)?\s+(?:president|ceo|chief executive officer|founder)\s+is\s+([A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+){{1,3}})",
                    re.IGNORECASE,
                ),
                "led_by",
                0.54,
                "leadership_control_snippet",
            ),
        )
        for pattern, rel_type, confidence, scope in snippet_patterns:
            for hit in pattern.finditer(text):
                parent_name = public_html_ownership._clean_parent_name(hit.group(1))
                if (
                    not parent_name
                    or not public_html_ownership._looks_like_entity_name(parent_name, parent_name)
                    or public_html_ownership._looks_like_vendor(parent_name, vendor_name)
                ):
                    continue
                start, end = hit.span()
                snippet = text[max(0, start - 180):min(len(text), end + 180)].strip()
                extracted_candidates.append(
                    {
                        "target_entity": parent_name,
                        "rel_type": rel_type,
                        "confidence": confidence,
                        "scope": scope,
                        "snippet": snippet or text[:360],
                    }
                )
        if extracted_candidates:
            break
    return extracted_candidates


def _extract_snippet_identifiers(
    website: str,
    candidate: dict,
    *,
    vendor_name: str,
) -> tuple[dict[str, str], list[Finding], list[str]]:
    url = str(candidate.get("url") or "").strip()
    title = _clean_text(str(candidate.get("title") or "")).strip()
    snippet = _clean_text(str(candidate.get("snippet") or "")).strip()
    if not url or not snippet:
        return {}, [], []

    snippet_text = f"{title}. {snippet}".strip()
    identifiers: dict[str, str] = {}
    findings: list[Finding] = []
    for key, hint in public_html_ownership._extract_identifier_hints(
        snippet_text,
        vendor_name=vendor_name,
    ).items():
        if float(hint["confidence"]) < SNIPPET_IDENTIFIER_MIN_CONFIDENCE:
            continue
        value = str(hint["value"])
        identifiers[key] = value
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category="identity",
                title=f"Public search identifier hint: {hint['label']} {value}",
                detail=f"{snippet} | Search result: {title} | Source page: {url}",
                severity="info",
                confidence=max(0.46, min(float(hint["confidence"]) - 0.16, 0.60)),
                url=url,
                artifact_ref=url,
                source_class="public_connector",
                authority_level="third_party_public",
                access_model="search_snippet_only",
                structured_fields={
                    "identifier_type": key,
                    "identifier_value": value,
                    "search_result_title": title,
                    "search_result_url": url,
                    "search_score": int(candidate.get("score") or 0),
                    "snippet_only": True,
                    "identifier_confidence": float(hint["confidence"]),
                    "website": website,
                },
            )
        )
    return identifiers, findings, [url] if identifiers else []


def _collect_snippet_relationships(
    vendor_name: str,
    country: str,
    website: str,
    base_candidates: Iterable[dict],
    *,
    deadline: float,
    provider_state: dict[str, bool] | None = None,
    vendor_variants: Iterable[str] | None = None,
) -> tuple[list[dict], list[Finding], list[dict], list[str]]:
    snippet_candidates: list[dict] = list(base_candidates)
    seen_snippet_urls = {str(candidate.get("url") or "") for candidate in snippet_candidates}
    for query in _search_queries(vendor_name):
        if not _within_budget(deadline):
            break
        if not _search_providers_available(provider_state):
            break
        for suffix in SNIPPET_SEARCH_SUFFIXES:
            if not _within_budget(deadline):
                break
            variant_candidates = _search_with_fallbacks(
                f"{query}{suffix}",
                vendor_name,
                allow_blocked=True,
                country=country,
                provider_state=provider_state,
            )
            for candidate in variant_candidates:
                url = str(candidate.get("url") or "")
                if url in seen_snippet_urls:
                    continue
                seen_snippet_urls.add(url)
                snippet_candidates.append(candidate)
    snippet_signal_candidates = _snippet_signal_candidates(snippet_candidates, website, vendor_name)
    if not snippet_signal_candidates:
        for query in _search_queries(vendor_name):
            if not _within_budget(deadline):
                break
            if provider_state is not None and not provider_state.get("brave", True):
                break
            for suffix in SNIPPET_SEARCH_SUFFIXES:
                if not _within_budget(deadline):
                    break
                try:
                    variant_candidates = _search_brave(
                        f"{query}{suffix}",
                        vendor_name,
                        allow_blocked=True,
                        country=country,
                    )
                except Exception:
                    continue
                for candidate in variant_candidates:
                    url = str(candidate.get("url") or "")
                    if url in seen_snippet_urls:
                        continue
                    seen_snippet_urls.add(url)
                    snippet_candidates.append(candidate)
        snippet_signal_candidates = _snippet_signal_candidates(snippet_candidates, website, vendor_name)

    relationships: list[dict] = []
    findings: list[Finding] = []
    risk_signals: list[dict] = []
    artifact_refs: list[str] = []
    for candidate in snippet_signal_candidates:
        candidate_relationships, candidate_findings, candidate_risk_signals, refs = _extract_snippet_relationships(
            vendor_name,
            country,
            website,
            candidate,
            vendor_variants=vendor_variants,
        )
        relationships.extend(candidate_relationships)
        findings.extend(candidate_findings)
        risk_signals.extend(candidate_risk_signals)
        artifact_refs.extend(refs)
    return relationships, findings, risk_signals, artifact_refs


def _extract_external_identifiers(
    website: str,
    candidate: dict,
    *,
    vendor_name: str,
) -> tuple[dict[str, str], list[Finding], list[str]]:
    url = str(candidate.get("url") or "").strip()
    title = _clean_text(str(candidate.get("title") or "")).strip()
    if not url:
        return {}, [], []

    try:
        html_text, _content_type = public_html_ownership._fetch_page(url)
    except Exception:
        return {}, [], []

    text = public_html_ownership._extract_text(html_text)
    if not text:
        return {}, [], []

    identifiers: dict[str, str] = {}
    findings: list[Finding] = []
    for key, hint in public_html_ownership._extract_identifier_hints(
        text,
        vendor_name=vendor_name,
    ).items():
        if float(hint["confidence"]) < EXTERNAL_IDENTIFIER_MIN_CONFIDENCE:
            continue
        value = str(hint["value"])
        identifiers[key] = value
        findings.append(
            Finding(
                source=SOURCE_NAME,
                category="identity",
                title=f"Public search identifier hint: {hint['label']} {value}",
                detail=f"{hint['snippet']} | Search result: {title} | Source page: {url}",
                severity="info",
                confidence=max(0.54, min(float(hint["confidence"]) - 0.06, 0.74)),
                url=url,
                artifact_ref=url,
                source_class="public_connector",
                authority_level="third_party_public",
                access_model="search_public_html",
                structured_fields={
                    "identifier_type": key,
                    "identifier_value": value,
                    "search_result_title": title,
                    "search_result_url": url,
                    "search_score": int(candidate.get("score") or 0),
                    "source_page": url,
                    "identifier_confidence": float(hint["confidence"]),
                    "website": website,
                },
            )
        )
    return identifiers, findings, [url] if identifiers else []


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    result = EnrichmentResult(source=SOURCE_NAME, vendor_name=vendor_name)
    started = datetime.utcnow()
    deadline = time.monotonic() + CONNECTOR_BUDGET_SECONDS
    search_provider_state: dict[str, bool] = {}
    result.source_class = "public_connector"
    result.authority_level = "third_party_public"
    result.access_model = "search_public_html"

    try:
        candidates: list[dict] = []
        identifier_ranks: dict[str, int] = {}
        for query in _search_queries(vendor_name):
            if not _within_budget(deadline):
                break
            candidates = _search_with_fallbacks(
                query,
                vendor_name,
                country=country,
                provider_state=search_provider_state,
            )
            if candidates:
                break
            if not _search_providers_available(search_provider_state):
                break
        if not candidates:
            candidates = _synthetic_official_candidates(vendor_name, country=country)
        if not candidates:
            result.elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
            return result

        official_candidate = _pick_official_candidate(candidates, country=country) or candidates[0]
        website = _official_site_root(official_candidate["url"])
        if not website:
            result.elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
            return result

        result.identifiers["website"] = website
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="identity",
                title=f"Public search discovered official site candidate: {website}",
                detail=(
                    f"Top public search result for {vendor_name} points to {website}. "
                    f"Result title: {official_candidate['title']}"
                ),
                severity="info",
                confidence=min(0.85, 0.45 + (official_candidate["score"] / 40.0)),
                url=website,
                source_class="public_connector",
                authority_level="third_party_public",
                access_model="search_public_html",
                structured_fields={
                    "search_result_title": official_candidate["title"],
                    "search_score": official_candidate["score"],
                },
            )
        )

        merged_relationships: list[dict] = []
        merged_findings: list[Finding] = list(result.findings)
        merged_risk_signals: list[dict] = []
        artifact_refs: list[str] = [website]
        visited_pages: set[str] = set()
        seen_finding_keys: set[tuple[str, str, str]] = {
            (finding.category, finding.title, str(finding.artifact_ref or finding.url or ""))
            for finding in merged_findings
        }

        same_host_pages: list[str] = []
        if _within_budget(deadline):
            root_result, discovered_links = public_html_ownership.extract_page(
                vendor_name,
                country,
                website=website,
                page_url=website,
                discover_links=True,
            )
            _merge_enrichment_result(
                result,
                root_result,
                relationships=merged_relationships,
                findings=merged_findings,
                risk_signals=merged_risk_signals,
                artifact_refs=artifact_refs,
                seen_finding_keys=seen_finding_keys,
            )
            visited_pages.add(website.rstrip("/"))
            same_host_pages.extend(discovered_links)
        if not merged_relationships and _within_budget(deadline, reserve_seconds=8):
            snippet_relationships, snippet_findings, snippet_risk_signals, snippet_refs = _collect_snippet_relationships(
                vendor_name,
                country,
                website,
                candidates,
                deadline=deadline,
                provider_state=search_provider_state,
                vendor_variants=_search_queries(vendor_name),
            )
            merged_relationships.extend(snippet_relationships)
            merged_findings.extend(snippet_findings)
            merged_risk_signals.extend(snippet_risk_signals)
            artifact_refs.extend(snippet_refs)

        same_host_pages.extend(_same_host_candidate_pages(candidates, website))
        for candidate_page in list(dict.fromkeys(same_host_pages)):
            normalized_page = candidate_page.rstrip("/")
            if normalized_page in visited_pages or not _within_budget(deadline):
                continue
            page_result, _discovered = public_html_ownership.extract_page(
                vendor_name,
                country,
                website=website,
                page_url=candidate_page,
                discover_links=False,
            )
            visited_pages.add(normalized_page)
            _merge_enrichment_result(
                result,
                page_result,
                relationships=merged_relationships,
                findings=merged_findings,
                risk_signals=merged_risk_signals,
                artifact_refs=artifact_refs,
                seen_finding_keys=seen_finding_keys,
            )

        if not merged_relationships:
            merged_candidates = list(candidates)
            seen_urls = {str(item.get("url") or "") for item in candidates}
            for query in _site_scoped_queries(vendor_name, website):
                if not _within_budget(deadline):
                    break
                site_candidates = _search_with_fallbacks(
                    query,
                    vendor_name,
                    country=country,
                    provider_state=search_provider_state,
                )
                for candidate in site_candidates:
                    url = str(candidate.get("url") or "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    merged_candidates.append(candidate)
                if not _search_providers_available(search_provider_state):
                    break
            for candidate_page in _same_host_candidate_pages(merged_candidates, website):
                normalized_page = candidate_page.rstrip("/")
                if normalized_page in visited_pages or not _within_budget(deadline):
                    continue
                page_result, _discovered = public_html_ownership.extract_page(
                    vendor_name,
                    country,
                    website=website,
                    page_url=candidate_page,
                    discover_links=False,
                )
                visited_pages.add(normalized_page)
                _merge_enrichment_result(
                    result,
                    page_result,
                    relationships=merged_relationships,
                    findings=merged_findings,
                    risk_signals=merged_risk_signals,
                    artifact_refs=artifact_refs,
                    seen_finding_keys=seen_finding_keys,
                )

        if not merged_relationships:
            expanded_queries = _expanded_search_queries(vendor_name)
            ownership_queries: list[str] = []
            for query in expanded_queries:
                if len(ownership_queries) >= MAX_OWNERSHIP_QUERIES or not _within_budget(deadline):
                    break
                ownership_queries.append(query)
                ownership_candidates = _search_with_fallbacks(
                    f"{query}{OWNERSHIP_SEARCH_SUFFIX}",
                    vendor_name,
                    country=country,
                    provider_state=search_provider_state,
                )
                for candidate in ownership_candidates:
                    url = str(candidate.get("url") or "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    merged_candidates.append(candidate)
            aliases = _extract_legacy_aliases(vendor_name, merged_candidates)
            if aliases:
                for query in _expanded_search_queries(vendor_name, aliases):
                    if query in ownership_queries or len(ownership_queries) >= MAX_OWNERSHIP_QUERIES or not _within_budget(deadline):
                        continue
                    ownership_queries.append(query)
                    ownership_candidates = _search_with_fallbacks(
                        f"{query}{OWNERSHIP_SEARCH_SUFFIX}",
                        vendor_name,
                        country=country,
                        provider_state=search_provider_state,
                    )
                    for candidate in ownership_candidates:
                        url = str(candidate.get("url") or "")
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        merged_candidates.append(candidate)
            vendor_variants = _expanded_search_queries(vendor_name, aliases)
            if not merged_relationships:
                snippet_relationships, snippet_findings, snippet_risk_signals, snippet_refs = _collect_snippet_relationships(
                    vendor_name,
                    country,
                    website,
                    merged_candidates,
                    deadline=deadline,
                    provider_state=search_provider_state,
                    vendor_variants=vendor_variants,
                )
                merged_relationships.extend(snippet_relationships)
                merged_findings.extend(snippet_findings)
                merged_risk_signals.extend(snippet_risk_signals)
                artifact_refs.extend(snippet_refs)
            if not merged_relationships and _within_budget(deadline):
                for candidate in _synthetic_finance_profile_candidates(vendor_name, aliases):
                    if not _within_budget(deadline):
                        break
                    relationships, findings, risk_signals, refs, identifiers = _extract_external_relationships(
                        vendor_name,
                        country,
                        website,
                        candidate,
                        vendor_variants=vendor_variants,
                    )
                    merged_relationships.extend(relationships)
                    merged_findings.extend(findings)
                    merged_risk_signals.extend(risk_signals)
                    artifact_refs.extend(refs)
                    if relationships:
                        break

            if not merged_relationships:
                finance_queries: list[str] = []
                for query in [*vendor_variants, *_legacy_corporate_query_variants(vendor_name)]:
                    if query not in finance_queries:
                        finance_queries.append(query)
                finance_query_count = 0
                for query in finance_queries:
                    if finance_query_count >= MAX_FINANCE_QUERIES or not _within_budget(deadline):
                        break
                    finance_query_count += 1
                    finance_candidates = _search_with_fallbacks(
                        f"{query}{FINANCING_SEARCH_SUFFIX}",
                        vendor_name,
                        allow_blocked=True,
                        country=country,
                        provider_state=search_provider_state,
                    )
                    for candidate in finance_candidates:
                        url = str(candidate.get("url") or "")
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        merged_candidates.append(candidate)
            if not merged_relationships:
                for candidate in _external_candidate_pages(merged_candidates, website):
                    relationships, findings, risk_signals, refs, identifiers = _extract_external_relationships(
                        vendor_name,
                        country,
                        website,
                        candidate,
                        vendor_variants=vendor_variants,
                    )
                    merged_relationships.extend(relationships)
                    merged_findings.extend(findings)
                    merged_risk_signals.extend(risk_signals)
                    artifact_refs.extend(refs)
            if not merged_relationships and _within_budget(deadline):
                for candidate in _synthetic_finance_profile_candidates(vendor_name, aliases):
                    if not _within_budget(deadline):
                        break
                    relationships, findings, risk_signals, refs, identifiers = _extract_external_relationships(
                        vendor_name,
                        country,
                        website,
                        candidate,
                        vendor_variants=vendor_variants,
                    )
                    merged_relationships.extend(relationships)
                    merged_findings.extend(findings)
                    merged_risk_signals.extend(risk_signals)
                    artifact_refs.extend(refs)
                    if relationships:
                        break

        identifier_keys = ("cage", "uei", "duns", "ncage")
        missing_identifier_keys = [key for key in identifier_keys if not result.identifiers.get(key)]
        if missing_identifier_keys and _within_budget(deadline, reserve_seconds=IDENTIFIER_PHASE_MIN_REMAINING_SECONDS):
            identifier_candidates: list[dict] = list(candidates)
            seen_urls = {str(candidate.get("url") or "") for candidate in identifier_candidates}
            identifier_query_count = 0
            for query in _identifier_search_queries(vendor_name, missing_identifier_keys):
                if identifier_query_count >= MAX_IDENTIFIER_QUERIES or not _within_budget(deadline):
                    break
                identifier_query_count += 1
                variant_candidates = _search_with_fallbacks(
                    query,
                    vendor_name,
                    allow_blocked=True,
                    country=country,
                    provider_state=search_provider_state,
                )
                for candidate in variant_candidates:
                    url = str(candidate.get("url") or "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    candidate = dict(candidate)
                    candidate["identifier_query"] = True
                    identifier_candidates.append(candidate)
            for candidate in _identifier_signal_candidates(identifier_candidates, website, vendor_name):
                identifiers, findings, refs = _extract_snippet_identifiers(
                    website,
                    candidate,
                    vendor_name=vendor_name,
                )
                _merge_identifier_values(
                    result.identifiers,
                    identifiers,
                    identifier_ranks=identifier_ranks,
                    incoming_rank=1,
                    incoming_ranks=_identifier_ranks_from_findings(findings),
                )
                merged_findings.extend(findings)
                artifact_refs.extend(refs)
                if any(not result.identifiers.get(key) for key in missing_identifier_keys):
                    identifiers, findings, refs = _extract_external_identifiers(
                        website,
                        candidate,
                        vendor_name=vendor_name,
                    )
                    _merge_identifier_values(
                        result.identifiers,
                        identifiers,
                        identifier_ranks=identifier_ranks,
                        incoming_rank=2,
                        incoming_ranks=_identifier_ranks_from_findings(
                            findings,
                            access_bonus=EXTERNAL_IDENTIFIER_ACCESS_BONUS,
                        ),
                    )
                    merged_findings.extend(findings)
                    artifact_refs.extend(refs)
                if all(result.identifiers.get(key) for key in identifier_keys):
                    break

        result.relationships = _merge_unique_relationships(merged_relationships)
        result.findings = merged_findings
        result.risk_signals = merged_risk_signals
        result.artifact_refs = artifact_refs
        if not _within_budget(deadline):
            result.structured_fields["budget_exhausted"] = True
    except Exception as exc:
        result.error = str(exc)

    result.elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
    return result
