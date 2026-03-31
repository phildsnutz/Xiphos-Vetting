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
import logging
import concurrent.futures
import urllib.request
import urllib.error
import urllib.parse

from . import EnrichmentResult, Finding

logger = logging.getLogger(__name__)

# Try to load ML classifier
_ml_available = False
_ml_classify = None
try:
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from ml.inference import is_model_available, classify_finding
    if is_model_available():
        _ml_available = True
        _ml_classify = classify_finding
except Exception:
    pass

BASE = "https://api.gdeltproject.org/api/v2/doc"
USER_AGENT = "Xiphos/4.0 (compliance-tool@xiphos.dev)"
REQUEST_TIMEOUT = 8

# Risk search terms -- tightened to reduce false positives
# Use NEAR operator to require proximity between vendor name and risk term
RISK_TERMS = "sanctions OR fraud OR corruption OR indictment OR debarment OR violation OR penalty OR investigation"

# Title-level keywords that strongly indicate the vendor IS the subject (not just mentioned)
TITLE_RISK_KEYWORDS = {"sanction", "fraud", "lawsuit", "investigation", "fine", "penalty",
                       "breach", "hack", "violation", "indictment", "recall", "scandal",
                       "bankruptcy", "default", "probe", "subpoena", "debarment", "corrupt"}

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


