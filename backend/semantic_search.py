"""
Lightweight Semantic Sanctions Matching (Sprint 15-02)

Provides semantic matching for sanctions screening using TF-IDF character n-grams
and pgvector for fast ANN search. No heavy ML libraries required.

Uses character-level n-grams (3,4,5) to build embedding vectors stored as pgvector.
Hybrid approach combines fuzzy string matching (existing OFAC module) with semantic
search for robust sanctions entity matching.

Classes:
- SanctionsSemanticMatcher: Main class for semantic search and indexing

Database tables:
- sanctions_embeddings: Stores SDN entries with TF-IDF embeddings
"""

import logging
import math
from collections import Counter
from typing import Dict, List, Optional, Any
import numpy as np

from db import get_conn

logger = logging.getLogger(__name__)

# Default embedding dimension (cap vocabulary at 128 features)
DEFAULT_EMBEDDING_DIM = 128


class SanctionsSemanticMatcher:
    """
    Lightweight semantic matching for sanctions screening.

    Uses TF-IDF character n-grams (3,4,5-gram) to approximate semantic similarity.
    Vectors are L2-normalized and stored in pgvector for ANN search.

    Algorithm:
    1. Extract character n-grams from all SDN entity names
    2. Build vocabulary from top N n-grams by frequency
    3. Compute TF-IDF weights for each n-gram in each entity
    4. L2-normalize to unit vectors
    5. Store as pgvector vector(dim) for fast cosine similarity search

    At query time:
    1. Convert query to same TF-IDF vector format
    2. Use pgvector cosine similarity for ANN search
    3. Merge results with fuzzy string matching
    """

    def __init__(self, pg_url: Optional[str] = None, dim: int = DEFAULT_EMBEDDING_DIM):
        """
        Initialize semantic matcher.

        Args:
            pg_url: PostgreSQL URL (optional, uses db.get_conn() if not provided)
            dim: Embedding dimension (default 128)
        """
        self.dim = dim
        self.pg_url = pg_url
        self.ngram_size = [3, 4, 5]  # Use 3-grams, 4-grams, 5-grams
        self.vocabulary = {}  # {ngram: vocab_index}
        self.idf_weights = {}  # {ngram: idf_weight}

    def _extract_ngrams(self, text: str) -> List[str]:
        """Extract character n-grams (3,4,5) from text."""
        text = text.lower().strip()
        ngrams = []

        for size in self.ngram_size:
            for i in range(len(text) - size + 1):
                ngrams.append(text[i : i + size])

        return ngrams

    def _build_vocabulary(self, all_texts: List[str], max_vocab_size: int = 128) -> None:
        """
        Build vocabulary from all texts (SDN entities).

        Keeps top N n-grams by frequency. Rare n-grams are dropped.

        Args:
            all_texts: List of entity names
            max_vocab_size: Max vocabulary size (default 128)
        """
        ngram_counts = Counter()

        for text in all_texts:
            ngrams = self._extract_ngrams(text)
            ngram_counts.update(ngrams)

        # Keep top N n-grams
        top_ngrams = ngram_counts.most_common(max_vocab_size)
        self.vocabulary = {ngram: idx for idx, (ngram, _) in enumerate(top_ngrams)}

        # Compute IDF weights for each n-gram
        num_docs = len(all_texts)
        doc_freq = Counter()

        for text in all_texts:
            unique_ngrams = set(self._extract_ngrams(text))
            doc_freq.update(unique_ngrams)

        for ngram in self.vocabulary.keys():
            df = doc_freq.get(ngram, 1)
            # IDF = log(total_docs / doc_frequency)
            self.idf_weights[ngram] = math.log(num_docs / max(df, 1))

        logger.info(f"Built vocabulary with {len(self.vocabulary)} n-grams from {num_docs} documents")

    def _text_to_vector(self, text: str) -> np.ndarray:
        """
        Convert text to TF-IDF vector.

        Args:
            text: Entity name

        Returns:
            L2-normalized numpy array of shape (dim,)
        """
        vector = np.zeros(self.dim, dtype=np.float32)

        ngrams = self._extract_ngrams(text)
        ngram_counts = Counter(ngrams)

        # TF-IDF: term_frequency * inverse_document_frequency
        for ngram, count in ngram_counts.items():
            if ngram in self.vocabulary:
                idx = self.vocabulary[ngram]
                tf = count / max(len(ngrams), 1)  # Normalize by doc length
                idf = self.idf_weights.get(ngram, 1.0)
                vector[idx] = tf * idf

        # L2 normalize
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm

        return vector

    def _vector_to_pgvector_string(self, vector: np.ndarray) -> str:
        """Convert numpy array to pgvector string format."""
        # pgvector format: "[val1, val2, ..., valN]"
        return "[" + ",".join(f"{v:.6f}" for v in vector.tolist()) + "]"

    def build_index(self) -> Dict[str, Any]:
        """
        Build TF-IDF index for all SDN entries and store in pgvector.

        Fetches all SDN entities, builds vocabulary, computes embeddings,
        and stores in sanctions_embeddings table.

        Returns:
            Dict with:
            - entities_indexed: Number of entities indexed
            - duration_ms: Processing time in milliseconds
            - vocabulary_size: Size of TF-IDF vocabulary
        """
        import time

        start_time = time.time()
        conn = get_conn()

        try:
            cur = conn.cursor()

            # Create sanctions_embeddings table if not exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sanctions_embeddings (
                    sdn_id TEXT PRIMARY KEY,
                    entity_name TEXT NOT NULL,
                    embedding vector(%d),
                    programs TEXT[],
                    entity_type TEXT,
                    indexed_at TIMESTAMP DEFAULT NOW()
                );
            """, (self.dim,))

            # Create vector index for fast ANN search
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_sanctions_embeddings_vector
                ON sanctions_embeddings USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 50);
            """)

            # Fetch all SDN entries (assuming they come from ofac.py integration)
            # This assumes an ofac table or similar exists in the database
            cur.execute("""
                SELECT DISTINCT sdn_id, entity_name
                FROM ofac_entities
                ORDER BY sdn_id
            """)

            sdn_rows = cur.fetchall()
            logger.info(f"Fetched {len(sdn_rows)} SDN entities for indexing")

            if not sdn_rows:
                logger.warning("No SDN entities found to index")
                return {
                    "entities_indexed": 0,
                    "duration_ms": 0,
                    "vocabulary_size": 0,
                }

            # Build vocabulary from all entity names
            entity_names = [row[1] for row in sdn_rows]
            self._build_vocabulary(entity_names)

            # Compute embeddings and insert
            inserted_count = 0
            for sdn_id, entity_name in sdn_rows:
                vector = self._text_to_vector(entity_name)
                vector_str = self._vector_to_pgvector_string(vector)

                try:
                    cur.execute("""
                        INSERT INTO sanctions_embeddings
                        (sdn_id, entity_name, embedding, entity_type)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (sdn_id) DO UPDATE
                        SET embedding = EXCLUDED.embedding,
                            indexed_at = NOW()
                    """,
                    (sdn_id, entity_name, vector_str, "entity"),
                    )
                    inserted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to insert embedding for {sdn_id}: {e}")

            conn.commit()
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(
                f"Indexed {inserted_count} entities in {duration_ms}ms. "
                f"Vocabulary size: {len(self.vocabulary)}"
            )

            return {
                "entities_indexed": inserted_count,
                "duration_ms": duration_ms,
                "vocabulary_size": len(self.vocabulary),
            }

        except Exception as e:
            logger.error(f"Error building semantic index: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def search(
        self,
        query: str,
        top_k: int = 20,
        threshold: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search against sanctions embeddings.

        Uses pgvector cosine similarity for ANN search.

        Args:
            query: Entity name to search for
            top_k: Number of results to return (default 20)
            threshold: Minimum similarity threshold (default 0.3)

        Returns:
            List of dicts with:
            - entity_name: Matched entity name
            - sdn_id: SDN identifier
            - similarity: Cosine similarity score (0-1)
            - entity_type: Entity type
        """
        conn = get_conn()

        try:
            cur = conn.cursor()

            # Convert query to embedding
            query_vector = self._text_to_vector(query)
            query_vector_str = self._vector_to_pgvector_string(query_vector)

            # Search using pgvector cosine similarity
            cur.execute("""
                SELECT sdn_id, entity_name, embedding <=> %s::vector AS distance,
                       entity_type
                FROM sanctions_embeddings
                ORDER BY distance ASC
                LIMIT %s
            """,
            (query_vector_str, top_k),
            )

            results = []
            for sdn_id, entity_name, distance, entity_type in cur.fetchall():
                # Convert distance to similarity (cosine distance = 1 - cosine similarity)
                similarity = max(0, 1.0 - float(distance))

                if similarity >= threshold:
                    results.append({
                        "entity_name": entity_name,
                        "sdn_id": sdn_id,
                        "similarity": round(similarity, 4),
                        "entity_type": entity_type,
                    })

            return results

        except Exception as e:
            logger.error(f"Error in semantic search: {e}")
            return []
        finally:
            conn.close()

    def hybrid_search(
        self,
        query: str,
        top_k: int = 20,
        fuzzy_threshold: float = 0.75,
    ) -> List[Dict[str, Any]]:
        """
        Combine semantic search + fuzzy string matching.

        Uses both pgvector semantic search and existing OFAC fuzzy matcher.
        Deduplicates results and ranks by combined score.

        Args:
            query: Entity name to search for
            top_k: Number of results to return
            fuzzy_threshold: Fuzzy matching threshold (0-1)

        Returns:
            List of matched entities with combined scores, sorted by relevance
        """
        try:
            # Semantic search
            semantic_results = self.search(query, top_k=top_k, threshold=0.2)

            # Fuzzy string matching via OFAC module
            from ofac import fuzzy_match_sdn_entities

            fuzzy_results = fuzzy_match_sdn_entities(query, threshold=fuzzy_threshold)

            # Combine results by sdn_id
            combined = {}

            for result in semantic_results:
                sdn_id = result["sdn_id"]
                combined[sdn_id] = {
                    "entity_name": result["entity_name"],
                    "sdn_id": sdn_id,
                    "semantic_score": result["similarity"],
                    "fuzzy_score": 0.0,
                    "entity_type": result.get("entity_type"),
                }

            for result in fuzzy_results:
                sdn_id = result.get("sdn_id")
                if sdn_id:
                    if sdn_id in combined:
                        combined[sdn_id]["fuzzy_score"] = result.get("score", 0.0)
                    else:
                        combined[sdn_id] = {
                            "entity_name": result.get("entity_name"),
                            "sdn_id": sdn_id,
                            "semantic_score": 0.0,
                            "fuzzy_score": result.get("score", 0.0),
                            "entity_type": result.get("entity_type"),
                        }

            # Compute combined score (weighted average: 60% semantic, 40% fuzzy)
            for entry in combined.values():
                combined_score = (
                    0.6 * entry["semantic_score"] + 0.4 * entry["fuzzy_score"]
                )
                entry["combined_score"] = round(combined_score, 4)

            # Sort by combined score, take top_k
            results = sorted(
                combined.values(),
                key=lambda x: x["combined_score"],
                reverse=True,
            )[:top_k]

            return results

        except ImportError:
            logger.warning("OFAC module not available, using semantic search only")
            return self.search(query, top_k=top_k, threshold=0.3)
        except Exception as e:
            logger.error(f"Error in hybrid search: {e}")
            return []
