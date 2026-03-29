"""
EPA ECHO (Enforcement and Compliance History Online) Connector

Queries EPA ECHO REST services for environmental compliance data:
  - Clean Air Act violations
  - Clean Water Act violations
  - RCRA (hazardous waste) violations
  - Enforcement actions and penalties
  - Compliance status across 800,000+ regulated facilities

API: https://echo.epa.gov/tools/web-services
No authentication required. Free to use.
Output: JSON

Key risk signals:
  - Active violations (significant non-compliance)
  - Enforcement actions (formal/informal)
  - Penalty amounts
  - Quarters in non-compliance
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse

from . import EnrichmentResult, Finding

BASE = "https://echodata.epa.gov/echo"
USER_AGENT = "Xiphos-Vetting/2.1"


def _get(url: str) -> dict | None:
    """GET request to EPA ECHO API."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _search_facilities(name: str, state: str = "") -> list[dict]:
    """Search ECHO for facilities by name (two-step: get QID then fetch results)."""
    params = {
        "output": "JSON",
        "p_fn": name,
        "responseset": "10",
    }
    if state:
        params["p_st"] = state

    query = urllib.parse.urlencode(params)
    url = f"{BASE}/echo_rest_services.get_facilities?{query}"
    data = _get(url)

    if not data:
        return []

    results = data.get("Results", {})
    qid = results.get("QueryID", "")
    query_rows = int(results.get("QueryRows", "0") or "0")

    if not qid or query_rows == 0:
        return []

    # Step 2: Use QID to fetch actual facility records
    params2 = {
        "output": "JSON",
        "qid": qid,
        "responseset": "10",
    }
    query2 = urllib.parse.urlencode(params2)
    url2 = f"{BASE}/echo_rest_services.get_qid?{query2}"
    data2 = _get(url2)

    if not data2:
        return []

    return data2.get("Results", {}).get("Facilities", [])


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query EPA ECHO for environmental compliance data."""
    t0 = time.time()
    result = EnrichmentResult(source="epa_echo", vendor_name=vendor_name)

    # Only query for US-based entities (or unknown country)
    if country and country.upper() not in ("US", "USA", ""):
        result.findings.append(Finding(
            source="epa_echo",
            category="environmental_compliance",
            title="EPA ECHO: Non-US entity skipped",
            detail=f"EPA ECHO covers US-regulated facilities only. Entity country: {country}",
            severity="info",
            confidence=1.0,
        ))
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    try:
        # Step 1: Search for facilities (two-step QID approach)
        facilities = _search_facilities(vendor_name)

        if not facilities:
            result.findings.append(Finding(
                source="epa_echo",
                category="environmental_compliance",
                title="No EPA ECHO facilities found",
                detail=f"No EPA-regulated facilities matched '{vendor_name}'.",
                severity="info",
                confidence=0.7,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Step 2: Process each facility
        total_violations = 0
        total_penalties = 0.0
        critical_facilities = []

        for facility in facilities[:10]:  # Cap at 10 facilities
            fac_name = facility.get("FacName", "")
            registry_id = facility.get("RegistryID", "")
            fac_street = facility.get("FacStreet", "")
            fac_city = facility.get("FacCity", "")
            fac_state = facility.get("FacState", "")
            fac_zip = facility.get("FacZip", "")

            # Compliance status fields
            caa_status = facility.get("CAAComplianceStatus", "")
            cwa_status = facility.get("CWAComplianceStatus", "")
            rcra_status = facility.get("RCRAComplianceStatus", "")

            # Quarters in non-compliance (last 3 years = 12 quarters)
            caa_qtrs = facility.get("CAAQtrsInNC", "0") or "0"
            cwa_qtrs = facility.get("CWAQtrsInNC", "0") or "0"
            rcra_qtrs = facility.get("RCRAQtrsInNC", "0") or "0"

            # Inspection counts
            caa_inspections = facility.get("CAAInspectionCount", "0") or "0"
            cwa_inspections = facility.get("CWAInspectionCount", "0") or "0"
            rcra_inspections = facility.get("RCRAInspectionCount", "0") or "0"

            # Enforcement actions
            fea_count = facility.get("FEACaseCount", "0") or "0"

            # Penalties
            caa_penalties = facility.get("CAAPenalties", "0") or "0"
            cwa_penalties = facility.get("CWAPenalties", "0") or "0"
            rcra_penalties = facility.get("RCRAPenalties", "0") or "0"

            try:
                qtrs_nc = int(caa_qtrs) + int(cwa_qtrs) + int(rcra_qtrs)
                fea_cnt = int(fea_count)
                penalties = float(caa_penalties) + float(cwa_penalties) + float(rcra_penalties)
            except (ValueError, TypeError):
                qtrs_nc = 0
                fea_cnt = 0
                penalties = 0.0

            total_penalties += penalties

            # Determine severity for this facility
            has_snc = any(
                "Significant" in s or "SNC" in s.upper()
                for s in [caa_status, cwa_status, rcra_status]
                if s
            )

            if has_snc or penalties > 100000:
                severity = "high"
                total_violations += 1
                critical_facilities.append(fac_name)
            elif qtrs_nc > 4 or fea_cnt > 0:
                severity = "medium"
                total_violations += 1
            elif qtrs_nc > 0:
                severity = "low"
            else:
                severity = "info"

            # Build compliance summary
            statuses = []
            if caa_status:
                statuses.append(f"CAA: {caa_status}")
            if cwa_status:
                statuses.append(f"CWA: {cwa_status}")
            if rcra_status:
                statuses.append(f"RCRA: {rcra_status}")

            address = f"{fac_street}, {fac_city}, {fac_state} {fac_zip}".strip(", ")

            finding_detail = (
                f"Facility: {fac_name}\n"
                f"Registry ID: {registry_id}\n"
                f"Address: {address}\n"
                f"Compliance Status: {'; '.join(statuses) if statuses else 'No data'}\n"
                f"Quarters in Non-Compliance (3yr): CAA={caa_qtrs}, CWA={cwa_qtrs}, RCRA={rcra_qtrs}\n"
                f"Enforcement Actions: {fea_count}\n"
                f"Penalties: ${penalties:,.0f}\n"
                f"Inspections: CAA={caa_inspections}, CWA={cwa_inspections}, RCRA={rcra_inspections}"
            )

            echo_url = f"https://echo.epa.gov/detailed-facility-report?fid={registry_id}" if registry_id else ""

            result.findings.append(Finding(
                source="epa_echo",
                category="environmental_compliance",
                title=f"EPA facility: {fac_name} [{severity.upper()}]",
                detail=finding_detail,
                severity=severity,
                confidence=0.85,
                url=echo_url,
                raw_data={
                    "registry_id": registry_id,
                    "caa_status": caa_status,
                    "cwa_status": cwa_status,
                    "rcra_status": rcra_status,
                    "quarters_nc": qtrs_nc,
                    "enforcement_actions": fea_cnt,
                    "penalties": penalties,
                },
            ))

            # Store registry ID as identifier
            if registry_id:
                result.identifiers[f"epa_registry_{registry_id}"] = registry_id

        # Add summary risk signal
        if total_violations > 0 or total_penalties > 0:
            overall_severity = "high" if critical_facilities else "medium"
            result.risk_signals.append({
                "signal": "environmental_violations",
                "severity": overall_severity,
                "detail": (
                    f"Found {len(facilities)} EPA-regulated facilities. "
                    f"{total_violations} with compliance issues. "
                    f"Total penalties: ${total_penalties:,.0f}. "
                    f"Critical facilities: {', '.join(critical_facilities[:5]) if critical_facilities else 'None'}"
                ),
                "facility_count": len(facilities),
                "violation_count": total_violations,
                "total_penalties": total_penalties,
            })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
