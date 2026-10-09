"""Rebuild the Chroma health collection with the fine-tuned model's document vectors.

    uv run python scripts/rebuild_health_collection.py

Documents, metadata and ids are copied from the current `pet_care` collection, so only the vectors
change. The vectors are the fine-tuned model's float embeddings of the 19,206 corpus questions,
computed on Colab with sentence-transformers (`corpus_embeddings.npy` in the model repo, the same
vectors scripts/evaluate_finetuned_embedding.py measured), L2-normalized like the current ones
(cosine space). Works on a copy and only replaces data/chroma_db/ at the end; the old database
is kept in output/chroma_db_before_finetune/. The report collection is untouched.
Upload the new database with `uv run python -m src.private_data --upload`.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

REPO_ID = "blanden77/ko-sroberta-dograg-b"
SOURCE = PROJECT_DIR / "data" / "chroma_db"
WORK = PROJECT_DIR / "output" / "chroma_db_finetuned"
BACKUP = PROJECT_DIR / "output" / "chroma_db_before_finetune"
COLLECTION = "pet_care"
BATCH = 2000


def main() -> int:
    import chromadb
    from dotenv import load_dotenv
    from huggingface_hub import snapshot_download

    load_dotenv(PROJECT_DIR / ".env")
    model_dir = Path(snapshot_download(REPO_ID, token=os.environ["HF_TOKEN"]))
    ids_order = json.loads((model_dir / "corpus_ids.json").read_text())
    vectors = np.load(model_dir / "corpus_embeddings.npy").astype("float64")
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    vector_of = dict(zip(ids_order, vectors))

    shutil.rmtree(WORK, ignore_errors=True)
    shutil.copytree(SOURCE, WORK)
    client = chromadb.PersistentClient(path=str(WORK))
    old = client.get_collection(COLLECTION)
    metadata = old.metadata
    stored = old.get(include=["documents", "metadatas"])
    ids, documents, metadatas = stored["ids"], stored["documents"], stored["metadatas"]
    assert len(ids) == len(vector_of) == 19206 and set(ids) == set(vector_of), "corpus ids differ"
    client.delete_collection(COLLECTION)
    new = client.create_collection(COLLECTION, metadata=metadata)
    for start in range(0, len(ids), BATCH):
        part = slice(start, start + BATCH)
        new.add(ids=ids[part], documents=documents[part], metadatas=metadatas[part],
                embeddings=[vector_of[i].tolist() for i in ids[part]])
    check = new.get(ids=["0"], include=["embeddings"])["embeddings"][0]
    assert abs(float(np.dot(check, vector_of["0"])) - 1) < 1e-5
    print(f"rebuilt {new.count()} vectors in {COLLECTION} ({metadata})")
    del new, old, client
    chromadb.api.client.SharedSystemClient.clear_system_cache()
    with sqlite3.connect(WORK / "chroma.sqlite3") as connection:
        connection.execute("VACUUM")
        live = {row[0] for row in connection.execute("SELECT id FROM segments")}
    # Chroma leaves the deleted collection's index folder behind (and Windows may still hold it
    # open), so copy only the database and the live segment folders.
    final = WORK.with_name(WORK.name + "_final")
    shutil.rmtree(final, ignore_errors=True)
    final.mkdir()
    shutil.copy2(WORK / "chroma.sqlite3", final / "chroma.sqlite3")
    for folder in WORK.iterdir():
        if folder.is_dir() and folder.name in live:
            shutil.copytree(folder, final / folder.name)
    shutil.rmtree(BACKUP, ignore_errors=True)
    shutil.move(str(SOURCE), str(BACKUP))
    shutil.move(str(final), str(SOURCE))
    shutil.rmtree(WORK, ignore_errors=True)
    size = sum(f.stat().st_size for f in SOURCE.rglob("*") if f.is_file())
    print(f"data/chroma_db replaced ({size / 1e6:.0f} MB); old copy in {BACKUP.relative_to(PROJECT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
