"""Live OSV.dev connector for declared OSS package inventories."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from . import EnrichmentResult, Finding
from .package_inventory import normalize_package_inventory


SOURCE_NAME = "osv_dev"
QUERY_BATCH_URL = "https://api.osv.dev/v1/querybatch"
USER_AGENT = "Xiphos-Vetting/2.1"


def _post_json(url: str, payload: dict) -> dict | None:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
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
    package_inventory = normalize_package_inventory(ids)
    if not package_inventory:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    queries = []
    for package in package_inventory[:20]:
        query: dict[str, object] = {}
        if package.get("purl"):
            query["package"] = {"purl": package["purl"]}
        else:
            query["package"] = {
                "ecosystem": package["ecosystem"],
                "name": package["name"],
            }
            if package.get("version"):
                query["version"] = package["version"]
        queries.append(query)

    payload = _post_json(QUERY_BATCH_URL, {"queries": queries})
    if not isinstance(payload, dict):
        result.error = "Unable to query OSV.dev"
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    vulns_by_package: dict[str, list[str]] = {}
    advisory_ids: list[str] = []
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    for package, package_result in zip(package_inventory, results):
        vulns = package_result.get("vulns") if isinstance(package_result, dict) else []
        if not isinstance(vulns, list) or not vulns:
            continue
        package_key = f"{package['ecosystem']}:{package['name']}" + (f"@{package['version']}" if package.get("version") else "")
        ids_for_package: list[str] = []
        for vuln in vulns:
            vuln_id = str((vuln or {}).get("id") or "").strip()
            if vuln_id:
                ids_for_package.append(vuln_id)
                if vuln_id not in advisory_ids:
                    advisory_ids.append(vuln_id)
        if ids_for_package:
            vulns_by_package[package_key] = ids_for_package

    if advisory_ids:
        result.findings.append(
            Finding(
                source=SOURCE_NAME,
                category="supply_chain_assurance",
                title=f"OSV package vulnerabilities surfaced: {len(advisory_ids)} advisories",
                detail=(
                    f"OSV.dev returned advisories for {len(vulns_by_package)} declared package"
                    f"{'s' if len(vulns_by_package) != 1 else ''}: "
                    + "; ".join(
                        f"{package} -> {', '.join(vuln_ids[:4])}"
                        for package, vuln_ids in list(vulns_by_package.items())[:4]
                    )
                ),
                severity="high" if len(advisory_ids) >= 3 else "medium",
                confidence=0.9,
                url=QUERY_BATCH_URL,
                raw_data={"advisory_ids": advisory_ids, "package_count": len(package_inventory)},
                structured_fields={
                    "summary": {
                        "package_inventory_present": True,
                        "package_inventory_count": len(package_inventory),
                        "osv_vulnerability_count": len(advisory_ids),
                        "osv_advisory_ids": advisory_ids,
                        "osv_vulnerable_packages": list(vulns_by_package.keys()),
                    }
                },
                source_class="public_connector",
                authority_level="third_party_public",
                access_model="public_api",
            )
        )
        result.risk_signals.append(
            {
                "signal": "osv_package_vulnerabilities",
                "source": SOURCE_NAME,
                "severity": "high" if len(advisory_ids) >= 3 else "medium",
                "confidence": 0.9,
                "summary": f"{len(advisory_ids)} OSV advisories surfaced across {len(vulns_by_package)} declared packages",
            }
        )

    result.structured_fields = {
        "summary": {
            "package_inventory_present": True,
            "package_inventory_count": len(package_inventory),
            "osv_vulnerability_count": len(advisory_ids),
            "osv_advisory_ids": advisory_ids,
            "osv_vulnerable_packages": list(vulns_by_package.keys()),
        }
    }
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result

