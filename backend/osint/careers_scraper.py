"""
Careers Scraper -- Grey Zone OSINT Connector

Scrapes public job boards and company careers pages to identify subcontractors
on government contracts. Primary intelligence source when federal subaward
reporting APIs (SAM.gov) return zero records, which is systematic for
FEDSIM-managed task orders (OASIS, ASTRO, Alliant 2, etc.).

Intelligence value:
  - Subcontractor identification where SAM Subaward API fails
  - Teaming relationship discovery (company X hiring for contract Y)
  - Workforce size estimation per contract
  - Clearance requirements and technical scope indicators
  - Installation/location correlation

Sources:
  - ClearanceJobs (clearancejobs.com) -- cleared defense positions
  - Indeed (indeed.com) -- general job aggregator
  - Company careers pages (vendor website /careers, /jobs)

Evidence classification:
  - source_class: grey_zone_osint
  - authority_level: third_party_public
  - access_model: public_scrape
"""

import logging
import os
import re
import time
import random
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from . import EnrichmentResult, Finding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIMEOUT = float(os.environ.get("XIPHOS_CAREERS_TIMEOUT_SECONDS", "4"))
REQUEST_DELAY = float(os.environ.get("XIPHOS_CAREERS_REQUEST_DELAY_SECONDS", "0.1"))
MAX_RESULTS_PER_SOURCE = 25
MAX_COMPANY_CAREERS_CANDIDATES = int(os.environ.get("XIPHOS_CAREERS_MAX_COMPANY_URLS", "4"))
ENABLE_CLEARANCEJOBS = os.environ.get("XIPHOS_CAREERS_ENABLE_CLEARANCEJOBS", "true").lower() in {"1", "true", "yes"}
ENABLE_INDEED = os.environ.get("XIPHOS_CAREERS_ENABLE_INDEED", "false").lower() in {"1", "true", "yes"}
ENABLE_COMPANY_GUESSING = os.environ.get("XIPHOS_CAREERS_ENABLE_COMPANY_GUESSING", "false").lower() in {"1", "true", "yes"}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# Contract/mission keywords that indicate government contract work
CONTRACT_INDICATORS = [
    "TS/SCI", "Top Secret", "Secret clearance", "clearance required",
    "COCOM", "INDOPACOM", "CENTCOM", "EUCOM", "AFRICOM", "SOCOM", "CYBERCOM",
    "HUMINT", "SIGINT", "GEOINT", "MASINT", "OSINT", "ISR", "C5ISR", "C4ISR",
    "JOPES", "JOPEX", "EW", "electronic warfare", "information warfare",
    "cyber operations", "DCI", "defense critical infrastructure",
    "FEDSIM", "OASIS", "ASTRO", "Alliant", "ITEAMS", "LEIA",
    "Camp Smith", "Fort Meade", "Fort Liberty", "Fort Huachuca",
    "SOFA", "SOF", "special operations", "joint exercise",
    "CMMC", "NIST 800-171", "DFARS", "ITAR",
    "task order", "contract vehicle", "ID/IQ", "BPA",
]

