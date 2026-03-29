"""Live OpenSSF Scorecard connector for source repositories."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from . import EnrichmentResult, Finding
from .package_inventory import github_slug_from_url, normalize_repository_urls


SOURCE_NAME = "openssf_scorecard"
BASE_URL = "https://api.scorecard.dev/projects/github.com"
USER_AGENT = "Xiphos-Vetting/2.1"


def _get_json(url: str) -> dict | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    started = time.perf_counter()
    result = EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        source_class="public_connector",
        authority_level="third_party_public",
        access_model="public_api",
    )
    repository_urls = normalize_repository_urls(ids)
    github_repos = []
    for url in repository_urls:
        slug = github_slug_from_url(url)
        if slug:
            github_repos.append((url, slug))
    if not github_repos:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    repo_scores: list[dict[str, object]] = []
    low_repo_count = 0
    for url, slug in github_repos[:10]:
        payload = _get_json(f"{BASE_URL}/{slug}")
        if not isinstance(payload, dict):
            continue
        score = payload.get("score")
        try:
            numeric_score = float(score) if score is not None else None
        except (TypeError, ValueError):
            numeric_score = None
        if numeric_score is not None and numeric_score < 7.0:
            low_repo_count += 1
        repo_scores.append(
            {
                "repository_url": url,
                "score": numeric_score,
                "date": str(payload.get("date") or ""),
                "critical_checks": [
                    str((check or {}).get("name") or "")
                    for check in (payload.get("checks") or [])
                    if isinstance(check, dict)
                    and float((check or {}).get("score") or 0) < 5.0
                ][:4],
            }
        )

    if repo_scores:
        average = sum(float(item["score"]) for item in repo_scores if isinstance(item.get("score"), (int, float))) / max(
            1, sum(1 for item in repo_scores if isinstance(item.get("score"), (int, float)))
        )
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="supply_chain_assurance",
                title="OpenSSF Scorecard repository posture captured",
                detail=(
                    f"Scorecard reviewed {len(repo_scores)} GitHub repos with an average score of {average:.1f}. "
                    f"{low_repo_count} repos fell below the 7.0 hygiene floor."
                ),
                severity="medium" if low_repo_count else "info",
                confidence=0.84,
                url="https://api.scorecard.dev/",
                raw_data={"repo_scores": repo_scores},
                structured_fields={
                    "summary": {
                        "repository_count": len(repo_scores),
                        "scorecard_average": round(average, 2),
                        "scorecard_low_repo_count": low_repo_count,
                        "scorecard_repo_scores": repo_scores,
                    }
                },
                source_class="public_connector",
                authority_level="third_party_public",
                access_model="public_api",
            )
        )
        if low_repo_count:
            result.risk_signals.append(
                {
                    "signal": "scorecard_repository_hygiene_gap",
                    "source": SOURCE_NAME,
                    "severity": "medium",
                    "confidence": 0.84,
                    "summary": f"{low_repo_count} repositories scored below the Scorecard hygiene floor",
                }
            )
        result.structured_fields = {
            "summary": {
                "repository_count": len(repo_scores),
                "scorecard_average": round(average, 2),
                "scorecard_low_repo_count": low_repo_count,
                "scorecard_repo_scores": repo_scores,
            }
        }
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
