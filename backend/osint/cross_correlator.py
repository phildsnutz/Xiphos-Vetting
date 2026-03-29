"""
Sanctions Cross-Correlation Engine

Analyzes findings across all 8 sanctions lists to:
1. Identify corroborated hits (entity on 2+ lists)
2. Flag near-miss fuzzy matches across different list names
3. Detect alias patterns (entity known by different names on different lists)
4. Generate composite severity scores

This dramatically improves signal quality without any new data sources.
"""

import re
import logging
from difflib import SequenceMatcher
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)

SANCTIONS_SOURCES = {
    "dod_sam_exclusions", "trade_csl", "un_sanctions", "ofac_sdn",
    "eu_sanctions", "uk_hmt_sanctions", "opensanctions_pep", "worldbank_debarred",
}

# Display names for correlation reports
SOURCE_NAMES = {
    "dod_sam_exclusions": "SAM.gov Exclusions",
    "trade_csl": "Consolidated Screening List",
    "un_sanctions": "UN Security Council",
    "ofac_sdn": "OFAC SDN",
    "eu_sanctions": "EU Sanctions",
    "uk_hmt_sanctions": "UK HMT Sanctions",
    "opensanctions_pep": "PEP Screening",
    "worldbank_debarred": "World Bank Debarment",
}


def _normalize_name(name: str) -> str:
    """Normalize a name for fuzzy matching."""
    name = name.upper().strip()
    # Remove common suffixes
    for suffix in ["LLC", "INC", "CORP", "LTD", "PLC", "LP", "LLP", "CO", "CORPORATION", "INCORPORATED", "LIMITED"]:
        name = re.sub(rf"\b{suffix}\b\.?", "", name)
    # Remove punctuation and extra whitespace
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _extract_matched_name(finding: dict) -> Optional[str]:
    """Extract the matched entity name from a sanctions finding."""
    title = finding.get("title", "")
    detail = finding.get("detail", "")

    # Common patterns in our findings:
    # "CSL MATCH: Entity Name [source]"
    # "OFAC SDN MATCH: Entity Name"
    # "SAM Exclusion: Entity Name"
    match_patterns = [
        r"MATCH:\s*(.+?)(?:\s*\[|\s*$)",
        r"Exclusion:\s*(.+?)(?:\s*\(|\s*$)",
        r"Sanction(?:ed)?:\s*(.+?)(?:\s*\(|\s*$)",
        r"Debarment:\s*(.+?)(?:\s*\(|\s*$)",
        r"PEP:\s*(.+?)(?:\s*\(|\s*$)",
    ]
    for pattern in match_patterns:
        m = re.search(pattern, title)
        if m:
            return m.group(1).strip()

    # Check detail field for name patterns
    m = re.search(r"Name:\s*(.+?)(?:\n|$)", detail)
    if m:
        return m.group(1).strip()

    return None


def _similarity(a: str, b: str) -> float:
    """Compute name similarity ratio (0-1)."""
    return SequenceMatcher(None, _normalize_name(a), _normalize_name(b)).ratio()


