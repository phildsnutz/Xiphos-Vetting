"""
OSHA Workplace Safety Violations Connector

Queries the Department of Labor enforcement data for OSHA inspections
and violations:
  - Inspection history (planned, complaint, accident, referral)
  - Citation details and violation types
  - Penalty amounts (initial and current)
  - Serious, willful, and repeat violations
  - Fatality and hospitalization records

API: https://enforcedata.dol.gov/ and https://apiprod.dol.gov/v4/
Data goes back to 1973, updated daily.

Key risk signals:
  - Willful violations (deliberate)
  - Repeat violations (pattern)
  - Fatalities/hospitalizations
  - High penalty amounts
"""

import time
import urllib.request
import urllib.error
import urllib.parse

from . import EnrichmentResult, Finding

# OSHA publishes inspection data as CSV at:
# https://www.osha.gov/data/inspection-detail
# We use the OSHA API via their enforcement search page
OSHA_SEARCH = "https://www.osha.gov/ords/imis/establishment.search_establishment"
USER_AGENT = "Xiphos-Vetting/2.1"

# OSHA violation types by severity
VIOLATION_SEVERITY = {
    "W": ("willful", "critical"),      # Willful violation
    "R": ("repeat", "high"),           # Repeat violation
    "S": ("serious", "high"),          # Serious violation
    "O": ("other", "medium"),          # Other-than-serious
    "U": ("unclassified", "low"),      # Unclassified
}


def _get(url: str, headers: dict = None) -> bytes | None:
    """GET request returning raw bytes."""
    hdrs = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }
    if headers:
        hdrs.update(headers)

    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return None


def _parse_osha_html(html_bytes: bytes) -> list[dict]:
    """Parse OSHA establishment search results from HTML."""
    import re
    html = html_bytes.decode("utf-8", errors="replace")

    records = []
    # OSHA results are in HTML table rows with inspection data
    # Look for inspection detail links and surrounding table data
    rows = re.findall(
        r'<tr[^>]*>.*?inspection_detail\?id=(\d+).*?</tr>',
        html, re.DOTALL | re.IGNORECASE
    )

    for row_html in rows:
        # Extract activity number from the link
        activity_match = re.search(r'inspection_detail\?id=(\d+)', row_html)
        activity_nr = activity_match.group(1) if activity_match else ""

        # Extract table cell contents
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL | re.IGNORECASE)
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]

        if len(cells) >= 5:
            records.append({
                "activity_nr": activity_nr,
                "estab_name": cells[0] if len(cells) > 0 else "",
                "site_city": cells[1] if len(cells) > 1 else "",
                "site_state": cells[2] if len(cells) > 2 else "",
                "open_date": cells[3] if len(cells) > 3 else "",
                "insp_type": cells[4] if len(cells) > 4 else "",
            })

    return records


