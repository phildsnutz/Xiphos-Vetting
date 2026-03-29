"""Live deps.dev connector for declared OSS package inventories."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import EnrichmentResult, Finding
from .package_inventory import normalize_package_inventory


SOURCE_NAME = "deps_dev"
BASE_URL = "https://api.deps.dev/v3"
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


def _version_url(package: dict[str, str]) -> str:
    encoded_name = urllib.parse.quote(package["name"], safe="")
    encoded_version = urllib.parse.quote(package["version"], safe="")
    return f"{BASE_URL}/systems/{package['system']}/packages/{encoded_name}/versions/{encoded_version}"


def _repo_url_from_project_id(project_id: str) -> str:
    text = str(project_id or "").strip()
    if not text:
        return ""
    if text.startswith(("github.com/", "gitlab.com/", "bitbucket.org/")):
        return f"https://{text}"
    return ""


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    started = time.perf_counter()
    result = EnrichmentResult(
        source=SOURCE_NAME,
        vendor_name=vendor_name,
        source_class="public_connector",
        authority_level="third_party_public",
        access_model="public_api",
    )
    package_inventory = [package for package in normalize_package_inventory(ids) if package.get("version")]
    if not package_inventory:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    advisory_ids: list[str] = []
    repository_urls: list[str] = []
    verified_attestations = 0
    slsa_verified = 0
    packages_with_advisories: list[str] = []

    for package in package_inventory[:12]:
        payload = _get_json(_version_url(package))
        if not isinstance(payload, dict):
            continue

        package_key = f"{package['system']}:{package['name']}@{package['version']}"
        advisory_keys = payload.get("advisoryKeys") if isinstance(payload.get("advisoryKeys"), list) else []
        package_advisory_ids = []
        for advisory in advisory_keys:
            advisory_id = str((advisory or {}).get("id") or "").strip()
            if not advisory_id:
                continue
            package_advisory_ids.append(advisory_id)
            if advisory_id not in advisory_ids:
                advisory_ids.append(advisory_id)
        if package_advisory_ids:
            packages_with_advisories.append(package_key)

        for project in payload.get("relatedProjects") or []:
            project_id = str(((project or {}).get("projectKey") or {}).get("id") or "").strip()
            repo_url = _repo_url_from_project_id(project_id)
            if repo_url and repo_url not in repository_urls:
                repository_urls.append(repo_url)

        for link in payload.get("links") or []:
            label = str((link or {}).get("label") or "").strip().lower()
            url = str((link or {}).get("url") or "").strip()
            if label in {"source", "repository", "repo", "source code"} and url and url not in repository_urls:
                repository_urls.append(url)

        attestations = payload.get("attestations") if isinstance(payload.get("attestations"), list) else []
        slsa_entries = payload.get("slsaProvenances") if isinstance(payload.get("slsaProvenances"), list) else []
        verified_attestations += sum(1 for att in attestations if bool((att or {}).get("verified")))
        slsa_verified += sum(1 for att in slsa_entries if bool((att or {}).get("verified")))

    if repository_urls:
        result.identifiers["repository_urls"] = repository_urls

    if advisory_ids or repository_urls or verified_attestations or slsa_verified:
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="supply_chain_assurance",
                title="deps.dev package assurance metadata captured",
                detail=(
                    f"deps.dev resolved {len(package_inventory)} package versions, surfaced {len(advisory_ids)} advisory reference"
                    f"{'s' if len(advisory_ids) != 1 else ''}, and mapped {len(repository_urls)} related source repositories."
                ),
                severity="medium" if advisory_ids else "info",
                confidence=0.86,
                url="https://docs.deps.dev/api/v3/",
                raw_data={
                    "advisory_ids": advisory_ids,
                    "repository_urls": repository_urls,
                    "verified_attestations": verified_attestations,
                    "slsa_verified": slsa_verified,
                },
                structured_fields={
                    "summary": {
                        "package_inventory_present": True,
                        "package_inventory_count": len(package_inventory),
                        "deps_dev_advisory_count": len(advisory_ids),
                        "deps_dev_advisory_ids": advisory_ids,
                        "deps_dev_related_repositories": repository_urls,
                        "deps_dev_packages_with_advisories": packages_with_advisories,
                        "deps_dev_verified_attestations": verified_attestations,
                        "deps_dev_verified_slsa_provenances": slsa_verified,
                    }
                },
                source_class="public_connector",
                authority_level="third_party_public",
                access_model="public_api",
            )
        )
        if advisory_ids:
            result.risk_signals.append(
                {
                    "signal": "deps_dev_advisory_pressure",
                    "source": SOURCE_NAME,
                    "severity": "medium",
                    "confidence": 0.86,
                    "summary": f"{len(advisory_ids)} package advisories mapped through deps.dev",
                }
            )

    result.structured_fields = {
        "summary": {
            "package_inventory_present": True,
            "package_inventory_count": len(package_inventory),
            "deps_dev_advisory_count": len(advisory_ids),
            "deps_dev_advisory_ids": advisory_ids,
            "deps_dev_related_repositories": repository_urls,
            "deps_dev_packages_with_advisories": packages_with_advisories,
            "deps_dev_verified_attestations": verified_attestations,
            "deps_dev_verified_slsa_provenances": slsa_verified,
        }
    }
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result