def cross_correlate_sanctions(findings: list[dict], vendor_name: str) -> list[dict]:
    """
    Cross-correlate sanctions findings across all 8 lists.

    Returns additional synthetic findings that represent cross-list patterns.
    """
    # Separate sanctions findings (hits only, not clears)
    sanctions_hits: dict[str, list[dict]] = defaultdict(list)
    sanctions_clears: set[str] = set()

    for f in findings:
        source = f.get("source", "")
        if source not in SANCTIONS_SOURCES:
            continue
        sev = f.get("severity", "info")
        title = f.get("title", "").lower()

        # Classify as hit vs clear
        if sev in ("high", "critical", "medium") and "clear" not in title and "no " not in title[:5]:
            sanctions_hits[source].append(f)
        elif "clear" in title or "no match" in title or "no " in title[:5] or sev == "info":
            sanctions_clears.add(source)

    cross_findings = []

    if not sanctions_hits:
        # No sanctions hits at all. Check coverage.
        coverage = len(sanctions_clears)
        if coverage >= 6:
            cross_findings.append({
                "source": "cross_correlation",
                "category": "screening",
                "title": f"Sanctions cross-check: CLEAR across {coverage}/{len(SANCTIONS_SOURCES)} lists",
                "detail": (
                    f"Entity cleared across {coverage} independent sanctions databases: "
                    + ", ".join(SOURCE_NAMES.get(s, s) for s in sorted(sanctions_clears))
                    + ". High confidence that entity is not sanctioned."
                ),
                "severity": "info",
                "confidence": min(0.95, 0.5 + coverage * 0.065),
                "url": "",
            })
        return cross_findings

    # We have sanctions hits. Analyze cross-list patterns.
    hit_sources = set(sanctions_hits.keys())
    hit_count = len(hit_sources)

    # 1. Multi-list corroboration
    if hit_count >= 2:
        source_list = ", ".join(SOURCE_NAMES.get(s, s) for s in sorted(hit_sources))
        # Extract matched names for each source
        matched_names = {}
        for src, hits in sanctions_hits.items():
            for h in hits:
                name = _extract_matched_name(h)
                if name:
                    matched_names[src] = name
                    break

        detail_parts = [
            f"CORROBORATED: Entity appears on {hit_count} independent sanctions/exclusion lists: {source_list}.",
        ]

        # Check if names match across lists
        names_list = list(matched_names.values())
        if len(names_list) >= 2:
            name_pairs = []
            for i, n1 in enumerate(names_list):
                for n2 in names_list[i + 1:]:
                    sim = _similarity(n1, n2)
                    if sim < 0.85:
                        name_pairs.append((n1, n2, sim))
            if name_pairs:
                detail_parts.append("Alias detection: entity listed under different names:")
                for n1, n2, sim in name_pairs:
                    detail_parts.append(f"  - '{n1}' vs '{n2}' (similarity: {sim:.0%})")

        # Boost severity based on corroboration
        base_sev = max(
            (f.get("severity", "info") for hits in sanctions_hits.values() for f in hits),
            key=lambda s: {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}.get(s, 0),
        )
        if hit_count >= 3:
            sev = "critical"
        elif base_sev in ("high", "critical"):
            sev = "critical"
        else:
            sev = "high"

        cross_findings.append({
            "source": "cross_correlation",
            "category": "screening",
            "title": f"MULTI-LIST CORROBORATION: Entity flagged on {hit_count} sanctions lists",
            "detail": "\n".join(detail_parts),
            "severity": sev,
            "confidence": min(0.99, 0.7 + hit_count * 0.1),
            "url": "",
        })

    # 2. Single-list hit with clear on others = possible false positive or partial match
    elif hit_count == 1:
        hit_source = list(hit_sources)[0]
        clear_count = len(sanctions_clears)
        if clear_count >= 5:
            cross_findings.append({
                "source": "cross_correlation",
                "category": "screening",
                "title": f"Uncorroborated hit: flagged only on {SOURCE_NAMES.get(hit_source, hit_source)}",
                "detail": (
                    f"Entity flagged on {SOURCE_NAMES.get(hit_source, hit_source)} but cleared on "
                    f"{clear_count} other sanctions databases. This may indicate a partial name match, "
                    "a different entity with a similar name, or a listing in only one jurisdiction. "
                    "Manual review recommended."
                ),
                "severity": "medium",
                "confidence": 0.6,
                "url": "",
            })

    # 3. Check for near-miss vendor name vs sanctions hits
    for src, hits in sanctions_hits.items():
        for h in hits:
            matched = _extract_matched_name(h)
            if matched:
                sim = _similarity(vendor_name, matched)
                if 0.6 < sim < 0.85:
                    cross_findings.append({
                        "source": "cross_correlation",
                        "category": "screening",
                        "title": f"Near-miss match: '{matched}' on {SOURCE_NAMES.get(src, src)}",
                        "detail": (
                            f"The sanctioned entity '{matched}' has {sim:.0%} name similarity to the "
                            f"assessed vendor '{vendor_name}'. This is below the exact match threshold "
                            "but warrants manual review to confirm these are different entities."
                        ),
                        "severity": "medium",
                        "confidence": sim,
                        "url": "",
                    })

    return cross_findings


