"""Copy the Chroma collections into the exact in-memory store's files (src/vector_store.py, ADR-0003).

    uv run python scripts/export_vector_store.py [--out data/vector_store]

Writes <out>/health and <out>/report: vectors.npy and documents.jsonl, the same ids, texts,
metadata and vectors Chroma holds (no re-embedding). Checks that every vector is unit length.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=PROJECT_DIR / "data" / "vector_store")
    args = parser.parse_args()
    import chromadb

    from src import resources
    from src.vector_store import write_store

    client = chromadb.PersistentClient(path=str(resources.chroma_dir()))
    for name, collection_name in (("health", resources.HEALTH_COLLECTION_NAME), ("report", resources.REPORT_COLLECTION_NAME)):
        got = client.get_collection(collection_name).get(include=["embeddings", "documents", "metadatas"])
        vectors = np.asarray(got["embeddings"], dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1)
        if not np.allclose(norms, 1.0, atol=1e-3):
            raise SystemExit(f"{name}: vectors are not unit length ({norms.min():.4f}~{norms.max():.4f})")
        write_store(args.out / name, list(got["ids"]), list(got["documents"]), list(got["metadatas"]), vectors)
        size = sum(p.stat().st_size for p in (args.out / name).iterdir())
        print(f"{name}: {len(vectors)} x {vectors.shape[1]}, {size / 2**20:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
