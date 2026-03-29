"""Shared threat-intel summary layer built from enrichment connector outputs."""

from __future__ import annotations

from typing import Any


def _summary_from_connector(report: dict[str, Any] | None, connector_name: str) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    connector_status = report.get("connector_status")
    if not isinstance(connector_status, dict):
        return {}
    status = connector_status.get(connector_name)
    if not isinstance(status, dict):
        return {}
    structured_fields = status.get("structured_fields")
    if not isinstance(structured_fields, dict):
        return {}
    summary = structured_fields.get("summary")
    return dict(summary) if isinstance(summary, dict) else {}


def _dedupe_text_list(values: list[Any]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def build_threat_intel_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    attack = _summary_from_connector(report, "mitre_attack_fixture")
    cisa = _summary_from_connector(report, "cisa_advisory_fixture")
    if not attack and not cisa:
        return None

    attack_technique_ids = _dedupe_text_list(
        list(attack.get("technique_ids") or [])
        + list(cisa.get("technique_ids") or [])
    )
    attack_techniques = []
    for item in list(attack.get("techniques") or []):
        if not isinstance(item, dict):
            continue
        technique_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        tactic = str(item.get("tactic") or "").strip()
        if technique_id or name or tactic:
            attack_techniques.append(
                {
                    "id": technique_id,
                    "name": name,
                    "tactic": tactic,
                }
            )

    actor_families = _dedupe_text_list(list(attack.get("actor_families") or []))
    campaigns = _dedupe_text_list(list(attack.get("campaigns") or []))
    tactics = _dedupe_text_list(list(attack.get("tactics") or []))
    advisory_ids = _dedupe_text_list(list(cisa.get("advisory_ids") or []))
    advisory_titles = _dedupe_text_list(list(cisa.get("advisory_titles") or []))
    sectors = _dedupe_text_list(list(cisa.get("sectors") or []))
    mitigation_focus = _dedupe_text_list(list(cisa.get("mitigations") or []))
    ioc_types = _dedupe_text_list(list(cisa.get("ioc_types") or []))

    threat_pressure = "low"
    if len(advisory_ids) >= 2 or len(attack_technique_ids) >= 4:
        threat_pressure = "high"
    elif advisory_ids or attack_technique_ids:
        threat_pressure = "medium"

    return {
        "shared_threat_intel_present": True,
        "attack_actor_families": actor_families,
        "attack_campaigns": campaigns,
        "attack_technique_ids": attack_technique_ids,
        "attack_techniques": attack_techniques,
        "attack_tactics": tactics,
        "cisa_advisory_ids": advisory_ids,
        "cisa_advisory_titles": advisory_titles,
        "threat_sectors": sectors,
        "mitigation_focus": mitigation_focus,
        "ioc_types": ioc_types,
        "threat_intel_sources": [
            source
            for source, summary in (
                ("mitre_attack_fixture", attack),
                ("cisa_advisory_fixture", cisa),
            )
            if summary
        ],
        "threat_pressure": threat_pressure,
    }