def cross_correlate_domains(findings: list[dict], vendor_name: str) -> list[dict]:
    """
    Cross-domain correlation: analyze patterns across different risk domains.

    Detects compound risk patterns like:
    - Sanctions hit + SEC enforcement = regulatory pattern
    - High-risk litigation + sanctions = elevated risk profile
    - SEC enforcement + high litigation volume = governance concern
    - Supply chain concentration + sanctions on subcontractor = supply chain risk

    Returns additional synthetic findings.
    """
    cross_findings = []

    # Categorize all findings by domain
    domains = {
        "sanctions": [],
        "sec_enforce": [],
        "litigation_high": [],
        "litigation_any": [],
        "supply_chain": [],
        "exclusion": [],
        "media_adverse": [],
    }

    for f in findings:
        source = f.get("source", "")
        category = f.get("category", "")
        severity = f.get("severity", "info")
        title = f.get("title", "").lower()

        if source in SANCTIONS_SOURCES and severity in ("high", "critical", "medium"):
            if "clear" not in title and "no " not in title[:5]:
                domains["sanctions"].append(f)

        if source == "sec_edgar" and (category == "enforcement" or "enforcement" in title):
            domains["sec_enforce"].append(f)

        if source == "recap_courts" and category == "litigation":
            domains["litigation_any"].append(f)
            if severity in ("high", "critical"):
                domains["litigation_high"].append(f)

        if category == "supply_chain":
            domains["supply_chain"].append(f)

        if source in ("dod_sam_exclusions", "worldbank_debarred") and severity in ("high", "critical"):
            domains["exclusion"].append(f)

        if source in ("gdelt_media", "google_news") and severity in ("high", "medium"):
            domains["media_adverse"].append(f)

    # Pattern 1: Sanctions + SEC Enforcement = Regulatory Pattern
    if domains["sanctions"] and domains["sec_enforce"]:
        sanctions_sources = set(f.get("source", "") for f in domains["sanctions"])
        cross_findings.append({
            "source": "cross_correlation",
            "category": "risk_pattern",
            "title": "REGULATORY PATTERN: Sanctions flag + SEC enforcement action detected",
            "detail": (
                f"Entity appears on {len(sanctions_sources)} sanctions/screening list(s) AND has "
                f"{len(domains['sec_enforce'])} SEC enforcement-related filing(s). "
                "This combination suggests a pattern of regulatory non-compliance. "
                "Recommend escalating to senior compliance review."
            ),
            "severity": "critical",
            "confidence": 0.85,
            "url": "",
        })

    # Pattern 2: High-risk litigation + Sanctions = Elevated Risk
    if domains["litigation_high"] and domains["sanctions"]:
        cross_findings.append({
            "source": "cross_correlation",
            "category": "risk_pattern",
            "title": "COMPOUND RISK: High-risk litigation + sanctions flags",
            "detail": (
                f"Entity has {len(domains['litigation_high'])} high-risk federal litigation case(s) "
                f"(fraud, securities, RICO) AND sanctions/screening flags. "
                "Multiple independent risk indicators across legal and regulatory domains "
                "significantly reduce the likelihood of false positive."
            ),
            "severity": "high",
            "confidence": 0.8,
            "url": "",
        })

    # Pattern 3: SEC Enforcement + High Litigation Volume = Governance Concern
    if domains["sec_enforce"] and len(domains["litigation_any"]) >= 2:
        cross_findings.append({
            "source": "cross_correlation",
            "category": "risk_pattern",
            "title": "GOVERNANCE CONCERN: SEC enforcement + significant litigation history",
            "detail": (
                f"Entity has {len(domains['sec_enforce'])} SEC enforcement-related finding(s) "
                f"combined with {len(domains['litigation_any'])} federal litigation record(s). "
                "Pattern may indicate systemic governance or compliance weaknesses."
            ),
            "severity": "medium",
            "confidence": 0.7,
            "url": "",
        })

    # Pattern 4: Government exclusion + federal contracts = high risk
    if domains["exclusion"] and any(
        f.get("source") == "usaspending" and f.get("category") == "contracts"
        for f in findings
    ):
        cross_findings.append({
            "source": "cross_correlation",
            "category": "risk_pattern",
            "title": "EXCLUSION RISK: Excluded/debarred entity has federal contract history",
            "detail": (
                f"Entity has {len(domains['exclusion'])} government exclusion/debarment finding(s) "
                "AND active or historical federal contract awards. "
                "If the entity is currently excluded, any ongoing federal contracts may be in violation."
            ),
            "severity": "critical",
            "confidence": 0.9,
            "url": "",
        })

    # Pattern 5: Supply chain concentration + sanctions
    if domains["supply_chain"] and domains["sanctions"]:
        concentration = [f for f in domains["supply_chain"] if "concentration" in f.get("title", "").lower()]
        if concentration:
            cross_findings.append({
                "source": "cross_correlation",
                "category": "risk_pattern",
                "title": "SUPPLY CHAIN + SANCTIONS: Concentrated supply chain with sanctions exposure",
                "detail": (
                    "Entity has supply chain concentration risk AND sanctions/screening flags. "
                    "If sanctions apply to a concentrated subcontractor, this creates "
                    "cascading compliance risk across the supply chain."
                ),
                "severity": "high",
                "confidence": 0.65,
                "url": "",
            })

    # Pattern 6: Clean across all domains = strong positive signal
    if (not domains["sanctions"] and not domains["sec_enforce"]
            and not domains["litigation_high"] and not domains["exclusion"]
            and not domains["media_adverse"]):
        checked_domains = 0
        sources_seen = set(f.get("source", "") for f in findings)
        if sources_seen & SANCTIONS_SOURCES:
            checked_domains += 1
        if "sec_edgar" in sources_seen:
            checked_domains += 1
        if "recap_courts" in sources_seen:
            checked_domains += 1
        if "usaspending" in sources_seen:
            checked_domains += 1
        if sources_seen & {"gdelt_media", "google_news"}:
            checked_domains += 1

        if checked_domains >= 3:
            cross_findings.append({
                "source": "cross_correlation",
                "category": "risk_pattern",
                "title": f"CROSS-DOMAIN CLEAR: No adverse findings across {checked_domains} risk domains",
                "detail": (
                    f"Entity cleared across {checked_domains} independent risk domains "
                    "(sanctions, regulatory, litigation, contracts, media). "
                    "Multi-domain clearance provides high confidence in low-risk assessment."
                ),
                "severity": "info",
                "confidence": min(0.95, 0.6 + checked_domains * 0.07),
                "url": "",
            })

    return cross_findings
