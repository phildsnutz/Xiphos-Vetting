"""Seeded Wayback/CDX contract-vehicle lineage connector."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from requests import exceptions as requests_exceptions

from http_trust import resolve_verify_target

from . import EnrichmentResult
from .public_html_contract_vehicle import enrich_pages


SOURCE_NAME = "contract_vehicle_wayback"
REPO_ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 12
MAX_CAPTURES_PER_URL = 3
CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
SEED_URL_KEYS = (
    "contract_vehicle_archive_url",
    "contract_vehicle_archive_urls",
    "contract_vehicle_archive_seed_url",
    "contract_vehicle_archive_seed_urls",
)
FIXTURE_KEYS = (
    "contract_vehicle_wayback_fixture",
    "contract_vehicle_wayback_fixture_path",
)


def _verify_ssl() -> bool | str:
    return resolve_verify_target(
        verify_env="XIPHOS_WAYBACK_VERIFY_SSL",
        bundle_envs=("XIPHOS_WAYBACK_CA_BUNDLE",),
    )


def _resolve_seed_urls(ids: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in SEED_URL_KEYS:
        raw = ids.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, (list, tuple, set)):
            values.extend(str(item or "") for item in raw)
    seen: set[str] = set()
    urls: list[str] = []
    for raw in values:
        candidate = str(raw or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def _resolve_fixture_payload(ids: dict[str, Any]) -> dict[str, Any]:
    for key in FIXTURE_KEYS:
        raw = ids.get(key)
        if not raw:
            continue
        path = Path(str(raw))
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _capture_url(timestamp: str, original: str) -> str:
    return f"https://web.archive.org/web/{timestamp}id_/{quote(original, safe=':/?&=%#')}"


def _fixture_captures(seed_urls: list[str], payload: dict[str, Any]) -> list[dict[str, Any]]:
    captures_by_seed = payload.get("captures_by_seed")
    if not isinstance(captures_by_seed, dict):
        return []
    captures: list[dict[str, Any]] = []
    for seed in seed_urls:
        for item in captures_by_seed.get(seed, []) or []:
            if not isinstance(item, dict):
                continue
            capture_url = str(item.get("capture_url") or "").strip()
            capture_path = str(item.get("capture_path") or "").strip()
            if not capture_url and capture_path:
                path = Path(capture_path)
                if not path.is_absolute():
                    path = (REPO_ROOT / path).resolve()
                if path.exists():
                    capture_url = path.as_uri()
            captures.append(
                {
                    "seed_url": seed,
                    "timestamp": str(item.get("timestamp") or ""),
                    "original": str(item.get("original") or seed),
                    "capture_url": capture_url,
                    "statuscode": str(item.get("statuscode") or ""),
                    "mimetype": str(item.get("mimetype") or ""),
                }
            )
    return captures


def _fetch_cdx(seed_url: str) -> list[dict[str, str]]:
    response = requests.get(
        CDX_ENDPOINT,
        params={
            "url": seed_url,
            "output": "json",
            "fl": "timestamp,original,statuscode,mimetype",
            "filter": ["statuscode:200", "mimetype:text/html"],
            "collapse": "digest",
            "limit": str(MAX_CAPTURES_PER_URL),
            "from": "2019",
        },
        timeout=TIMEOUT,
        headers={"User-Agent": "Helios/5.2 (+https://xiphosllc.com)"},
        verify=_verify_ssl(),
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or len(rows) <= 1:
        return []
    captures: list[dict[str, str]] = []
    for row in rows[1:]:
        if not isinstance(row, list) or len(row) < 4:
            continue
        captures.append(
            {
                "timestamp": str(row[0] or ""),
                "original": str(row[1] or seed_url),
                "statuscode": str(row[2] or ""),
                "mimetype": str(row[3] or ""),
            }
        )
    return captures


def enrich(vendor_name: str, **ids) -> EnrichmentResult:
    started = time.perf_counter()
    seed_urls = _resolve_seed_urls(ids)
    result = EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        source_class="public_connector",
        authority_level="third_party_public",
        access_model="public_archive",
    )
    if not seed_urls:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    fixture_payload = _resolve_fixture_payload(ids)
    captures = _fixture_captures(seed_urls, fixture_payload)
    errors: list[str] = []
    used_fixture = bool(captures)
    if not captures:
        for seed_url in seed_urls:
            try:
                for capture in _fetch_cdx(seed_url):
                    captures.append({"seed_url": seed_url, **capture})
            except requests_exceptions.SSLError as exc:
                errors.append(
                    f"{seed_url}: {exc}. Set XIPHOS_WAYBACK_CA_BUNDLE, REQUESTS_CA_BUNDLE, or SSL_CERT_FILE if your network uses a custom trust chain."
                )
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"{seed_url}: {exc}")

    page_urls: list[str] = []
    for capture in captures:
        capture_url = str(capture.get("capture_url") or "").strip()
        if not capture_url:
            timestamp = str(capture.get("timestamp") or "").strip()
            original = str(capture.get("original") or "").strip()
            if not timestamp or not original:
                continue
            capture_url = _capture_url(timestamp, original)
        if capture_url and capture_url not in page_urls:
            page_urls.append(capture_url)

    derived = enrich_pages(
        vendor_name,
        page_urls,
        source_name=SOURCE_NAME,
        source_class="public_connector",
        default_authority_level="third_party_public",
        default_access_model="public_archive",
    )
    derived.structured_fields["seed_urls"] = seed_urls
    derived.structured_fields["captures_resolved"] = len(page_urls)
    derived.structured_fields["used_fixture"] = used_fixture
    if errors and not derived.error:
        derived.structured_fields["partial_errors"] = errors[:4]
    elif errors and derived.error:
        derived.error = derived.error[:400]
    derived.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return derived