CONTRACT_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in CONTRACT_INDICATORS),
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get_session() -> requests.Session:
    """Create a requests session with random user agent."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def _safe_get(session: requests.Session, url: str, **kwargs) -> Optional[requests.Response]:
    """GET with timeout and error handling. Returns None on failure."""
    try:
        resp = session.get(url, timeout=TIMEOUT, **kwargs)
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        logger.warning("careers_scraper: GET %s failed: %s", url, e)
        return None


def _sleep_if_needed() -> None:
    if REQUEST_DELAY > 0:
        time.sleep(REQUEST_DELAY)


# ---------------------------------------------------------------------------
# Source: ClearanceJobs
# ---------------------------------------------------------------------------

def _scrape_clearancejobs(session: requests.Session, query: str) -> list[dict]:
    """Scrape ClearanceJobs search results for contract-related positions."""
    posts = []
    url = f"https://www.clearancejobs.com/jobs?keywords={quote_plus(query)}"
    logger.info("careers_scraper: querying ClearanceJobs for '%s'", query)

    resp = _safe_get(session, url)
    if not resp:
        return posts

    soup = BeautifulSoup(resp.text, "html.parser")

    # ClearanceJobs uses job card elements
    cards = soup.select("div.job-listing, article.job-card, div[data-job-id], li.job-result")
    if not cards:
        # Fallback: look for any structured job data
        cards = soup.find_all("div", class_=re.compile(r"job|listing|result", re.I))

    for card in cards[:MAX_RESULTS_PER_SOURCE]:
        post = _extract_job_card(card, "clearancejobs")
        if post.get("title"):
            post["source_url"] = url
            posts.append(post)

    logger.info("careers_scraper: ClearanceJobs returned %d postings", len(posts))
    return posts


# ---------------------------------------------------------------------------
# Source: Indeed
# ---------------------------------------------------------------------------

def _scrape_indeed(session: requests.Session, query: str) -> list[dict]:
    """Scrape Indeed search results for contract-related positions."""
    posts = []
    url = f"https://www.indeed.com/jobs?q={quote_plus(query)}&sort=date"
    logger.info("careers_scraper: querying Indeed for '%s'", query)

    resp = _safe_get(session, url)
    if not resp:
        return posts

    soup = BeautifulSoup(resp.text, "html.parser")

    cards = soup.select("div.job_seen_beacon, div.jobsearch-ResultsList div.result, td.resultContent")
    if not cards:
        cards = soup.find_all("div", class_=re.compile(r"result|job", re.I))

    for card in cards[:MAX_RESULTS_PER_SOURCE]:
        post = _extract_job_card(card, "indeed")
        if post.get("title"):
            post["source_url"] = url
            posts.append(post)

    logger.info("careers_scraper: Indeed returned %d postings", len(posts))
    return posts


# ---------------------------------------------------------------------------
# Source: Company Careers Page
# ---------------------------------------------------------------------------

def _scrape_company_careers(session: requests.Session, company_name: str,
                            website: str = "") -> list[dict]:
    """Attempt to discover and scrape company careers page."""
    posts = []

    if not website:
        if not ENABLE_COMPANY_GUESSING:
            logger.info("careers_scraper: skipping speculative careers-domain guessing for '%s'", company_name)
            return posts
        # Generate smarter domain slug candidates instead of naive full-name slug
        company_lower = company_name.lower()

        # Extract first word (before space, comma, or parenthesis)
        first_word_match = re.match(r"(\w+)", company_lower)
        first_word = first_word_match.group(1) if first_word_match else ""

        # Extract first two words for hyphenated variant
        two_words_match = re.match(r"(\w+)\s+(\w+)", company_lower)
        two_words = f"{two_words_match.group(1)}-{two_words_match.group(2)}" if two_words_match else ""

        # Extract acronym (all caps words, first letter of each word)
        acronym = ""
        words = re.findall(r"[A-Za-z]+", company_lower)
        if len(words) > 1 and all(w.isupper() or w.istitle() for w in company_name.split()):
            acronym = "".join(w[0] for w in words)

        # Naive full slug as fallback (least preferred)
        full_slug = re.sub(r"[^a-z0-9]", "", company_lower)

        # Build candidates list: smart guesses first, fallback last
        slug_candidates = []
        if first_word:
            slug_candidates.append(first_word)
        if two_words and two_words != first_word:
            slug_candidates.append(two_words)
        if acronym and acronym != first_word and acronym != two_words:
            slug_candidates.append(acronym)
        if full_slug not in slug_candidates:
            slug_candidates.append(full_slug)  # Last resort

        # Generate URL candidates from slugs
        candidates = []
        for slug in slug_candidates:
            candidates.extend([
                f"https://www.{slug}.com/careers",
                f"https://www.{slug}.com/jobs",
                f"https://{slug}.com/careers",
                f"https://careers.{slug}.com",
            ])
    else:
        base = website.rstrip("/")
        if not base.startswith("http"):
            base = f"https://{base}"
        candidates = [
            f"{base}/careers",
            f"{base}/jobs",
            f"{base}/join-us",
            f"{base}/opportunities",
        ]

    candidates = candidates[:MAX_COMPANY_CAREERS_CANDIDATES]

    for careers_url in candidates:
        resp = _safe_get(session, careers_url, allow_redirects=True)
        if resp and resp.status_code == 200:
            logger.info("careers_scraper: found careers page at %s", careers_url)
            soup = BeautifulSoup(resp.text, "html.parser")

            # Look for job listing elements
            cards = soup.find_all(["div", "li", "article", "tr"],
                                  class_=re.compile(r"job|position|opening|career|role", re.I))

            for card in cards[:MAX_RESULTS_PER_SOURCE]:
                post = _extract_job_card(card, "company_careers")
                if post.get("title"):
                    post["company"] = company_name
                    post["source_url"] = careers_url
                    posts.append(post)

            if posts:
                break  # Found a working careers page
            _sleep_if_needed()

    logger.info("careers_scraper: company careers returned %d postings", len(posts))
    return posts


# ---------------------------------------------------------------------------
# Job card extraction
# ---------------------------------------------------------------------------

def _extract_job_card(element, source: str) -> dict:
    """Extract structured data from a job listing HTML element."""
    post = {
        "title": "",
        "company": "",
        "location": "",
        "clearance": "",
        "description_snippet": "",
        "contract_indicators": [],
        "source_board": source,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }

    # Title: look for h2, h3, a tags with job-like classes
    title_el = element.find(["h2", "h3", "a", "span"],
                            class_=re.compile(r"title|heading|name", re.I))
    if not title_el:
        title_el = element.find(["h2", "h3", "a"])
    if title_el:
        post["title"] = title_el.get_text(strip=True)[:200]

    # Company name
    company_el = element.find(["span", "div", "a"],
                              class_=re.compile(r"company|employer|org", re.I))
    if company_el:
        post["company"] = company_el.get_text(strip=True)[:150]

    # Location
    loc_el = element.find(["span", "div"],
                          class_=re.compile(r"location|loc|place|city", re.I))
    if loc_el:
        post["location"] = loc_el.get_text(strip=True)[:150]

    # Full text for indicator scanning
    full_text = element.get_text(" ", strip=True)[:2000]
    post["description_snippet"] = full_text[:500]

    # Clearance level extraction
    clearance_match = re.search(
        r"(TS/SCI|Top Secret/SCI|Top Secret|Secret|Confidential|Public Trust)",
        full_text, re.IGNORECASE
    )
    if clearance_match:
        post["clearance"] = clearance_match.group(0)

    # Contract indicator matching
    indicators = CONTRACT_PATTERN.findall(full_text)
    post["contract_indicators"] = list(set(indicators))

    return post


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def _identify_subcontractors(posts: list[dict], prime_name: str) -> dict[str, list[dict]]:
    """
    Group job postings by company name, separating prime from potential subs.
    Returns dict: { company_name: [posts] } excluding the prime.
    """
    subs: dict[str, list[dict]] = {}
    prime_lower = prime_name.lower()
    prime_tokens = set(prime_lower.split())

    for post in posts:
        company = post.get("company", "").strip()
        if not company:
            continue

        company_lower = company.lower()
        # Skip if this IS the prime contractor
        if (prime_lower in company_lower or company_lower in prime_lower
                or prime_tokens & set(company_lower.split())):
            continue

        if company not in subs:
            subs[company] = []
        subs[company].append(post)

    return subs


def _analyze_employment_patterns(posts: list[dict]) -> dict:
    """Analyze aggregate employment patterns from job postings."""
    patterns = {
        "total_positions": len(posts),
        "clearance_distribution": {},
        "location_distribution": {},
        "top_contract_indicators": {},
        "companies_identified": set(),
    }

    for post in posts:
        # Clearance
        clearance = post.get("clearance", "Not specified")
        patterns["clearance_distribution"][clearance] = \
            patterns["clearance_distribution"].get(clearance, 0) + 1

        # Location
        loc = post.get("location", "Unknown")
        if loc:
            patterns["location_distribution"][loc] = \
                patterns["location_distribution"].get(loc, 0) + 1

        # Contract indicators
        for indicator in post.get("contract_indicators", []):
            patterns["top_contract_indicators"][indicator] = \
                patterns["top_contract_indicators"].get(indicator, 0) + 1

        # Companies
        if post.get("company"):
            patterns["companies_identified"].add(post["company"])

    # Convert set to list for JSON serialization
    patterns["companies_identified"] = sorted(patterns["companies_identified"])
    return patterns


# ---------------------------------------------------------------------------
# Main enrich function
# ---------------------------------------------------------------------------

def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """
    Scrape job boards and careers pages to identify subcontractors
    and employment patterns for a vendor (prime contractor).

    Optional keyword arguments via **ids:
      - contract_name: str   -- contract name to include in search queries
      - vehicle_name: str    -- vehicle name (OASIS, ASTRO, etc.)
      - installation: str    -- installation name (Camp Smith, Fort Meade)
      - website: str         -- company website URL for careers page scraping

    Returns:
      EnrichmentResult with subcontractor findings, employment intelligence,
      and relationship entries for KG ingestion.
    """
    result = EnrichmentResult(
        source="careers_scraper",
        vendor_name=vendor_name,
        source_class="grey_zone_osint",
        authority_level="third_party_public",
        access_model="public_scrape",
    )
    start = datetime.now(timezone.utc)

    try:
        session = _get_session()
        all_posts: list[dict] = []

        # Build search queries
        contract_name = ids.get("contract_name", "")
        vehicle_name = ids.get("vehicle_name", "")
        installation = ids.get("installation", "")
        website = ids.get("website", "") or ids.get("sam_website", "")

        # Primary query: vendor + contract context
        queries = []
        if contract_name:
            queries.append(f"{vendor_name} {contract_name}")
        if vehicle_name:
            queries.append(f"{vendor_name} {vehicle_name}")
        if installation:
            queries.append(f"{vendor_name} {installation}")
        if not queries:
            queries.append(vendor_name)

        # Use first query for job boards (time budget)
        primary_query = queries[0]

        # Source 1: ClearanceJobs
        if ENABLE_CLEARANCEJOBS:
            cj_posts = _scrape_clearancejobs(session, primary_query)
            all_posts.extend(cj_posts)
            _sleep_if_needed()

        # Source 2: Indeed
        if ENABLE_INDEED:
            indeed_posts = _scrape_indeed(session, primary_query)
            all_posts.extend(indeed_posts)
            _sleep_if_needed()

        # Source 3: Company careers page
        careers_posts = _scrape_company_careers(session, vendor_name, website)
        all_posts.extend(careers_posts)

        if not all_posts:
            result.findings.append(Finding(
                source="careers_scraper",
                category="employment_intelligence",
                title=f"No job postings found for '{vendor_name}'",
                detail=(
                    f"Searched ClearanceJobs, Indeed, and company careers pages "
                    f"for '{primary_query}'. Zero postings returned. This may indicate "
                    f"the vendor uses non-public recruiting channels, or the search "
                    f"terms need refinement."
                ),
                severity="info",
                confidence=0.4,
                source_class="grey_zone_osint",
                authority_level="third_party_public",
                access_model="public_scrape",
            ))
            result.elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
            return result

        # Identify subcontractors
        subs = _identify_subcontractors(all_posts, vendor_name)

        # Generate findings per subcontractor
        for sub_name, sub_posts in sorted(subs.items(), key=lambda x: -len(x[1])):
            locations = set(p.get("location", "") for p in sub_posts if p.get("location"))
            clearances = set(p.get("clearance", "") for p in sub_posts if p.get("clearance"))
            indicators = set()
            for p in sub_posts:
                indicators.update(p.get("contract_indicators", []))

            titles = [p.get("title", "") for p in sub_posts if p.get("title")]

            # Confidence scoring
            confidence = 0.5  # base
            if len(sub_posts) >= 5:
                confidence += 0.15
            if any("TS/SCI" in c for c in clearances):
                confidence += 0.1
            if indicators:
                confidence += 0.1
            if contract_name and any(contract_name.lower() in (p.get("description_snippet", "").lower()) for p in sub_posts):
                confidence += 0.15
            confidence = min(confidence, 0.95)

            severity = "medium" if len(sub_posts) >= 5 else "low" if len(sub_posts) >= 2 else "info"

            result.findings.append(Finding(
                source="careers_scraper",
                category="subcontractor_identification",
                title=f"Probable subcontractor: {sub_name} ({len(sub_posts)} positions)",
                detail=(
                    f"{sub_name} has {len(sub_posts)} job posting(s) consistent with "
                    f"subcontract work under {vendor_name}. "
                    f"Locations: {', '.join(sorted(locations)) or 'not specified'}. "
                    f"Clearance levels: {', '.join(sorted(clearances)) or 'not specified'}. "
                    f"Contract indicators: {', '.join(sorted(indicators)) or 'none detected'}. "
                    f"Sample titles: {'; '.join(titles[:3])}."
                ),
                severity=severity,
                confidence=confidence,
                source_class="grey_zone_osint",
                authority_level="third_party_public",
                access_model="public_scrape",
                raw_data={
                    "sub_name": sub_name,
                    "position_count": len(sub_posts),
                    "locations": sorted(locations),
                    "clearances": sorted(clearances),
                    "contract_indicators": sorted(indicators),
                    "sample_titles": titles[:5],
                    "posts": sub_posts[:5],  # Cap raw data
                },
                structured_fields={
                    "entity_type": "subcontractor_candidate",
                    "prime_contractor": vendor_name,
                    "position_count": len(sub_posts),
                },
            ))

            # Relationship entry for KG ingestion
            result.relationships.append({
                "type": "subcontractor_of",
                "source_entity": sub_name,
                "target_entity": vendor_name,
                "data_source": "careers_scraper",
                "confidence": confidence,
                "detail": f"Identified via {len(sub_posts)} job posting(s) on public job boards",
                "evidence_type": "job_board_osint",
                "positions_observed": len(sub_posts),
            })

        # Employment patterns analysis
        patterns = _analyze_employment_patterns(all_posts)

        result.findings.append(Finding(
            source="careers_scraper",
            category="employment_intelligence",
            title=f"Employment pattern analysis: {patterns['total_positions']} positions across {len(patterns['companies_identified'])} companies",
            detail=(
                f"Aggregated {patterns['total_positions']} job postings for '{primary_query}'. "
                f"Companies identified: {', '.join(patterns['companies_identified'][:10])}. "
                f"Clearance distribution: {patterns['clearance_distribution']}. "
                f"Top locations: {dict(sorted(patterns['location_distribution'].items(), key=lambda x: -x[1])[:5])}. "
                f"Top contract indicators: {dict(sorted(patterns['top_contract_indicators'].items(), key=lambda x: -x[1])[:10])}."
            ),
            severity="info",
            confidence=0.7,
            source_class="grey_zone_osint",
            authority_level="third_party_public",
            access_model="public_scrape",
            raw_data=patterns,
            structured_fields={
                "total_positions": patterns["total_positions"],
                "companies_count": len(patterns["companies_identified"]),
            },
        ))

        # Risk signals
        for sub_name, sub_posts in subs.items():
            if len(sub_posts) >= 10:
                result.risk_signals.append({
                    "signal": "high_subcontractor_concentration",
                    "severity": "medium",
                    "detail": (
                        f"{sub_name} has {len(sub_posts)} positions under {vendor_name}, "
                        f"indicating deep workforce dependency. Loss of this sub would "
                        f"significantly impact contract performance."
                    ),
                    "sub_name": sub_name,
                    "position_count": len(sub_posts),
                })

        # Identifiers
        result.identifiers["careers_scraper_total_posts"] = len(all_posts)
        result.identifiers["careers_scraper_subs_found"] = len(subs)
        result.identifiers["careers_scraper_sources"] = [
            s for s in ["clearancejobs", "indeed", "company_careers"]
            if any(p.get("source_board") == s for p in all_posts)
        ]

    except Exception as e:
        logger.exception("careers_scraper: unexpected error for '%s'", vendor_name)
        result.error = str(e)

    result.elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    return result
