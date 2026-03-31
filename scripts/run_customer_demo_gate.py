#!/usr/bin/env python3
"""
Run a pre-demo acceptance gate against a named company or existing case.

This script is designed for the exact failure mode that keeps hurting live
company runs:
  - a case opens, but enrichment is weak or slow
  - the supplier passport looks thin or obviously wrong
  - the website is a junk ATS / directory host
  - the AI brief is not ready when the dossier is opened
  - the dossier technically renders but contains embarrassing anomalies

It intentionally returns a blunt result:
  - GO: safe to show
  - CAUTION: usable, but needs analyst caveats
  - NO_GO: do not put in front of a customer yet
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests

try:
    from pypdf import PdfReader  # type: ignore
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"pypdf is required for customer demo gating: {exc}")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_REPORT_DIR = ROOT / "docs" / "reports" / "customer_demo_gate"

HTML_SECTION_CHECKS = {
    "hero": "Defense counterparty trust dossier",
    "executive_strip": "Recent change",
    "risk_storyline": "Risk Storyline",
    "supplier_passport": "Supplier passport",
    "ai_brief": "AI Narrative Brief",
    "executive_judgment": "Executive judgment",
}

PDF_SECTION_CHECKS = {
    "hero": "DEFENSE COUNTERPARTY TRUST DOSSIER",
    "executive_strip": "RECENT CHANGE",
    "risk_storyline": "RISK STORYLINE",
    "supplier_passport": "SUPPLIER PASSPORT",
    "ai_brief": "AI NARRATIVE BRIEF",
}

BANNED_DOSSIER_PHRASES = (
    "0 years of verifiable records",
    "No verifiable operating history was found.",
    "Supplier passport build failed",
    "AI narrative unavailable",
)

SUSPICIOUS_WEBSITE_HOST_PATTERNS = (
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
    "linkedin.com",
    "cbinsights.com",
    "pitchbook.com",
    "crunchbase.com",
    "govtribe.com",
    "industry.ausa.org",
    "wikipedia.org",
    "wikidata.org",
)

SUSPICIOUS_WEBSITE_PATH_HINTS = (
    "/jobs",
    "/job",
    "/careers",
    "/career",
    "/positions",
    "/openings",
    "/apply",
)

KEY_IDENTIFIERS = (
    "cage",
    "uei",
    "duns",
    "lei",
    "cik",
    "uen",
    "abn",
    "acn",
    "uk_company_number",
    "ca_corporation_number",
    "business_number",
    "nzbn",
    "nz_company_number",
    "norway_org_number",
    "kvk_number",
    "fr_siren",
    "website",
)
OFFICIAL_CORROBORATION_RANK = {
    "missing": 0,
    "public_only": 1,
    "partial": 2,
    "strong": 3,
}
OFFICIAL_CONNECTOR_COUNTRY_HINTS = {
    "sam_gov": {"US", "USA"},
    "uk_companies_house": {"UK", "GB", "GBR", "UNITED KINGDOM", "ENGLAND", "SCOTLAND", "WALES", "NORTHERN IRELAND"},
    "corporations_canada": {"CA", "CAN", "CANADA"},
    "australia_abn_asic": {"AU", "AUS", "AUSTRALIA"},
    "singapore_acra": {"SG", "SGP", "SINGAPORE"},
    "new_zealand_companies_office": {"NZ", "NZL", "NEW ZEALAND"},
    "norway_brreg": {"NO", "NOR", "NORWAY"},
    "netherlands_kvk": {"NL", "NLD", "NETHERLANDS"},
    "france_inpi_rne": {"FR", "FRA", "FRANCE"},
}
OFFICIAL_CONNECTOR_DOMAIN_HINTS = {
    "uk_companies_house": (".uk", ".co.uk", ".org.uk", ".gov.uk"),
    "corporations_canada": (".ca",),
    "australia_abn_asic": (".au",),
    "singapore_acra": (".sg",),
    "new_zealand_companies_office": (".nz",),
    "norway_brreg": (".no",),
    "netherlands_kvk": (".nl",),
    "france_inpi_rne": (".fr",),
}
OFFICIAL_CONNECTOR_IDENTIFIER_HINTS = {
    "sam_gov": ("cage", "uei", "ncage", "duns", "federal_contractor", "has_sam_subcontract_reports"),
    "gleif_lei": ("lei",),
    "sec_edgar": ("cik",),
    "uk_companies_house": ("uk_company_number",),
    "corporations_canada": ("ca_corporation_number", "business_number"),
    "australia_abn_asic": ("abn", "acn"),
    "singapore_acra": ("uen",),
    "new_zealand_companies_office": ("nzbn", "nz_company_number"),
    "norway_brreg": ("norway_org_number",),
    "netherlands_kvk": ("kvk_number",),
    "france_inpi_rne": ("fr_siren",),
}

STABILIZATION_PASSES: tuple[tuple[str, list[str] | None], ...] = (
    (
        "identity_refresh",
        [
            "sam_gov",
            "gleif_lei",
            "sec_edgar",
            "corporations_canada",
            "australia_abn_asic",
            "singapore_acra",
            "new_zealand_companies_office",
            "norway_brreg",
            "netherlands_kvk",
            "france_inpi_rne",
            "opencorporates",
            "uk_companies_house",
            "wikidata_company",
            "public_search_ownership",
            "public_html_ownership",
        ],
    ),
    (
        "ownership_refresh",
        [
            "google_news",
            "gleif_lei",
            "corporations_canada",
            "australia_abn_asic",
            "singapore_acra",
            "new_zealand_companies_office",
            "norway_brreg",
            "netherlands_kvk",
            "france_inpi_rne",
            "opencorporates",
            "uk_companies_house",
            "public_search_ownership",
            "public_html_ownership",
            "wikidata_company",
        ],
    ),
    ("full_reconcile", None),
)

READINESS_PRIMARY_CONNECTORS: tuple[str, ...] = (
    "sam_gov",
    "gleif_lei",
    "sec_edgar",
    "corporations_canada",
    "australia_abn_asic",
    "singapore_acra",
    "new_zealand_companies_office",
    "norway_brreg",
    "netherlands_kvk",
    "france_inpi_rne",
    "opencorporates",
    "uk_companies_house",
    "wikidata_company",
    "google_news",
    "public_search_ownership",
    "public_html_ownership",
)

NAME_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
REPO_RELATIVE_FIXTURE_KEYS = {"public_html_fixture_page", "public_html_fixture_pages"}


@dataclass
class DemoGateResult:
    verdict: str
    company_name: str
    case_id: str
    failures: list[str]
    warnings: list[str]
    timings_ms: dict[str, int]
    identifiers: dict[str, Any]
    identifier_status: dict[str, Any]
    graph: dict[str, Any]
    ai_status: dict[str, Any]
    assistant_ok: bool
    artifacts: dict[str, str]
    stabilization_steps: list[dict[str, Any]] = field(default_factory=list)


class DemoGateClient:
    def __init__(self, base_url: str, *, email: str = "", password: str = "", token: str = "", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.timeout = timeout
        self._email = email
        self._password = password
        self._token = token
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def close(self) -> None:
        self.session.close()

    def wait_until_ready(self, wait_seconds: int, poll_seconds: float = 2.0) -> None:
        deadline = time.monotonic() + max(wait_seconds, 0)
        last_error: Exception | None = None
        while True:
            try:
                response = self.session.get(f"{self.base_url}/api/health", timeout=min(self.timeout, 20))
                response.raise_for_status()
                return
            except Exception as exc:
                last_error = exc
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"service not ready: {last_error}") from exc
                time.sleep(poll_seconds)

    def _login(self) -> None:
        if self._token:
            self.session.headers["Authorization"] = f"Bearer {self._token}"
            return
        if not (self._email and self._password):
            raise RuntimeError("email/password or token are required")
        response = self.session.post(
            f"{self.base_url}/api/auth/login",
            json={"email": self._email, "password": self._password},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("token")
        if not token:
            raise RuntimeError("login succeeded without token")
        self.session.headers["Authorization"] = f"Bearer {token}"

    def _request(self, method: str, path: str, **kwargs):
        response = self.session.request(method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs)
        if response.status_code == 401 and (self._token or (self._email and self._password)):
            self._login()
            response = self.session.request(method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response

    def request_json(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        response = self._request(method, path, **kwargs)
        return response.json() if response.content else {}

    def request_text(self, method: str, path: str, **kwargs) -> str:
        response = self._request(method, path, **kwargs)
        return response.text

    def request_bytes(self, method: str, path: str, **kwargs) -> bytes:
        response = self._request(method, path, **kwargs)
        return response.content


def _normalized_name_tokens(value: str) -> list[str]:
    return [token.lower() for token in NAME_TOKEN_RE.findall(str(value or ""))]


def _control_target_matches(expected_control_target: str, path: dict[str, Any]) -> bool:
    expected = str(expected_control_target or "").strip()
    if not expected:
        return True
    haystack = " ".join(
        str(path.get(key) or "")
        for key in ("source_name", "target_name", "rel_type")
    ).lower()
    expected_lower = expected.lower()
    if expected_lower in haystack:
        return True

    expected_tokens = _normalized_name_tokens(expected)
    if not expected_tokens:
        return False
    for key in ("source_name", "target_name"):
        actual_tokens = _normalized_name_tokens(str(path.get(key) or ""))
        if not actual_tokens:
            continue
        if all(token in actual_tokens for token in expected_tokens):
            return True
        if (
            len(expected_tokens) >= 2
            and len(actual_tokens) >= 2
            and expected_tokens[-1] == actual_tokens[-1]
            and expected_tokens[0][:1] == actual_tokens[0][:1]
        ):
            return True
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a pre-demo company acceptance gate.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--company", default="")
    parser.add_argument("--country", default="US")
    parser.add_argument("--case-id", default="")
    parser.add_argument("--program", default="dod_unclassified")
    parser.add_argument("--profile", default="defense_acquisition")
    parser.add_argument("--connector", action="append", default=[])
    parser.add_argument("--include-ai", action="store_true", default=True)
    parser.add_argument("--skip-ai", dest="include_ai", action="store_false")
    parser.add_argument("--check-assistant", action="store_true", default=True)
    parser.add_argument("--skip-assistant", dest="check_assistant", action="store_false")
    parser.add_argument("--require-dossier-html", action="store_true", default=True)
    parser.add_argument("--skip-dossier-html", dest="require_dossier_html", action="store_false")
    parser.add_argument("--require-dossier-pdf", action="store_true", default=True)
    parser.add_argument("--skip-dossier-pdf", dest="require_dossier_pdf", action="store_false")
    parser.add_argument("--max-enrich-seconds", type=int, default=90)
    parser.add_argument("--max-dossier-seconds", type=int, default=60)
    parser.add_argument("--max-pdf-seconds", type=int, default=60)
    parser.add_argument("--max-ai-seconds", type=int, default=90)
    parser.add_argument("--ai-readiness-mode", choices=("full", "surface"), default="surface")
    parser.add_argument("--max-warnings", type=int, default=2)
    parser.add_argument("--wait-for-ready-seconds", type=int, default=0)
    parser.add_argument("--auto-stabilize", action="store_true", default=True)
    parser.add_argument("--skip-auto-stabilize", dest="auto_stabilize", action="store_false")
    parser.add_argument("--expected-domain", default="")
    parser.add_argument("--expected-cage", default="")
    parser.add_argument("--expected-uei", default="")
    parser.add_argument("--expected-duns", default="")
    parser.add_argument("--expected-cik", default="")
    parser.add_argument("--expected-uen", default="")
    parser.add_argument("--expected-abn", default="")
    parser.add_argument("--expected-acn", default="")
    parser.add_argument("--expected-business-number", default="")
    parser.add_argument("--expected-ca-corporation-number", default="")
    parser.add_argument("--expected-nzbn", default="")
    parser.add_argument("--expected-nz-company-number", default="")
    parser.add_argument("--expected-norway-org-number", default="")
    parser.add_argument("--expected-kvk-number", default="")
    parser.add_argument("--expected-fr-siren", default="")
    parser.add_argument("--expected-min-control-paths", type=int, default=0)
    parser.add_argument("--expected-control-target", default="")
    parser.add_argument("--warn-on-empty-control-paths", action="store_true", default=False)
    parser.add_argument("--ignore-empty-control-path-warnings", dest="warn_on_empty_control_paths", action="store_false")
    parser.add_argument("--require-monitoring-history", action="store_true", default=False)
    parser.add_argument(
        "--minimum-official-corroboration",
        choices=("missing", "public_only", "partial", "strong"),
        default="missing",
    )
    parser.add_argument("--max-blocked-official-connectors", type=int, default=-1)
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--print-json", action="store_true")
    args = parser.parse_args()
    if not args.company and not args.case_id:
        parser.error("--company or --case-id is required")
    return args


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return text or "company"


def extract_pdf_text(pdf_bytes: bytes) -> str:
    from io import BytesIO

    reader = PdfReader(BytesIO(pdf_bytes))
    return "".join(page.extract_text() or "" for page in reader.pages)


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def website_host(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return parsed.netloc.lower()


def _clean_value(value: Any) -> str:
    if value in (None, "", "null", "None"):
        return ""
    return str(value).strip()


def _country_hints_for_passport(vendor: dict[str, Any], identifiers: dict[str, Any]) -> set[str]:
    hints: set[str] = set()

    def add(value: Any) -> None:
        text = _clean_value(value).upper()
        if not text:
            return
        hints.add(text)
        if "-" in text:
            hints.add(text.split("-", 1)[0])

    add(vendor.get("country"))
    for key in ("country", "country_code", "jurisdiction", "legal_jurisdiction"):
        add(identifiers.get(key))

    website = website_host(_clean_value(identifiers.get("website")))
    for country, suffixes in {
        "UK": (".uk", ".co.uk", ".org.uk", ".gov.uk"),
        "CA": (".ca",),
        "AU": (".au",),
        "SG": (".sg",),
        "NZ": (".nz",),
    }.items():
        if website and any(website.endswith(suffix) for suffix in suffixes):
            hints.add(country)
    return hints


def _official_connector_is_relevant(
    source: str,
    connector: dict[str, Any],
    identifiers: dict[str, Any],
    identifier_status: dict[str, dict[str, Any]],
    country_hints: set[str],
) -> bool:
    if bool(connector.get("has_data")):
        return True
    for identifier_key in OFFICIAL_CONNECTOR_IDENTIFIER_HINTS.get(source, ()):
        value = _clean_value(identifiers.get(identifier_key))
        if value:
            return True
        item = identifier_status.get(identifier_key)
        if isinstance(item, dict) and _clean_value(item.get("value")):
            return True
    if country_hints.intersection(OFFICIAL_CONNECTOR_COUNTRY_HINTS.get(source, set())):
        return True
    website = website_host(_clean_value(identifiers.get("website")))
    if website and any(website.endswith(suffix) for suffix in OFFICIAL_CONNECTOR_DOMAIN_HINTS.get(source, ())):
        return True
    return False


def relevant_blocked_official_connector_count(
    vendor: dict[str, Any],
    identifiers: dict[str, Any],
    identifier_status: dict[str, dict[str, Any]],
    official: dict[str, Any],
) -> int:
    relevant_connectors = official.get("relevant_connectors")
    if isinstance(relevant_connectors, list):
        return sum(
            1
            for connector in relevant_connectors
            if isinstance(connector, dict) and (connector.get("throttled") or connector.get("error"))
        )

    connectors = official.get("connectors")
    if not isinstance(connectors, list):
        return int(official.get("blocked_connector_count") or 0)

    country_hints = _country_hints_for_passport(vendor, identifiers)
    return sum(
        1
        for connector in connectors
        if isinstance(connector, dict)
        and _official_connector_is_relevant(
            str(connector.get("source") or ""),
            connector,
            identifiers,
            identifier_status,
            country_hints,
        )
        and (connector.get("throttled") or connector.get("error"))
    )


def is_suspicious_website(value: str) -> str | None:
    if not value:
        return "website missing"
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if not host:
        return "website host missing"
    if any(pattern in host for pattern in SUSPICIOUS_WEBSITE_HOST_PATTERNS):
        return f"suspicious website host: {host}"
    if any(token in path for token in SUSPICIOUS_WEBSITE_PATH_HINTS):
        return f"suspicious website path: {path}"
    return None


def validate_identifier_expectation(
    identifier_status: dict[str, Any],
    key: str,
    expected_value: str,
) -> list[str]:
    if not expected_value:
        return []
    item = identifier_status.get(key)
    if not isinstance(item, dict):
        return [f"expected {key.upper()} {expected_value}, but no {key} was captured"]
    actual = normalize_identifier(str(item.get("value") or ""))
    expected = normalize_identifier(expected_value)
    if actual != expected:
        return [f"expected {key.upper()} {expected_value}, got {item.get('value') or 'missing'}"]
    return []


def check_dossier_text(document: str, checks: dict[str, str], *, include_ai: bool, label: str) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    required = dict(checks)
    if not include_ai:
        required.pop("ai_brief", None)
        required.pop("executive_judgment", None)
    for name, marker in required.items():
        if marker not in document:
            failures.append(f"{label} missing {name.replace('_', ' ')}")
    for phrase in BANNED_DOSSIER_PHRASES:
        if phrase.lower() in document.lower():
            failures.append(f"{label} contains banned phrase: {phrase}")
    if "Publicly captured" in document:
        warnings.append(f"{label} includes third-party public identifier evidence")
    return failures, warnings


def _expected_identifiers_from_args(args: argparse.Namespace) -> dict[str, str]:
    expected: dict[str, str] = {}
    for key in (
        "cage",
        "uei",
        "duns",
        "cik",
        "uen",
        "abn",
        "acn",
        "business_number",
        "ca_corporation_number",
        "nzbn",
        "nz_company_number",
        "norway_org_number",
        "kvk_number",
        "fr_siren",
    ):
        value = str(getattr(args, f"expected_{key}", "") or "").strip()
        if value:
            expected[key] = value
    return expected


def analyze_passport(
    passport: dict[str, Any],
    *,
    company_name: str,
    expected_domain: str,
    expected_cage: str,
    expected_uei: str,
    expected_duns: str,
    expected_cik: str,
    expected_identifiers: dict[str, str] | None = None,
    expected_min_control_paths: int = 0,
    expected_control_target: str = "",
    warn_on_empty_control_paths: bool = False,
    require_monitoring_history: bool = False,
    minimum_official_corroboration: str = "missing",
    max_blocked_official_connectors: int = -1,
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    vendor = passport.get("vendor") if isinstance(passport.get("vendor"), dict) else {}
    identity = passport.get("identity") if isinstance(passport.get("identity"), dict) else {}
    identifier_status = identity.get("identifier_status") if isinstance(identity.get("identifier_status"), dict) else {}
    identifiers = identity.get("identifiers") if isinstance(identity.get("identifiers"), dict) else {}
    official = identity.get("official_corroboration") if isinstance(identity.get("official_corroboration"), dict) else {}
    graph = passport.get("graph") if isinstance(passport.get("graph"), dict) else {}
    monitoring = passport.get("monitoring") if isinstance(passport.get("monitoring"), dict) else {}
    ownership = passport.get("ownership") if isinstance(passport.get("ownership"), dict) else {}
    cyber = passport.get("cyber") if isinstance(passport.get("cyber"), dict) else {}
    threat_intel = passport.get("threat_intel") if isinstance(passport.get("threat_intel"), dict) else {}

    website = str(identifiers.get("website") or "")
    website_issue = is_suspicious_website(website)
    if website_issue:
        failures.append(website_issue)
    if expected_domain and website:
        host = website_host(website)
        if host != expected_domain.lower() and not host.endswith(f".{expected_domain.lower()}"):
            failures.append(f"expected website domain {expected_domain}, got {host}")

    expectations = {
        "cage": expected_cage,
        "uei": expected_uei,
        "duns": expected_duns,
        "cik": expected_cik,
    }
    expectations.update({key: value for key, value in (expected_identifiers or {}).items() if value})
    for key, expected in expectations.items():
        failures.extend(validate_identifier_expectation(identifier_status, key, expected))

    present_key_ids = [
        key for key in KEY_IDENTIFIERS
        if isinstance(identifier_status.get(key), dict) and identifier_status[key].get("value")
    ]
    if not present_key_ids:
        failures.append("no key identifiers captured")

    if int(graph.get("network_entity_count") or 0) <= 0:
        failures.append("graph network entity count is zero")
    if int(graph.get("entity_count") or 0) <= 0:
        failures.append("supplier passport control graph is empty")
    if warn_on_empty_control_paths and int(graph.get("relationship_count") or 0) <= 0:
        warnings.append("supplier passport has no control-path relationships")
    control_paths = graph.get("control_paths") if isinstance(graph.get("control_paths"), list) else []
    if expected_min_control_paths > 0 and len(control_paths) < expected_min_control_paths:
        failures.append(
            f"expected at least {expected_min_control_paths} control paths, got {len(control_paths)}"
        )
    if expected_control_target:
        matched = any(
            _control_target_matches(expected_control_target, path)
            for path in control_paths
            if isinstance(path, dict)
        )
        if not matched:
            failures.append(f"expected control path target containing {expected_control_target}")

    claim_health = graph.get("claim_health") if isinstance(graph.get("claim_health"), dict) else {}
    if int(claim_health.get("contradicted_claims") or 0) > 0:
        warnings.append(f"{int(claim_health.get('contradicted_claims') or 0)} contradicted claims in control graph")
    if int(claim_health.get("stale_paths") or 0) > 0:
        warnings.append(f"{int(claim_health.get('stale_paths') or 0)} stale control paths")

    if require_monitoring_history and int(monitoring.get("check_count") or 0) <= 0:
        warnings.append("no monitoring history yet")

    ownership_profile = ownership.get("profile") if isinstance(ownership.get("profile"), dict) else {}
    if ownership_profile.get("publicly_traded") and not identifiers.get("cik"):
        warnings.append("publicly traded flag present without CIK corroboration")
    if float(ownership_profile.get("ownership_pct_resolved") or 0.0) >= 0.7 and int(graph.get("relationship_count") or 0) == 0:
        warnings.append("ownership looks highly resolved in scoring input but graph control paths are empty")
    if official:
        coverage_level = str(official.get("coverage_level") or "").lower()
        required_coverage = str(minimum_official_corroboration or "missing").lower()
        if OFFICIAL_CORROBORATION_RANK.get(coverage_level, 0) < OFFICIAL_CORROBORATION_RANK.get(required_coverage, 0):
            failures.append(
                f"official corroboration below required threshold: need {required_coverage}, got {coverage_level or 'missing'}"
            )
        if coverage_level in {"public_only", "missing"} and present_key_ids:
            warnings.append("identity is relying on public capture without strong official corroboration")
        blocked_connector_count = relevant_blocked_official_connector_count(
            vendor,
            identifiers,
            identifier_status,
            official,
        )
        if max_blocked_official_connectors >= 0 and blocked_connector_count > max_blocked_official_connectors:
            failures.append(
                f"official connector blockage exceeded threshold: {blocked_connector_count} > {max_blocked_official_connectors}"
            )
        elif blocked_connector_count > 0:
            warnings.append(f"{blocked_connector_count} official connector checks were blocked or throttled")

    threat_pressure = str(threat_intel.get("threat_pressure") or cyber.get("threat_pressure") or "").lower()
    cisa_advisory_count = len(threat_intel.get("cisa_advisory_ids") or cyber.get("cisa_advisory_ids") or [])
    attack_technique_count = len(threat_intel.get("attack_technique_ids") or cyber.get("attack_technique_ids") or [])
    open_source_risk_level = str(cyber.get("open_source_risk_level") or "").lower()
    open_source_advisory_count = int(cyber.get("open_source_advisory_count") or 0)
    low_score_repo_count = int(cyber.get("scorecard_low_repo_count") or 0)
    if threat_pressure == "high":
        warnings.append(
            f"active threat pressure is high with {cisa_advisory_count} CISA advisories and {attack_technique_count} ATT&CK techniques in scope"
        )
    elif threat_pressure == "medium" and (cisa_advisory_count > 0 or attack_technique_count > 0):
        warnings.append(
            f"active threat pressure is present with {cisa_advisory_count} CISA advisories and {attack_technique_count} ATT&CK techniques in scope"
        )
    if open_source_risk_level == "high" and open_source_advisory_count > 0:
        warnings.append(
            f"open-source assurance pressure is high with {open_source_advisory_count} advisories and {low_score_repo_count} low-score repositories"
        )

    return failures, warnings


def gate_verdict(failures: list[str], warnings: list[str], max_warnings: int) -> str:
    if failures:
        return "NO_GO"
    if len(warnings) > max_warnings:
        return "CAUTION"
    return "GO"


def supplier_passport_mode(
    *,
    expected_min_control_paths: int,
    expected_control_target: str,
    warn_on_empty_control_paths: bool,
) -> str:
    if expected_min_control_paths > 0 or str(expected_control_target or "").strip() or warn_on_empty_control_paths:
        return "control"
    return "light"


def write_report(output_dir: Path, result: DemoGateResult) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "summary.json"
    json_path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")

    lines = [
        "# Helios Customer Demo Gate",
        "",
        f"- Verdict: **{result.verdict}**",
        f"- Company: {result.company_name}",
        f"- Case ID: `{result.case_id}`",
        "",
        "## Timings",
        "",
    ]
    for key, value in result.timings_ms.items():
        lines.append(f"- {key}: {value} ms")
    lines.extend(["", "## Failures", ""])
    if result.failures:
        lines.extend([f"- {item}" for item in result.failures])
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    if result.warnings:
        lines.extend([f"- {item}" for item in result.warnings])
    else:
        lines.append("- none")
    lines.extend(["", "## Stabilization", ""])
    if result.stabilization_steps:
        for step in result.stabilization_steps:
            connectors = step.get("connectors") or ["<full>"]
            lines.append(
                f"- {step.get('name')}: verdict={step.get('verdict')} failures={step.get('failure_count')} warnings={step.get('warning_count')} connectors={', '.join(connectors)}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Passport Snapshot",
            "",
            f"- Identifiers: {', '.join(f'{k}={v}' for k, v in result.identifiers.items() if v) or 'none'}",
            f"- Control graph entities: {result.graph.get('entity_count', 0)}",
            f"- Control graph relationships: {result.graph.get('relationship_count', 0)}",
            f"- Network entities: {result.graph.get('network_entity_count', 0)}",
            f"- Network relationships: {result.graph.get('network_relationship_count', 0)}",
            f"- Assistant path: {'PASS' if result.assistant_ok else 'SKIPPED/FAILED'}",
            "",
            "## Artifacts",
            "",
        ]
    )
    for key, value in result.artifacts.items():
        lines.append(f"- {key}: [{Path(value).name}]({value})")
    md_path = output_dir / "summary.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path


def _write_progress(output_dir: Path, stage: str, message: str, **extra: Any) -> None:
    payload = {
        "stage": stage,
        "message": message,
        "updated_at": datetime.utcnow().isoformat() + "Z",
        **extra,
    }
    (output_dir / "progress.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[{stage}] {message}", file=sys.stderr, flush=True)


def _normalize_fixture_seed_value(value: Any) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return value
    if "://" in raw:
        parsed = urlparse(raw)
        if parsed.scheme != "file":
            return raw
        candidate = Path(unquote(parsed.path)).resolve()
    else:
        candidate = Path(raw)
        if not candidate.is_absolute():
            return candidate.as_posix()
        candidate = candidate.resolve()
    try:
        return candidate.relative_to(ROOT).as_posix()
    except ValueError:
        return raw


def _normalize_seed_metadata_for_remote_case(seed_metadata: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in seed_metadata.items():
        if key not in REPO_RELATIVE_FIXTURE_KEYS:
            normalized[key] = value
            continue
        if isinstance(value, str):
            normalized[key] = _normalize_fixture_seed_value(value)
            continue
        if isinstance(value, (list, tuple, set)):
            normalized[key] = [
                _normalize_fixture_seed_value(item)
                for item in value
                if str(item or "").strip()
            ]
            continue
        normalized[key] = value
    return normalized


def run_demo_gate(args: argparse.Namespace, client: DemoGateClient | None = None) -> DemoGateResult:
    own_client = client is None
    resolved_client = client or DemoGateClient(
        args.base_url,
        email=args.email,
        password=args.password,
        token=args.token,
        timeout=max(args.max_enrich_seconds, args.max_dossier_seconds, args.max_pdf_seconds, args.max_ai_seconds, 30),
    )
    if client is None and args.wait_for_ready_seconds:
        resolved_client.wait_until_ready(args.wait_for_ready_seconds)
    if not args.token and client is None:
        resolved_client._login()

    company_name = args.company.strip() or args.case_id
    case_id = args.case_id.strip()
    if not case_id:
        seed_metadata = {
            "demo_gate_company": company_name,
            "demo_gate_created_at": datetime.utcnow().isoformat() + "Z",
        }
        extra_seed_metadata = getattr(args, "seed_metadata", {})
        if isinstance(extra_seed_metadata, dict):
            for key, value in extra_seed_metadata.items():
                if str(key).startswith("__") or value in (None, "", []):
                    continue
                seed_metadata[str(key)] = value
        seed_metadata = _normalize_seed_metadata_for_remote_case(seed_metadata)
        created = resolved_client.request_json(
            "POST",
            "/api/cases",
            json={
                "name": company_name,
                "country": args.country,
                "program": args.program,
                "profile": args.profile,
                "seed_metadata": seed_metadata,
            },
        )
        case_id = str(created["case_id"])

    output_dir = Path(args.report_dir) / f"{slugify(company_name)}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    output_dir.mkdir(parents=True, exist_ok=True)
    failure_html_path = output_dir / "dossier-html.error.txt"
    failure_pdf_path = output_dir / "dossier-pdf.error.txt"
    _write_progress(output_dir, "start", f"Starting demo gate for {company_name}", case_id=case_id or None)

    def _run_enrich(connectors: list[str] | None = None, *, full_reconcile: bool = False) -> int:
        start = time.perf_counter()
        primary_connectors = list(getattr(args, "connector", []) or READINESS_PRIMARY_CONNECTORS)
        payload: dict[str, Any] = {"force": True}
        if not full_reconcile:
            payload["connectors"] = connectors or primary_connectors
        stage_name = "full_reconcile" if full_reconcile else "enrich_and_score"
        _write_progress(
            output_dir,
            stage_name,
            "Running enrich-and-score",
            case_id=case_id,
            connectors=payload.get("connectors"),
        )
        resolved_client.request_json(
            "POST",
            f"/api/cases/{case_id}/enrich-and-score",
            json=payload,
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _write_progress(
            output_dir,
            stage_name,
            f"Completed enrich-and-score in {elapsed_ms} ms",
            case_id=case_id,
            elapsed_ms=elapsed_ms,
            connectors=payload.get("connectors"),
        )
        return elapsed_ms

    def _evaluate_case(enrich_elapsed_ms: int, stabilization_steps: list[dict[str, Any]]) -> DemoGateResult:
        timings_ms: dict[str, int] = {"enrich_and_score": enrich_elapsed_ms}
        failures: list[str] = []
        warnings: list[str] = []
        html_path = output_dir / "dossier.html"
        pdf_path = output_dir / "dossier-pdf.skipped.txt"
        require_dossier_html = bool(getattr(args, "require_dossier_html", True))
        require_dossier_pdf = bool(getattr(args, "require_dossier_pdf", True))
        if enrich_elapsed_ms > args.max_enrich_seconds * 1000:
            failures.append(f"enrich-and-score exceeded {args.max_enrich_seconds}s budget")

        ai_status: dict[str, Any] = {}
        ai_sections_required = args.include_ai
        include_ai_in_dossier = args.include_ai
        if args.include_ai:
            _write_progress(output_dir, "ai_status", "Checking AI readiness", case_id=case_id)
            start = time.perf_counter()
            ai_status = resolved_client.request_json("GET", f"/api/cases/{case_id}/analysis-status")
            if args.ai_readiness_mode == "full":
                deadline = time.time() + max(10, args.max_ai_seconds)
                while time.time() < deadline:
                    if ai_status.get("status") == "ready":
                        break
                    time.sleep(2)
                    ai_status = resolved_client.request_json("GET", f"/api/cases/{case_id}/analysis-status")
            timings_ms["ai_ready_wait"] = int((time.perf_counter() - start) * 1000)
            if args.ai_readiness_mode == "full" and ai_status.get("status") != "ready":
                failures.append(f"ai analysis not ready within {args.max_ai_seconds}s")
            if args.ai_readiness_mode == "surface" and ai_status.get("status") == "failed":
                failures.append("ai analysis status reported failed")
            if args.ai_readiness_mode == "surface" and ai_status.get("status") != "ready":
                ai_sections_required = False
                include_ai_in_dossier = False

        if require_dossier_html:
            _write_progress(output_dir, "dossier_html", "Rendering HTML dossier", case_id=case_id)
            start = time.perf_counter()
            html = resolved_client.request_text(
                "POST",
                f"/api/cases/{case_id}/dossier",
                json={"format": "html", "include_ai": include_ai_in_dossier},
            )
            timings_ms["dossier_html"] = int((time.perf_counter() - start) * 1000)
            _write_progress(
                output_dir,
                "dossier_html",
                f"Rendered HTML dossier in {timings_ms['dossier_html']} ms",
                case_id=case_id,
                elapsed_ms=timings_ms["dossier_html"],
            )
            html_path.write_text(html, encoding="utf-8")
            if timings_ms["dossier_html"] > args.max_dossier_seconds * 1000:
                failures.append(f"html dossier exceeded {args.max_dossier_seconds}s budget")
            html_failures, html_warnings = check_dossier_text(
                html,
                HTML_SECTION_CHECKS,
                include_ai=ai_sections_required,
                label="html dossier",
            )
            failures.extend(html_failures)
            warnings.extend(html_warnings)
        else:
            html_path.write_text("HTML dossier skipped by gate profile.\n", encoding="utf-8")
            _write_progress(output_dir, "dossier_html", "Skipped HTML dossier by gate profile", case_id=case_id)

        if require_dossier_pdf:
            pdf_path = output_dir / "dossier.pdf"
            _write_progress(output_dir, "dossier_pdf", "Rendering PDF dossier", case_id=case_id)
            start = time.perf_counter()
            pdf_bytes = resolved_client.request_bytes(
                "POST",
                f"/api/cases/{case_id}/dossier-pdf",
                json={"include_ai": include_ai_in_dossier},
            )
            timings_ms["dossier_pdf"] = int((time.perf_counter() - start) * 1000)
            _write_progress(
                output_dir,
                "dossier_pdf",
                f"Rendered PDF dossier in {timings_ms['dossier_pdf']} ms",
                case_id=case_id,
                elapsed_ms=timings_ms["dossier_pdf"],
            )
            pdf_path.write_bytes(pdf_bytes)
            if timings_ms["dossier_pdf"] > args.max_pdf_seconds * 1000:
                failures.append(f"pdf dossier exceeded {args.max_pdf_seconds}s budget")
            pdf_text = extract_pdf_text(pdf_bytes)
            pdf_failures, pdf_warnings = check_dossier_text(
                pdf_text.upper(),
                PDF_SECTION_CHECKS,
                include_ai=ai_sections_required,
                label="pdf dossier",
            )
            failures.extend(pdf_failures)
            warnings.extend(pdf_warnings)
        else:
            pdf_path.write_text("PDF dossier skipped by gate profile.\n", encoding="utf-8")
            _write_progress(output_dir, "dossier_pdf", "Skipped PDF dossier by gate profile", case_id=case_id)

        _write_progress(output_dir, "supplier_passport", "Loading supplier passport", case_id=case_id)
        passport = resolved_client.request_json(
            "GET",
            f"/api/cases/{case_id}/supplier-passport",
            params={
                "mode": supplier_passport_mode(
                    expected_min_control_paths=int(getattr(args, "expected_min_control_paths", 0) or 0),
                    expected_control_target=str(getattr(args, "expected_control_target", "") or ""),
                    warn_on_empty_control_paths=bool(getattr(args, "warn_on_empty_control_paths", False)),
                )
            },
        )
        passport_failures, passport_warnings = analyze_passport(
            passport,
            company_name=company_name,
            expected_domain=args.expected_domain,
            expected_cage=args.expected_cage,
            expected_uei=args.expected_uei,
            expected_duns=args.expected_duns,
            expected_cik=args.expected_cik,
            expected_identifiers=_expected_identifiers_from_args(args),
            expected_min_control_paths=args.expected_min_control_paths,
            expected_control_target=args.expected_control_target,
            warn_on_empty_control_paths=args.warn_on_empty_control_paths,
            require_monitoring_history=args.require_monitoring_history,
            minimum_official_corroboration=getattr(args, "minimum_official_corroboration", "missing"),
            max_blocked_official_connectors=int(
                getattr(args, "max_blocked_official_connectors", -1)
                if getattr(args, "max_blocked_official_connectors", -1) is not None
                else -1
            ),
        )
        failures.extend(passport_failures)
        warnings.extend(passport_warnings)

        assistant_ok = False
        if args.check_assistant:
            _write_progress(output_dir, "assistant", "Checking assistant control plane", case_id=case_id)
            try:
                plan = resolved_client.request_json(
                    "POST",
                    f"/api/cases/{case_id}/assistant-plan",
                    json={"prompt": "Summarize the strongest control path, key identifiers, and top analyst caveats."},
                )
                planned_steps = plan.get("plan", []) if isinstance(plan.get("plan"), list) else []
                if args.ai_readiness_mode == "surface":
                    assistant_ok = bool(planned_steps)
                    if not assistant_ok:
                        failures.append("assistant plan produced no steps")
                else:
                    approved_tool_ids = [step["tool_id"] for step in planned_steps if step.get("required")]
                    execution = resolved_client.request_json(
                        "POST",
                        f"/api/cases/{case_id}/assistant-execute",
                        json={"prompt": plan.get("analyst_prompt"), "approved_tool_ids": approved_tool_ids},
                    )
                    assistant_ok = bool(execution.get("executed_steps"))
                    if not assistant_ok:
                        failures.append("assistant execution produced no executed steps")
            except requests.HTTPError as exc:
                failures.append(f"assistant control plane failed: {exc}")

        identifiers = passport.get("identity", {}).get("identifiers", {}) if isinstance(passport.get("identity"), dict) else {}
        identifier_status = passport.get("identity", {}).get("identifier_status", {}) if isinstance(passport.get("identity"), dict) else {}
        graph = passport.get("graph", {}) if isinstance(passport.get("graph"), dict) else {}

        preview_verdict = gate_verdict(failures, warnings, args.max_warnings)
        _write_progress(
            output_dir,
            "evaluation_complete",
            f"Evaluation complete with verdict {preview_verdict}",
            case_id=case_id,
            verdict=preview_verdict,
            failure_count=len(failures),
            warning_count=len(warnings),
        )

        return DemoGateResult(
            verdict=preview_verdict,
            company_name=company_name,
            case_id=case_id,
            failures=failures,
            warnings=warnings,
            timings_ms=timings_ms,
            identifiers=identifiers,
            identifier_status=identifier_status,
            graph=graph,
            ai_status=ai_status,
            assistant_ok=assistant_ok,
            artifacts={"html": str(html_path), "pdf": str(pdf_path)},
            stabilization_steps=list(stabilization_steps),
        )

    stabilization_steps: list[dict[str, Any]] = []
    try:
        result = _evaluate_case(_run_enrich(), stabilization_steps)
        if result.verdict == "GO" or not args.auto_stabilize:
            _write_progress(output_dir, "done", f"Demo gate finished with verdict {result.verdict}", case_id=case_id, verdict=result.verdict)
            return result

        for pass_name, connectors in STABILIZATION_PASSES:
            _write_progress(
                output_dir,
                "stabilization",
                f"Running stabilization pass {pass_name}",
                case_id=case_id,
                stabilization_steps=stabilization_steps,
            )
            enrich_elapsed_ms = _run_enrich(connectors, full_reconcile=connectors is None)
            result = _evaluate_case(
                enrich_elapsed_ms,
                [
                    *stabilization_steps,
                    {
                        "name": pass_name,
                        "connectors": list(connectors or []),
                    },
                ],
            )
            stabilization_steps = [
                *stabilization_steps,
                {
                    "name": pass_name,
                    "connectors": list(connectors or []),
                    "verdict": result.verdict,
                    "failure_count": len(result.failures),
                    "warning_count": len(result.warnings),
                },
            ]
            result.stabilization_steps = list(stabilization_steps)
            if result.verdict == "GO":
                break

        _write_progress(output_dir, "done", f"Demo gate finished with verdict {result.verdict}", case_id=case_id, verdict=result.verdict)
        return result
    except Exception as exc:
        failure_message = f"demo gate execution failed: {exc.__class__.__name__}: {exc}"
        failure_html_path.write_text(failure_message + "\n", encoding="utf-8")
        failure_pdf_path.write_text(failure_message + "\n", encoding="utf-8")
        _write_progress(output_dir, "failed", failure_message, case_id=case_id, verdict="NO_GO")
        return DemoGateResult(
            verdict="NO_GO",
            company_name=company_name,
            case_id=case_id,
            failures=[failure_message],
            warnings=[],
            timings_ms={},
            identifiers={},
            identifier_status={},
            graph={},
            ai_status={},
            assistant_ok=False,
            artifacts={"html": str(failure_html_path), "pdf": str(failure_pdf_path)},
            stabilization_steps=list(stabilization_steps),
        )
    finally:
        if own_client:
            resolved_client.close()


def main() -> int:
    args = parse_args()
    result = run_demo_gate(args)
    output_dir = Path(result.artifacts["html"]).parent
    md_path, json_path = write_report(output_dir, result)

    if args.print_json:
        print(json.dumps(asdict(result), indent=2))
    else:
        print(f"{result.verdict}: {result.company_name} ({result.case_id})")
        print(f"Failures: {len(result.failures)} | Warnings: {len(result.warnings)}")
        print(f"Report: {md_path}")
        print(f"JSON: {json_path}")

    if result.verdict == "NO_GO":
        return 1
    if result.verdict == "CAUTION":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
