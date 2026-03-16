"""
Xiphos OSINT Connector Framework  (v2.5 -- 17 connectors)

Modular connectors for ingesting, normalizing, and enriching vendor data
from publicly available intelligence sources. Each connector follows the
same interface: query by vendor name/identifiers, return structured findings.

Connector categories aligned to the Xiphos scoring rubric:

  SANCTIONS & RESTRICTED PARTIES (25% weight)
    - sanctions_sync.py     (OFAC, UK, EU, UN, OpenSanctions) -- batch sync
    - trade_csl.py          (Commerce Dept Consolidated Screening List, 13 lists)
    - un_sanctions.py       (UN Security Council consolidated list, direct XML)
    - opensanctions_pep.py  (PEP screening via OpenSanctions)

  INTERNATIONAL DEBARMENT & OFFSHORE EXPOSURE
    - worldbank_debarred.py (World Bank/IDB/ADB/AfDB/EBRD debarments)
    - icij_offshore.py      (Panama/Paradise/Pandora Papers)

  CORPORATE IDENTITY & OWNERSHIP (25% weight)
    - sec_edgar.py          (SEC filings, ownership, subsidiaries)
    - gleif_lei.py          (Legal Entity Identifiers, parent chains)
    - opencorporates.py     (Global corporate registry, officers)
    - uk_companies_house.py (UK PSC/beneficial ownership register)

  GOVERNMENT CONTRACTS & EXCLUSIONS (15% weight)
    - sam_gov.py            (SAM.gov entity registration, exclusions)
    - usaspending.py        (Federal contract awards, spending history)

  REGULATORY COMPLIANCE
    - epa_echo.py           (EPA environmental violations, penalties)
    - osha_safety.py        (OSHA workplace safety violations)

  FOREIGN INFLUENCE & AGENT REGISTRATION
    - fara.py               (DOJ FARA foreign agent registrations)

  ADVERSE MEDIA & LITIGATION
    - gdelt_media.py        (Adverse media via GDELT Project)
    - courtlistener.py      (Federal/state court dockets)

  FINANCIAL REGULATION
    - fdic_bankfind.py      (FDIC bank regulatory data)

Each connector exports:
    enrich(vendor_name, country=None, **ids) -> EnrichmentResult
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class Finding:
    """A single piece of intelligence from an OSINT source."""
    source: str                 # e.g. "sec_edgar", "sam_gov"
    category: str               # e.g. "ownership", "exclusion", "contract"
    title: str                  # human-readable headline
    detail: str                 # full finding text
    severity: str = "info"      # info, low, medium, high, critical
    confidence: float = 0.0     # 0.0 to 1.0
    url: str = ""               # provenance link
    raw_data: dict = field(default_factory=dict)
    timestamp: str = ""         # when this data was fetched


@dataclass
class EnrichmentResult:
    """Aggregated results from a single OSINT connector."""
    source: str
    vendor_name: str
    findings: list[Finding] = field(default_factory=list)
    identifiers: dict = field(default_factory=dict)   # discovered IDs (CIK, UEI, LEI, etc.)
    relationships: list[dict] = field(default_factory=list)  # ownership, subsidiary, etc.
    risk_signals: list[dict] = field(default_factory=list)   # structured risk indicators
    elapsed_ms: int = 0
    error: str = ""

    @property
    def has_data(self) -> bool:
        return len(self.findings) > 0 or len(self.identifiers) > 0
