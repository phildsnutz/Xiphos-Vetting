"""
GDELT Global Media Monitoring - LIVE API

Real-time queries to GDELT Project for adverse media coverage:
  - News articles with risk keywords (sanctions, fraud, corruption, etc.)
  - Tone analysis for sentiment assessment
  - Global media aggregation across 1000+ sources

API: https://api.gdeltproject.org/api/v2/doc/doc
No authentication required. Free to use.
Timeout: 12 seconds (GDELT can be slow)
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

from . import EnrichmentResult, Finding

BASE = "https://api.gdeltproject.org/api/v2/doc"
USER_AGENT = "Xiphos/4.0 (compliance-tool@xiphos.dev)"

# Risk search terms to append
RISK_TERMS = "sanctions OR fraud OR corruption OR indictment OR money laundering OR debarment OR violation"

# Credibility tiers for news domains
HIGH_CREDIBILITY_DOMAINS = {
    "reuters.com",
    "nytimes.com",
    "washingtonpost.com",
    "bbc.com",
    "theguardian.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
}


def _get(url: str, retries: int = 2) -> dict | None:
    """GET request to GDELT API with retry on 429."""
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None


def _get_domain_credibility(domain: str) -> str:
    """Assess domain credibility."""
    domain_lower = domain.lower()
    for cred_domain in HIGH_CREDIBILITY_DOMAINS:
        if cred_domain in domain_lower:
            return "high"
    return "medium"


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc or "unknown"
    except:
        return "unknown"


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query GDELT for adverse media coverage."""
    t0 = time.time()
    result = EnrichmentResult(source="gdelt_media", vendor_name=vendor_name)

    try:
        # Step 1: Run a clean query to get baseline article count (no risk terms)
        clean_query = urllib.parse.quote(f'"{vendor_name}"')
        clean_url = (
            f"{BASE}/doc?"
            f"query={clean_query}"
            f"&mode=ArtList&maxrecords=10&format=json"
        )
        clean_data = _get(clean_url)
        baseline_count = 0
        if clean_data and "articles" in clean_data:
            baseline_count = len(clean_data.get("articles", []))

        time.sleep(0.5)

        # Step 2: Query with risk terms
        risk_query = f'"{vendor_name}" ({RISK_TERMS})'
        risk_query_encoded = urllib.parse.quote(risk_query)
        risk_url = (
            f"{BASE}/doc?"
            f"query={risk_query_encoded}"
            f"&mode=ArtList&maxrecords=10&format=json"
        )
        risk_data = _get(risk_url)

        if not risk_data or "articles" not in risk_data:
            result.findings.append(Finding(
                source="gdelt_media",
                category="adverse_media",
                title="No adverse media found",
                detail=(
                    f"No articles found for '{vendor_name}' with adverse keywords "
                    f"(sanctions, fraud, corruption, indictment, money laundering, debarment, violation). "
                    f"Baseline articles found: {baseline_count}"
                ),
                severity="info",
                confidence=0.8,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        articles = risk_data.get("articles", [])
        if not articles:
            result.findings.append(Finding(
                source="gdelt_media",
                category="adverse_media",
                title="No adverse media found",
                detail=(
                    f"No articles found for '{vendor_name}' with adverse keywords. "
                    f"Baseline articles found: {baseline_count}"
                ),
                severity="info",
                confidence=0.8,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        time.sleep(0.5)

        # Step 3: Query tone chart for sentiment analysis
        tone_url = (
            f"{BASE}/doc?"
            f"query={risk_query_encoded}"
            f"&mode=ToneChart&format=json"
        )
        tone_data = _get(tone_url)
        tone_info = {}
        if tone_data and "tonechart" in tone_data:
            tonechart = tone_data.get("tonechart", [])
            if tonechart:
                # Get first entry with tone data
                tone_info = tonechart[0] if isinstance(tonechart, list) else tonechart

        # Step 4: Process findings
        high_confidence_count = 0
        medium_confidence_count = 0

        for article in articles:
            url = article.get("url", "")
            title = article.get("title", "")
            seen_date = article.get("seendate", "")
            domain = article.get("domain", "")
            language = article.get("language", "")

            domain_credibility = _get_domain_credibility(domain)

            if domain_credibility == "high":
                severity = "high"
                high_confidence_count += 1
                confidence = 0.9
            else:
                severity = "medium"
                medium_confidence_count += 1
                confidence = 0.7

            finding_detail = (
                f"URL: {url}\n"
                f"Title: {title}\n"
                f"Seen: {seen_date}\n"
                f"Domain: {domain} (Credibility: {domain_credibility})\n"
                f"Language: {language}"
            )

            result.findings.append(Finding(
                source="gdelt_media",
                category="adverse_media",
                title=f"Adverse media: {title[:80]}...",
                detail=finding_detail,
                severity=severity,
                confidence=confidence,
                url=url,
                raw_data={
                    "domain": domain,
                    "domain_credibility": domain_credibility,
                    "seen_date": seen_date,
                    "language": language,
                },
            ))

        # Add risk signal
        total_adverse = high_confidence_count + medium_confidence_count
        overall_severity = "high" if high_confidence_count > 0 else "medium"

        result.risk_signals.append({
            "signal": "adverse_media_coverage",
            "severity": overall_severity,
            "detail": (
                f"Found {total_adverse} adverse media articles "
                f"({high_confidence_count} from high-credibility sources, "
                f"{medium_confidence_count} from other sources). "
                f"Baseline articles (no risk filter): {baseline_count}"
            ),
            "article_count": total_adverse,
            "high_credibility_count": high_confidence_count,
            "baseline_count": baseline_count,
            "tone_data": tone_info,
        })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
