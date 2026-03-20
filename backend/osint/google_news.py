"""
Google News RSS Connector

Free RSS feed, no auth required.
Fetches recent news articles about a vendor from Google News.
Complements GDELT with more consumer-facing coverage.

Source: https://news.google.com/rss
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote
from . import EnrichmentResult, Finding

TIMEOUT = 10

# Try to load ML classifier (graceful fallback to keyword matching if unavailable)
_ml_available = False
_ml_classify = None
try:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from ml.inference import is_model_available, classify_finding
    if is_model_available():
        _ml_available = True
        _ml_classify = classify_finding
except Exception:
    pass


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    result = EnrichmentResult(source="google_news", vendor_name=vendor_name)
    start = datetime.now()

    try:
        encoded = quote(f'"{vendor_name}"')
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Xiphos/5.0"})
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        items = root.findall(".//item")

        # Keyword fallback: only used when ML model is not available
        adverse_kw = {"sanction", "sanctioned", "fraud", "lawsuit", "indictment", "indicted",
                      "penalty", "scandal", "bankruptcy", "subpoena", "convicted", "debarred",
                      "money laundering", "bribery", "corruption", "embezzlement", "insider trading"}
        vendor_words = [w.lower() for w in vendor_name.split() if len(w) >= 3]

        article_count = 0
        adverse_count = 0

        for item in items[:15]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            source_name = item.findtext("source", "")

            if not title:
                continue

            # ML-based classification (preferred) or keyword fallback
            if _ml_available and _ml_classify:
                ml_result = _ml_classify(f"{title}. Source: {source_name}")
                is_adverse = ml_result["adverse"] and ml_result["confidence"] > 0.65
                detection_method = "ml"
                ml_confidence = ml_result["confidence"]
            else:
                title_lower = title.lower()
                vendor_in_title = any(vw in title_lower for vw in vendor_words)
                has_adverse_kw = any(kw in title_lower for kw in adverse_kw)
                is_adverse = has_adverse_kw and vendor_in_title
                detection_method = "keyword"
                ml_confidence = 0.50 if is_adverse else 0.30

            if is_adverse:
                adverse_count += 1

            severity = "medium" if is_adverse else "info"
            article_count += 1

            result.findings.append(Finding(
                source="google_news", category="adverse_media" if is_adverse else "media",
                title=f"{'[ADVERSE] ' if is_adverse else ''}{title[:80]}",
                detail=f"Source: {source_name} | Published: {pub_date} | Detection: {detection_method}\nURL: {link}",
                severity=severity,
                confidence=ml_confidence if detection_method == "ml" else (0.50 if is_adverse else 0.30),
                url=link,
            ))

        result.identifiers["news_article_count"] = article_count
        result.identifiers["adverse_article_count"] = adverse_count

        if adverse_count > 0:
            result.risk_signals.append({
                "signal": "adverse_news_coverage",
                "severity": "high" if adverse_count >= 3 else "medium",
                "detail": f"{adverse_count} adverse news articles found for '{vendor_name}'",
            })

        if article_count == 0:
            result.findings.append(Finding(
                source="google_news", category="media",
                title=f"Google News: No recent articles found for '{vendor_name}'",
                detail="No news coverage found. Entity may be private, recently renamed, or low-profile.",
                severity="info", confidence=0.3,
            ))

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
    return result
