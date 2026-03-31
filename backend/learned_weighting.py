"""Learned weighting models for Helios graph truth and tribunal stance.

This module replaces hand-tuned weight blends with small fixture-trained models
that remain transparent and cheap to run locally.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math
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
TRIBUNAL_CALIBRATION_PATH = REPO_ROOT / "fixtures" / "adversarial_gym" / "decision_tribunal_calibration_cases_v1.json"

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
    calibration_count: int
    temperature: float
    confidence_floor: float
    margin_floor: float
    entropy_ceiling: float
    mean_brier: float


@dataclass(frozen=True)
class FamilyReliabilityProfile:
    posterior_mean_by_family: dict[str, float]
    global_posterior_mean: float
    training_count: int


@dataclass(frozen=True)
class HierarchicalEdgePriorModel:
    global_posterior_mean: float
    posterior_by_family: dict[str, float]
    support_by_family: dict[str, int]
    posterior_by_authority: dict[str, float]
    support_by_authority: dict[str, int]
    posterior_by_temporal: dict[str, float]
    support_by_temporal: dict[str, int]
    posterior_by_corroboration: dict[str, float]
    support_by_corroboration: dict[str, int]
    posterior_by_claim_backed: dict[str, float]
    support_by_claim_backed: dict[str, int]
    posterior_by_evidence_backed: dict[str, float]
    support_by_evidence_backed: dict[str, int]
    posterior_by_descriptor_only: dict[str, float]
    support_by_descriptor_only: dict[str, int]
    posterior_by_legacy_unscoped: dict[str, float]
    support_by_legacy_unscoped: dict[str, int]
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


def _mean_brier_multiclass(probabilities: np.ndarray, labels: np.ndarray) -> float:
    one_hot = np.eye(probabilities.shape[1])[labels]
    squared = np.sum((probabilities - one_hot) ** 2, axis=1)
    return float(np.mean(squared))


def _normalized_entropy(probabilities: np.ndarray) -> np.ndarray:
    clipped = np.clip(probabilities, 1e-12, 1.0)
    entropy = -np.sum(clipped * np.log(clipped), axis=1)
    max_entropy = np.log(probabilities.shape[1]) if probabilities.shape[1] > 1 else 1.0
    return entropy / max(max_entropy, 1e-12)


def _logit_scalar(value: float) -> float:
    clipped = min(max(float(value), 1e-6), 1.0 - 1e-6)
    return float(np.log(clipped / (1.0 - clipped)))


def _sigmoid_scalar(value: float) -> float:
    return float(_sigmoid(np.array([value], dtype=float))[0])


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


def _bucket_key(value: Any) -> str:
    return str(value).strip().lower()


def _posterior_and_support(labels: list[int]) -> tuple[float, int]:
    support = len(labels)
    positive_count = sum(int(label) for label in labels)
    posterior_mean = (1.0 + positive_count) / (2.0 + support)
    return posterior_mean, support


def _feature_bucket_tables(rows: list[dict[str, Any]], key_name: str) -> tuple[dict[str, float], dict[str, int]]:
    grouped: dict[str, list[int]] = {}
    for row in rows:
        features = row.get("features") if isinstance(row.get("features"), dict) else {}
        bucket = _bucket_key(features.get(key_name))
        grouped.setdefault(bucket, []).append(int(row.get("label") or 0))
    posterior: dict[str, float] = {}
    support: dict[str, int] = {}
    for bucket, labels in grouped.items():
        posterior[bucket], support[bucket] = _posterior_and_support(labels)
    return posterior, support


@lru_cache(maxsize=1)
def get_hierarchical_edge_prior_model() -> HierarchicalEdgePriorModel | None:
    rows = _build_raw_edge_truth_training_rows()
    if not rows:
        return None

    global_posterior, _ = _posterior_and_support([int(row.get("label") or 0) for row in rows])
    posterior_by_family, support_by_family = _feature_bucket_tables(rows, "edge_family")
    posterior_by_authority, support_by_authority = _feature_bucket_tables(rows, "authority_bucket")
    posterior_by_temporal, support_by_temporal = _feature_bucket_tables(rows, "temporal_state")
    posterior_by_corroboration, support_by_corroboration = _feature_bucket_tables(rows, "corroboration_bucket")
    posterior_by_claim_backed, support_by_claim_backed = _feature_bucket_tables(rows, "claim_backed")
    posterior_by_evidence_backed, support_by_evidence_backed = _feature_bucket_tables(rows, "evidence_backed")
    posterior_by_descriptor_only, support_by_descriptor_only = _feature_bucket_tables(rows, "descriptor_only")
    posterior_by_legacy_unscoped, support_by_legacy_unscoped = _feature_bucket_tables(rows, "legacy_unscoped")

    return HierarchicalEdgePriorModel(
        global_posterior_mean=round(global_posterior, 4),
        posterior_by_family={key: round(value, 4) for key, value in posterior_by_family.items()},
        support_by_family=support_by_family,
        posterior_by_authority={key: round(value, 4) for key, value in posterior_by_authority.items()},
        support_by_authority=support_by_authority,
        posterior_by_temporal={key: round(value, 4) for key, value in posterior_by_temporal.items()},
        support_by_temporal=support_by_temporal,
        posterior_by_corroboration={key: round(value, 4) for key, value in posterior_by_corroboration.items()},
        support_by_corroboration=support_by_corroboration,
        posterior_by_claim_backed={key: round(value, 4) for key, value in posterior_by_claim_backed.items()},
        support_by_claim_backed=support_by_claim_backed,
        posterior_by_evidence_backed={key: round(value, 4) for key, value in posterior_by_evidence_backed.items()},
        support_by_evidence_backed=support_by_evidence_backed,
        posterior_by_descriptor_only={key: round(value, 4) for key, value in posterior_by_descriptor_only.items()},
        support_by_descriptor_only=support_by_descriptor_only,
        posterior_by_legacy_unscoped={key: round(value, 4) for key, value in posterior_by_legacy_unscoped.items()},
        support_by_legacy_unscoped=support_by_legacy_unscoped,
        training_count=len(rows),
    )


def _edge_hierarchical_prior(payload: dict[str, Any]) -> float:
    model = get_hierarchical_edge_prior_model()
    if model is None:
        return 0.5

    priors: list[tuple[float, int]] = [(float(model.global_posterior_mean), max(model.training_count, 1))]

    def add_group(value: Any, posterior_table: dict[str, float], support_table: dict[str, int]) -> None:
        key = _bucket_key(value)
        posterior = float(posterior_table.get(key, model.global_posterior_mean))
        support = int(support_table.get(key, 0))
        priors.append((posterior, max(support, 1)))

    add_group(payload.get("edge_family") or "other", model.posterior_by_family, model.support_by_family)
    add_group(payload.get("authority_bucket") or "unspecified", model.posterior_by_authority, model.support_by_authority)
    add_group(payload.get("temporal_state") or "unknown", model.posterior_by_temporal, model.support_by_temporal)
    add_group(payload.get("corroboration_bucket") or "0.25", model.posterior_by_corroboration, model.support_by_corroboration)
    add_group(bool(payload.get("claim_backed")), model.posterior_by_claim_backed, model.support_by_claim_backed)
    add_group(bool(payload.get("evidence_backed")), model.posterior_by_evidence_backed, model.support_by_evidence_backed)
    add_group(bool(payload.get("descriptor_only")), model.posterior_by_descriptor_only, model.support_by_descriptor_only)
    add_group(bool(payload.get("legacy_unscoped")), model.posterior_by_legacy_unscoped, model.support_by_legacy_unscoped)

    weighted_logit_sum = 0.0
    total_weight = 0.0
    for posterior, support in priors:
        weight = math.log1p(max(support, 1))
        weighted_logit_sum += _logit_scalar(posterior) * weight
        total_weight += weight
    if total_weight <= 0.0:
        return float(model.global_posterior_mean)
    return round(_sigmoid_scalar(weighted_logit_sum / total_weight), 4)


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
        "corroboration_bucket": f"{corroboration_norm:.2f}",
    }
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
    payload["corroboration_bucket"] = f"{float(payload['corroboration_norm']):.2f}"
    return payload


def _attach_edge_hierarchical_prior(payload: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(payload)
    enriched["hierarchical_prior"] = _edge_hierarchical_prior(enriched)
    return enriched


def _edge_feature_vector(payload: dict[str, Any]) -> tuple[list[float], list[str]]:
    features: list[float] = []
    names: list[str] = []

    def add(name: str, value: float) -> None:
        names.append(name)
        features.append(float(value))

    add("hierarchical_prior", payload.get("hierarchical_prior", 0.5))
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


def _build_raw_edge_truth_training_rows() -> list[dict[str, Any]]:
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


def _build_edge_truth_training_rows() -> list[dict[str, Any]]:
    rows = _build_raw_edge_truth_training_rows()
    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        features = row.get("features") if isinstance(row.get("features"), dict) else {}
        enriched_rows.append({**row, "features": _attach_edge_hierarchical_prior(features)})
    return enriched_rows


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
    payload = _attach_edge_hierarchical_prior(_edge_feature_payload_from_relationship(row))
    if model is None or np is None:  # pragma: no cover
        return {
            "probability": float(payload["hierarchical_prior"]),
            "threshold": 0.5,
            "hierarchical_prior": float(payload["hierarchical_prior"]),
            "training_count": 0,
        }
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
        "hierarchical_prior": round(float(payload["hierarchical_prior"]), 4),
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


def _load_tribunal_calibration_rows() -> list[dict[str, Any]]:
    payload = json.loads(TRIBUNAL_CALIBRATION_PATH.read_text(encoding="utf-8")) if TRIBUNAL_CALIBRATION_PATH.exists() else {}
    cases = payload.get("cases") if isinstance(payload, dict) else None
    return [row for row in cases if isinstance(row, dict)] if isinstance(cases, list) else []


def _multiclass_log_loss(probabilities: np.ndarray, labels: np.ndarray) -> float:
    clipped = np.clip(probabilities[np.arange(len(labels)), labels], 1e-12, 1.0)
    return float(-np.mean(np.log(clipped)))


def _fit_temperature(logits: np.ndarray, labels: np.ndarray) -> float:
    if len(labels) == 0:
        return 1.0
    candidate_temperatures = np.exp(np.linspace(np.log(0.5), np.log(5.0), 160))
    best_temperature = 1.0
    best_loss = float("inf")
    for temperature in candidate_temperatures:
        probabilities = _softmax(logits / float(temperature))
        loss = _multiclass_log_loss(probabilities, labels)
        if loss < best_loss:
            best_loss = loss
            best_temperature = float(temperature)
    return best_temperature


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
    training_logits = standardized @ weights + biases

    calibration_rows = _load_tribunal_calibration_rows()
    calibration_vectors: list[list[float]] = []
    calibration_labels: list[int] = []
    for row in calibration_rows:
        signal_packet = row.get("signal_packet") if isinstance(row.get("signal_packet"), dict) else {}
        heuristic_scores = row.get("heuristic_scores") if isinstance(row.get("heuristic_scores"), dict) else {}
        vector, _ = _tribunal_feature_vector(signal_packet, heuristic_scores)
        calibration_vectors.append(vector)
        calibration_labels.append(TRIBUNAL_CLASSES.index(str(row.get("target_view") or "watch")))

    calibration_count = len(calibration_vectors)
    if calibration_vectors:
        calibration_matrix = np.array(calibration_vectors, dtype=float)
        calibration_standardized = _standardize_apply(calibration_matrix, means, scales)
        calibration_logits = calibration_standardized @ weights + biases
        calibration_label_array = np.array(calibration_labels, dtype=int)
        temperature = _fit_temperature(calibration_logits, calibration_label_array)
        evaluation_probs = _softmax(calibration_logits / temperature)
        evaluation_labels = calibration_label_array
    else:
        temperature = 1.0
        evaluation_probs = _softmax(training_logits)
        evaluation_labels = label_array

    true_probs = evaluation_probs[np.arange(len(evaluation_labels)), evaluation_labels]
    sorted_probs = np.sort(evaluation_probs, axis=1)
    top_probs = sorted_probs[:, -1]
    runner_up_probs = sorted_probs[:, -2] if evaluation_probs.shape[1] > 1 else np.zeros(len(evaluation_labels), dtype=float)
    margins = top_probs - runner_up_probs
    entropies = _normalized_entropy(evaluation_probs)
    confidence_floor = float(np.quantile(true_probs, 0.2))
    margin_floor = float(np.quantile(margins, 0.2))
    entropy_ceiling = float(np.quantile(entropies, 0.8))
    mean_brier = _mean_brier_multiclass(evaluation_probs, evaluation_labels)

    return SoftmaxModel(
        feature_names=tuple(feature_names or []),
        means=tuple(float(value) for value in means.tolist()),
        scales=tuple(float(value) for value in scales.tolist()),
        weights=tuple(tuple(float(value) for value in column) for column in weights.tolist()),
        biases=tuple(float(value) for value in biases.tolist()),
        classes=TRIBUNAL_CLASSES,
        training_count=len(rows),
        calibration_count=calibration_count,
        temperature=round(float(temperature), 4),
        confidence_floor=round(confidence_floor, 4),
        margin_floor=round(margin_floor, 4),
        entropy_ceiling=round(entropy_ceiling, 4),
        mean_brier=round(mean_brier, 4),
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
    probabilities = _softmax((standardized @ weights + biases) / max(float(model.temperature), 1e-6))[0]
    return {
        stance: round(float(probability), 4)
        for stance, probability in zip(model.classes, probabilities.tolist())
    }


def assess_tribunal_prediction(signal_packet: dict[str, Any], heuristic_scores: dict[str, float] | None = None) -> dict[str, Any] | None:
    model = get_tribunal_model()
    probabilities = predict_tribunal_probabilities(signal_packet, heuristic_scores)
    if model is None or probabilities is None:
        return None
    ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    top_view, top_prob = ranked[0]
    runner_up_prob = float(ranked[1][1]) if len(ranked) > 1 else 0.0
    margin = float(top_prob) - runner_up_prob
    probability_vector = np.array([[float(probabilities[stance]) for stance in model.classes]], dtype=float)
    entropy = float(_normalized_entropy(probability_vector)[0])
    below_confidence_floor = float(top_prob) < float(model.confidence_floor)
    below_margin_floor = margin < float(model.margin_floor)
    above_entropy_ceiling = entropy > float(model.entropy_ceiling)
    failed_signals = sum((below_confidence_floor, below_margin_floor, above_entropy_ceiling))
    if failed_signals >= 2:
        decision_posture = "abstain"
    elif failed_signals == 1:
        decision_posture = "escalate"
    else:
        decision_posture = "confident"

    material_evidence_gap = any(
        (
            bool(signal_packet.get("graph_thin")),
            int(signal_packet.get("graph_missing_required_edge_family_count") or 0) > 0,
            bool(signal_packet.get("ownership_evidence_thin")),
            bool(signal_packet.get("control_evidence_thin")),
            bool(signal_packet.get("official_coverage_thin")),
            bool(signal_packet.get("export_evidence_missing")),
            bool(signal_packet.get("cyber_evidence_missing")),
        )
    )
    if material_evidence_gap and top_view in {"approve", "watch"}:
        if decision_posture == "confident":
            decision_posture = "escalate"
        elif decision_posture == "escalate":
            decision_posture = "abstain"

    return {
        "top_view": top_view,
        "top_probability": round(float(top_prob), 4),
        "runner_up_probability": round(runner_up_prob, 4),
        "margin": round(margin, 4),
        "confidence_floor": float(model.confidence_floor),
        "margin_floor": float(model.margin_floor),
        "entropy": round(entropy, 4),
        "entropy_ceiling": float(model.entropy_ceiling),
        "temperature": float(model.temperature),
        "mean_brier": float(model.mean_brier),
        "material_evidence_gap": material_evidence_gap,
        "decision_posture": decision_posture,
        "requires_human_escalation": decision_posture in {"abstain", "escalate"},
    }


@lru_cache(maxsize=1)
def get_edge_family_reliability_profile() -> FamilyReliabilityProfile | None:
    if np is None:  # pragma: no cover
        return None
    rows = _build_edge_truth_training_rows()
    if not rows:
        return None

    positive_counts: dict[str, int] = {}
    negative_counts: dict[str, int] = {}
    total_positive = 0
    total_negative = 0

    for row in rows:
        family = str(row.get("edge_family") or "other")
        label = int(row.get("label") or 0)
        if label:
            positive_counts[family] = positive_counts.get(family, 0) + 1
            total_positive += 1
        else:
            negative_counts[family] = negative_counts.get(family, 0) + 1
            total_negative += 1

    family_scores: dict[str, float] = {}
    alpha = 1.0
    beta = 1.0
    for family in sorted(set(positive_counts) | set(negative_counts) | {"other"}):
        positives = float(positive_counts.get(family, 0))
        negatives = float(negative_counts.get(family, 0))
        posterior_mean = (alpha + positives) / (alpha + beta + positives + negatives)
        family_scores[family] = round(float(posterior_mean), 4)

    global_posterior = (alpha + total_positive) / (alpha + beta + total_positive + total_negative)
    return FamilyReliabilityProfile(
        posterior_mean_by_family=family_scores,
        global_posterior_mean=round(float(global_posterior), 4),
        training_count=len(rows),
    )