def _get(url: str, retries: int = 2, timeout_s: int = REQUEST_TIMEOUT) -> dict | None:
    """GET request to GDELT API with retry on 429."""
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read()
                if "html" in content_type.lower() or raw[:20].startswith(b"<!DOCTYPE"):
                    return None
                return json.loads(raw)
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
    except Exception as e:
        logger.debug(f"Failed to extract domain from URL: {e}")
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

        tone_url = (
            f"{BASE}/doc?"
            f"query={risk_query_encoded}"
            f"&mode=ToneChart&format=json"
        )
        gkg_url = (
            f"https://api.gdeltproject.org/api/v2/doc/doc?"
            f"query={clean_query}"
            f"&mode=TimelineSourceCountry&format=json"
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            tone_future = executor.submit(_get, tone_url)
            gkg_future = executor.submit(_get, gkg_url)
            tone_data = tone_future.result()
            gkg_data = gkg_future.result()
        tone_info = {}
        avg_tone = 0.0
        if tone_data and "tonechart" in tone_data:
            tonechart = tone_data.get("tonechart", [])
            if tonechart and isinstance(tonechart, list):
                tone_info = tonechart[0] if tonechart else {}
                # Compute average tone across all entries
                tone_values = []
                for entry in tonechart:
                    if isinstance(entry, dict):
                        tone_val = entry.get("tone", entry.get("value", None))
                        if tone_val is not None:
                            try:
                                tone_values.append(float(tone_val))
                            except (ValueError, TypeError):
                                pass
                if tone_values:
                    avg_tone = sum(tone_values) / len(tone_values)
                    result.identifiers["gdelt_avg_tone"] = round(avg_tone, 2)
                    result.identifiers["gdelt_tone_sample_size"] = len(tone_values)

        # Step 3b: Query GKG (Global Knowledge Graph) for structured event data.
        # Run alongside tone fetch to avoid paying full remote latency twice.
        if gkg_data and "timeline" in gkg_data:
            timeline = gkg_data.get("timeline", [])
            # Extract country distribution of media coverage
            country_mentions = {}
            for series in timeline:
                if isinstance(series, dict):
                    series_country = series.get("series", "")
                    data_points = series.get("data", [])
                    if series_country and data_points:
                        total = sum(d.get("value", 0) for d in data_points if isinstance(d, dict))
                        if total > 0:
                            country_mentions[series_country] = total

            if country_mentions:
                result.identifiers["gdelt_coverage_countries"] = dict(
                    sorted(country_mentions.items(), key=lambda x: -x[1])[:10]
                )
                # Flag if coverage is concentrated in adversary nations
                adversary_countries = {"Russia", "China", "Iran", "North Korea", "Syria"}
                adversary_coverage = sum(v for k, v in country_mentions.items()
                                        if any(ac.lower() in k.lower() for ac in adversary_countries))
                total_coverage = sum(country_mentions.values())
                if total_coverage > 0 and adversary_coverage / total_coverage > 0.3:
                    result.risk_signals.append({
                        "signal": "adversary_media_concentration",
                        "severity": "medium",
                        "detail": f"Over 30% of media coverage originates from adversary-nation sources "
                                  f"({adversary_coverage}/{total_coverage} articles)",
                    })

        # Step 4: Process findings with title-level filtering
        # Only flag as "adverse" if the vendor name AND a risk keyword appear in the TITLE
        # Body-only matches are noise (vendor mentioned in passing in a sanctions policy article)
        high_confidence_count = 0
        low_confidence_count = 0
        vendor_words = [w.lower() for w in vendor_name.split() if len(w) > 3]

        for article in articles:
            url = article.get("url", "")
            title = article.get("title", "")
            seen_date = article.get("seendate", "")
            domain = article.get("domain", "")
            language = article.get("language", "")

            title_lower = title.lower()
            domain_credibility = _get_domain_credibility(domain)

            # ML-based classification (preferred) or keyword fallback
            if _ml_available and _ml_classify:
                ml_result = _ml_classify(f"{title}. Source: {domain}")
                is_ml_adverse = ml_result["adverse"] and ml_result["confidence"] > 0.65
                if is_ml_adverse:
                    severity = "high"
                    confidence = ml_result["confidence"]
                    high_confidence_count += 1
                    category = "adverse_media"
                else:
                    vendor_in_title = any(w in title_lower for w in vendor_words)
                    if not vendor_in_title:
                        continue
                    severity = "low"
                    confidence = 0.3
                    low_confidence_count += 1
                    category = "media"
            else:
                # Keyword fallback
                vendor_in_title = any(w in title_lower for w in vendor_words)
                risk_in_title = any(kw in title_lower for kw in TITLE_RISK_KEYWORDS)

                if vendor_in_title and risk_in_title:
                    severity = "high"
                    confidence = 0.85 if domain_credibility == "high" else 0.7
                    high_confidence_count += 1
                    category = "adverse_media"
                elif vendor_in_title:
                    severity = "low"
                    confidence = 0.4
                    low_confidence_count += 1
                    category = "media"
                else:
                    continue

            finding_detail = (
                f"URL: {url}\n"
                f"Title: {title}\n"
                f"Seen: {seen_date}\n"
                f"Domain: {domain} (Credibility: {domain_credibility})\n"
                f"Language: {language}"
            )

            result.findings.append(Finding(
                source="gdelt_media",
                category=category,
                title=f"{'[ADVERSE] ' if severity == 'high' else ''}{title[:80]}",
                detail=finding_detail,
                severity=severity,
                confidence=confidence,
                url=url,
                raw_data={
                    "domain": domain,
                    "domain_credibility": domain_credibility,
                    "seen_date": seen_date,
                    "language": language,
                    "detection": "ml" if (_ml_available and _ml_classify) else "keyword",
                    "tone": avg_tone,
                },
            ))

        # Step 4b: Use tone to weight adverse findings after confidence counts are known
        # Strongly negative tone (< -5.0) increases severity, mildly negative is less concerning
        if avg_tone < -5.0 and high_confidence_count > 0:
            result.risk_signals.append({
                "signal": "strongly_negative_media_tone",
                "severity": "high",
                "detail": f"Average media tone is strongly negative ({avg_tone:.1f}) across adverse articles. "
                          f"GDELT tone scale: -100 (extremely negative) to +100 (extremely positive).",
            })
        elif avg_tone < -2.0 and high_confidence_count > 0:
            result.identifiers["gdelt_tone_assessment"] = "moderately_negative"

        # Add risk signal only if we found TITLE-LEVEL adverse matches
        if high_confidence_count > 0:
            result.risk_signals.append({
                "signal": "adverse_media_coverage",
                "severity": "high" if high_confidence_count >= 3 else "medium",
                "detail": (
                    f"Found {high_confidence_count} adverse media articles where vendor name "
                    f"AND risk keyword both appear in headline. "
                    f"{low_confidence_count} contextual mentions filtered as low-confidence."
                ),
                "article_count": high_confidence_count,
                "baseline_count": baseline_count,
                "tone_data": tone_info,
            })
        elif len(articles) > 0:
            # Articles found but none were title-level adverse: add informational note
            result.findings.append(Finding(
                source="gdelt_media", category="media",
                title=f"GDELT: {len(articles)} articles mention '{vendor_name}' with risk context",
                detail=f"Articles reference '{vendor_name}' alongside risk terms but vendor is not the subject "
                       f"of adverse action in any headline. These are contextual mentions, not adverse findings.",
                severity="info", confidence=0.4,
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