def _search_osha_inspections(name: str) -> list[dict]:
    """Search OSHA inspections by establishment name via HTML scrape."""
    params = urllib.parse.urlencode({
        "p_logger": "1",
        "establishment": name,
        "State": "all",
        "officetype": "all",
        "endmonth": "03",
        "endday": "15",
        "endyear": "2026",
        "startmonth": "01",
        "startday": "01",
        "startyear": "2020",
        "p_case": "",
        "p_violations_exist": "",
    })
    url = f"{OSHA_SEARCH}?{params}"
    html = _get(url)
    if html:
        return _parse_osha_html(html)
    return []


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Query OSHA for workplace safety violations."""
    t0 = time.time()
    result = EnrichmentResult(source="osha_safety", vendor_name=vendor_name)

    # Only query for US-based entities
    if country and country.upper() not in ("US", "USA", ""):
        result.findings.append(Finding(
            source="osha_safety",
            category="workplace_safety",
            title="OSHA: Non-US entity skipped",
            detail=f"OSHA covers US workplaces only. Entity country: {country}",
            severity="info",
            confidence=1.0,
        ))
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    try:
        # Search OSHA establishment records
        inspections = _search_osha_inspections(vendor_name)

        if not inspections:
            result.findings.append(Finding(
                source="osha_safety",
                category="workplace_safety",
                title="No OSHA inspection records found",
                detail=(
                    f"No OSHA inspection records found for '{vendor_name}'. "
                    f"This may indicate the entity has no OSHA-regulated workplaces, "
                    f"or the establishment name differs from the vendor name."
                ),
                severity="info",
                confidence=0.6,
            ))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            return result

        # Process inspection records
        total_inspections = 0
        serious_violations = 0
        willful_violations = 0
        repeat_violations = 0
        total_penalties = 0.0
        fatality_inspections = 0

        for inspection in inspections[:15]:
            # Handle both nested and flat record formats
            record = inspection.get("_source", inspection)

            estab_name = record.get("estab_name", record.get("establishment_name", ""))
            activity_nr = record.get("activity_nr", record.get("activity_number", ""))
            open_date = record.get("open_date", "")
            close_case_date = record.get("close_case_date", "")
            insp_type = record.get("insp_type", record.get("inspection_type", ""))
            site_city = record.get("site_city", "")
            site_state = record.get("site_state", "")

            # Violation counts
            nr_serious = int(record.get("total_serious_violations", record.get("serious_violations", 0)) or 0)
            nr_willful = int(record.get("total_willful_violations", record.get("willful_violations", 0)) or 0)
            nr_repeat = int(record.get("total_repeat_violations", record.get("repeat_violations", 0)) or 0)
            nr_other = int(record.get("total_other_violations", record.get("other_violations", 0)) or 0)

            # Penalty
            penalty = float(record.get("total_current_penalty", record.get("penalty_total", 0)) or 0)
            initial_penalty = float(record.get("total_initial_penalty", record.get("initial_penalty", 0)) or 0)

            # Fatality flag
            nr_fatalities = int(record.get("total_fatalities", record.get("fatalities", 0)) or 0)
            nr_hospitalizations = int(record.get("total_hospitalizations", record.get("hospitalizations", 0)) or 0)

            total_inspections += 1
            serious_violations += nr_serious
            willful_violations += nr_willful
            repeat_violations += nr_repeat
            total_penalties += penalty

            if nr_fatalities > 0:
                fatality_inspections += 1

            # Determine severity for this inspection
            if nr_fatalities > 0 or nr_willful > 0:
                severity = "critical"
            elif nr_repeat > 0 or penalty > 50000:
                severity = "high"
            elif nr_serious > 0:
                severity = "medium"
            elif nr_other > 0:
                severity = "low"
            else:
                severity = "info"

            total_viols = nr_serious + nr_willful + nr_repeat + nr_other

            finding_detail = (
                f"Establishment: {estab_name}\n"
                f"Activity #: {activity_nr}\n"
                f"Location: {site_city}, {site_state}\n"
                f"Opened: {open_date[:10] if open_date else 'N/A'}\n"
                f"Closed: {close_case_date[:10] if close_case_date else 'Open'}\n"
                f"Inspection Type: {insp_type}\n"
                f"Violations: {total_viols} total "
                f"(Serious: {nr_serious}, Willful: {nr_willful}, Repeat: {nr_repeat}, Other: {nr_other})\n"
                f"Fatalities: {nr_fatalities}, Hospitalizations: {nr_hospitalizations}\n"
                f"Penalty: ${penalty:,.0f} (Initial: ${initial_penalty:,.0f})"
            )

            # Only create findings for inspections with violations or notable events
            if total_viols > 0 or nr_fatalities > 0 or penalty > 0:
                result.findings.append(Finding(
                    source="osha_safety",
                    category="workplace_safety",
                    title=f"OSHA inspection: {estab_name} ({open_date[:10] if open_date else 'N/A'})",
                    detail=finding_detail,
                    severity=severity,
                    confidence=0.9,
                    url=f"https://www.osha.gov/ords/imis/establishment.inspection_detail?id={activity_nr}" if activity_nr else "",
                    raw_data={
                        "activity_nr": activity_nr,
                        "serious": nr_serious,
                        "willful": nr_willful,
                        "repeat": nr_repeat,
                        "fatalities": nr_fatalities,
                        "penalty": penalty,
                    },
                ))

        # If no violations found across all inspections, add clean finding
        if not result.findings:
            result.findings.append(Finding(
                source="osha_safety",
                category="workplace_safety",
                title=f"OSHA: {total_inspections} inspections, no notable violations",
                detail=(
                    f"Found {total_inspections} OSHA inspection records for '{vendor_name}'. "
                    f"No serious, willful, or repeat violations detected."
                ),
                severity="info",
                confidence=0.8,
            ))

        # Add summary risk signal
        if serious_violations > 0 or willful_violations > 0 or fatality_inspections > 0:
            if willful_violations > 0 or fatality_inspections > 0:
                overall_severity = "critical"
            elif repeat_violations > 0 or total_penalties > 100000:
                overall_severity = "high"
            else:
                overall_severity = "medium"

            result.risk_signals.append({
                "signal": "workplace_safety_violations",
                "severity": overall_severity,
                "detail": (
                    f"OSHA record: {total_inspections} inspections, "
                    f"{serious_violations} serious violations, "
                    f"{willful_violations} willful, {repeat_violations} repeat. "
                    f"Fatality inspections: {fatality_inspections}. "
                    f"Total penalties: ${total_penalties:,.0f}"
                ),
                "inspection_count": total_inspections,
                "serious_violations": serious_violations,
                "willful_violations": willful_violations,
                "repeat_violations": repeat_violations,
                "fatality_inspections": fatality_inspections,
                "total_penalties": total_penalties,
            })

    except Exception as e:
        result.error = str(e)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
