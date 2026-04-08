"""First-party public RSS / Atom collector.

Local-first rules:
  - Prefer analyst-seeded feed URLs or fixture files.
  - If a website is available, only inspect the homepage and a short list of
    standard feed endpoints.
  - Do not crawl, bypass, or escalate beyond public feed discovery.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

from . import EnrichmentResult, Finding


SOURCE_NAME = "rss_public"
TIMEOUT = 8
MAX_FEEDS = 4
MAX_ITEMS = 8
USER_AGENT = "Helios/5.2.1"
REPO_ROOT = Path(__file__).resolve().parents[2]

FEED_KEYS = (
    "rss_feed_url",
    "rss_feed_urls",
    "rss_public_feed_url",
    "rss_public_feed_urls",
)
FIXTURE_KEYS = (
    "rss_public_fixture",
    "rss_public_fixture_path",
    "rss_public_fixture_feed",
    "rss_public_fixture_feeds",
)
WEBSITE_KEYS = ("website", "official_website", "sam_website", "domain")
DISCOVERY_SUFFIXES = (
    "/feed",
    "/feed.xml",
    "/rss",
    "/rss.xml",
    "/news/feed",
    "/news/feed.xml",
    "/blog/feed",
    "/press/feed",
)

CONTRACT_KEYWORDS = (
    "award",
    "task order",
    "contract",
    "subcontract",
    "prime",
    "idiq",
    "bpa",
    "contract vehicle",
    "oasis",
    "seaport",
    "fedsim",
    "navy",
    "army",
    "air force",
    "dod",
    "mda",
)
OWNERSHIP_KEYWORDS = (
    "acquire",
    "acquisition",
    "merger",
    "invest",
    "investment",
    "backed by",
    "backing",
    "stake",
    "private equity",
)
ASSURANCE_KEYWORDS = (
    "cmmc",
    "fedramp",
    "iso 27001",
    "soc 2",
    "nist 800-171",
    "cyber certification",
    "compliance certification",
    "attestation",
)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _coerce_values(ids: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = ids.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, (list, tuple, set)):
            values.extend(str(item or "") for item in raw)
    return [str(value or "").strip() for value in values if str(value or "").strip()]


def _normalize_homepage(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith("file://"):
        return text
    if "://" not in text:
        if "/" not in text and "." in text:
            text = f"https://{text}"
        elif Path(text).exists():
            return Path(text).resolve().as_uri()
    parsed = urlparse(text)
    if parsed.scheme == "file":
        return text
    if parsed.scheme and parsed.netloc:
        return text.rstrip("/")
    return ""


def _normalize_feed_url(raw: str, *, base_url: str = "") -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith("file://"):
        return text
    path = Path(text).expanduser()
    if path.exists():
        return path.resolve().as_uri()
    if base_url:
        text = urljoin(base_url.rstrip("/") + "/", text)
    elif "://" not in text and "." in text:
        text = f"https://{text}"
    parsed = urlparse(text)
    if parsed.scheme == "file":
        return text
    if parsed.scheme and parsed.netloc:
        return text
    return ""


def _fetch_content(url: str) -> tuple[bytes, str, str]:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path or "")).resolve()
        content_type = "application/xml" if path.suffix.lower() in {".xml", ".rss", ".atom"} else "text/plain"
        return path.read_bytes(), content_type, path.as_uri()
    response = requests.get(
        url,
        timeout=TIMEOUT,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html",
        },
    )
    response.raise_for_status()
    return response.content, response.headers.get("Content-Type", ""), str(getattr(response, "url", "") or url)


def _discover_feed_links(markup: bytes, base_url: str) -> list[str]:
    soup = BeautifulSoup(markup, "html.parser")
    candidates: list[str] = []
    for link in soup.find_all("link", href=True):
        rel_values = {str(value).lower() for value in (link.get("rel") or [])}
        content_type = str(link.get("type") or "").lower()
        if "alternate" not in rel_values:
            continue
        if "rss" not in content_type and "atom" not in content_type and "xml" not in content_type:
            continue
        normalized = _normalize_feed_url(str(link.get("href") or ""), base_url=base_url)
        if normalized:
            candidates.append(normalized)
    return candidates


def _normalize_timestamp(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, IndexError):
        pass
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return text


def _text_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, ET.Element):
        text = "".join(value.itertext())
    else:
        text = str(value)
    if "<" in text or "&" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    return " ".join(text.split())


def _child_text(node: ET.Element, *names: str) -> str:
    for child in list(node):
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag in names:
            return _text_content(child)
    return ""


def _parse_feed(payload: bytes) -> dict[str, Any]:
    root = ET.fromstring(payload)
    root_tag = root.tag.rsplit("}", 1)[-1].lower()
    if root_tag == "rss":
        channel = root.find("channel")
        if channel is None:
            return {}
        feed_title = _child_text(channel, "title")
        items: list[dict[str, str]] = []
        for item in channel.findall("item"):
            items.append(
                {
                    "title": _child_text(item, "title"),
                    "link": _child_text(item, "link"),
                    "summary": _child_text(item, "description", "encoded"),
                    "published_at": _normalize_timestamp(_child_text(item, "pubdate", "date")),
                }
            )
        return {"feed_title": feed_title, "items": items}

    if root_tag == "feed":
        feed_title = _child_text(root, "title")
        items = []
        for entry in root.findall("{*}entry"):
            link = ""
            for child in list(entry):
                tag = child.tag.rsplit("}", 1)[-1].lower()
                if tag == "link":
                    href = str(child.attrib.get("href") or "").strip()
                    if href:
                        link = href
                        break
            items.append(
                {
                    "title": _child_text(entry, "title"),
                    "link": link,
                    "summary": _child_text(entry, "summary", "content"),
                    "published_at": _normalize_timestamp(_child_text(entry, "updated", "published")),
                }
            )
        return {"feed_title": feed_title, "items": items}
    return {}


def _classify_item(title: str, summary: str) -> tuple[str, str, str, float, str]:
    haystack = f"{title} {summary}".lower()
    if any(keyword in haystack for keyword in CONTRACT_KEYWORDS):
        return ("contracts", "First-party contract activity", "medium", 0.67, "first_party_contract_activity")
    if any(keyword in haystack for keyword in OWNERSHIP_KEYWORDS):
        return ("ownership", "First-party ownership or financing signal", "medium", 0.61, "first_party_control_activity")
    if any(keyword in haystack for keyword in ASSURANCE_KEYWORDS):
        return ("assurance", "First-party assurance signal", "low", 0.58, "first_party_assurance_activity")
    return ("activity", "First-party activity", "info", 0.45, "first_party_activity")


def _resolve_candidate_feeds(ids: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def add(value: str, *, base_url: str = "") -> None:
        normalized = _normalize_feed_url(value, base_url=base_url)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered.append(normalized)

    for value in _coerce_values(ids, FIXTURE_KEYS):
        add(value)
    for value in _coerce_values(ids, FEED_KEYS):
        add(value)

    if ordered or _truthy(ids.get("rss_public_fixture_only")):
        return ordered[:MAX_FEEDS]

    homepage = ""
    for key in WEBSITE_KEYS:
        homepage = _normalize_homepage(str(ids.get(key) or ""))
        if homepage:
            break
    if not homepage:
        return ordered[:MAX_FEEDS]

    try:
        markup, content_type, resolved_url = _fetch_content(homepage)
        if "html" in content_type.lower() or str(markup[:64]).lstrip().startswith("b'<") or markup.lstrip()[:1] == b"<":
            for candidate in _discover_feed_links(markup, resolved_url):
                add(candidate)
    except Exception:
        resolved_url = homepage

    if ordered:
        return ordered[:MAX_FEEDS]

    for suffix in DISCOVERY_SUFFIXES:
        add(suffix, base_url=resolved_url)
    return ordered[:MAX_FEEDS]


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    result = EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        source_class="public_connector",
        authority_level="first_party_self_disclosed",
        access_model="rss_public",
    )

    feeds = _resolve_candidate_feeds(ids)
    if not feeds:
        return result

    items: list[dict[str, str]] = []
    feed_title = ""
    resolved_feed_url = ""
    seen_items: set[tuple[str, str]] = set()

    for feed_url in feeds:
        try:
            payload, _content_type, resolved_url = _fetch_content(feed_url)
            parsed = _parse_feed(payload)
        except Exception:
            continue
        if not parsed:
            continue
        if not feed_title:
            feed_title = str(parsed.get("feed_title") or "").strip()
        if not resolved_feed_url:
            resolved_feed_url = resolved_url or feed_url
        for item in parsed.get("items") or []:
            title = str(item.get("title") or "").strip()
            link = str(item.get("link") or "").strip()
            summary = str(item.get("summary") or "").strip()
            key = (title, link)
            if not title or key in seen_items:
                continue
            seen_items.add(key)
            items.append(
                {
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "published_at": str(item.get("published_at") or "").strip(),
                }
            )

    if not items:
        return result

    def sort_key(item: dict[str, str]) -> tuple[int, str, str]:
        published = item.get("published_at") or ""
        return (0 if published else 1, published or "", item.get("title") or "")

    items.sort(key=sort_key, reverse=True)
    latest_item = items[0]

    result.identifiers["rss_public_latest_item_at"] = latest_item.get("published_at") or ""
    if feed_title:
        result.identifiers["rss_public_feed_title"] = feed_title
    if resolved_feed_url:
        result.identifiers["rss_public_feed_url"] = resolved_feed_url
    result.structured_fields = {
        "items": items[:MAX_ITEMS],
        "feed_title": feed_title,
        "feed_url": resolved_feed_url,
    }

    for item in items[:MAX_ITEMS]:
        category, label, severity, confidence, signal = _classify_item(item.get("title", ""), item.get("summary", ""))
        if signal == "first_party_activity":
            continue
        detail_bits = [
            item.get("summary", ""),
            f"Published {item.get('published_at')}" if item.get("published_at") else "",
            f"Feed: {feed_title}" if feed_title else "",
        ]
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category=category,
                title=f"{label}: {item.get('title', '')}",
                detail=" ".join(bit for bit in detail_bits if bit).strip(),
                severity=severity,
                confidence=confidence,
                url=item.get("link", ""),
                raw_data={"feed_title": feed_title, "feed_url": resolved_feed_url, **item},
                timestamp=item.get("published_at", ""),
                source_class="public_connector",
                authority_level="first_party_self_disclosed",
                access_model="rss_public",
                artifact_ref=item.get("link", "") or resolved_feed_url,
                structured_fields={
                    "signal": signal,
                    "feed_title": feed_title,
                    "feed_url": resolved_feed_url,
                    "published_at": item.get("published_at", ""),
                },
            )
        )
        result.risk_signals.append(
            {
                "signal": signal,
                "severity": severity,
                "confidence": confidence,
                "source": SOURCE_NAME,
                "evidence": item.get("title", ""),
                "published_at": item.get("published_at", ""),
                "url": item.get("link", ""),
                "authority_level": "first_party_self_disclosed",
                "access_model": "rss_public",
            }
        )

    return result
