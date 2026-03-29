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

import logging
import time
from datetime import datetime
from typing import Any
import json

try:
    import numpy as np
except ImportError:
    raise ImportError("NumPy is required for graph embeddings. Install: pip install numpy>=1.24")

logger = logging.getLogger(__name__)


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
            cur.execute("""
                SELECT source_entity_id, relationship_type, target_entity_id
                FROM kg_relationships
                WHERE source_entity_id IS NOT NULL
                  AND target_entity_id IS NOT NULL
                ORDER BY created_at ASC
            """)

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
                emb_list = json.loads(embedding_str)
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
                emb_list = json.loads(embedding_str)
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
                score FLOAT NOT NULL,
                model_version TEXT NOT NULL,
                reviewed BOOLEAN DEFAULT FALSE,
                analyst_confirmed BOOLEAN,
                created_at TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (source_entity_id) REFERENCES kg_entities(entity_id),
                FOREIGN KEY (target_entity_id) REFERENCES kg_entities(entity_id)
            )
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_kg_predicted_links_source
            ON kg_predicted_links(source_entity_id)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_kg_predicted_links_reviewed
            ON kg_predicted_links(reviewed)
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
        for pred in predictions:
            target_id = pred["target_entity_id"]
            cur.execute("SELECT name FROM kg_entities WHERE entity_id = %s", (target_id,))
            row = cur.fetchone()
            if row:
                pred["target_name"] = row[0]

    finally:
        cur.close()
        conn.close()

    return predictions
