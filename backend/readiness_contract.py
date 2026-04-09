from __future__ import annotations

from typing import Any


_SURFACE_STATUS_ORDER = {
    "ready": 0,
    "skipped": 1,
    "degraded": 2,
    "stale": 3,
    "failed": 4,
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _surface(status: str, **kwargs: Any) -> dict[str, Any]:
    payload = {"status": status}
    payload.update(kwargs)
    return payload


def _connector_errors(connector_status: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for source, status in connector_status.items():
        if not isinstance(status, dict):
            continue
        message = _clean_text(status.get("error"))
        if message:
            errors.append(f"{source}: {message}")
    return errors


def _surface_has_usable_data(surface: dict[str, Any]) -> bool:
    return any(
        _as_int(surface.get(field)) > 0
        for field in (
            "connectors_with_data",
            "official_connectors_with_data",
            "relationship_count",
            "control_path_count",
            "entities_found",
            "relationships_found",
            "connector_calls_with_data",
            "findings_total",
        )
    )


def build_enrichment_surface(enrichment: dict[str, Any] | None) -> dict[str, Any]:
    if enrichment is None:
        return _surface(
            "skipped",
            connectors_run=0,
            connectors_with_data=0,
            findings_total=0,
            errors=[],
        )

    payload = _as_dict(enrichment)
    if _clean_text(payload.get("error")):
        return _surface(
            "failed",
            connectors_run=0,
            connectors_with_data=0,
            findings_total=0,
            errors=[_clean_text(payload.get("error"))],
        )

    summary = _as_dict(payload.get("summary"))
    connector_status = _as_dict(payload.get("connector_status"))
    connectors_run = _as_int(summary.get("connectors_run")) or len(connector_status)
    connectors_with_data = _as_int(summary.get("connectors_with_data"))
    findings_total = _as_int(summary.get("findings_total")) or len(_as_list(payload.get("findings")))
    errors = [_clean_text(item) for item in _as_list(payload.get("errors")) if _clean_text(item)]
    errors.extend(error for error in _connector_errors(connector_status) if error not in errors)

    if connectors_run <= 0 and findings_total <= 0 and not errors:
        status = "skipped"
    elif connectors_with_data <= 0 and errors:
        status = "failed"
    elif connectors_with_data < 2 or errors:
        status = "degraded"
    else:
        status = "ready"

    return _surface(
        status,
        connectors_run=connectors_run,
        connectors_with_data=connectors_with_data,
        findings_total=findings_total,
        errors=errors[:6],
    )


def build_ownership_surface(support_bundle: dict[str, Any] | None) -> dict[str, Any]:
    if support_bundle is None:
        return _surface(
            "skipped",
            connectors_run=0,
            connectors_with_data=0,
            official_connectors_with_data=0,
            relationship_count=0,
            errors=[],
            gap_lines=[],
        )

    payload = _as_dict(support_bundle)
    if _clean_text(payload.get("error")):
        return _surface(
            "failed",
            connectors_run=0,
            connectors_with_data=0,
            official_connectors_with_data=0,
            relationship_count=0,
            errors=[_clean_text(payload.get("error"))],
            gap_lines=[],
        )

    metrics = _as_dict(payload.get("metrics"))
    connector_status = _as_dict(payload.get("connector_status"))
    connectors_run = _as_int(payload.get("connectors_run")) or len(connector_status)
    connectors_with_data = _as_int(payload.get("connectors_with_data"))
    official_connectors_with_data = _as_int(
        payload.get("official_connectors_with_data") or metrics.get("official_connectors_with_data")
    )
    relationship_count = _as_int(metrics.get("ownership_relationship_count"))
    if relationship_count <= 0:
        relationship_count = len(_as_list(payload.get("relationships")))
    errors = _connector_errors(connector_status)
    gap_lines = [_clean_text(item) for item in _as_list(payload.get("gap_lines")) if _clean_text(item)]

    if connectors_run <= 0 and relationship_count <= 0 and not errors:
        status = "skipped"
    elif connectors_with_data <= 0 and errors:
        status = "failed"
    elif (
        connectors_run >= 3
        and connectors_with_data >= 2
        and official_connectors_with_data > 0
        and relationship_count > 0
    ):
        status = "ready"
    else:
        status = "degraded"

    return _surface(
        status,
        connectors_run=connectors_run,
        connectors_with_data=connectors_with_data,
        official_connectors_with_data=official_connectors_with_data,
        relationship_count=relationship_count,
        errors=errors[:6],
        gap_lines=gap_lines[:6],
    )


def build_procurement_surface(support_bundle: dict[str, Any] | None) -> dict[str, Any]:
    if support_bundle is None:
        return _surface(
            "skipped",
            connectors_run=0,
            connectors_with_data=0,
            relationship_count=0,
            top_customer_count=0,
            prime_vehicle_count=0,
            errors=[],
        )

    payload = _as_dict(support_bundle)
    if _clean_text(payload.get("error")):
        return _surface(
            "failed",
            connectors_run=0,
            connectors_with_data=0,
            relationship_count=0,
            top_customer_count=0,
            prime_vehicle_count=0,
            errors=[_clean_text(payload.get("error"))],
        )

    connectors_run = _as_int(payload.get("connectors_run"))
    connectors_with_data = _as_int(payload.get("connectors_with_data"))
    relationship_count = len(_as_list(payload.get("relationships")))
    top_customer_count = len(_as_list(payload.get("top_customers")))
    prime_vehicle_count = len(_as_list(payload.get("prime_vehicles")))
    award_momentum = _as_dict(payload.get("award_momentum"))
    errors = [_clean_text(item) for item in _as_list(payload.get("errors")) if _clean_text(item)]

    if connectors_run <= 0 and relationship_count <= 0 and top_customer_count <= 0 and prime_vehicle_count <= 0:
        status = "skipped"
    elif connectors_with_data <= 0 and errors:
        status = "failed"
    elif connectors_with_data > 0 and (
        relationship_count > 0
        or top_customer_count > 0
        or prime_vehicle_count > 0
        or bool(award_momentum)
    ):
        status = "ready"
    else:
        status = "degraded"

    return _surface(
        status,
        connectors_run=connectors_run,
        connectors_with_data=connectors_with_data,
        relationship_count=relationship_count,
        top_customer_count=top_customer_count,
        prime_vehicle_count=prime_vehicle_count,
        errors=errors[:6],
    )


def build_graph_surface(graph_summary: dict[str, Any] | None) -> dict[str, Any]:
    if graph_summary is None:
        return _surface(
            "skipped",
            relationship_count=0,
            control_path_count=0,
            thin_graph=True,
            missing_required_edge_families=[],
            errors=[],
        )

    payload = _as_dict(graph_summary)
    if _clean_text(payload.get("error")):
        return _surface(
            "failed",
            relationship_count=0,
            control_path_count=0,
            thin_graph=True,
            missing_required_edge_families=[],
            errors=[_clean_text(payload.get("error"))],
        )

    intelligence = _as_dict(payload.get("intelligence"))
    relationship_count = _as_int(payload.get("relationship_count")) or len(_as_list(payload.get("relationships")))
    control_path_count = _as_int(intelligence.get("control_path_count"))
    thin_graph = bool(intelligence.get("thin_graph")) or relationship_count <= 0
    missing_required_edge_families = [
        _clean_text(item)
        for item in _as_list(intelligence.get("missing_required_edge_families"))
        if _clean_text(item)
    ]

    if relationship_count <= 0:
        status = "stale"
    elif not thin_graph and control_path_count > 0 and not missing_required_edge_families:
        status = "ready"
    else:
        status = "degraded"

    return _surface(
        status,
        relationship_count=relationship_count,
        control_path_count=control_path_count,
        thin_graph=thin_graph,
        missing_required_edge_families=missing_required_edge_families[:6],
        errors=[],
    )


def summarize_axiom_connector_accounting(agent_result: Any = None) -> dict[str, Any]:
    payload = agent_result.to_dict() if hasattr(agent_result, "to_dict") else _as_dict(agent_result)
    iterations = _as_list(payload.get("iterations"))
    connector_calls: list[dict[str, Any]] = []
    for iteration in iterations:
        if not isinstance(iteration, dict):
            continue
        connector_calls.extend(
            call for call in _as_list(iteration.get("connector_calls")) if isinstance(call, dict)
        )

    connector_calls_attempted = len(connector_calls)
    connector_calls_with_data = 0
    connector_calls_failed = 0
    connector_findings_returned = 0
    connector_relationships_returned = 0
    errors: list[str] = []

    for call in connector_calls:
        findings_count = _as_int(call.get("findings_count"))
        relationship_count = _as_int(call.get("relationship_count"))
        has_data = bool(call.get("has_data")) or findings_count > 0 or relationship_count > 0 or bool(_as_dict(call.get("identifiers")))
        connector_findings_returned += findings_count
        connector_relationships_returned += relationship_count
        if has_data:
            connector_calls_with_data += 1
        if not bool(call.get("success")):
            connector_calls_failed += 1
            message = _clean_text(call.get("error"))
            if message:
                errors.append(message)

    return {
        "connector_calls_attempted": connector_calls_attempted,
        "connector_calls_with_data": connector_calls_with_data,
        "connector_calls_failed": connector_calls_failed,
        "connector_findings_returned": connector_findings_returned,
        "connector_relationships_returned": connector_relationships_returned,
        "errors": errors[:6],
    }


def build_axiom_gap_surface(
    *,
    agent_result: Any = None,
    connector_accounting: dict[str, Any] | None = None,
    local_fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = agent_result.to_dict() if hasattr(agent_result, "to_dict") else _as_dict(agent_result)
    accounting = connector_accounting or summarize_axiom_connector_accounting(payload)
    if not payload and not local_fallback:
        return _surface(
            "skipped",
            passes=0,
            entities_found=0,
            relationships_found=0,
            gap_count=0,
            connector_calls_attempted=0,
            connector_calls_with_data=0,
            unresolved_reasons=[],
            errors=[],
        )

    entities_found = len(_as_list(payload.get("entities")))
    relationships_found = len(_as_list(payload.get("relationships")))
    gap_count = len(_as_list(payload.get("intelligence_gaps")))
    passes = _as_int(payload.get("iteration")) or len(_as_list(payload.get("iterations"))) or 1
    unresolved_reasons = [
        _clean_text(gap.get("description") or gap.get("gap") or gap.get("gap_type"))
        for gap in _as_list(payload.get("intelligence_gaps"))
        if isinstance(gap, dict) and _clean_text(gap.get("description") or gap.get("gap") or gap.get("gap_type"))
    ]
    errors = list(accounting.get("errors") or [])

    if local_fallback:
        reason = _clean_text(_as_dict(local_fallback).get("reason"))
        if reason:
            unresolved_reasons.insert(0, reason)
        status = "degraded"
    elif (
        accounting.get("connector_calls_attempted", 0) >= 3
        and accounting.get("connector_calls_with_data", 0) >= 2
        and relationships_found >= 2
    ):
        status = "ready"
    elif (
        accounting.get("connector_calls_attempted", 0) > 0
        or entities_found > 0
        or relationships_found > 0
        or gap_count > 0
    ):
        status = "degraded"
    else:
        status = "failed"

    return _surface(
        status,
        passes=passes,
        entities_found=entities_found,
        relationships_found=relationships_found,
        gap_count=gap_count,
        connector_calls_attempted=_as_int(accounting.get("connector_calls_attempted")),
        connector_calls_with_data=_as_int(accounting.get("connector_calls_with_data")),
        unresolved_reasons=unresolved_reasons[:6],
        errors=errors[:6],
    )


def build_readiness_contract(
    *,
    enrichment: dict[str, Any] | None = None,
    ownership: dict[str, Any] | None = None,
    procurement: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
    agent_result: Any = None,
    local_fallback: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    connector_accounting = summarize_axiom_connector_accounting(agent_result)
    surfaces = {
        "enrichment": build_enrichment_surface(enrichment),
        "ownership": build_ownership_surface(ownership),
        "procurement": build_procurement_surface(procurement),
        "graph": build_graph_surface(graph),
        "axiom_gap_closure": build_axiom_gap_surface(
            agent_result=agent_result,
            connector_accounting=connector_accounting,
            local_fallback=local_fallback,
        ),
    }

    blocking_failures = [
        name for name, surface in surfaces.items()
        if surface.get("status") == "failed"
    ]
    evidence_actions_attempted = (
        _as_int(surfaces["enrichment"].get("connectors_run"))
        + _as_int(surfaces["ownership"].get("connectors_run"))
        + _as_int(surfaces["procurement"].get("connectors_run"))
        + _as_int(surfaces["axiom_gap_closure"].get("connector_calls_attempted"))
    )
    usable_surface_count = sum(
        1 for surface in surfaces.values() if _surface_has_usable_data(surface)
    )

    worst_surface_status = max(
        (str(surface.get("status") or "ready") for surface in surfaces.values()),
        key=lambda status: _SURFACE_STATUS_ORDER.get(status, 99),
        default="ready",
    )
    if blocking_failures:
        status = "failed"
    elif local_fallback or worst_surface_status in {"degraded", "stale"}:
        status = "degraded"
    else:
        status = "ready"

    contract = {
        "status": status,
        "blocking_failures": blocking_failures,
        "evidence_actions_attempted": evidence_actions_attempted,
        "usable_surface_count": usable_surface_count,
        "surfaces": surfaces,
    }
    return contract, connector_accounting
