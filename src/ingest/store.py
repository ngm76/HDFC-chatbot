"""Phase 4: persist chunk embeddings in ChromaDB (architecture §4.1 Store, §11).

Persistent client at data/chroma/, collection hdfc_mf_faq, cosine space.
Rebuild is idempotent: the collection is dropped and recreated, then filled with
ids=chunk_id, so re-running never duplicates rows or keeps chunks from URLs that
left the registry. The user-query retriever is Phase 6 (src/rag/retrieve.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import src.ingest.chroma_compat  # noqa: F401  (must run before chromadb is imported)
import chromadb
import numpy as np
from chromadb.api.models.Collection import Collection

from src.ingest.chunk import Chunk
from src.ingest.embed import EMBED_DIM, MODEL_ID

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHROMA_DIR = PROJECT_ROOT / "data" / "chroma"
COLLECTION_NAME = "hdfc_mf_faq"
UPSERT_BATCH = 500

# Embeddings are L2-normalized, so cosine distance = 1 - dot product.
_COLLECTION_METADATA = {"hnsw:space": "cosine", "embedding_model": MODEL_ID}


def _client(path: Path) -> chromadb.ClientAPI:
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def open_collection(path: Path = CHROMA_DIR) -> Collection:
    """Open the existing collection (raises if ingest has not run)."""
    return _client(path).get_collection(COLLECTION_NAME)


def rebuild_collection(
    chunks: Sequence[Chunk],
    embeddings: np.ndarray,
    path: Path = CHROMA_DIR,
) -> Collection:
    """Drop and recreate the collection, then store documents + vectors + metadata."""
    if len(chunks) != len(embeddings):
        raise ValueError(f"{len(chunks)} chunks but {len(embeddings)} embeddings")
    if len(embeddings) and embeddings.shape[1] != EMBED_DIM:
        raise ValueError(f"expected {EMBED_DIM}-dim embeddings, got {embeddings.shape[1]}")
    ids = [c.chunk_id for c in chunks]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate chunk_id values; check sources.csv for repeated URLs")

    client = _client(path)
    if COLLECTION_NAME in {c.name for c in client.list_collections()}:
        client.delete_collection(COLLECTION_NAME)
    collection = client.create_collection(COLLECTION_NAME, metadata=_COLLECTION_METADATA)

    for start in range(0, len(chunks), UPSERT_BATCH):
        batch = chunks[start : start + UPSERT_BATCH]
        collection.upsert(
            ids=[c.chunk_id for c in batch],
            documents=[c.text for c in batch],
            embeddings=embeddings[start : start + UPSERT_BATCH].tolist(),
            metadatas=[c.metadata() for c in batch],
        )
    return collection
