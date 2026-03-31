"""Learned weighting models for Helios graph truth and tribunal stance.

This module replaces hand-tuned weight blends with small fixture-trained models
that remain transparent and cheap to run locally.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

try:  # pragma: no cover
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
GRAPH_GOLD_PATH = REPO_ROOT / "fixtures" / "adversarial_gym" / "graph_construction_gold_set_v1.json"
GRAPH_NEGATIVE_PATH = REPO_ROOT / "fixtures" / "adversarial_gym" / "graph_construction_hard_negatives_v1.json"
TRIBUNAL_TRAINING_PATH = REPO_ROOT / "fixtures" / "adversarial_gym" / "decision_tribunal_training_cases_v1.json"

EDGE_AUTHORITY_BUCKETS = (
    "official_or_modeled",
    "first_party",
    "third_party_public_only",
    "unspecified",
)
EDGE_TEMPORAL_STATES = (
    "active",
    "watch",
    "stale",
    "historical",
    "contradicted",
    "unknown",
)
EDGE_FAMILIES = (
    "ownership_control",
    "contracts_and_programs",
    "trade_and_logistics",
    "cyber_supply_chain",
    "official_and_regulatory",
    "sanctions_and_legal",
    "identity_and_alias",
    "intermediaries_and_services",
    "component_dependency",
    "finance_intermediary",
    "other",
)

TRIBUNAL_CLASSES = ("approve", "watch", "deny")
TRIBUNAL_POSTURES = ("approved", "review", "pending", "blocked")
TRIBUNAL_LANES = ("defense_counterparty_trust", "supplier_cyber_trust", "export_authorization", "")
TRIBUNAL_TIER_BANDS = ("clear", "conditional", "elevated", "critical")
TRIBUNAL_LATEST_DECISIONS = ("", "approve", "escalate", "reject")
TRIBUNAL_NETWORK_LEVELS = ("none", "low", "medium", "high", "critical")


@dataclass(frozen=True)
class BinaryLogisticModel:
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    weights: tuple[float, ...]
    bias: float
    global_threshold: float
    thresholds_by_family: dict[str, float]
    training_count: int


@dataclass(frozen=True)
class SoftmaxModel:
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    weights: tuple[tuple[float, ...], ...]
    biases: tuple[float, ...]
    classes: tuple[str, ...]
    training_count: int


def _sigmoid(values):
    if np is None:  # pragma: no cover
        raise RuntimeError("NumPy is required for learned weighting")
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _softmax(logits):
    if np is None:  # pragma: no cover
        raise RuntimeError("NumPy is required for learned weighting")
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exps = np.exp(shifted)
    return exps / np.sum(exps, axis=1, keepdims=True)


def _standardize_fit(matrix):
    means = np.mean(matrix, axis=0)
    scales = np.std(matrix, axis=0)
    scales = np.where(scales < 1e-6, 1.0, scales)
    return means, scales, (matrix - means) / scales


def _standardize_apply(matrix, means, scales):
    return (matrix - means) / scales


def _fit_binary_logistic(features, labels, *, l2: float = 0.08, lr: float = 0.18, epochs: int = 900) -> tuple[np.ndarray, float]:
    labels = labels.astype(float)
    weights = np.zeros(features.shape[1], dtype=float)
    positive_rate = float(np.mean(labels)) if len(labels) else 0.5
    positive_rate = min(max(positive_rate, 1e-4), 1.0 - 1e-4)
    bias = float(np.log(positive_rate / (1.0 - positive_rate)))

    positives = max(float(np.sum(labels)), 1.0)
    negatives = max(float(len(labels) - np.sum(labels)), 1.0)
    sample_weights = np.where(labels > 0.5, len(labels) / (2.0 * positives), len(labels) / (2.0 * negatives))

    for _ in range(epochs):
        logits = features @ weights + bias
        probs = _sigmoid(logits)
        errors = (probs - labels) * sample_weights
        grad_w = (features.T @ errors) / len(labels) + l2 * weights
        grad_b = float(np.sum(errors) / len(labels))
        weights -= lr * grad_w
        bias -= lr * grad_b
    return weights, bias


def _fit_softmax(features, labels, *, l2: float = 0.05, lr: float = 0.12, epochs: int = 1200) -> tuple[np.ndarray, np.ndarray]:
    class_count = int(np.max(labels)) + 1 if len(labels) else 1
    weights = np.zeros((features.shape[1], class_count), dtype=float)
    biases = np.zeros(class_count, dtype=float)
    one_hot = np.eye(class_count)[labels]
    class_counts = np.maximum(np.sum(one_hot, axis=0), 1.0)
    sample_weights = np.array([len(labels) / (class_count * class_counts[label]) for label in labels], dtype=float)

    for _ in range(epochs):
        logits = features @ weights + biases
        probs = _softmax(logits)
        errors = (probs - one_hot) * sample_weights[:, None]
        grad_w = (features.T @ errors) / len(labels) + l2 * weights
        grad_b = np.sum(errors, axis=0) / len(labels)
        weights -= lr * grad_w
        biases -= lr * grad_b
    return weights, biases


def _best_threshold(probabilities: np.ndarray, labels: np.ndarray) -> float:
    candidate_thresholds = sorted({float(value) for value in probabilities.tolist()} | {0.5})
    best_threshold = 0.5
    best_f1 = -1.0
    for threshold in candidate_thresholds:
        predictions = probabilities >= threshold
        tp = int(np.sum((predictions == 1) & (labels == 1)))
        fp = int(np.sum((predictions == 1) & (labels == 0)))
        fn = int(np.sum((predictions == 0) & (labels == 1)))
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 0.0 if precision + recall == 0 else (2.0 * precision * recall) / (precision + recall)
        if f1 > best_f1 or (abs(f1 - best_f1) < 1e-9 and threshold > best_threshold):
            best_f1 = f1
            best_threshold = threshold
    return round(float(best_threshold), 4)


def _map_source_authority_to_bucket(source_authority: str) -> str:
    normalized = str(source_authority or "").strip().lower()
    if normalized in {"analyst_modeled", "official_registry", "official_program_system", "official_regulatory", "official_judicial_record", "analyst_curated_fixture", "standards_modeled_fixture"}:
        return "official_or_modeled"
    if normalized in {"first_party", "first_party_self_disclosed"}:
        return "first_party"
    if normalized in {"secondary_public", "public_html", "third_party_public", "public_registry_aggregator"}:
        return "third_party_public_only"
    return "unspecified"


def _map_freshness_to_temporal_state(freshness: str, contradiction: str) -> str:
    contradiction_state = str(contradiction or "").strip().lower()
    if contradiction_state in {"contradicted", "disputed", "challenged"}:
        return "contradicted"
    normalized = str(freshness or "").strip().lower()
    if normalized in {"current", "recent", "active"}:
        return "active"
    if normalized in {"watch"}:
        return "watch"
    if normalized in {"stale"}:
        return "stale"
    if normalized in {"historical", "expired"}:
        return "historical"
    return "unknown"


def _clip_corroboration(value: Any) -> float:
    try:
        count = int(value or 0)
    except (TypeError, ValueError):
        count = 0
    count = max(1, min(count, 4))
    return count / 4.0


def _edge_heuristic_prior(payload: dict[str, Any]) -> float:
    authority_bucket = str(payload.get("authority_bucket") or "unspecified")
    temporal_state = str(payload.get("temporal_state") or "unknown")
    family = str(payload.get("edge_family") or "other")
    corroboration = float(payload.get("corroboration_norm") or 0.25)
    claim_backed = 1.0 if bool(payload.get("claim_backed")) else 0.0
    evidence_backed = 1.0 if bool(payload.get("evidence_backed")) else 0.0
    legacy_unscoped = 1.0 if bool(payload.get("legacy_unscoped")) else 0.0
    descriptor_only = 1.0 if bool(payload.get("descriptor_only")) else 0.0

    authority_strength = {
        "official_or_modeled": 0.94,
        "first_party": 0.82,
        "third_party_public_only": 0.58,
        "unspecified": 0.45,
    }.get(authority_bucket, 0.45)
    temporal_strength = {
        "active": 0.94,
        "watch": 0.72,
        "stale": 0.42,
        "historical": 0.25,
        "contradicted": 0.02,
        "unknown": 0.55,
    }.get(temporal_state, 0.55)
    family_prior = {
        "ownership_control": 0.74,
        "contracts_and_programs": 0.68,
        "trade_and_logistics": 0.66,
        "cyber_supply_chain": 0.66,
        "official_and_regulatory": 0.71,
        "sanctions_and_legal": 0.73,
        "identity_and_alias": 0.58,
        "intermediaries_and_services": 0.64,
        "component_dependency": 0.64,
        "finance_intermediary": 0.67,
        "other": 0.63,
    }.get(family, 0.63)
    score = (
        family_prior * 0.28
        + authority_strength * 0.24
        + temporal_strength * 0.2
        + corroboration * 0.12
        + claim_backed * 0.08
        + evidence_backed * 0.08
    )
    score -= 0.16 * legacy_unscoped
    score -= 0.24 * descriptor_only
    if temporal_state == "contradicted":
        score *= 0.35
    return round(max(0.0, min(score, 1.0)), 4)


def _edge_feature_payload_from_training_row(row: dict[str, Any], *, positive: bool) -> dict[str, Any]:
    source_authority = row.get("source_authority") or row.get("authority_bucket") or ""
    edge_family = str(row.get("edge_family") or "other").strip().lower() or "other"
    contradiction = row.get("contradiction_state") or ""
    descriptor_only = bool(row.get("descriptor_only"))
    temporal_state = _map_freshness_to_temporal_state(str(row.get("freshness_class") or ""), str(contradiction))
    claim_backed = True
    evidence_backed = bool(row.get("evidence_text") or row.get("source_url"))
    corroboration_norm = 0.75 if str(contradiction or "").strip().lower() in {"corroborated", "uncontradicted"} and positive else 0.25
    payload = {
        "authority_bucket": _map_source_authority_to_bucket(str(source_authority)),
        "temporal_state": temporal_state,
        "edge_family": edge_family if edge_family in EDGE_FAMILIES else "other",
        "descriptor_only": descriptor_only,
        "claim_backed": claim_backed,
        "evidence_backed": evidence_backed,
        "legacy_unscoped": False,
        "corroboration_norm": corroboration_norm,
    }
    payload["heuristic_prior"] = _edge_heuristic_prior(payload)
    return payload


def _edge_feature_payload_from_relationship(row: dict[str, Any]) -> dict[str, Any]:
    claim_records = [claim for claim in (row.get("claim_records") or []) if isinstance(claim, dict)]
    edge_families = row.get("edge_families") if isinstance(row.get("edge_families"), list) else []
    raw_edge_family = (
        row.get("primary_edge_family")
        or row.get("edge_family")
        or (edge_families[0] if edge_families else None)
        or "other"
    )
    authority_bucket = str(row.get("authority_bucket") or "").strip().lower()
    if authority_bucket not in EDGE_AUTHORITY_BUCKETS:
        authority_bucket = _map_source_authority_to_bucket(str(row.get("source_authority") or ""))
    temporal_state = str(row.get("temporal_state") or "").strip().lower()
    if temporal_state not in EDGE_TEMPORAL_STATES:
        temporal_state = _map_freshness_to_temporal_state(
            str(row.get("freshness_class") or ""),
            str(row.get("contradiction_state") or ""),
        )
    payload = {
        "authority_bucket": authority_bucket or "unspecified",
        "temporal_state": temporal_state or "unknown",
        "edge_family": str(raw_edge_family).strip().lower() or "other",
        "descriptor_only": bool(row.get("descriptor_only")),
        "claim_backed": bool(claim_records),
        "evidence_backed": bool(
            any((claim.get("evidence_records") or []) for claim in claim_records)
            or row.get("evidence_refs")
            or row.get("evidence_text")
            or row.get("source_url")
        ),
        "legacy_unscoped": bool(row.get("legacy_unscoped")),
        "corroboration_norm": _clip_corroboration(row.get("corroboration_count")),
    }
    if payload["edge_family"] not in EDGE_FAMILIES:
        payload["edge_family"] = "other"
    payload["heuristic_prior"] = _edge_heuristic_prior(payload)
    return payload


def _edge_feature_vector(payload: dict[str, Any]) -> tuple[list[float], list[str]]:
    features: list[float] = []
    names: list[str] = []

    def add(name: str, value: float) -> None:
        names.append(name)
        features.append(float(value))

    add("heuristic_prior", payload.get("heuristic_prior", 0.0))
    add("descriptor_only", 1.0 if bool(payload.get("descriptor_only")) else 0.0)
    add("claim_backed", 1.0 if bool(payload.get("claim_backed")) else 0.0)
    add("evidence_backed", 1.0 if bool(payload.get("evidence_backed")) else 0.0)
    add("legacy_unscoped", 1.0 if bool(payload.get("legacy_unscoped")) else 0.0)
    add("corroboration_norm", payload.get("corroboration_norm", 0.25))
    authority_bucket = str(payload.get("authority_bucket") or "unspecified")
    temporal_state = str(payload.get("temporal_state") or "unknown")
    edge_family = str(payload.get("edge_family") or "other")
    for bucket in EDGE_AUTHORITY_BUCKETS:
        add(f"authority:{bucket}", 1.0 if authority_bucket == bucket else 0.0)
    for state in EDGE_TEMPORAL_STATES:
        add(f"temporal:{state}", 1.0 if temporal_state == state else 0.0)
    for family in EDGE_FAMILIES:
        add(f"family:{family}", 1.0 if edge_family == family else 0.0)
    return features, names


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    rows = payload.get("rows") if isinstance(payload, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _build_edge_truth_training_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _load_json_rows(GRAPH_GOLD_PATH):
        if bool(row.get("should_create_edge")):
            payload = _edge_feature_payload_from_training_row(row, positive=True)
            rows.append({"label": 1, "edge_family": payload["edge_family"], "features": payload})
    for row in _load_json_rows(GRAPH_NEGATIVE_PATH):
        if not bool(row.get("should_create_edge")):
            payload = _edge_feature_payload_from_training_row(row, positive=False)
            rows.append({"label": 0, "edge_family": payload["edge_family"], "features": payload})
    return rows


@lru_cache(maxsize=1)
def get_edge_truth_model() -> BinaryLogisticModel | None:
    if np is None:  # pragma: no cover
        return None
    rows = _build_edge_truth_training_rows()
    if not rows:
        return None

    feature_vectors: list[list[float]] = []
    feature_names: list[str] | None = None
    labels: list[int] = []
    families: list[str] = []
    for row in rows:
        vector, names = _edge_feature_vector(row["features"])
        if feature_names is None:
            feature_names = names
        feature_vectors.append(vector)
        labels.append(int(row["label"]))
        families.append(str(row["edge_family"]))

    matrix = np.array(feature_vectors, dtype=float)
    label_array = np.array(labels, dtype=int)
    means, scales, standardized = _standardize_fit(matrix)
    weights, bias = _fit_binary_logistic(standardized, label_array)
    probabilities = _sigmoid(standardized @ weights + bias)

    global_threshold = _best_threshold(probabilities, label_array)
    thresholds_by_family: dict[str, float] = {}
    for family in sorted(set(families)):
        family_indices = [index for index, current_family in enumerate(families) if current_family == family]
        if len(family_indices) < 2:
            continue
        family_probs = probabilities[family_indices]
        family_labels = label_array[family_indices]
        if len(set(family_labels.tolist())) < 2:
            continue
        thresholds_by_family[family] = _best_threshold(family_probs, family_labels)

    return BinaryLogisticModel(
        feature_names=tuple(feature_names or []),
        means=tuple(float(value) for value in means.tolist()),
        scales=tuple(float(value) for value in scales.tolist()),
        weights=tuple(float(value) for value in weights.tolist()),
        bias=float(bias),
        global_threshold=global_threshold,
        thresholds_by_family=thresholds_by_family,
        training_count=len(rows),
    )


def predict_edge_truth_probability(row: dict[str, Any]) -> dict[str, Any]:
    model = get_edge_truth_model()
    if model is None or np is None:  # pragma: no cover
        return {"probability": float(_edge_heuristic_prior(_edge_feature_payload_from_relationship(row))), "threshold": 0.5, "training_count": 0}
    payload = _edge_feature_payload_from_relationship(row)
    vector, names = _edge_feature_vector(payload)
    matrix = np.array([vector], dtype=float)
    standardized = _standardize_apply(matrix, np.array(model.means), np.array(model.scales))
    weights = np.array(model.weights)
    probability = float(_sigmoid(standardized @ weights + model.bias)[0])
    family = str(payload.get("edge_family") or "other")
    threshold = float(model.thresholds_by_family.get(family, model.global_threshold))
    return {
        "probability": round(probability, 4),
        "threshold": round(threshold, 4),
        "heuristic_prior": round(float(payload["heuristic_prior"]), 4),
        "training_count": model.training_count,
        "feature_names": tuple(names),
        "feature_values": tuple(float(value) for value in vector),
    }


def _tribunal_feature_vector(signal_packet: dict[str, Any], heuristic_scores: dict[str, float] | None = None) -> tuple[list[float], list[str]]:
    packet = signal_packet or {}
    features: list[float] = []
    names: list[str] = []

    def add(name: str, value: float) -> None:
        names.append(name)
        features.append(float(value))

    numeric_keys = (
        "connector_coverage",
        "identifier_count",
        "control_path_count",
        "ownership_path_count",
        "intermediary_path_count",
        "contradicted_path_count",
        "stale_path_count",
        "corroborated_path_count",
        "network_score",
        "graph_missing_required_edge_family_count",
        "graph_claim_coverage_pct",
        "graph_evidence_coverage_pct",
        "graph_contradicted_edge_count",
        "graph_stale_edge_count",
        "graph_legacy_unscoped_edge_count",
        "graph_official_edge_count",
        "graph_public_only_edge_count",
        "ownership_resolution_pct",
        "control_resolution_pct",
        "shell_layers",
        "critical_cves",
        "kev_count",
        "blocked_official_connectors",
    )
    for key in numeric_keys:
        add(key, float(packet.get(key) or 0.0))

    boolean_keys = (
        "hard_stop",
        "foreign_control_risk",
        "mitigated_foreign_interest",
        "official_coverage_thin",
        "graph_thin",
        "named_owner_known",
        "controlling_parent_known",
        "owner_class_known",
        "descriptor_only",
        "ownership_evidence_thin",
        "control_evidence_thin",
        "export_prohibited",
        "export_review_required",
        "export_evidence_missing",
        "export_route_ambiguity",
        "cyber_gap",
        "cyber_evidence_missing",
        "pep_connection",
    )
    for key in boolean_keys:
        add(key, 1.0 if bool(packet.get(key)) else 0.0)

    posture = str(packet.get("posture") or "pending").lower()
    workflow_lane = str(packet.get("workflow_lane") or "").lower()
    tier_band = str(packet.get("tier_band") or "clear").lower()
    latest_decision = str(packet.get("latest_decision") or "").lower()
    network_level = str(packet.get("network_level") or "none").lower()

    for value in TRIBUNAL_POSTURES:
        add(f"posture:{value}", 1.0 if posture == value else 0.0)
    for value in TRIBUNAL_LANES:
        add(f"workflow_lane:{value or 'none'}", 1.0 if workflow_lane == value else 0.0)
    for value in TRIBUNAL_TIER_BANDS:
        add(f"tier_band:{value}", 1.0 if tier_band == value else 0.0)
    for value in TRIBUNAL_LATEST_DECISIONS:
        add(f"latest_decision:{value or 'none'}", 1.0 if latest_decision == value else 0.0)
    for value in TRIBUNAL_NETWORK_LEVELS:
        add(f"network_level:{value}", 1.0 if network_level == value else 0.0)

    heuristic_scores = heuristic_scores or {}
    for stance in TRIBUNAL_CLASSES:
        add(f"heuristic:{stance}", float(heuristic_scores.get(stance) or 0.0))
    return features, names


def _load_tribunal_training_rows() -> list[dict[str, Any]]:
    payload = json.loads(TRIBUNAL_TRAINING_PATH.read_text(encoding="utf-8")) if TRIBUNAL_TRAINING_PATH.exists() else {}
    cases = payload.get("cases") if isinstance(payload, dict) else None
    return [row for row in cases if isinstance(row, dict)] if isinstance(cases, list) else []


@lru_cache(maxsize=1)
def get_tribunal_model() -> SoftmaxModel | None:
    if np is None:  # pragma: no cover
        return None
    rows = _load_tribunal_training_rows()
    if not rows:
        return None

    feature_vectors: list[list[float]] = []
    feature_names: list[str] | None = None
    labels: list[int] = []

    for row in rows:
        signal_packet = row.get("signal_packet") if isinstance(row.get("signal_packet"), dict) else {}
        heuristic_scores = row.get("heuristic_scores") if isinstance(row.get("heuristic_scores"), dict) else {}
        vector, names = _tribunal_feature_vector(signal_packet, heuristic_scores)
        if feature_names is None:
            feature_names = names
        feature_vectors.append(vector)
        labels.append(TRIBUNAL_CLASSES.index(str(row.get("target_view") or "watch")))

    matrix = np.array(feature_vectors, dtype=float)
    label_array = np.array(labels, dtype=int)
    means, scales, standardized = _standardize_fit(matrix)
    weights, biases = _fit_softmax(standardized, label_array)

    return SoftmaxModel(
        feature_names=tuple(feature_names or []),
        means=tuple(float(value) for value in means.tolist()),
        scales=tuple(float(value) for value in scales.tolist()),
        weights=tuple(tuple(float(value) for value in column) for column in weights.tolist()),
        biases=tuple(float(value) for value in biases.tolist()),
        classes=TRIBUNAL_CLASSES,
        training_count=len(rows),
    )


def predict_tribunal_probabilities(signal_packet: dict[str, Any], heuristic_scores: dict[str, float] | None = None) -> dict[str, float] | None:
    model = get_tribunal_model()
    if model is None or np is None:  # pragma: no cover
        return None
    vector, _ = _tribunal_feature_vector(signal_packet, heuristic_scores)
    matrix = np.array([vector], dtype=float)
    standardized = _standardize_apply(matrix, np.array(model.means), np.array(model.scales))
    weights = np.array(model.weights)
    biases = np.array(model.biases)
    probabilities = _softmax(standardized @ weights + biases)[0]
    return {
        stance: round(float(probability), 4)
        for stance, probability in zip(model.classes, probabilities.tolist())
    }
