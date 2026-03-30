-- Sprint 16: Graph Embeddings & Link Prediction Schema
-- pgvector extension required: CREATE EXTENSION IF NOT EXISTS vector;

-- Entity embeddings (64-dimensional TransE vectors)
CREATE TABLE IF NOT EXISTS kg_embeddings (
    entity_id TEXT PRIMARY KEY REFERENCES kg_entities(entity_id) ON DELETE CASCADE,
    embedding vector(64) NOT NULL,
    model_version TEXT NOT NULL,
    trained_at TIMESTAMP DEFAULT NOW()
);

-- Relationship type embeddings (64-dimensional TransE vectors)
CREATE TABLE IF NOT EXISTS kg_relation_embeddings (
    relation_type TEXT PRIMARY KEY,
    embedding vector(64) NOT NULL,
    model_version TEXT NOT NULL,
    trained_at TIMESTAMP DEFAULT NOW()
);

-- Predicted links awaiting analyst review
CREATE TABLE IF NOT EXISTS kg_predicted_links (
    id SERIAL PRIMARY KEY,
    source_entity_id TEXT NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    target_entity_id TEXT NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
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
    UNIQUE (source_entity_id, target_entity_id, predicted_relation, model_version)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_kg_embeddings_model_version
  ON kg_embeddings(model_version);

CREATE INDEX IF NOT EXISTS idx_kg_predicted_links_source
  ON kg_predicted_links(source_entity_id);

CREATE INDEX IF NOT EXISTS idx_kg_predicted_links_reviewed
  ON kg_predicted_links(reviewed);

CREATE INDEX IF NOT EXISTS idx_kg_predicted_links_confirmed
  ON kg_predicted_links(analyst_confirmed);

CREATE INDEX IF NOT EXISTS idx_kg_predicted_links_model
  ON kg_predicted_links(model_version);

CREATE INDEX IF NOT EXISTS idx_kg_predicted_links_edge_family
  ON kg_predicted_links(predicted_edge_family);

-- Optional: pgvector HNSW index for faster similarity search
-- Requires: CREATE EXTENSION hnsw;
-- CREATE INDEX IF NOT EXISTS idx_kg_embeddings_vector_hnsw
--   ON kg_embeddings USING hnsw (embedding vector_cosine_ops);

-- Optional: pgvector IVFFlat index (more memory efficient for large datasets)
CREATE INDEX IF NOT EXISTS idx_kg_embeddings_vector_ivfflat
  ON kg_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 30);
