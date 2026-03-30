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
                score FLOAT NOT NULL,
                model_version TEXT NOT NULL,
                candidate_rank INTEGER,
                source_entity_name TEXT,
                target_entity_name TEXT,
                reviewed BOOLEAN DEFAULT FALSE,
                analyst_confirmed BOOLEAN,
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
        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS candidate_rank INTEGER")
        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS source_entity_name TEXT")
        cur.execute("ALTER TABLE kg_predicted_links ADD COLUMN IF NOT EXISTS target_entity_name TEXT")
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
                        candidate_rank = %s,
                        source_entity_name = %s,
                        target_entity_name = %s
                    WHERE id = %s
                    """,
                    (score, edge_family, rank, source_name, target_name, row[0]),
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
                        score,
                        model_version,
                        candidate_rank,
                        source_entity_name,
                        target_entity_name
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (entity_id, target_id, rel_type, edge_family, score, model_version, rank, source_name, target_name),
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
                score,
                model_version,
                candidate_rank,
                reviewed,
                analyst_confirmed,
                review_notes,
                reviewed_by,
                reviewed_at,
                relationship_created,
                promoted_relationship_id,
                created_at
            FROM kg_predicted_links
            {where}
            ORDER BY
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
                "score": float(row[7]),
                "model_version": str(row[8]),
                "candidate_rank": int(row[9]) if row[9] is not None else None,
                "reviewed": bool(row[10]),
                "analyst_confirmed": row[11],
                "review_notes": row[12],
                "reviewed_by": row[13],
                "reviewed_at": row[14].isoformat() if row[14] else None,
                "relationship_created": bool(row[15]),
                "promoted_relationship_id": int(row[16]) if row[16] is not None else None,
                "created_at": row[17].isoformat() if row[17] else None,
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
            else:
                rejected_count += 1

            cur.execute(
                """
                UPDATE kg_predicted_links
                SET reviewed = TRUE,
                    analyst_confirmed = %s,
                    review_notes = %s,
                    reviewed_by = %s,
                    reviewed_at = %s,
                    relationship_created = %s,
                    promoted_relationship_id = %s
                WHERE id = %s
                """,
                (
                    confirmed,
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
                "confirmed_links": int(row[4]),
                "promoted_relationships": int(row[5]),
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
        confirmed_links = int(totals[3] or 0)
        rejected_links = int(totals[4] or 0)
        promoted_relationships = int(totals[5] or 0)
        unsupported_promoted_edges = int(totals[6] or 0)
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
            "confirmed_links": confirmed_links,
            "rejected_links": rejected_links,
            "promoted_relationships": promoted_relationships,
            "unsupported_promoted_edges": unsupported_promoted_edges,
            "unsupported_promoted_edge_rate": unsupported_promoted_edge_rate,
            "confirmation_rate": confirmation_rate,
            "review_coverage_pct": review_coverage_pct,
            "latest_activity_at": totals[6].isoformat() if totals[6] else None,
            "by_edge_family": by_family,
            "by_source_entity": by_source,
            "scope": {
                "source_entity_id": source_entity_id,
            },
            "missing_edge_recovery": {
                "queue_depth": pending_links,
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
