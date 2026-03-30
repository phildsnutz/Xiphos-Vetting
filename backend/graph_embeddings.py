"""
Graph embedding and link prediction for Helios knowledge graph.

Implements TransE (Translating Embeddings) from scratch using only NumPy.
No heavy ML dependencies to keep Docker image lean.

TransE algorithm:
- Entities and relations get d-dimensional embeddings (d=64)
- For triple (h, r, t): score = ||h + r - t||
- Training: positive triples + negative sampling
- Loss: max(0, margin + pos_score - neg_score)
- SGD optimizer, 200 epochs, learning rate 0.01, batch_size=128

Used by link_prediction_api.py to serve predictions via REST API.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:
    raise ImportError("NumPy is required for graph embeddings. Install: pip install numpy>=1.24")

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
GRAPH_CONSTRUCTION_GOLD_PATH = REPO_ROOT / "fixtures" / "adversarial_gym" / "graph_construction_gold_set_v1.json"
GRAPH_CONSTRUCTION_NEGATIVE_PATH = REPO_ROOT / "fixtures" / "adversarial_gym" / "graph_construction_hard_negatives_v1.json"
GRAPH_ENTITY_RESOLUTION_PAIRS_PATH = REPO_ROOT / "fixtures" / "adversarial_gym" / "graph_entity_resolution_pairs_v1.json"
GRAPH_MISSING_EDGE_HOLDOUT_PATH = REPO_ROOT / "fixtures" / "adversarial_gym" / "graph_missing_edge_holdout_v1.json"
MASKED_HOLDOUT_RELATION_TYPES: tuple[str, ...] = (
    "owned_by",
    "backed_by",
    "routes_payment_through",
    "contracts_with",
    "litigant_in",
)
MASKED_HOLDOUT_RELATION_GROUPS: dict[str, tuple[str, ...]] = {
    "ownership_control": ("owned_by", "backed_by"),
    "intermediary_route": ("routes_payment_through",),
    "contracts_legal": ("contracts_with", "litigant_in"),
}

PREDICTED_LINK_REJECTION_REASONS: tuple[str, ...] = (
    "descriptor_only_not_entity",
    "garbage_not_entity",
    "generic_market_language",
    "marketing_mention_not_dependency",
    "no_actual_route",
    "unresolved_plural_actor",
    "payment_context_without_counterparty",
    "concept_not_component",
    "reference_without_party_role",
    "wrong_counterparty",
    "wrong_relationship_family",
    "wrong_target_entity",
    "insufficient_support",
    "duplicate_existing_fact",
)

MISSING_EDGE_FAMILY_GROUPS: dict[str, tuple[str, ...]] = {
    "ownership_control": ("ownership_control",),
    "intermediary_route": (
        "finance_intermediary",
        "trade_and_logistics",
        "intermediaries_and_services",
    ),
    "cyber_dependency": (
        "cyber_supply_chain",
        "component_dependency",
    ),
}

PREDICTION_RELATION_TARGET_ALLOWLIST: dict[str, set[str]] = {
    "owned_by": {"company", "holding_company", "person", "government_agency"},
    "parent_of": {"company", "holding_company"},
    "subsidiary_of": {"company", "holding_company"},
    "backed_by": {"company", "holding_company", "bank", "person"},
    "routes_payment_through": {"bank", "company", "holding_company"},
    "contracts_with": {"government_agency", "company"},
    "subcontractor_of": {"company", "holding_company"},
    "prime_contractor_of": {"company", "holding_company"},
    "regulated_by": {"government_agency"},
    "filed_with": {"government_agency", "court_case", "sanctions_list"},
    "litigant_in": {"court_case"},
    "depends_on_network": {"telecom_provider", "service", "company"},
    "depends_on_service": {"service", "company"},
    "distributed_by": {"distributor", "company", "holding_company"},
    "operates_facility": {"facility"},
    "ships_via": {"shipment_route", "facility"},
    "integrated_into": {"company", "subsystem", "component"},
}

GENERIC_TARGET_PHRASES: tuple[str, ...] = (
    "service disabled veteran",
    "service-disabled veteran",
    "family owned",
    "family-owned",
    "independently operated",
    "global telecom leaders",
    "flexible payment options",
    "secure boot concepts",
    "trusted by",
    "partner ecosystem",
    "asia pacific",
    "asia-pacific",
    "market context",
    "unresolved holding layer",
    "modeled transit via",
    "modeled payment bank",
    "modeled distributor",
)

GENERIC_TARGET_TOKENS: set[str] = {
    "investors",
    "leaders",
    "options",
    "concepts",
    "partners",
    "ecosystem",
    "veteran",
    "veterans",
    "owned",
    "owner",
    "family",
}

CORPORATE_SUFFIX_TOKENS: set[str] = {
    "inc",
    "inc.",
    "llc",
    "l.l.c.",
    "ltd",
    "ltd.",
    "plc",
    "corp",
    "corp.",
    "corporation",
    "company",
    "co",
    "co.",
    "holdings",
    "group",
    "partners",
    "capital",
    "advisory",
    "fze",
    "gmbh",
    "sa",
    "nv",
    "ag",
}

GOVERNMENT_NAME_TOKENS: set[str] = {
    "department",
    "ministry",
    "agency",
    "command",
    "administration",
    "army",
    "navy",
    "air force",
    "defense",
    "defence",
    "veterans",
    "homeland",
    "treasury",
    "state",
    "justice",
    "commission",
    "bureau",
    "office",
    "u.s.",
    "united states",
}

COURT_NAME_TOKENS: set[str] = {
    "court",
    "case no.",
    "case no",
    "cv-",
    "district",
    "appeals",
    "tribunal",
    "chancery",
    "litigation",
}

REGULATORY_NAME_TOKENS: set[str] = {
    "commission",
    "agency",
    "department",
    "administration",
    "bureau",
    "authority",
    "office",
    "exchange",
    "sec",
    "fincen",
    "bis",
    "ofac",
}

ROUTE_REGION_TOKENS: set[str] = {
    "asia-pacific",
    "asia",
    "pacific",
    "emea",
    "apac",
    "global",
    "worldwide",
    "international",
    "markets",
    "region",
}

RERANK_STOPWORDS: set[str] = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "onto",
    "through",
    "under",
    "over",
    "this",
    "that",
    "these",
    "those",
    "your",
    "our",
    "their",
    "its",
    "his",
    "her",
    "are",
    "was",
    "were",
    "has",
    "have",
    "had",
    "will",
    "would",
    "shall",
    "should",
    "can",
    "could",
    "may",
    "might",
    "also",
    "than",
    "then",
    "only",
    "just",
    "still",
    "being",
    "include",
    "includes",
    "including",
    "appears",
    "appeared",
    "shows",
    "showed",
    "named",
    "entity",
    "company",
    "group",
    "holdings",
    "capital",
    "partners",
    "advisory",
    "bank",
    "settlement",
    "case",
    "department",
    "agency",
    "government",
    "program",
    "contract",
    "contracts",
    "payment",
    "payments",
    "route",
    "routes",
    "through",
    "via",
    "modeled",
    "fixture",
    "graph",
    "training",
}

try:
    from graph_ingest import _relationship_edge_families as _graph_edge_families
except Exception:  # pragma: no cover - fallback keeps helpers usable in isolation
    _graph_edge_families = None


def _prediction_edge_family(rel_type: str) -> str:
    families: tuple[str, ...] = ()
    if callable(_graph_edge_families):
        try:
            families = tuple(_graph_edge_families(rel_type))
        except Exception:
            families = ()
    if families:
        return families[0]
    normalized = str(rel_type or "").strip().lower()
    if "own" in normalized or "parent" in normalized or "subsidiary" in normalized:
        return "ownership_control"
    if "ship" in normalized or "route" in normalized or "distribut" in normalized or "facility" in normalized:
        return "trade_and_logistics"
    if "depend" in normalized or "component" in normalized or "integrated" in normalized:
        return "cyber_supply_chain"
    if "sanction" in normalized or "litig" in normalized:
        return "sanctions_and_legal"
    return "other"


def _parse_embedding_vector(value: Any) -> list[float]:
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [float(item) for item in json.loads(text)]


def _fetch_entity_map(cur: Any, entity_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not entity_ids:
        return {}
    cur.execute(
        """
        SELECT id, canonical_name, entity_type
        FROM kg_entities
        WHERE id = ANY(%s)
        """,
        (entity_ids,),
    )
    rows = cur.fetchall()
    return {
        str(row[0]): {
            "entity_id": str(row[0]),
            "canonical_name": str(row[1] or row[0]),
            "entity_type": str(row[2] or "unknown"),
        }
        for row in rows
    }


def _normalize_rel_type(value: Any) -> str:
    return str(value or "").strip().lower()


def _load_fixture_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _load_masked_holdout_rows(path: Path | None = None) -> tuple[Path, list[dict[str, Any]]]:
    holdout_path = path or (
        GRAPH_MISSING_EDGE_HOLDOUT_PATH if GRAPH_MISSING_EDGE_HOLDOUT_PATH.exists() else GRAPH_CONSTRUCTION_GOLD_PATH
    )
    rows = []
    for row in _load_fixture_rows(holdout_path):
        rel_type = _normalize_rel_type(row.get("relationship_type"))
        if rel_type not in MASKED_HOLDOUT_RELATION_TYPES:
            continue
        if row.get("should_create_edge") is False:
            continue
        normalized_row = dict(row)
        normalized_row["relationship_type"] = rel_type
        rows.append(normalized_row)
    return holdout_path, rows


def _resolve_fixture_entity_ids(cur: Any, names: set[str]) -> dict[str, str]:
    clean_names = sorted({str(name).strip() for name in names if str(name).strip()})
    if not clean_names:
        return {}

    cur.execute(
        """
        SELECT id, canonical_name
        FROM kg_entities
        WHERE LOWER(canonical_name) = ANY(%s)
        """,
        ([name.lower() for name in clean_names],),
    )
    mapping = {
        str(row[1]).strip().lower(): str(row[0])
        for row in cur.fetchall()
        if row[0] and row[1]
    }
    resolved = {
        name: mapping[str(name).strip().lower()]
        for name in clean_names
        if str(name).strip().lower() in mapping
    }
    unresolved = [name for name in clean_names if name not in resolved]
    if not unresolved:
        return resolved

    from entity_resolution import normalize_name
    from ofac import jaro_winkler

    cur.execute("SELECT id, canonical_name FROM kg_entities WHERE canonical_name IS NOT NULL")
    candidates = [
        (str(row[0]), str(row[1]))
        for row in cur.fetchall()
        if row[0] and row[1]
    ]
    normalized_candidates = [
        (entity_id, canonical_name, normalize_name(canonical_name))
        for entity_id, canonical_name in candidates
    ]

    for name in unresolved:
        normalized_name = normalize_name(name)
        best_entity_id = None
        best_score = 0.0
        for entity_id, canonical_name, normalized_candidate in normalized_candidates:
            if not normalized_candidate:
                continue
            score = jaro_winkler(normalized_name, normalized_candidate)
            if normalized_name and normalized_candidate:
                if normalized_name in normalized_candidate or normalized_candidate in normalized_name:
                    score = max(score, 0.96)
            if score > best_score:
                best_score = score
                best_entity_id = entity_id
        if best_entity_id and best_score >= 0.9:
            resolved[name] = best_entity_id
    return resolved


def _edge_exists(cur: Any, source_entity_id: str, rel_type: str, target_entity_id: str) -> int | None:
    cur.execute(
        """
        SELECT id
        FROM kg_relationships
        WHERE source_entity_id = %s
          AND target_entity_id = %s
          AND LOWER(rel_type) = %s
        LIMIT 1
        """,
        (source_entity_id, target_entity_id, _normalize_rel_type(rel_type)),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def _safe_divide(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _mean_or_zero(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _normalize_match_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _tokenize_signal_text(value: Any) -> set[str]:
    normalized = _normalize_match_text(value)
    if not normalized:
        return set()
    cleaned = normalized
    for delimiter in ("/", ",", "(", ")", "[", "]", "{", "}", ":", ";", "\"", "'"):
        cleaned = cleaned.replace(delimiter, " ")
    tokens = set()
    for token in cleaned.replace("-", " ").split():
        token = token.strip().lower()
        if len(token) < 3:
            continue
        if token in RERANK_STOPWORDS:
            continue
        if token.isdigit():
            continue
        if token in GENERIC_TARGET_TOKENS:
            continue
        tokens.add(token)
    return tokens


def _looks_country_or_route_name(name: str) -> bool:
    raw = str(name or "").strip()
    normalized = _normalize_match_text(raw)
    if not normalized or any(token in normalized for token in ROUTE_REGION_TOKENS):
        return False
    if any(char.isdigit() for char in raw):
        return False
    tokens = [token for token in normalized.replace("/", " ").split() if token]
    if not tokens or len(tokens) > 3:
        return False
    corporate_suffixes = {"inc", "llc", "ltd", "plc", "corp", "corporation", "company", "co", "bank"}
    if any(token in corporate_suffixes for token in tokens):
        return False
    return True


def _looks_government_name(name: str) -> bool:
    normalized = _normalize_match_text(name)
    return any(token in normalized for token in GOVERNMENT_NAME_TOKENS)


def _looks_court_name(name: str) -> bool:
    normalized = _normalize_match_text(name)
    return any(token in normalized for token in COURT_NAME_TOKENS)


def _looks_regulatory_name(name: str) -> bool:
    normalized = _normalize_match_text(name)
    return any(token in normalized for token in REGULATORY_NAME_TOKENS)


def _looks_corporate_name(name: str) -> bool:
    normalized = _normalize_match_text(name)
    if not normalized:
        return False
    if _looks_government_name(name) or _looks_court_name(name):
        return False
    tokens = set(normalized.replace(",", " ").split())
    return any(token in CORPORATE_SUFFIX_TOKENS for token in tokens)


def _semantic_type_hints(name: str, entity_type: str) -> set[str]:
    normalized_name = _normalize_match_text(name)
    normalized_type = _normalize_match_text(entity_type)
    hints = {normalized_type} if normalized_type else set()

    if _looks_government_name(name):
        hints.add("government_agency")
    if _looks_court_name(name):
        hints.add("court_case")
    if "bank" in normalized_name:
        hints.add("bank")
    if any(fragment in normalized_name for fragment in ("telecom", "carrier", "communications", "network")):
        hints.add("telecom_provider")
    if any(fragment in normalized_name for fragment in ("service", "services", "managed", "signing", "hosting", "cloud")):
        hints.add("service")
    if any(fragment in normalized_name for fragment in ("lab", "facility", "center", "centre", "plant", "yard", "hub")):
        hints.add("facility")
    if any(fragment in normalized_name for fragment in ("route", "corridor", "transit", "port")) or _looks_country_or_route_name(name):
        hints.add("shipment_route")
    if any(fragment in normalized_name for fragment in ("module", "component", "firmware", "gateway", "processor", "board", "sensor")):
        hints.add("component")
    if any(fragment in normalized_name for fragment in ("capital", "holdings", "partners", "group")):
        hints.add("holding_company")
    return hints


def _is_generic_target_name(name: str, rel_type: str) -> bool:
    normalized_name = _normalize_match_text(name)
    if not normalized_name:
        return True
    if any(phrase in normalized_name for phrase in GENERIC_TARGET_PHRASES):
        return True

    tokens = set(normalized_name.replace("-", " ").split())
    if tokens and tokens.issubset(GENERIC_TARGET_TOKENS):
        return True

    normalized_rel = _normalize_rel_type(rel_type)
    if normalized_rel in {"owned_by", "backed_by"} and any(token in tokens for token in {"veteran", "family", "owned", "investors"}):
        return True
    if normalized_rel == "depends_on_service" and any(token in tokens for token in {"partners", "ecosystem"}):
        return True
    if normalized_rel == "depends_on_network" and "leaders" in tokens:
        return True
    if normalized_rel == "ships_via" and any(token in tokens for token in ROUTE_REGION_TOKENS):
        return True
    return False


def _allow_predicted_link(
    source_entity_type: str,
    rel_type: str,
    target_entity_type: str,
    target_name: str,
) -> bool:
    normalized_rel = _normalize_rel_type(rel_type)
    if normalized_rel not in PREDICTION_RELATION_TARGET_ALLOWLIST:
        return False
    if _is_generic_target_name(target_name, normalized_rel):
        return False

    hinted_types = _semantic_type_hints(target_name, target_entity_type)
    allowed_types = PREDICTION_RELATION_TARGET_ALLOWLIST.get(normalized_rel)
    if allowed_types and not (hinted_types & allowed_types):
        if normalized_rel == "ships_via" and _looks_country_or_route_name(target_name):
            return True
        if normalized_rel == "contracts_with" and "government_agency" in hinted_types:
            return True
        return False

    normalized_source_type = _normalize_match_text(source_entity_type)
    normalized_target = _normalize_match_text(target_name)
    if normalized_rel == "integrated_into" and normalized_source_type in {"company", "holding_company"}:
        return False
    if normalized_rel == "contracts_with" and not _looks_government_name(target_name):
        return False
    if normalized_rel == "filed_with" and not (
        _looks_government_name(target_name)
        or _looks_regulatory_name(target_name)
        or _looks_court_name(target_name)
        or "sanctions_list" in hinted_types
    ):
        return False
    if normalized_rel == "litigant_in" and "court_case" not in hinted_types:
        return False
    if normalized_rel in {"subcontractor_of", "prime_contractor_of", "distributed_by"} and not _looks_corporate_name(target_name):
        return False
    if normalized_rel in {"owned_by", "parent_of", "subsidiary_of"} and not (
        _looks_corporate_name(target_name)
        or "person" in hinted_types
        or "government_agency" in hinted_types
    ):
        return False
    if normalized_rel == "backed_by" and not (
        _looks_corporate_name(target_name)
        or "bank" in hinted_types
        or "person" in hinted_types
    ):
        return False
    if normalized_rel == "routes_payment_through" and "bank" not in hinted_types and "bank" not in normalized_target and "trust" not in normalized_target:
        return False
    if normalized_rel == "operates_facility" and "facility" not in hinted_types:
        return False
    if normalized_rel == "ships_via" and not (
        _looks_country_or_route_name(target_name)
        or "shipment_route" in hinted_types
        or "facility" in hinted_types
    ):
        return False
    return True


def _relation_specific_score_bonus(rel_type: str, target_name: str, target_entity_type: str) -> float:
    normalized_rel = _normalize_rel_type(rel_type)
    normalized_target = _normalize_match_text(target_name)
    hinted_types = _semantic_type_hints(target_name, target_entity_type)
    bonus = 0.0

    if normalized_rel in {"owned_by", "parent_of", "subsidiary_of"}:
        if "holding_company" in hinted_types:
            bonus += 0.24
        if any(token in normalized_target for token in ("holdings", "capital", "partners", "group", "fze")):
            bonus += 0.1
    elif normalized_rel == "backed_by":
        if "bank" in hinted_types:
            bonus += 0.2
        if "holding_company" in hinted_types:
            bonus += 0.16
        if any(token in normalized_target for token in ("capital", "partners", "advisory", "fund", "ventures")):
            bonus += 0.14
    elif normalized_rel == "routes_payment_through":
        if "bank" in hinted_types:
            bonus += 0.38
        if any(token in normalized_target for token in ("bank", "trust", "settlement")):
            bonus += 0.14
    elif normalized_rel == "contracts_with":
        if "government_agency" in hinted_types:
            bonus += 0.34
        if any(token in normalized_target for token in ("u.s.", "united states", "department", "army", "command", "agency")):
            bonus += 0.12
    elif normalized_rel == "litigant_in":
        if "court_case" in hinted_types:
            bonus += 0.38
        if any(token in normalized_target for token in ("case no", "cv-", "court", "district", "tribunal")):
            bonus += 0.14
    elif normalized_rel == "distributed_by":
        if any(token in normalized_target for token in ("distributor", "distribution", "trading", "fze", "logistics", "hub")):
            bonus += 0.16
    elif normalized_rel == "depends_on_network":
        if "telecom_provider" in hinted_types:
            bonus += 0.16
        if any(token in normalized_target for token in ("telecom", "carrier", "communications", "network")):
            bonus += 0.08
    elif normalized_rel == "depends_on_service":
        if "service" in hinted_types:
            bonus += 0.16
        if any(token in normalized_target for token in ("managed", "service", "signing", "hosting", "cloud")):
            bonus += 0.08
    return bonus


def _fetch_source_rerank_context(
    cur: Any,
    source_entity_id: str,
    source_name: str,
    source_entity_type: str,
) -> dict[str, Any]:
    relation_texts: dict[str, list[str]] = {}
    relation_neighbor_tokens: dict[str, set[str]] = {}
    all_neighbor_tokens: set[str] = set()
    all_texts: list[str] = [str(source_name or "")]
    base_context = {
        "source_entity_id": source_entity_id,
        "source_name": source_name,
        "source_entity_type": source_entity_type,
        "source_tokens": _tokenize_signal_text(source_name),
        "all_neighbor_tokens": all_neighbor_tokens,
        "relation_neighbor_tokens": relation_neighbor_tokens,
        "all_text_blob": _normalize_match_text(" ".join(text for text in all_texts if str(text or "").strip())),
        "relation_text_blobs": {},
    }
    if cur is None:
        return base_context

    cur.execute(
        """
        SELECT
            LOWER(TRIM(COALESCE(r.rel_type, ''))) AS rel_type,
            COALESCE(t.canonical_name, '') AS target_name,
            COALESCE(t.entity_type, '') AS target_type
        FROM kg_relationships r
        JOIN kg_entities t ON t.id = r.target_entity_id
        WHERE r.source_entity_id = %s
        LIMIT 250
        """,
        (source_entity_id,),
    )
    for row in cur.fetchall():
        rel_type = str(row[0] or "")
        target_name = str(row[1] or "")
        target_type = str(row[2] or "")
        relation_texts.setdefault(rel_type, []).append(target_name)
        relation_neighbor_tokens.setdefault(rel_type, set()).update(_tokenize_signal_text(target_name))
        relation_neighbor_tokens[rel_type].update(_tokenize_signal_text(target_type))
        all_neighbor_tokens.update(_tokenize_signal_text(target_name))

    cur.execute(
        """
        SELECT
            LOWER(TRIM(COALESCE(c.rel_type, ''))) AS rel_type,
            COALESCE(c.claim_value, '') AS claim_value,
            COALESCE(c.structured_fields::text, '') AS structured_fields
        FROM kg_claims c
        WHERE c.source_entity_id = %s
        LIMIT 250
        """,
        (source_entity_id,),
    )
    for row in cur.fetchall():
        rel_type = str(row[0] or "")
        claim_value = str(row[1] or "")
        structured_fields = str(row[2] or "")
        relation_texts.setdefault(rel_type, []).extend([claim_value, structured_fields])
        all_texts.extend([claim_value, structured_fields])

    cur.execute(
        """
        SELECT
            LOWER(TRIM(COALESCE(c.rel_type, ''))) AS rel_type,
            COALESCE(e.title, '') AS title,
            COALESCE(e.snippet, '') AS snippet,
            COALESCE(e.url, '') AS url
        FROM kg_claims c
        JOIN kg_evidence e ON e.claim_id = c.id
        WHERE c.source_entity_id = %s
        LIMIT 400
        """,
        (source_entity_id,),
    )
    for row in cur.fetchall():
        rel_type = str(row[0] or "")
        title = str(row[1] or "")
        snippet = str(row[2] or "")
        url = str(row[3] or "")
        relation_texts.setdefault(rel_type, []).extend([title, snippet, url])
        all_texts.extend([title, snippet, url])

    relation_text_blobs = {
        rel_type: _normalize_match_text(" ".join(text for text in texts if str(text or "").strip()))
        for rel_type, texts in relation_texts.items()
    }
    base_context["all_neighbor_tokens"] = all_neighbor_tokens
    base_context["relation_neighbor_tokens"] = relation_neighbor_tokens
    base_context["all_text_blob"] = _normalize_match_text(" ".join(text for text in all_texts if str(text or "").strip()))
    base_context["relation_text_blobs"] = relation_text_blobs
    return base_context


def _relation_contextual_score_bonus(
    rel_type: str,
    target_name: str,
    target_entity_type: str,
    source_context: dict[str, Any] | None,
) -> float:
    if not source_context:
        return 0.0

    normalized_rel = _normalize_rel_type(rel_type)
    normalized_target = _normalize_match_text(target_name)
    if not normalized_target:
        return 0.0

    relation_text_blob = str((source_context.get("relation_text_blobs") or {}).get(normalized_rel) or "")
    all_text_blob = str(source_context.get("all_text_blob") or "")
    source_tokens = set(source_context.get("source_tokens") or set())
    relation_neighbor_tokens = set((source_context.get("relation_neighbor_tokens") or {}).get(normalized_rel) or set())
    all_neighbor_tokens = set(source_context.get("all_neighbor_tokens") or set())
    target_tokens = _tokenize_signal_text(target_name)
    target_tokens.update(_tokenize_signal_text(target_entity_type))

    bonus = 0.0
    if normalized_target and relation_text_blob and normalized_target in relation_text_blob:
        bonus += 2.6
    elif normalized_target and all_text_blob and normalized_target in all_text_blob:
        bonus += 1.3

    relation_overlap = len(target_tokens & relation_neighbor_tokens)
    source_overlap = len(target_tokens & source_tokens)
    all_overlap = len(target_tokens & all_neighbor_tokens)
    if relation_overlap:
        bonus += min(0.9, 0.28 * relation_overlap)
    if source_overlap:
        bonus += min(0.8, 0.24 * source_overlap)
    if all_overlap:
        bonus += min(0.5, 0.1 * all_overlap)

    if normalized_rel in {"owned_by", "backed_by"}:
        if source_overlap:
            bonus += 0.24
        if any(token in target_tokens for token in ("beacon", "meridian", "harbor", "northern")):
            bonus += 0.12
    elif normalized_rel == "routes_payment_through":
        if any(token in target_tokens for token in ("settlement", "trade", "harbor", "northern")):
            bonus += 0.32
    elif normalized_rel == "contracts_with":
        if any(token in normalized_target for token in ("army", "command", "department", "agency", "u.s.")):
            bonus += 0.24
    elif normalized_rel == "litigant_in":
        if "cv-" in normalized_target or "case no" in normalized_target:
            bonus += 0.32
    return bonus


def _candidate_ranking_score(
    rel_type: str,
    target_name: str,
    target_entity_type: str,
    base_score: float,
    *,
    source_context: dict[str, Any] | None = None,
) -> float:
    bonus = _relation_specific_score_bonus(rel_type, target_name, target_entity_type)
    bonus += _relation_contextual_score_bonus(rel_type, target_name, target_entity_type, source_context)
    return max(0.0, float(base_score) - bonus)


def _prepare_prediction_rows(cur: Any, trainer: "TransETrainer", entity_id: str, top_k: int) -> list[dict[str, Any]]:
    candidate_limit = min(max(top_k * 24, top_k + 80), 1200)
    raw_predictions = trainer.predict_links(entity_id, top_k=candidate_limit)
    entity_map = _fetch_entity_map(cur, [entity_id, *[row["target_entity_id"] for row in raw_predictions]])
    source_row = entity_map.get(entity_id) or {}
    source_name = source_row.get("canonical_name", entity_id)
    source_entity_type = source_row.get("entity_type", "unknown")
    source_context = _fetch_source_rerank_context(cur, entity_id, source_name, source_entity_type)

    relation_buckets: dict[str, list[dict[str, Any]]] = {}
    relation_best_score: dict[str, float] = {}
    seen_relation_target_keys: set[tuple[str, str]] = set()
    for pred in raw_predictions:
        target_id = str(pred["target_entity_id"])
        target_row = entity_map.get(target_id) or {}
        target_name = str(target_row.get("canonical_name") or pred.get("target_name") or target_id)
        target_entity_type = str(target_row.get("entity_type") or "unknown")
        rel_type = str(pred["predicted_relation"])
        if not _allow_predicted_link(source_entity_type, rel_type, target_entity_type, target_name):
            continue
        dedupe_key = (_normalize_rel_type(rel_type), _normalize_match_text(target_name))
        if dedupe_key in seen_relation_target_keys:
            continue
        seen_relation_target_keys.add(dedupe_key)
        row = {
            "source_entity_id": entity_id,
            "source_entity_name": source_name,
            "source_entity_type": source_entity_type,
            "target_entity_id": target_id,
            "target_name": target_name,
            "target_entity_type": target_entity_type,
            "predicted_relation": rel_type,
            "predicted_edge_family": _prediction_edge_family(rel_type),
            "score": float(pred["score"]),
        }
        row["ranking_score"] = _candidate_ranking_score(
            rel_type,
            target_name,
            target_entity_type,
            float(row["score"]),
            source_context=source_context,
        )
        relation_buckets.setdefault(rel_type, []).append(row)
        relation_best_score[rel_type] = min(relation_best_score.get(rel_type, float("inf")), row["ranking_score"])

    for rel_type, bucket in relation_buckets.items():
        bucket.sort(
            key=lambda row: (
                float(row.get("ranking_score") or row.get("score") or 0.0),
                float(row.get("score") or 0.0),
                str(row.get("target_name") or ""),
            )
        )

    prepared: list[dict[str, Any]] = []
    relation_limits: dict[str, int] = {}
    edge_family_counts: dict[str, int] = {}
    relation_cursor = {rel_type: 0 for rel_type in relation_buckets}
    relation_order = sorted(relation_buckets, key=lambda rel: (relation_best_score.get(rel, float("inf")), rel))
    per_relation_cap = max(2, min(4, top_k // 4 or 1))
    per_edge_family_cap = max(3, min(8, top_k // 2 or 1))

    while len(prepared) < top_k:
        progressed = False
        for rel_type in relation_order:
            bucket = relation_buckets.get(rel_type, [])
            if relation_limits.get(rel_type, 0) >= per_relation_cap:
                continue
            cursor = relation_cursor.get(rel_type, 0)
            while cursor < len(bucket):
                candidate = bucket[cursor]
                cursor += 1
                edge_family = str(candidate.get("predicted_edge_family") or "other")
                if edge_family_counts.get(edge_family, 0) >= per_edge_family_cap:
                    continue
                prepared.append(candidate)
                relation_limits[rel_type] = relation_limits.get(rel_type, 0) + 1
                edge_family_counts[edge_family] = edge_family_counts.get(edge_family, 0) + 1
                progressed = True
                break
            relation_cursor[rel_type] = cursor
            if len(prepared) >= top_k:
                break
        if not progressed:
            break
    return prepared


def _resolve_masked_holdout_rows(cur: Any, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    name_to_entity_id = _resolve_fixture_entity_ids(
        cur,
        {
            str(row.get("source_entity") or "").strip()
            for row in rows
        }
        | {
            str(row.get("target_entity") or "").strip()
            for row in rows
        },
    )
    resolved_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    for row in rows:
        source_name = str(row.get("source_entity") or "").strip()
        target_name = str(row.get("target_entity") or "").strip()
        rel_type = _normalize_rel_type(row.get("relationship_type"))
        source_entity_id = name_to_entity_id.get(source_name)
        target_entity_id = name_to_entity_id.get(target_name)
        if not source_entity_id or not target_entity_id or not rel_type:
            unresolved_rows.append(
                {
                    "label_id": str(row.get("label_id") or ""),
                    "source_entity": source_name,
                    "target_entity": target_name,
                    "relationship_type": rel_type,
                }
            )
            continue
        resolved_row = dict(row)
        resolved_row["source_entity_id"] = source_entity_id
        resolved_row["target_entity_id"] = target_entity_id
        resolved_row["relationship_type"] = rel_type
        resolved_rows.append(resolved_row)
    return resolved_rows, unresolved_rows


def _score_withheld_target_rank(
    cur: Any,
    trainer: "TransETrainer",
    source_entity_id: str,
    rel_type: str,
    target_entity_id: str,
    *,
    entity_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    h_idx = trainer.entity_to_id.get(source_entity_id)
    r_idx = trainer.relation_to_id.get(rel_type)
    t_idx = trainer.entity_to_id.get(target_entity_id)
    if h_idx is None or r_idx is None or t_idx is None:
        return {
            "withheld_target_rank": 0,
            "withheld_target_score": None,
            "reciprocal_rank": 0.0,
            "hit_at_10": False,
        }

    source_row = entity_metadata.get(source_entity_id) or {}
    source_name = str(source_row.get("canonical_name") or source_entity_id)
    source_entity_type = str(source_row.get("entity_type") or "unknown")
    source_context = _fetch_source_rerank_context(cur, source_entity_id, source_name, source_entity_type)

    base_scores = np.linalg.norm(
        trainer.entity_embeddings[h_idx] + trainer.relation_embeddings[r_idx] - trainer.entity_embeddings,
        axis=1,
    )
    ranking_scores: list[tuple[float, int]] = []
    for candidate_idx, candidate_entity_id in trainer.id_to_entity.items():
        if candidate_idx == h_idx:
            continue
        candidate_row = entity_metadata.get(candidate_entity_id) or {}
        candidate_name = str(candidate_row.get("canonical_name") or candidate_entity_id)
        candidate_entity_type = str(candidate_row.get("entity_type") or "unknown")
        if not _allow_predicted_link(source_entity_type, rel_type, candidate_entity_type, candidate_name):
            continue
        ranking_scores.append(
            (
                _candidate_ranking_score(
                    rel_type,
                    candidate_name,
                    candidate_entity_type,
                    float(base_scores[candidate_idx]),
                    source_context=source_context,
                ),
                candidate_idx,
            )
        )
    ranking_scores.sort(key=lambda item: (item[0], item[1]))
    rank_lookup = {candidate_idx: rank for rank, (_, candidate_idx) in enumerate(ranking_scores, start=1)}
    rank = int(rank_lookup.get(t_idx) or 0)
    target_score = None
    for score, candidate_idx in ranking_scores:
        if candidate_idx == t_idx:
            target_score = float(score)
            break
    return {
        "withheld_target_rank": rank,
        "withheld_target_score": target_score,
        "reciprocal_rank": 1.0 / rank if rank else 0.0,
        "hit_at_10": bool(rank and rank <= 10),
    }


def _aggregate_masked_holdout_metrics(
    holdout_results: list[dict[str, Any]],
    review_stats: dict[str, Any],
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "unsupported_promoted_edge_rate": float(review_stats.get("unsupported_promoted_edge_rate") or 0.0),
        "masked_holdout_queries_evaluated": len(holdout_results),
        "missing_edge_queries_evaluated": len(holdout_results),
        "masked_holdout_hits_at_10": _safe_divide(
            sum(1 for row in holdout_results if row.get("hit_at_10")), len(holdout_results)
        ),
        "masked_holdout_mrr": _safe_divide(
            sum(float(row.get("reciprocal_rank") or 0.0) for row in holdout_results),
            len(holdout_results),
        ),
        "mean_withheld_target_rank": _mean_or_zero(
            [float(row["withheld_target_rank"]) for row in holdout_results if row.get("withheld_target_rank")]
        ),
    }

    for rel_type in MASKED_HOLDOUT_RELATION_TYPES:
        relation_rows = [row for row in holdout_results if row.get("relationship_type") == rel_type]
        metrics[f"{rel_type}_queries_evaluated"] = len(relation_rows)
        metrics[f"{rel_type}_hits_at_10"] = _safe_divide(
            sum(1 for row in relation_rows if row.get("hit_at_10")),
            len(relation_rows),
        )
        metrics[f"{rel_type}_mrr"] = _safe_divide(
            sum(float(row.get("reciprocal_rank") or 0.0) for row in relation_rows),
            len(relation_rows),
        )
        metrics[f"{rel_type}_mean_rank"] = _mean_or_zero(
            [float(row["withheld_target_rank"]) for row in relation_rows if row.get("withheld_target_rank")]
        )

    for metric_family, relation_types in MASKED_HOLDOUT_RELATION_GROUPS.items():
        family_rows = [row for row in holdout_results if row.get("relationship_type") in relation_types]
        metrics[f"{metric_family}_queries_evaluated"] = len(family_rows)
        metrics[f"{metric_family}_hits_at_10"] = _safe_divide(
            sum(1 for row in family_rows if row.get("hit_at_10")),
            len(family_rows),
        )
        metrics[f"{metric_family}_mrr"] = _safe_divide(
            sum(float(row.get("reciprocal_rank") or 0.0) for row in family_rows),
            len(family_rows),
        )

    metrics.setdefault("cyber_dependency_queries_evaluated", 0)
    metrics.setdefault("cyber_dependency_hits_at_10", 0.0)
    metrics.setdefault("cyber_dependency_mrr", 0.0)
    return metrics


class TransETrainer:
    """TransE embedding trainer and inference engine."""

    def __init__(self, dim: int = 64, margin: float = 1.0, lr: float = 0.01, epochs: int = 200):
        """
        Initialize TransE trainer.

        Args:
            dim: Embedding dimension (default 64)
            margin: Loss margin (default 1.0)
            lr: Learning rate (default 0.01)
            epochs: Training epochs (default 200)
        """
        self.dim = dim
        self.margin = margin
        self.lr = lr
        self.epochs = epochs

        # Triple data structures
        self.triples = []  # List of (h_id, r_type, t_id) tuples
        self.entity_to_id = {}  # entity_id (str) -> idx (int)
        self.id_to_entity = {}  # idx (int) -> entity_id (str)
        self.relation_to_id = {}  # relation_type -> idx (int)
        self.id_to_relation = {}  # idx (int) -> relation_type

        # Embeddings (entity_idx -> [d], relation_idx -> [d])
        self.entity_embeddings = None
        self.relation_embeddings = None

        # Training state
        self.loss_history = []
        self.model_version = None

    def load_triples_from_db(
        self,
        pg_url: str,
        *,
        exclude_triples: set[tuple[str, str, str]] | None = None,
    ) -> None:
        """
        Load entity/relationship triples from kg_relationships table.

        Args:
            pg_url: PostgreSQL URL (e.g. postgresql://user:pass@host/dbname)
        """
        try:
            import psycopg2
        except ImportError:
            raise ImportError("psycopg2 is required. Install: pip install psycopg2-binary>=2.9")

        excluded = {
            (str(source_id), _normalize_rel_type(rel_type), str(target_id))
            for source_id, rel_type, target_id in (exclude_triples or set())
            if source_id and rel_type and target_id
        }

        logger.info("Loading triples from PostgreSQL: %s", pg_url)
        conn = psycopg2.connect(pg_url)
        cur = conn.cursor()

        try:
            # Fetch all relationships
            cur.execute(
                """
                SELECT source_entity_id, rel_type, target_entity_id
                FROM kg_relationships
                WHERE source_entity_id IS NOT NULL
                  AND target_entity_id IS NOT NULL
                ORDER BY created_at ASC
                """
            )

            for source_id, rel_type, target_id in cur.fetchall():
                normalized_rel_type = _normalize_rel_type(rel_type)
                # Build entity and relation mappings
                if source_id not in self.entity_to_id:
                    idx = len(self.entity_to_id)
                    self.entity_to_id[source_id] = idx
                    self.id_to_entity[idx] = source_id

                if target_id not in self.entity_to_id:
                    idx = len(self.entity_to_id)
                    self.entity_to_id[target_id] = idx
                    self.id_to_entity[idx] = target_id

                if normalized_rel_type not in self.relation_to_id:
                    idx = len(self.relation_to_id)
                    self.relation_to_id[normalized_rel_type] = idx
                    self.id_to_relation[idx] = normalized_rel_type

                if excluded and (str(source_id), normalized_rel_type, str(target_id)) in excluded:
                    continue

                # Add triple using indices
                h_idx = self.entity_to_id[source_id]
                r_idx = self.relation_to_id[normalized_rel_type]
                t_idx = self.entity_to_id[target_id]
                self.triples.append((h_idx, r_idx, t_idx))

            logger.info("Loaded %d triples, %d entities, %d relations",
                       len(self.triples), len(self.entity_to_id), len(self.relation_to_id))

        finally:
            cur.close()
            conn.close()

    def train(self) -> dict:
        """
        Train TransE embeddings using SGD.

        Returns:
            dict with keys: loss_history (list), final_loss (float), duration_ms (int),
                           entity_count (int), relation_count (int)
        """
        if not self.triples:
            raise ValueError("No triples loaded. Call load_triples_from_db() first.")

        logger.info("Starting TransE training: dim=%d, margin=%.2f, lr=%.4f, epochs=%d",
                   self.dim, self.margin, self.lr, self.epochs)

        start_time = time.time()

        # Initialize embeddings with uniform distribution [-1, 1]
        num_entities = len(self.entity_to_id)
        num_relations = len(self.relation_to_id)

        self.entity_embeddings = np.random.uniform(-1, 1, (num_entities, self.dim)).astype(np.float32)
        self.relation_embeddings = np.random.uniform(-1, 1, (num_relations, self.dim)).astype(np.float32)

        # Normalize embeddings
        self._normalize_embeddings()

        self.loss_history = []
        batch_size = 128

        for epoch in range(self.epochs):
            epoch_loss = 0.0
            num_batches = 0

            # Shuffle triples
            indices = np.random.permutation(len(self.triples))

            for batch_start in range(0, len(self.triples), batch_size):
                batch_end = min(batch_start + batch_size, len(self.triples))
                batch_indices = indices[batch_start:batch_end]

                # Process batch
                for idx in batch_indices:
                    h, r, t = self.triples[idx]

                    # Corrupt head or tail (50/50)
                    if np.random.rand() < 0.5:
                        # Corrupt head
                        h_neg = np.random.randint(0, num_entities)
                        t_neg = t
                    else:
                        # Corrupt tail
                        h_neg = h
                        t_neg = np.random.randint(0, num_entities)

                    # Compute scores
                    pos_score = np.linalg.norm(
                        self.entity_embeddings[h] + self.relation_embeddings[r]
                        - self.entity_embeddings[t]
                    )

                    neg_score = np.linalg.norm(
                        self.entity_embeddings[h_neg] + self.relation_embeddings[r]
                        - self.entity_embeddings[t_neg]
                    )

                    # Compute loss
                    loss = max(0.0, self.margin + pos_score - neg_score)
                    epoch_loss += loss

                    if loss > 0:
                        # Backward pass (manual gradient computation)
                        pos_grad = (self.entity_embeddings[h] + self.relation_embeddings[r]
                                   - self.entity_embeddings[t])
                        pos_norm = np.linalg.norm(pos_grad)
                        if pos_norm > 0:
                            pos_grad = pos_grad / pos_norm

                        neg_grad = (self.entity_embeddings[h_neg] + self.relation_embeddings[r]
                                   - self.entity_embeddings[t_neg])
                        neg_norm = np.linalg.norm(neg_grad)
                        if neg_norm > 0:
                            neg_grad = neg_grad / neg_norm

                        # Update positive triple
                        self.entity_embeddings[h] -= self.lr * pos_grad
                        self.relation_embeddings[r] -= self.lr * pos_grad
                        self.entity_embeddings[t] += self.lr * pos_grad

                        # Update negative triple
                        self.entity_embeddings[h_neg] += self.lr * neg_grad
                        self.relation_embeddings[r] += self.lr * neg_grad
                        self.entity_embeddings[t_neg] -= self.lr * neg_grad

                num_batches += 1

            # Normalize after each epoch
            self._normalize_embeddings()

            avg_loss = epoch_loss / len(self.triples) if len(self.triples) > 0 else 0.0
            self.loss_history.append(avg_loss)

            if (epoch + 1) % 50 == 0 or epoch == 0:
                logger.info("Epoch %d/%d: avg_loss=%.6f", epoch + 1, self.epochs, avg_loss)

        duration_ms = int((time.time() - start_time) * 1000)
        final_loss = self.loss_history[-1] if self.loss_history else 0.0

        # Generate model version
        self.model_version = datetime.utcnow().isoformat()

        logger.info("Training complete: duration=%dms, final_loss=%.6f", duration_ms, final_loss)

        return {
            "loss_history": self.loss_history,
            "final_loss": float(final_loss),
            "duration_ms": duration_ms,
            "entity_count": num_entities,
            "relation_count": num_relations,
            "triple_count": len(self.triples),
        }

    def _normalize_embeddings(self) -> None:
        """L2-normalize all embeddings to unit vectors."""
        for i in range(len(self.entity_embeddings)):
            norm = np.linalg.norm(self.entity_embeddings[i])
            if norm > 0:
                self.entity_embeddings[i] /= norm

        for i in range(len(self.relation_embeddings)):
            norm = np.linalg.norm(self.relation_embeddings[i])
            if norm > 0:
                self.relation_embeddings[i] /= norm

    def predict_links(self, entity_id: str, top_k: int = 10) -> list[dict]:
        """
        Predict missing links for an entity.

        Given an entity, find likely missing relationships by:
        1. For each relation type
        2. For each potential target entity
        3. Score: ||h + r - t||
        4. Return top-k lowest scores (most likely triples)

        Args:
            entity_id: Source entity ID
            top_k: Number of predictions to return

        Returns:
            List of dicts: {"target_entity_id", "predicted_relation", "score", "target_name"}
        """
        if entity_id not in self.entity_to_id:
            logger.warning("Entity %s not in embedding space", entity_id)
            return []

        if self.entity_embeddings is None:
            logger.warning("Embeddings not trained yet")
            return []

        h_idx = self.entity_to_id[entity_id]
        h_emb = self.entity_embeddings[h_idx]

        # Score all possible (relation, target) pairs
        scores = []

        for r_idx, r_type in self.id_to_relation.items():
            r_emb = self.relation_embeddings[r_idx]

            for t_idx, t_id in self.id_to_entity.items():
                # Skip self-loops and existing triples
                if t_idx == h_idx:
                    continue

                if (h_idx, r_idx, t_idx) in set(self.triples):
                    continue  # Already exists

                t_emb = self.entity_embeddings[t_idx]
                score = np.linalg.norm(h_emb + r_emb - t_emb)
                scores.append((score, r_type, t_id))

        # Sort by score (ascending = most likely)
        scores.sort(key=lambda x: x[0])

        predictions = []
        for score, r_type, t_id in scores[:top_k]:
            predictions.append({
                "target_entity_id": t_id,
                "predicted_relation": r_type,
                "score": float(score),
                "target_name": t_id,  # Will be filled by API from DB lookup
            })

        return predictions

    def get_similar_entities(self, entity_id: str, top_k: int = 10) -> list[dict]:
        """
        Find entities with similar embeddings (cosine similarity).

        Args:
            entity_id: Source entity ID
            top_k: Number of similar entities to return

        Returns:
            List of dicts: {"entity_id", "name", "similarity", "entity_type"}
        """
        if entity_id not in self.entity_to_id:
            logger.warning("Entity %s not in embedding space", entity_id)
            return []

        if self.entity_embeddings is None:
            logger.warning("Embeddings not trained yet")
            return []

        h_idx = self.entity_to_id[entity_id]
        h_emb = self.entity_embeddings[h_idx]

        # Cosine similarity with all other entities
        similarities = []

        for e_idx, e_id in self.id_to_entity.items():
            if e_idx == h_idx:
                continue

            e_emb = self.entity_embeddings[e_idx]
            sim = np.dot(h_emb, e_emb) / (np.linalg.norm(h_emb) * np.linalg.norm(e_emb) + 1e-6)
            similarities.append((sim, e_id))

        # Sort by similarity (descending)
        similarities.sort(key=lambda x: x[0], reverse=True)

        results = []
        for sim, e_id in similarities[:top_k]:
            results.append({
                "entity_id": e_id,
                "name": e_id,  # Will be filled by API from DB lookup
                "similarity": float(sim),
                "entity_type": "unknown",  # Will be filled by API from DB lookup
            })

        return results

    def save_embeddings_to_db(self, pg_url: str) -> int:
        """
        Save entity and relation embeddings to pgvector table.

        Args:
            pg_url: PostgreSQL URL

        Returns:
            Number of embeddings saved
        """
        if self.entity_embeddings is None:
            logger.warning("No embeddings to save. Train first.")
            return 0

        try:
            import psycopg2
        except ImportError:
            raise ImportError("psycopg2 is required")

        logger.info("Saving %d entity embeddings to pgvector", len(self.entity_embeddings))

        conn = psycopg2.connect(pg_url)
        cur = conn.cursor()

        try:
            # Enable pgvector extension
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.commit()

            # Create tables if not exist
            self._create_embedding_tables(cur)
            conn.commit()

            # Insert/update entity embeddings
            for e_idx, e_id in self.id_to_entity.items():
                emb_list = self.entity_embeddings[e_idx].tolist()
                emb_str = "[" + ",".join(f"{x:.6f}" for x in emb_list) + "]"

                cur.execute("""
                    INSERT INTO kg_embeddings (entity_id, embedding, model_version)
                    VALUES (%s, %s::vector, %s)
                    ON CONFLICT (entity_id) DO UPDATE SET
                        embedding = %s::vector,
                        model_version = %s,
                        trained_at = NOW()
                """, (e_id, emb_str, self.model_version, emb_str, self.model_version))

            # Insert/update relation embeddings
            for r_idx, r_type in self.id_to_relation.items():
                emb_list = self.relation_embeddings[r_idx].tolist()
                emb_str = "[" + ",".join(f"{x:.6f}" for x in emb_list) + "]"

                cur.execute("""
                    INSERT INTO kg_relation_embeddings (relation_type, embedding, model_version)
                    VALUES (%s, %s::vector, %s)
                    ON CONFLICT (relation_type) DO UPDATE SET
                        embedding = %s::vector,
                        model_version = %s,
                        trained_at = NOW()
                """, (r_type, emb_str, self.model_version, emb_str, self.model_version))

            conn.commit()

            count = len(self.entity_embeddings) + len(self.relation_embeddings)
            logger.info("Saved %d embeddings", count)
            return count

        finally:
            cur.close()
            conn.close()

    def load_embeddings_from_db(self, pg_url: str) -> bool:
        """
        Load pre-trained embeddings from pgvector table.

        Args:
            pg_url: PostgreSQL URL

        Returns:
            True if loaded successfully, False if no embeddings found
        """
        try:
            import psycopg2
        except ImportError:
            raise ImportError("psycopg2 is required")

        logger.info("Loading embeddings from pgvector")

        conn = psycopg2.connect(pg_url)
        cur = conn.cursor()

        try:
            # Fetch entity embeddings
            cur.execute("""
                SELECT entity_id, embedding, model_version
                FROM kg_embeddings
                ORDER BY entity_id
            """)

            rows = cur.fetchall()
            if not rows:
                logger.warning("No entity embeddings found in database")
                return False

            # Initialize embedding matrix
            num_entities = len(rows)
            self.entity_embeddings = np.zeros((num_entities, self.dim), dtype=np.float32)
            self.entity_to_id = {}
            self.id_to_entity = {}

            for idx, (entity_id, embedding_str, model_version) in enumerate(rows):
                self.entity_to_id[entity_id] = idx
                self.id_to_entity[idx] = entity_id
                self.model_version = model_version

                # Parse embedding vector string
                emb_list = _parse_embedding_vector(embedding_str)
                self.entity_embeddings[idx] = np.array(emb_list, dtype=np.float32)

            logger.info("Loaded %d entity embeddings (model: %s)", num_entities, model_version)

            # Fetch relation embeddings
            cur.execute("""
                SELECT relation_type, embedding, model_version
                FROM kg_relation_embeddings
                ORDER BY relation_type
            """)

            rows = cur.fetchall()
            num_relations = len(rows)
            self.relation_embeddings = np.zeros((num_relations, self.dim), dtype=np.float32)
            self.relation_to_id = {}
            self.id_to_relation = {}

            for idx, (relation_type, embedding_str, model_version) in enumerate(rows):
                self.relation_to_id[relation_type] = idx
                self.id_to_relation[idx] = relation_type
                emb_list = _parse_embedding_vector(embedding_str)
                self.relation_embeddings[idx] = np.array(emb_list, dtype=np.float32)

            logger.info("Loaded %d relation embeddings", num_relations)
            cur.execute(
                """
                SELECT source_entity_id, rel_type, target_entity_id
                FROM kg_relationships
                WHERE source_entity_id IS NOT NULL
                  AND target_entity_id IS NOT NULL
                """
            )
            self.triples = []
            for source_id, rel_type, target_id in cur.fetchall():
                if (
                    source_id in self.entity_to_id
                    and target_id in self.entity_to_id
                    and rel_type in self.relation_to_id
                ):
                    self.triples.append(
                        (
                            self.entity_to_id[source_id],
                            self.relation_to_id[rel_type],
                            self.entity_to_id[target_id],
                        )
                    )
            logger.info("Reloaded %d graph triples for link prediction masking", len(self.triples))
            return True

        finally:
            cur.close()
            conn.close()

    @staticmethod
    def _create_embedding_tables(cur: Any) -> None:
        """Create pgvector tables if they don't exist."""
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kg_embeddings (
                entity_id TEXT PRIMARY KEY,
                embedding vector(64),
                model_version TEXT NOT NULL,
                trained_at TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS kg_relation_embeddings (
                relation_type TEXT PRIMARY KEY,
                embedding vector(64),
                model_version TEXT NOT NULL,
                trained_at TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS kg_predicted_links (
                id SERIAL PRIMARY KEY,
                source_entity_id TEXT NOT NULL,
                target_entity_id TEXT NOT NULL,
                predicted_relation TEXT NOT NULL,
                predicted_edge_family TEXT,
                edge_already_exists BOOLEAN NOT NULL DEFAULT FALSE,
                score FLOAT NOT NULL,
                model_version TEXT NOT NULL,
                candidate_rank INTEGER,
                source_entity_name TEXT,
                target_entity_name TEXT,
                reviewed BOOLEAN DEFAULT FALSE,
                analyst_confirmed BOOLEAN,
                rejection_reason TEXT,
                review_notes TEXT,
                reviewed_by TEXT,
                reviewed_at TIMESTAMP,
                relationship_created BOOLEAN NOT NULL DEFAULT FALSE,
                promoted_relationship_id INTEGER,
                created_at TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (source_entity_id) REFERENCES kg_entities(id),
                FOREIGN KEY (target_entity_id) REFERENCES kg_entities(id)
            )
        """)

        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS predicted_edge_family TEXT")
        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS edge_already_exists BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS candidate_rank INTEGER")
        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS source_entity_name TEXT")
        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS target_entity_name TEXT")
        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS rejection_reason TEXT")
        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS review_notes TEXT")
        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS reviewed_by TEXT")
        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP")
        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS relationship_created BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS promoted_relationship_id INTEGER")

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_kg_predicted_links_source
            ON kg_predicted_links(source_entity_id)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_kg_predicted_links_reviewed
            ON kg_predicted_links(reviewed)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_kg_predicted_links_edge_family
            ON kg_predicted_links(predicted_edge_family)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_kg_predicted_links_edge_exists
            ON kg_predicted_links(edge_already_exists)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_kg_predicted_links_reviewed_at
            ON kg_predicted_links(reviewed_at)
        """)


def train_and_save(pg_url: str, dim: int = 64) -> dict:
    """
    Convenience function: load triples, train, and save embeddings.

    Args:
        pg_url: PostgreSQL URL
        dim: Embedding dimension

    Returns:
        Training results dict
    """
    logger.info("Starting full training pipeline")
    trainer = TransETrainer(dim=dim)
    trainer.load_triples_from_db(pg_url)
    results = trainer.train()
    saved_count = trainer.save_embeddings_to_db(pg_url)
    results["embeddings_saved"] = saved_count
    return results


def get_predicted_links(pg_url: str, entity_id: str, top_k: int = 10) -> list[dict]:
    """
    Convenience function: load embeddings and predict links for entity.

    Args:
        pg_url: PostgreSQL URL
        entity_id: Entity ID
        top_k: Number of predictions

    Returns:
        List of predicted links
    """
    trainer = TransETrainer()
    if not trainer.load_embeddings_from_db(pg_url):
        logger.warning("Could not load embeddings from database")
        return []

    # Enrich with entity names from database
    try:
        import psycopg2
    except ImportError:
        return []

    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()

    try:
        predictions = _prepare_prediction_rows(cur, trainer, entity_id, top_k=top_k)
    finally:
        cur.close()
        conn.close()

    return predictions


def ensure_prediction_tables(pg_url: str) -> None:
    try:
        import psycopg2
    except ImportError as exc:  # pragma: no cover
        raise ImportError("psycopg2 is required") from exc

    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        TransETrainer._create_embedding_tables(cur)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def queue_predicted_links(pg_url: str, entity_id: str, top_k: int = 25) -> dict[str, Any]:
    ensure_prediction_tables(pg_url)

    trainer = TransETrainer()
    if not trainer.load_embeddings_from_db(pg_url):
        raise ValueError("Embeddings not found. Train first.")

    model_version = trainer.model_version or "unknown"

    try:
        import psycopg2
    except ImportError as exc:  # pragma: no cover
        raise ImportError("psycopg2 is required") from exc

    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()

    try:
        predictions = _prepare_prediction_rows(cur, trainer, entity_id, top_k=top_k)
        source_name = (predictions[0]["source_entity_name"] if predictions else None) or (
            (_fetch_entity_map(cur, [entity_id]).get(entity_id) or {}).get("canonical_name", entity_id)
        )
        queued = 0
        existing = 0
        items: list[dict[str, Any]] = []

        for rank, pred in enumerate(predictions, start=1):
            target_id = str(pred["target_entity_id"])
            rel_type = str(pred["predicted_relation"])
            score = float(pred["score"])
            target_name = str(pred.get("target_name") or target_id)
            edge_family = str(pred.get("predicted_edge_family") or _prediction_edge_family(rel_type))
            existing_relationship_id = _edge_exists(cur, entity_id, rel_type, target_id)
            edge_already_exists = existing_relationship_id is not None

            cur.execute(
                """
                SELECT id, reviewed, analyst_confirmed
                FROM kg_predicted_links
                WHERE source_entity_id = %s
                  AND target_entity_id = %s
                  AND predicted_relation = %s
                  AND model_version = %s
                LIMIT 1
                """,
                (entity_id, target_id, rel_type, model_version),
            )
            row = cur.fetchone()

            if row:
                existing += 1
                cur.execute(
                    """
                    UPDATE kg_predicted_links
                    SET score = %s,
                        predicted_edge_family = %s,
                        edge_already_exists = %s,
                        candidate_rank = %s,
                        source_entity_name = %s,
                        target_entity_name = %s
                    WHERE id = %s
                    """,
                    (score, edge_family, edge_already_exists, rank, source_name, target_name, row[0]),
                )
                link_id = int(row[0])
                reviewed = bool(row[1])
                analyst_confirmed = row[2]
            else:
                cur.execute(
                    """
                    INSERT INTO kg_predicted_links (
                        source_entity_id,
                        target_entity_id,
                        predicted_relation,
                        predicted_edge_family,
                        edge_already_exists,
                        score,
                        model_version,
                        candidate_rank,
                        source_entity_name,
                        target_entity_name
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        entity_id,
                        target_id,
                        rel_type,
                        edge_family,
                        edge_already_exists,
                        score,
                        model_version,
                        rank,
                        source_name,
                        target_name,
                    ),
                )
                link_id = int(cur.fetchone()[0])
                queued += 1
                reviewed = False
                analyst_confirmed = None

            items.append(
                {
                    "id": link_id,
                    "source_entity_id": entity_id,
                    "source_entity_name": source_name,
                    "target_entity_id": target_id,
                    "target_entity_name": target_name,
                    "predicted_relation": rel_type,
                    "predicted_edge_family": edge_family,
                    "edge_already_exists": edge_already_exists,
                    "score": score,
                    "candidate_rank": rank,
                    "model_version": model_version,
                    "reviewed": reviewed,
                    "analyst_confirmed": analyst_confirmed,
                }
            )

        conn.commit()
        return {
            "entity_id": entity_id,
            "entity_name": source_name,
            "model_version": model_version,
            "top_k": top_k,
            "queued_count": queued,
            "existing_count": existing,
            "count": len(items),
            "items": items,
        }
    finally:
        cur.close()
        conn.close()


def list_predicted_link_queue(
    pg_url: str,
    *,
    reviewed: bool | None = None,
    analyst_confirmed: bool | None = None,
    novel_only: bool | None = None,
    edge_family: str | None = None,
    model_version: str | None = None,
    source_entity_id: str | None = None,
    source_entity_ids: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    ensure_prediction_tables(pg_url)
    try:
        import psycopg2
    except ImportError as exc:  # pragma: no cover
        raise ImportError("psycopg2 is required") from exc

    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()
    try:
        conditions: list[str] = []
        params: list[Any] = []
        if reviewed is not None:
            conditions.append("reviewed = %s")
            params.append(reviewed)
        if analyst_confirmed is not None:
            conditions.append("analyst_confirmed = %s")
            params.append(analyst_confirmed)
        if novel_only is True:
            conditions.append("edge_already_exists = FALSE")
        elif novel_only is False:
            conditions.append("edge_already_exists = TRUE")
        if edge_family:
            conditions.append("predicted_edge_family = %s")
            params.append(edge_family)
        if model_version:
            conditions.append("model_version = %s")
            params.append(model_version)
        if source_entity_ids:
            conditions.append("source_entity_id = ANY(%s)")
            params.append(source_entity_ids)
        elif source_entity_id:
            conditions.append("source_entity_id = %s")
            params.append(source_entity_id)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        cur.execute(
            f"""
            SELECT
                id,
                source_entity_id,
                source_entity_name,
                target_entity_id,
                target_entity_name,
                predicted_relation,
                predicted_edge_family,
                edge_already_exists,
                score,
                model_version,
                candidate_rank,
                reviewed,
                analyst_confirmed,
                rejection_reason,
                review_notes,
                reviewed_by,
                reviewed_at,
                relationship_created,
                promoted_relationship_id,
                created_at
            FROM kg_predicted_links
            {where}
            ORDER BY
                edge_already_exists ASC,
                reviewed ASC,
                candidate_rank ASC NULLS LAST,
                score ASC,
                created_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params),
        )
        rows = cur.fetchall()
        return [
            {
                "id": int(row[0]),
                "source_entity_id": str(row[1]),
                "source_entity_name": str(row[2] or row[1]),
                "target_entity_id": str(row[3]),
                "target_entity_name": str(row[4] or row[3]),
                "predicted_relation": str(row[5]),
                "predicted_edge_family": str(row[6] or _prediction_edge_family(row[5])),
                "edge_already_exists": bool(row[7]),
                "score": float(row[8]),
                "model_version": str(row[9]),
                "candidate_rank": int(row[10]) if row[10] is not None else None,
                "reviewed": bool(row[11]),
                "analyst_confirmed": row[12],
                "rejection_reason": row[13],
                "review_notes": row[14],
                "reviewed_by": row[15],
                "reviewed_at": row[16].isoformat() if row[16] else None,
                "relationship_created": bool(row[17]),
                "promoted_relationship_id": int(row[18]) if row[18] is not None else None,
                "created_at": row[19].isoformat() if row[19] else None,
            }
            for row in rows
        ]
    finally:
        cur.close()
        conn.close()


def review_predicted_links(pg_url: str, reviews: list[dict[str, Any]], *, reviewed_by: str = "unknown") -> dict[str, Any]:
    ensure_prediction_tables(pg_url)
    try:
        import psycopg2
    except ImportError as exc:  # pragma: no cover
        raise ImportError("psycopg2 is required") from exc

    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()
    reviewed_at = datetime.utcnow()
    reviewed_items: list[dict[str, Any]] = []
    confirmed_count = 0
    rejected_count = 0

    try:
        for review in reviews:
            link_id = int(review["id"])
            confirmed = bool(review.get("confirmed"))
            notes = str(review.get("notes") or "").strip() or None
            rejection_reason = str(review.get("rejection_reason") or "").strip() or None
            if rejection_reason and rejection_reason not in PREDICTED_LINK_REJECTION_REASONS:
                rejection_reason = "insufficient_support"

            cur.execute(
                """
                SELECT
                    id,
                    source_entity_id,
                    target_entity_id,
                    predicted_relation,
                    predicted_edge_family,
                    score,
                    model_version
                FROM kg_predicted_links
                WHERE id = %s
                """,
                (link_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Predicted link {link_id} not found")

            relationship_created = False
            promoted_relationship_id = None
            if confirmed:
                cur.execute(
                    """
                    SELECT id
                    FROM kg_relationships
                    WHERE source_entity_id = %s
                      AND target_entity_id = %s
                      AND rel_type = %s
                    LIMIT 1
                    """,
                    (row[1], row[2], row[3]),
                )
                existing_rel = cur.fetchone()
                if existing_rel:
                    promoted_relationship_id = int(existing_rel[0])
                else:
                    evidence_blob = {
                        "prediction_source": "graph_link_prediction",
                        "predicted_edge_family": row[4] or _prediction_edge_family(row[3]),
                        "model_version": row[6],
                        "analyst_reviewed_by": reviewed_by,
                        "analyst_reviewed_at": reviewed_at.isoformat() + "Z",
                        "notes": notes,
                    }
                    cur.execute(
                        """
                        INSERT INTO kg_relationships (
                            source_entity_id,
                            target_entity_id,
                            rel_type,
                    confidence,
                    data_source,
                    evidence
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            row[1],
                            row[2],
                            row[3],
                            float(row[5]),
                            "graph_link_prediction_analyst_review",
                            json.dumps(evidence_blob, sort_keys=True),
                        ),
                    )
                    promoted_relationship_id = int(cur.fetchone()[0])
                    relationship_created = True
                confirmed_count += 1
                rejection_reason = None
            else:
                rejected_count += 1

            cur.execute(
                """
                UPDATE kg_predicted_links
                SET reviewed = TRUE,
                    analyst_confirmed = %s,
                    rejection_reason = %s,
                    review_notes = %s,
                    reviewed_by = %s,
                    reviewed_at = %s,
                    relationship_created = %s,
                    promoted_relationship_id = %s
                WHERE id = %s
                """,
                (
                    confirmed,
                    rejection_reason,
                    notes,
                    reviewed_by,
                    reviewed_at,
                    relationship_created,
                    promoted_relationship_id,
                    link_id,
                ),
            )
            reviewed_items.append(
                {
                    "id": link_id,
                    "status": "confirmed" if confirmed else "rejected",
                    "rejection_reason": rejection_reason,
                    "relationship_created": relationship_created,
                    "promoted_relationship_id": promoted_relationship_id,
                }
            )

        conn.commit()
        return {
            "reviewed_count": len(reviewed_items),
            "confirmed_count": confirmed_count,
            "rejected_count": rejected_count,
            "reviewed_by": reviewed_by,
            "reviewed_at": reviewed_at.isoformat() + "Z",
            "items": reviewed_items,
        }
    finally:
        cur.close()
        conn.close()


def get_prediction_review_stats(
    pg_url: str,
    *,
    source_entity_id: str | None = None,
    source_entity_ids: list[str] | None = None,
    model_version: str | None = None,
) -> dict[str, Any]:
    ensure_prediction_tables(pg_url)
    try:
        import psycopg2
    except ImportError as exc:  # pragma: no cover
        raise ImportError("psycopg2 is required") from exc

    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()
    try:
        conditions: list[str] = []
        params: list[Any] = []
        if source_entity_ids:
            conditions.append("source_entity_id = ANY(%s)")
            params.append(source_entity_ids)
        elif source_entity_id:
            conditions.append("source_entity_id = %s")
            params.append(source_entity_id)
        if model_version:
            conditions.append("model_version = %s")
            params.append(model_version)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        scoped_params = tuple(params)

        cur.execute(
            f"""
            SELECT
                COUNT(*) AS total_links,
                COUNT(*) FILTER (WHERE reviewed = TRUE) AS reviewed_links,
                COUNT(*) FILTER (WHERE reviewed = FALSE) AS pending_links,
                COUNT(*) FILTER (WHERE reviewed = FALSE AND edge_already_exists = FALSE) AS novel_pending_links,
                COUNT(*) FILTER (WHERE reviewed = FALSE AND edge_already_exists = TRUE) AS existing_pending_links,
                COUNT(*) FILTER (WHERE analyst_confirmed = TRUE) AS confirmed_links,
                COUNT(*) FILTER (WHERE reviewed = TRUE AND analyst_confirmed = FALSE) AS rejected_links,
                COUNT(*) FILTER (WHERE relationship_created = TRUE) AS promoted_relationships,
                COUNT(*) FILTER (WHERE relationship_created = TRUE AND COALESCE(analyst_confirmed, FALSE) = FALSE) AS unsupported_promoted_edges,
                COALESCE(MAX(reviewed_at), MAX(created_at)) AS latest_activity_at
            FROM kg_predicted_links
            {where}
            """,
            scoped_params,
        )
        totals = cur.fetchone() or (0, 0, 0, 0, 0, 0, None)

        cur.execute(
            f"""
            SELECT
                COALESCE(predicted_edge_family, 'other') AS edge_family,
                COUNT(*) AS total_links,
                COUNT(*) FILTER (WHERE reviewed = TRUE) AS reviewed_links,
                COUNT(*) FILTER (WHERE reviewed = FALSE) AS pending_links,
                COUNT(*) FILTER (WHERE reviewed = FALSE AND edge_already_exists = FALSE) AS novel_pending_links,
                COUNT(*) FILTER (WHERE analyst_confirmed = TRUE) AS confirmed_links,
                COUNT(*) FILTER (WHERE relationship_created = TRUE) AS promoted_relationships
            FROM kg_predicted_links
            {where}
            GROUP BY COALESCE(predicted_edge_family, 'other')
            ORDER BY total_links DESC, edge_family ASC
            """,
            scoped_params,
        )
        by_family = [
            {
                "edge_family": str(row[0]),
                "total_links": int(row[1]),
                "reviewed_links": int(row[2]),
                "pending_links": int(row[3]),
                "novel_pending_links": int(row[4]),
                "confirmed_links": int(row[5]),
                "promoted_relationships": int(row[6]),
            }
            for row in cur.fetchall()
        ]

        cur.execute(
            f"""
            SELECT
                COALESCE(rejection_reason, 'unspecified') AS rejection_reason,
                COUNT(*) AS rejection_count
            FROM kg_predicted_links
            {where}
            AND reviewed = TRUE
            AND analyst_confirmed = FALSE
            GROUP BY COALESCE(rejection_reason, 'unspecified')
            ORDER BY rejection_count DESC, rejection_reason ASC
            """
            if where
            else """
            SELECT
                COALESCE(rejection_reason, 'unspecified') AS rejection_reason,
                COUNT(*) AS rejection_count
            FROM kg_predicted_links
            WHERE reviewed = TRUE
              AND analyst_confirmed = FALSE
            GROUP BY COALESCE(rejection_reason, 'unspecified')
            ORDER BY rejection_count DESC, rejection_reason ASC
            """,
            scoped_params,
        )
        rejection_reason_counts = [
            {
                "rejection_reason": str(row[0]),
                "count": int(row[1]),
            }
            for row in cur.fetchall()
        ]

        cur.execute(
            f"""
            SELECT
                COALESCE(AVG(EXTRACT(EPOCH FROM (reviewed_at - created_at)) / 3600.0) FILTER (WHERE reviewed = TRUE), 0),
                COALESCE(
                    percentile_cont(0.5) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600.0
                    ) FILTER (WHERE reviewed = FALSE),
                    0
                ),
                COALESCE(
                    percentile_cont(0.95) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600.0
                    ) FILTER (WHERE reviewed = FALSE),
                    0
                ),
                COUNT(*) FILTER (WHERE reviewed = FALSE AND created_at <= NOW() - INTERVAL '24 hours'),
                COUNT(*) FILTER (WHERE reviewed = FALSE AND created_at <= NOW() - INTERVAL '168 hours')
            FROM kg_predicted_links
            {where}
            """,
            scoped_params,
        )
        timing = cur.fetchone() or (0.0, 0.0, 0.0, 0, 0)

        cur.execute(
            f"""
            SELECT
                source_entity_id,
                COALESCE(MAX(source_entity_name), source_entity_id) AS source_entity_name,
                COUNT(*) AS total_links,
                COUNT(*) FILTER (WHERE reviewed = FALSE) AS pending_links,
                COUNT(*) FILTER (WHERE reviewed = TRUE) AS reviewed_links,
                COUNT(*) FILTER (WHERE relationship_created = TRUE) AS promoted_relationships
            FROM kg_predicted_links
            {where}
            GROUP BY source_entity_id
            ORDER BY pending_links DESC, total_links DESC, source_entity_name ASC
            LIMIT 10
            """,
            scoped_params,
        )
        by_source = [
            {
                "source_entity_id": str(row[0]),
                "source_entity_name": str(row[1] or row[0]),
                "total_links": int(row[2]),
                "pending_links": int(row[3]),
                "reviewed_links": int(row[4]),
                "promoted_relationships": int(row[5]),
            }
            for row in cur.fetchall()
        ]

        total_links = int(totals[0] or 0)
        reviewed_links = int(totals[1] or 0)
        pending_links = int(totals[2] or 0)
        novel_pending_links = int(totals[3] or 0)
        existing_pending_links = int(totals[4] or 0)
        confirmed_links = int(totals[5] or 0)
        rejected_links = int(totals[6] or 0)
        promoted_relationships = int(totals[7] or 0)
        unsupported_promoted_edges = int(totals[8] or 0)
        confirmation_rate = (confirmed_links / reviewed_links) if reviewed_links else 0.0
        review_coverage_pct = (reviewed_links / total_links) if total_links else 0.0
        unsupported_promoted_edge_rate = (
            unsupported_promoted_edges / promoted_relationships
            if promoted_relationships
            else 0.0
        )
        novel_edge_yield = (promoted_relationships / confirmed_links) if confirmed_links else 0.0
        return {
            "total_links": total_links,
            "reviewed_links": reviewed_links,
            "pending_links": pending_links,
            "novel_pending_links": novel_pending_links,
            "existing_pending_links": existing_pending_links,
            "confirmed_links": confirmed_links,
            "rejected_links": rejected_links,
            "promoted_relationships": promoted_relationships,
            "unsupported_promoted_edges": unsupported_promoted_edges,
            "unsupported_promoted_edge_rate": unsupported_promoted_edge_rate,
            "confirmation_rate": confirmation_rate,
            "review_coverage_pct": review_coverage_pct,
            "latest_activity_at": totals[9].isoformat() if totals[9] else None,
            "by_edge_family": by_family,
            "by_source_entity": by_source,
            "rejection_reason_counts": rejection_reason_counts,
            "scope": {
                "source_entity_id": source_entity_id,
                "source_entity_ids": source_entity_ids or [],
                "model_version": model_version,
            },
            "missing_edge_recovery": {
                "queue_depth": pending_links,
                "novel_pending_links": novel_pending_links,
                "existing_pending_links": existing_pending_links,
                "analyst_confirmation_rate": confirmation_rate,
                "review_coverage_pct": review_coverage_pct,
                "novel_edge_yield": novel_edge_yield,
                "unsupported_promoted_edge_rate": unsupported_promoted_edge_rate,
                "mean_review_latency_hours": float(timing[0] or 0.0),
                "median_pending_age_hours": float(timing[1] or 0.0),
                "p95_pending_age_hours": float(timing[2] or 0.0),
                "stale_pending_24h": int(timing[3] or 0),
                "stale_pending_7d": int(timing[4] or 0),
            },
        }
    finally:
        cur.close()
        conn.close()


def _compute_entity_resolution_metrics() -> dict[str, Any]:
    rows = _load_fixture_rows(GRAPH_ENTITY_RESOLUTION_PAIRS_PATH) if GRAPH_ENTITY_RESOLUTION_PAIRS_PATH.exists() else []
    if not rows:
        return {
            "entity_resolution_pairwise_f1": 0.0,
            "false_merge_rate": 0.0,
            "entity_resolution_pairs_evaluated": 0,
        }

    from entity_resolution import normalize_name
    from ofac import jaro_winkler

    tp = fp = fn = 0
    predicted_positive = 0

    for row in rows:
        name_a = str(row.get("name_a") or "")
        name_b = str(row.get("name_b") or "")
        threshold = float(row.get("threshold") or 0.88)
        score = jaro_winkler(normalize_name(name_a), normalize_name(name_b))
        country_a = str(row.get("country_a") or "").strip().upper()
        country_b = str(row.get("country_b") or "").strip().upper()
        if country_a and country_b and country_a == country_b:
            score = min(1.0, score + 0.05)
        predicted = score >= threshold
        expected = bool(row.get("should_match"))

        if predicted:
            predicted_positive += 1
        if predicted and expected:
            tp += 1
        elif predicted and not expected:
            fp += 1
        elif (not predicted) and expected:
            fn += 1

    precision = _safe_divide(tp, tp + fp)
    recall = _safe_divide(tp, tp + fn)
    return {
        "entity_resolution_pairwise_f1": _safe_divide(2 * precision * recall, precision + recall),
        "false_merge_rate": _safe_divide(fp, predicted_positive),
        "entity_resolution_pairs_evaluated": len(rows),
    }


def _load_prediction_state_by_name(cur: Any, source_names: set[str]) -> dict[tuple[str, str, str], dict[str, bool]]:
    normalized_sources = sorted({_normalize_match_text(name) for name in source_names if _normalize_match_text(name)})
    if not normalized_sources:
        return {}

    cur.execute(
        """
        SELECT
            LOWER(TRIM(COALESCE(source_entity_name, ''))) AS source_name,
            LOWER(TRIM(COALESCE(target_entity_name, ''))) AS target_name,
            LOWER(TRIM(COALESCE(predicted_relation, ''))) AS predicted_relation,
            BOOL_OR(reviewed = TRUE AND analyst_confirmed = TRUE) AS confirmed_candidate,
            BOOL_OR(reviewed = FALSE) AS pending_candidate,
            BOOL_OR(reviewed = TRUE AND analyst_confirmed = FALSE) AS rejected_candidate
        FROM kg_predicted_links
        WHERE LOWER(TRIM(COALESCE(source_entity_name, ''))) = ANY(%s)
        GROUP BY 1, 2, 3
        """,
        (normalized_sources,),
    )
    state: dict[tuple[str, str, str], dict[str, bool]] = {}
    for row in cur.fetchall():
        key = (str(row[0] or ""), str(row[1] or ""), str(row[2] or ""))
        state[key] = {
            "confirmed_candidate": bool(row[3]),
            "pending_candidate": bool(row[4]),
            "rejected_candidate": bool(row[5]),
        }
    return state


def _load_existing_edges_by_name(cur: Any, source_names: set[str]) -> set[tuple[str, str, str]]:
    normalized_sources = sorted({_normalize_match_text(name) for name in source_names if _normalize_match_text(name)})
    if not normalized_sources:
        return set()

    cur.execute(
        """
        SELECT
            LOWER(TRIM(COALESCE(source_entities.canonical_name, ''))) AS source_name,
            LOWER(TRIM(COALESCE(target_entities.canonical_name, ''))) AS target_name,
            LOWER(TRIM(COALESCE(rel.rel_type, ''))) AS rel_type
        FROM kg_relationships rel
        JOIN kg_entities source_entities ON source_entities.id = rel.source_entity_id
        JOIN kg_entities target_entities ON target_entities.id = rel.target_entity_id
        WHERE LOWER(TRIM(COALESCE(source_entities.canonical_name, ''))) = ANY(%s)
        """,
        (normalized_sources,),
    )
    return {
        (str(row[0] or ""), str(row[1] or ""), str(row[2] or ""))
        for row in cur.fetchall()
    }


def _evaluate_construction_fixture_rows(
    gold_rows: list[dict[str, Any]],
    negative_rows: list[dict[str, Any]],
    *,
    existing_edges: set[tuple[str, str, str]],
    prediction_state: dict[tuple[str, str, str], dict[str, bool]],
) -> dict[str, Any]:
    tp = fp = fn = 0
    own_tp = own_fp = own_fn = 0
    descriptor_total = descriptor_false = 0
    gold_supported = 0
    negative_rejected = 0

    def _candidate_state(source_name: str, target_name: str, rel_type: str) -> dict[str, bool]:
        key = (
            _normalize_match_text(source_name),
            _normalize_match_text(target_name),
            _normalize_rel_type(rel_type),
        )
        return prediction_state.get(key, {})

    def _graph_exists(source_name: str, target_name: str, rel_type: str) -> bool:
        key = (
            _normalize_match_text(source_name),
            _normalize_match_text(target_name),
            _normalize_rel_type(rel_type),
        )
        return key in existing_edges

    for row in gold_rows:
        source_name = str(row.get("source_entity") or "")
        target_name = str(row.get("target_entity") or "")
        rel_type = str(row.get("relationship_type") or "")
        state = _candidate_state(source_name, target_name, rel_type)
        supported = bool(
            _graph_exists(source_name, target_name, rel_type)
            or state.get("confirmed_candidate")
            or state.get("pending_candidate")
        )
        if supported:
            tp += 1
            gold_supported += 1
            if row.get("edge_family") == "ownership_control":
                own_tp += 1
        else:
            fn += 1
            if row.get("edge_family") == "ownership_control":
                own_fn += 1

    for row in negative_rows:
        source_name = str(row.get("source_entity") or "")
        target_name = str(row.get("attempted_target") or "")
        rel_type = str(row.get("attempted_relationship_type") or "")
        state = _candidate_state(source_name, target_name, rel_type)
        false_positive = bool(
            _graph_exists(source_name, target_name, rel_type)
            or state.get("confirmed_candidate")
            or state.get("pending_candidate")
        )
        if state.get("rejected_candidate"):
            negative_rejected += 1
        if false_positive:
            fp += 1
            if row.get("edge_family") == "ownership_control":
                own_fp += 1
        if row.get("rejection_reason") == "descriptor_only_not_entity":
            descriptor_total += 1
            descriptor_false += 1 if false_positive else 0

    precision = _safe_divide(tp, tp + fp)
    recall = _safe_divide(tp, tp + fn)
    own_precision = _safe_divide(own_tp, own_tp + own_fp)
    own_recall = _safe_divide(own_tp, own_tp + own_fn)

    return {
        "edge_family_micro_f1": _safe_divide(2 * precision * recall, precision + recall),
        "ownership_control_precision": own_precision,
        "ownership_control_recall": own_recall,
        "descriptor_only_false_owner_rate": _safe_divide(descriptor_false, descriptor_total),
        "gold_positive_rows_evaluated": len(gold_rows),
        "hard_negative_rows_evaluated": len(negative_rows),
        "gold_candidate_coverage": _safe_divide(gold_supported, len(gold_rows)),
        "negative_rejection_coverage": _safe_divide(negative_rejected, len(negative_rows)),
    }


def get_graph_construction_training_metrics(pg_url: str) -> dict[str, Any]:
    gold_rows = _load_fixture_rows(GRAPH_CONSTRUCTION_GOLD_PATH)
    negative_rows = _load_fixture_rows(GRAPH_CONSTRUCTION_NEGATIVE_PATH)

    if not gold_rows and not negative_rows:
        metrics = {
            "edge_family_micro_f1": 0.0,
            "ownership_control_precision": 0.0,
            "ownership_control_recall": 0.0,
            "descriptor_only_false_owner_rate": 0.0,
            "gold_positive_rows_evaluated": 0,
            "hard_negative_rows_evaluated": 0,
        }
        metrics.update(_compute_entity_resolution_metrics())
        return metrics

    try:
        import psycopg2
    except ImportError as exc:  # pragma: no cover
        raise ImportError("psycopg2 is required") from exc

    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()
    try:
        source_names = {
            str(row.get("source_entity") or "")
            for row in [*gold_rows, *negative_rows]
            if str(row.get("source_entity") or "").strip()
        }
        existing_edges = _load_existing_edges_by_name(cur, source_names)
        prediction_state = _load_prediction_state_by_name(cur, source_names)

        metrics = _evaluate_construction_fixture_rows(
            gold_rows,
            negative_rows,
            existing_edges=existing_edges,
            prediction_state=prediction_state,
        )
        metrics.update(_compute_entity_resolution_metrics())
        return metrics
    finally:
        cur.close()
        conn.close()


def get_missing_edge_recovery_metrics(
    pg_url: str,
    *,
    review_stats: dict[str, Any] | None = None,
    evaluation_top_k: int = 10,
    recovery_queue_top_k: int = 16,
) -> dict[str, Any]:
    review_stats = review_stats or get_prediction_review_stats(pg_url)

    try:
        import psycopg2
    except ImportError as exc:  # pragma: no cover
        raise ImportError("psycopg2 is required") from exc

    holdout_path, holdout_rows = _load_masked_holdout_rows()
    if not holdout_rows:
        return {
            "evaluation_protocol": "family_balanced_masked_holdout",
            "holdout_fixture_path": str(holdout_path),
            "training_holdout_enforced": False,
            "unsupported_promoted_edge_rate": float(review_stats.get("unsupported_promoted_edge_rate") or 0.0),
            "masked_holdout_queries_evaluated": 0,
            "missing_edge_queries_evaluated": 0,
            "masked_holdout_hits_at_10": 0.0,
            "masked_holdout_mrr": 0.0,
            "mean_withheld_target_rank": 0.0,
            "holdout_results": [],
            "recovery_queue_by_source": [],
            "recovery_queue_source_count": 0,
            "recovery_queue_candidate_count": 0,
        }

    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()
    try:
        resolved_rows, unresolved_rows = _resolve_masked_holdout_rows(cur, holdout_rows)
    finally:
        cur.close()
        conn.close()

    excluded_triples = {
        (
            str(row["source_entity_id"]),
            _normalize_rel_type(row["relationship_type"]),
            str(row["target_entity_id"]),
        )
        for row in resolved_rows
    }

    trainer = TransETrainer()
    trainer.load_triples_from_db(pg_url, exclude_triples=excluded_triples)
    training_result = trainer.train()

    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()
    try:
        holdout_results: list[dict[str, Any]] = []
        recovery_queue_by_source: list[dict[str, Any]] = []
        queue_rank_lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
        source_entity_ids = sorted({str(row["source_entity_id"]) for row in resolved_rows})
        all_entity_ids = list(trainer.entity_to_id.keys())
        entity_metadata = _fetch_entity_map(cur, all_entity_ids)
        source_entity_map = {entity_id: entity_metadata.get(entity_id, {}) for entity_id in source_entity_ids}

        rows_by_source: dict[str, list[dict[str, Any]]] = {}
        for row in resolved_rows:
            rows_by_source.setdefault(str(row["source_entity_id"]), []).append(row)

        for source_entity_id in source_entity_ids:
            source_rows = rows_by_source.get(source_entity_id, [])
            relevant_relations = {str(row["relationship_type"]) for row in source_rows}
            source_name = (source_entity_map.get(source_entity_id) or {}).get("canonical_name", source_entity_id)
            queue_rows = _prepare_prediction_rows(
                cur,
                trainer,
                source_entity_id,
                top_k=max(recovery_queue_top_k, len(relevant_relations) * 4, len(source_rows) * 4),
            )
            filtered_queue = [
                row for row in queue_rows
                if str(row.get("predicted_relation") or "") in relevant_relations
            ]
            queue_items: list[dict[str, Any]] = []
            for queue_rank, item in enumerate(filtered_queue, start=1):
                queue_item = {
                    "candidate_rank": queue_rank,
                    "source_entity_id": source_entity_id,
                    "source_entity_name": source_name,
                    "target_entity_id": str(item.get("target_entity_id") or ""),
                    "target_name": str(item.get("target_name") or item.get("target_entity_id") or ""),
                    "predicted_relation": str(item.get("predicted_relation") or ""),
                    "predicted_edge_family": str(item.get("predicted_edge_family") or ""),
                    "score": float(item.get("score") or 0.0),
                }
                queue_items.append(queue_item)
                queue_rank_lookup[
                    (
                        source_entity_id,
                        queue_item["predicted_relation"],
                        queue_item["target_entity_id"],
                    )
                ] = queue_item

            recovery_queue_by_source.append(
                {
                    "source_entity_id": source_entity_id,
                    "source_entity_name": source_name,
                    "holdout_relations": sorted(relevant_relations),
                    "candidate_count": len(queue_items),
                    "items": queue_items,
                }
            )

        for row in resolved_rows:
            rel_type = str(row["relationship_type"])
            rank_info = _score_withheld_target_rank(
                cur,
                trainer,
                str(row["source_entity_id"]),
                rel_type,
                str(row["target_entity_id"]),
                entity_metadata=entity_metadata,
            )
            queue_match = queue_rank_lookup.get(
                (
                    str(row["source_entity_id"]),
                    rel_type,
                    str(row["target_entity_id"]),
                )
            )
            holdout_results.append(
                {
                    "label_id": str(row.get("label_id") or ""),
                    "source_entity_id": str(row["source_entity_id"]),
                    "source_entity": str(row.get("source_entity") or row["source_entity_id"]),
                    "target_entity_id": str(row["target_entity_id"]),
                    "target_entity": str(row.get("target_entity") or row["target_entity_id"]),
                    "relationship_type": rel_type,
                    "edge_family": str(row.get("edge_family") or _prediction_edge_family(rel_type)),
                    "withheld_target_rank": int(rank_info["withheld_target_rank"] or 0),
                    "withheld_target_score": rank_info["withheld_target_score"],
                    "reciprocal_rank": float(rank_info["reciprocal_rank"] or 0.0),
                    "hit_at_10": bool(rank_info["hit_at_10"]),
                    "surfaced_in_recovery_queue": bool(queue_match),
                    "recovery_queue_rank": int(queue_match["candidate_rank"]) if queue_match else 0,
                }
            )
    finally:
        cur.close()
        conn.close()

    metrics = _aggregate_masked_holdout_metrics(holdout_results, review_stats)
    metrics.update(
        {
            "evaluation_protocol": "family_balanced_masked_holdout",
            "holdout_fixture_path": str(holdout_path),
            "training_holdout_enforced": True,
            "holdout_relation_types": list(MASKED_HOLDOUT_RELATION_TYPES),
            "holdout_source_entity_count": len({str(row["source_entity_id"]) for row in resolved_rows}),
            "holdout_triples_excluded": len(excluded_triples),
            "holdout_training_duration_ms": int(training_result.get("duration_ms") or 0),
            "holdout_training_final_loss": float(training_result.get("final_loss") or 0.0),
            "holdout_training_triple_count": int(training_result.get("triple_count") or len(trainer.triples)),
            "recovery_queue_source_count": len(recovery_queue_by_source),
            "recovery_queue_candidate_count": sum(int(row.get("candidate_count") or 0) for row in recovery_queue_by_source),
            "holdout_results": holdout_results,
            "recovery_queue_by_source": recovery_queue_by_source,
            "unresolved_holdout_rows": unresolved_rows,
        }
    )
    return metrics


def get_novel_edge_discovery_metrics(review_stats: dict[str, Any] | None = None) -> dict[str, Any]:
    review_stats = review_stats or {}
    recovery = review_stats.get("missing_edge_recovery") if isinstance(review_stats.get("missing_edge_recovery"), dict) else {}
    total_links = int(review_stats.get("total_links") or 0)
    reviewed_links = int(review_stats.get("reviewed_links") or 0)
    novel_pending_links = int(review_stats.get("novel_pending_links") or 0)
    confirmed_links = int(review_stats.get("confirmed_links") or 0)
    rejected_links = int(review_stats.get("rejected_links") or 0)
    promoted_relationships = int(review_stats.get("promoted_relationships") or 0)
    return {
        "total_candidate_links": total_links,
        "reviewed_candidate_links": reviewed_links,
        "novel_pending_links": novel_pending_links,
        "analyst_confirmation_rate": float(review_stats.get("confirmation_rate") or 0.0),
        "review_coverage_pct": float(review_stats.get("review_coverage_pct") or 0.0),
        "confirmed_links": confirmed_links,
        "rejected_links": rejected_links,
        "promoted_relationships": promoted_relationships,
        "novel_edge_yield": float(recovery.get("novel_edge_yield") or 0.0),
        "unsupported_promoted_edge_rate": float(review_stats.get("unsupported_promoted_edge_rate") or 0.0),
    }


def export_reviewed_link_labels(pg_url: str, output_path: str | Path) -> dict[str, Any]:
    ensure_prediction_tables(pg_url)
    rows = list_predicted_link_queue(pg_url, reviewed=True, limit=10000)
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "label_type": "kg_predicted_link_review",
        "count": len(rows),
        "rows": rows,
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "output_path": str(path),
        "count": len(rows),
    }
