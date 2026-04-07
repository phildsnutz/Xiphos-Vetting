"""Seeded public contract-opportunity notice capture.

This connector is intentionally narrow:
  - it only reads analyst-seeded or catalog-seeded public notice pages
  - it does not search, crawl, or bypass access controls
  - it reuses the deterministic contract-vehicle HTML parser so live notices
    and replayable fixtures land in the same provider-neutral shape
"""

from __future__ import annotations

from typing import Any

from . import EnrichmentResult
from .public_html_contract_vehicle import _normalize_page, enrich_pages


SOURCE_NAME = "contract_opportunities_public"
PAGE_KEYS = (
    "contract_opportunity_notice_url",
    "contract_opportunity_notice_urls",
    "contract_opportunity_notice_page",
    "contract_opportunity_notice_pages",
    "contract_opportunity_notice_fixture_page",
    "contract_opportunity_notice_fixture_pages",
)


def _resolve_pages(ids: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in PAGE_KEYS:
        raw = ids.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, (list, tuple, set)):
            values.extend(str(item or "") for item in raw)

    ordered: list[str] = []
    seen: set[str] = set()
    for raw in values:
        candidate = _normalize_page(str(raw or "").strip())
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return ordered[:8]


def enrich(vendor_name: str, **ids) -> EnrichmentResult:
    pages = _resolve_pages(ids)
    if not pages:
        return EnrichmentResult(
            source=SOURCE_NAME,
            vendor_name=vendor_name,
            source_class="public_connector",
            authority_level="official_program_system",
            access_model="public_html",
        )

    return enrich_pages(
        vendor_name,
        pages,
        source_name=SOURCE_NAME,
        source_class="public_connector",
        default_authority_level="official_program_system",
        default_access_model="public_html",
    )
