-- ============================================================================
-- GraphBrain v2: Relational, Vector, and Lexical Associative Memory Engine
-- ============================================================================

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA temp_store = MEMORY;

-- 1. Core Entity Nodes Table
CREATE TABLE IF NOT EXISTS memory_nodes (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,           -- 'PROJECT', 'CONCEPT', 'FILE', 'PREFERENCE', 'EPISODE'
    label TEXT NOT NULL,
    properties JSON NOT NULL,            -- Dynamic key-value attributes
    access_count INTEGER DEFAULT 1,
    decay_score REAL DEFAULT 1.0,        -- 0.0 to 1.0; exponential decay
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

-- 2. Directional Knowledge Edges
CREATE TABLE IF NOT EXISTS memory_edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL,              -- 'DEPENDS_ON', 'AUTHENTICATES_VIA', 'CONTAINS', 'PREFERS'
    weight REAL DEFAULT 1.0,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (source_id, target_id, relation),
    FOREIGN KEY(source_id) REFERENCES memory_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY(target_id) REFERENCES memory_nodes(id) ON DELETE CASCADE
);

-- 3. Lexical Full-Text Search (FTS5) Table
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    node_id UNINDEXED,
    content,
    tokenize = 'porter unicode61'
);

-- 4. Dense Vector Storage (Packed Float32/Int8 binary blobs)
CREATE TABLE IF NOT EXISTS memory_vectors (
    node_id TEXT PRIMARY KEY,
    dim INTEGER NOT NULL,
    embedding BLOB NOT NULL,             -- Contiguous float32 array
    FOREIGN KEY(node_id) REFERENCES memory_nodes(id) ON DELETE CASCADE
);

-- 5. Cold Archive Storage (Nodes with decay_score < 0.15)
CREATE TABLE IF NOT EXISTS cold_archive (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    label TEXT NOT NULL,
    properties JSON NOT NULL,
    final_decay_score REAL NOT NULL,
    archived_at INTEGER NOT NULL
);

-- Indexes for Fast Lookups & Traversal
CREATE INDEX IF NOT EXISTS idx_nodes_type_decay ON memory_nodes(entity_type, decay_score DESC);
CREATE INDEX IF NOT EXISTS idx_edges_lookup ON memory_edges(source_id, relation);
CREATE INDEX IF NOT EXISTS idx_edges_reverse ON memory_edges(target_id, relation);
