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
from collections import Counter
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

PREDICTED_LINK_REJECTION_REASONS: tuple[str, ...] = (
    "descriptor_only_not_entity",
    "garbage_not_entity",
    "generic_market_language",
    "marketing_mention_not_dependency",
    "no_actual_route",
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

    def load_triples_from_db(self, pg_url: str) -> None:
        """
        Load entity/relationship triples from kg_relationships table.

        Args:
            pg_url: PostgreSQL URL (e.g. postgresql://user:pass@host/dbname)
        """
        try:
            import psycopg2
        except ImportError:
            raise ImportError("psycopg2 is required. Install: pip install psycopg2-binary>=2.9")

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
                # Build entity and relation mappings
                if source_id not in self.entity_to_id:
                    idx = len(self.entity_to_id)
                    self.entity_to_id[source_id] = idx
                    self.id_to_entity[idx] = source_id

                if target_id not in self.entity_to_id:
                    idx = len(self.entity_to_id)
                    self.entity_to_id[target_id] = idx
                    self.id_to_entity[idx] = target_id

                if rel_type not in self.relation_to_id:
                    idx = len(self.relation_to_id)
                    self.relation_to_id[rel_type] = idx
                    self.id_to_relation[idx] = rel_type

                # Add triple using indices
                h_idx = self.entity_to_id[source_id]
                r_idx = self.relation_to_id[rel_type]
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

    predictions = trainer.predict_links(entity_id, top_k=top_k)

    # Enrich with entity names from database
    try:
        import psycopg2
    except ImportError:
        return predictions

    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()

    try:
        entity_map = _fetch_entity_map(cur, [pred["target_entity_id"] for pred in predictions])
        for pred in predictions:
            target_row = entity_map.get(str(pred["target_entity_id"]))
            pred["target_name"] = (target_row or {}).get("canonical_name", pred["target_name"])
            pred["predicted_edge_family"] = _prediction_edge_family(str(pred.get("predicted_relation") or ""))

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

    predictions = trainer.predict_links(entity_id, top_k=top_k)
    model_version = trainer.model_version or "unknown"

    try:
        import psycopg2
    except ImportError as exc:  # pragma: no cover
        raise ImportError("psycopg2 is required") from exc

    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()

    try:
        entity_map = _fetch_entity_map(cur, [entity_id, *[row["target_entity_id"] for row in predictions]])
        source_name = (entity_map.get(entity_id) or {}).get("canonical_name", entity_id)
        queued = 0
        existing = 0
        items: list[dict[str, Any]] = []

        for rank, pred in enumerate(predictions, start=1):
            target_id = str(pred["target_entity_id"])
            rel_type = str(pred["predicted_relation"])
            score = float(pred["score"])
            target_name = (entity_map.get(target_id) or {}).get("canonical_name", pred.get("target_name") or target_id)
            edge_family = _prediction_edge_family(rel_type)
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
        if source_entity_id:
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


def get_prediction_review_stats(pg_url: str, *, source_entity_id: str | None = None) -> dict[str, Any]:
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
        if source_entity_id:
            conditions.append("source_entity_id = %s")
            params.append(source_entity_id)
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
        names: set[str] = set()
        for row in gold_rows:
            names.add(str(row.get("source_entity") or ""))
            names.add(str(row.get("target_entity") or ""))
        for row in negative_rows:
            names.add(str(row.get("source_entity") or ""))
            names.add(str(row.get("attempted_target") or ""))
        entity_ids = _resolve_fixture_entity_ids(cur, names)

        tp = fp = fn = 0
        own_tp = own_fp = own_fn = 0
        descriptor_total = descriptor_false = 0

        for row in gold_rows:
            source_id = entity_ids.get(str(row.get("source_entity") or "").strip())
            target_id = entity_ids.get(str(row.get("target_entity") or "").strip())
            rel_type = _normalize_rel_type(row.get("relationship_type"))
            exists = bool(source_id and target_id and _edge_exists(cur, source_id, rel_type, target_id))
            if exists:
                tp += 1
                if row.get("edge_family") == "ownership_control":
                    own_tp += 1
            else:
                fn += 1
                if row.get("edge_family") == "ownership_control":
                    own_fn += 1

        for row in negative_rows:
            source_id = entity_ids.get(str(row.get("source_entity") or "").strip())
            target_id = entity_ids.get(str(row.get("attempted_target") or "").strip())
            rel_type = _normalize_rel_type(row.get("attempted_relationship_type"))
            exists = bool(source_id and target_id and _edge_exists(cur, source_id, rel_type, target_id))
            if exists:
                fp += 1
                if row.get("edge_family") == "ownership_control":
                    own_fp += 1
            if row.get("rejection_reason") == "descriptor_only_not_entity":
                descriptor_total += 1
                descriptor_false += 1 if exists else 0

        precision = _safe_divide(tp, tp + fp)
        recall = _safe_divide(tp, tp + fn)
        own_precision = _safe_divide(own_tp, own_tp + own_fp)
        own_recall = _safe_divide(own_tp, own_tp + own_fn)

        metrics = {
            "edge_family_micro_f1": _safe_divide(2 * precision * recall, precision + recall),
            "ownership_control_precision": own_precision,
            "ownership_control_recall": own_recall,
            "descriptor_only_false_owner_rate": _safe_divide(descriptor_false, descriptor_total),
            "gold_positive_rows_evaluated": len(gold_rows),
            "hard_negative_rows_evaluated": len(negative_rows),
        }
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
    max_queries_per_family: int = 100,
) -> dict[str, Any]:
    review_stats = review_stats or get_prediction_review_stats(pg_url)

    trainer = TransETrainer()
    if not trainer.load_embeddings_from_db(pg_url):
        return {
            "ownership_control_hits_at_10": 0.0,
            "ownership_control_mrr": 0.0,
            "intermediary_route_hits_at_10": 0.0,
            "intermediary_route_mrr": 0.0,
            "cyber_dependency_hits_at_10": 0.0,
            "analyst_confirmation_rate": float(review_stats.get("confirmation_rate") or 0.0),
            "unsupported_promoted_edge_rate": float(review_stats.get("unsupported_promoted_edge_rate") or 0.0),
            "missing_edge_queries_evaluated": 0,
        }

    try:
        import psycopg2
    except ImportError as exc:  # pragma: no cover
        raise ImportError("psycopg2 is required") from exc

    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT source_entity_id, rel_type, target_entity_id
            FROM kg_relationships
            WHERE source_entity_id IS NOT NULL
              AND target_entity_id IS NOT NULL
            ORDER BY created_at ASC, id ASC
            """
        )
        family_rows: dict[str, list[tuple[str, str, str]]] = {key: [] for key in MISSING_EDGE_FAMILY_GROUPS}
        for source_entity_id, rel_type, target_entity_id in cur.fetchall():
            if (
                source_entity_id not in trainer.entity_to_id
                or target_entity_id not in trainer.entity_to_id
                or rel_type not in trainer.relation_to_id
            ):
                continue
            predicted_family = _prediction_edge_family(rel_type)
            for metric_family, edge_families in MISSING_EDGE_FAMILY_GROUPS.items():
                if predicted_family in edge_families:
                    family_rows[metric_family].append((str(source_entity_id), str(rel_type), str(target_entity_id)))
                    break

        metrics: dict[str, Any] = {
            "analyst_confirmation_rate": float(review_stats.get("confirmation_rate") or 0.0),
            "unsupported_promoted_edge_rate": float(review_stats.get("unsupported_promoted_edge_rate") or 0.0),
        }

        total_queries = 0
        for metric_family, edge_families in MISSING_EDGE_FAMILY_GROUPS.items():
            hits = 0
            reciprocal_rank_total = 0.0
            queries = 0
            for source_id, rel_type, target_id in family_rows.get(metric_family, [])[:max_queries_per_family]:
                h_idx = trainer.entity_to_id.get(source_id)
                r_idx = trainer.relation_to_id.get(rel_type)
                t_idx = trainer.entity_to_id.get(target_id)
                if h_idx is None or r_idx is None or t_idx is None:
                    continue
                queries += 1
                total_queries += 1
                score_vector = np.linalg.norm(
                    trainer.entity_embeddings[h_idx] + trainer.relation_embeddings[r_idx] - trainer.entity_embeddings,
                    axis=1,
                )
                score_vector[h_idx] = np.inf
                target_score = float(score_vector[t_idx])
                rank = int(np.sum(score_vector < target_score) + 1)
                if rank and rank <= evaluation_top_k:
                    hits += 1
                if rank:
                    reciprocal_rank_total += 1.0 / rank

            metrics[f"{metric_family}_hits_at_10"] = _safe_divide(hits, queries)
            metrics[f"{metric_family}_mrr"] = _safe_divide(reciprocal_rank_total, queries)
            metrics[f"{metric_family}_queries_evaluated"] = queries

        metrics["missing_edge_queries_evaluated"] = total_queries
        return metrics
    finally:
        cur.close()
        conn.close()


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
