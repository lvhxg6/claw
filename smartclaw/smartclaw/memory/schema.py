"""Memory Schema — Database schema definitions for memory system.

Defines SQL statements for memory-related tables:
- memory_chunks: Stores markdown chunks with metadata
- memory_embeddings: Vector embeddings using sqlite-vec
- memory_fts: BM25 full-text search index
- facts: Extracted facts from conversations
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Memory Chunks Table (Task 10.1)
# ---------------------------------------------------------------------------

CREATE_MEMORY_CHUNKS_TABLE = """\
CREATE TABLE IF NOT EXISTS memory_chunks (
    hash TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding_input TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)"""

CREATE_MEMORY_CHUNKS_FILE_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_memory_chunks_file
    ON memory_chunks(file_path)"""

# ---------------------------------------------------------------------------
# Vector Embeddings Table (Task 10.2)
# Uses sqlite-vec extension for vector similarity search
# ---------------------------------------------------------------------------

# Note: sqlite-vec uses vec0 virtual table
# Dimension 1536 for OpenAI text-embedding-3-small
CREATE_MEMORY_EMBEDDINGS_TABLE = """\
CREATE VIRTUAL TABLE IF NOT EXISTS memory_embeddings USING vec0(
    hash TEXT PRIMARY KEY,
    embedding FLOAT[1536]
)"""

# ---------------------------------------------------------------------------
# BM25 Full-Text Search Table (Task 10.3)
# Uses FTS5 for keyword search
# ---------------------------------------------------------------------------

CREATE_MEMORY_FTS_TABLE = """\
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    hash,
    text,
    content='memory_chunks',
    content_rowid='rowid'
)"""

# Triggers to keep FTS index in sync with memory_chunks
CREATE_MEMORY_FTS_INSERT_TRIGGER = """\
CREATE TRIGGER IF NOT EXISTS memory_chunks_ai AFTER INSERT ON memory_chunks BEGIN
    INSERT INTO memory_fts(rowid, hash, text) VALUES (new.rowid, new.hash, new.text);
END"""

CREATE_MEMORY_FTS_DELETE_TRIGGER = """\
CREATE TRIGGER IF NOT EXISTS memory_chunks_ad AFTER DELETE ON memory_chunks BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, hash, text) VALUES('delete', old.rowid, old.hash, old.text);
END"""

CREATE_MEMORY_FTS_UPDATE_TRIGGER = """\
CREATE TRIGGER IF NOT EXISTS memory_chunks_au AFTER UPDATE ON memory_chunks BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, hash, text) VALUES('delete', old.rowid, old.hash, old.text);
    INSERT INTO memory_fts(rowid, hash, text) VALUES (new.rowid, new.hash, new.text);
END"""

# ---------------------------------------------------------------------------
# Facts Table (Task 10.4)
# Stores extracted facts from conversations
# ---------------------------------------------------------------------------

CREATE_FACTS_TABLE = """\
CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TIMESTAMP NOT NULL,
    source TEXT NOT NULL
)"""

CREATE_FACTS_CONFIDENCE_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_facts_confidence
    ON facts(confidence DESC)"""

# ---------------------------------------------------------------------------
# Schema initialization helpers
# ---------------------------------------------------------------------------

# All schema statements in order of execution
MEMORY_SCHEMA_STATEMENTS = [
    # Memory chunks
    CREATE_MEMORY_CHUNKS_TABLE,
    CREATE_MEMORY_CHUNKS_FILE_INDEX,
    # Facts (no dependencies)
    CREATE_FACTS_TABLE,
    CREATE_FACTS_CONFIDENCE_INDEX,
]

# Statements that require sqlite-vec extension
VECTOR_SCHEMA_STATEMENTS = [
    CREATE_MEMORY_EMBEDDINGS_TABLE,
]

# Statements that require FTS5 (built into SQLite)
FTS_SCHEMA_STATEMENTS = [
    CREATE_MEMORY_FTS_TABLE,
    CREATE_MEMORY_FTS_INSERT_TRIGGER,
    CREATE_MEMORY_FTS_DELETE_TRIGGER,
    CREATE_MEMORY_FTS_UPDATE_TRIGGER,
]


async def initialize_memory_schema(db: "aiosqlite.Connection") -> None:
    """Initialize memory-related tables.
    
    Args:
        db: aiosqlite database connection
    """
    for stmt in MEMORY_SCHEMA_STATEMENTS:
        await db.execute(stmt)
    await db.commit()


async def initialize_fts_schema(db: "aiosqlite.Connection") -> None:
    """Initialize FTS5 full-text search tables.
    
    Args:
        db: aiosqlite database connection
    """
    for stmt in FTS_SCHEMA_STATEMENTS:
        await db.execute(stmt)
    await db.commit()


async def initialize_vector_schema(db: "aiosqlite.Connection") -> bool:
    """Initialize sqlite-vec vector tables.
    
    Args:
        db: aiosqlite database connection
        
    Returns:
        True if sqlite-vec is available and tables created,
        False if sqlite-vec extension is not available
    """
    try:
        # Try to load sqlite-vec extension
        await db.enable_load_extension(True)
        # sqlite-vec is typically loaded as 'vec0' or via load_extension
        # The exact loading mechanism depends on installation
        for stmt in VECTOR_SCHEMA_STATEMENTS:
            await db.execute(stmt)
        await db.commit()
        return True
    except Exception:
        # sqlite-vec not available, will fall back to BM25-only search
        return False
