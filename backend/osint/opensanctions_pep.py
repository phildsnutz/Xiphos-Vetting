"""
OpenSanctions PEP (Politically Exposed Persons) Screening

OpenSanctions publishes bulk JSONL data that is ingested via sanctions_sync.py.
This connector provides two modes:
  1. Live API search (free tier, requires XIPHOS_OPENSANCTIONS_KEY env var)
     GET https://api.opensanctions.org/search/default?q={name}&schema=Person
  2. Fallback: local sanctions.db lookup for source="opensanctions" entities

Returns entities with: id, caption, schema, properties (name, country, position, topics)
Risk signals identified via topics array: "role.pep", "sanction", "crime"
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional
import os
import sqlite3

from . import EnrichmentResult, Finding

OPENSANCTIONS_API_URL = "https://api.opensanctions.org/search/default"
USER_AGENT = "Xiphos-Vetting/2.1"


def _get_api_key() -> Optional[str]:
    """Retrieve OpenSanctions API key from environment."""
    return os.environ.get("XIPHOS_OPENSANCTIONS_KEY")


def _search_api(name: str, api_key: str) -> list[dict]:
    """Query the OpenSanctions live search API."""
    params = urllib.parse.urlencode({
        "q": name,
        "schema": "Person"
    })
    url = f"{OPENSANCTIONS_API_URL}?{params}"
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {api_key}"
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")
            result = json.loads(data)
            return result.get("results", [])
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return []


def _fallback_local_search(name: str) -> list[dict]:
    """
    Fallback: search local sanctions.db for OpenSanctions entities.
    This uses the database populated by sanctions_sync.py
    """
    db_path = "/data/sanctions.db"
    if not os.path.exists(db_path):
        return []

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Search by entity name, limiting to opensanctions source
        # Exact match or LIKE match
        cursor.execute(
            """
            SELECT * FROM entities
            WHERE source = 'opensanctions'
              AND (name = ? OR name LIKE ?)
            LIMIT 20
            """,
            (name, f"%{name}%")
        )
        rows = cursor.fetchall()
        conn.close()

        results = []
        for row in rows:
            results.append(dict(row))
        return results
    except Exception:
        return []


def _extract_pep_risk(entity: dict) -> tuple[bool, str]:
    """
    Determine if entity is a PEP and assess severity.
    Looks for 'role.pep' in topics array.
    Returns: (is_pep, severity)
    """
    topics = entity.get("topics", [])
    if isinstance(topics, str):
        topics = topics.split(";")

    # Check for PEP topic
    is_pep = any("pep" in str(t).lower() for t in topics)

    if not is_pep:
        return False, "info"

    # Assess severity: "current" position = high, former = medium
    properties = entity.get("properties", {})
    position = properties.get("position", "")

    # Simple heuristic: if position contains "former" or "retired", medium severity
    if isinstance(position, str) and any(x in position.lower() for x in ["former", "retired", "ex-"]):
        return True, "medium"

    return True, "high"


def _extract_other_risks(entity: dict) -> list[str]:
    """Extract sanction and crime topics."""
    topics = entity.get("topics", [])
    if isinstance(topics, str):
        topics = topics.split(";")

    risks = []
    for t in topics:
        t_lower = str(t).lower()
        if "sanction" in t_lower:
            risks.append("sanction")
        elif "crime" in t_lower or "wanted" in t_lower:
            risks.append("crime")

    return list(set(risks))


def enrich(vendor_name: str, country: str = "", **ids) -> EnrichmentResult:
    """Screen a vendor against OpenSanctions PEP database."""
    t0 = time.time()
    result = EnrichmentResult(source="opensanctions_pep", vendor_name=vendor_name)

    entities = []

    # Try API first
    api_key = _get_api_key()
    if api_key:
        entities = _search_api(vendor_name, api_key)

    # Fall back to local database
    if not entities:
        entities = _fallback_local_search(vendor_name)

    if not entities:
        result.findings.append(Finding(
            source="opensanctions_pep", category="pep_screening",
            title="OpenSanctions PEP clear",
            detail=f"No PEP or sanctions matches found for '{vendor_name}'.",
            severity="info", confidence=0.85,
        ))
    else:
        for entity in entities:
            entity_id = entity.get("id", "unknown")
            caption = entity.get("caption", vendor_name)

            # Store identifier
            if entity_id and entity_id != "unknown":
                result.identifiers["opensanctions_id"] = entity_id

            # Check PEP status
            is_pep, pep_severity = _extract_pep_risk(entity)
            other_risks = _extract_other_risks(entity)

            if is_pep or other_risks:
                # There is risk
                risk_detail_parts = []
                if is_pep:
                    risk_detail_parts.append(f"PEP Status (severity: {pep_severity})")
                if other_risks:
                    risk_detail_parts.append(f"Additional risks: {', '.join(other_risks)}")

                finding_severity = pep_severity
                if "sanction" in other_risks:
                    finding_severity = "critical"

                result.findings.append(Finding(
                    source="opensanctions_pep", category="pep_screening",
                    title=f"OpenSanctions Match: {caption} [{entity_id}]",
                    detail=" | ".join(risk_detail_parts),
                    severity=finding_severity,
                    confidence=0.9,
                    url=f"https://opensanctions.org/entities/{entity_id}/",
                    raw_data=entity,
                ))

                if is_pep:
                    result.risk_signals.append({
                        "signal": "pep_match",
                        "severity": pep_severity,
                        "detail": f"Entity '{caption}' is a politically exposed person.",
                    })

                for risk in other_risks:
                    result.risk_signals.append({
                        "signal": f"opensanctions_{risk}",
                        "severity": "critical" if risk == "sanction" else "high",
                        "detail": f"Entity '{caption}' has '{risk}' topic in OpenSanctions.",
                    })
            else:
                # Entity found but no risks
                result.findings.append(Finding(
                    source="opensanctions_pep", category="pep_screening",
                    title=f"OpenSanctions Entity (clean): {caption} [{entity_id}]",
                    detail="Entity found in OpenSanctions but no PEP, sanction, or crime topics detected.",
                    severity="info",
                    confidence=0.85,
                    raw_data=entity,
                ))

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
