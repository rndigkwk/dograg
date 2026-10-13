"""Exact vector search in memory: the store ADR-0003 proposes in place of Chroma.

The vectors are normalized, so cosine similarity is a dot product; one matrix-vector product over
all documents is the same exact search as FAISS IndexFlatIP (19,206 x 768 in about 4 ms), without
adding faiss. The class has the three things the app uses from LangChain's Chroma:
similarity_search(query, k, filter), get(include=...) for the BM25 index, and `embeddings`.
Files: <dir>/vectors.npy (float32, row i = document i) and <dir>/documents.jsonl
({"id", "text", "metadata"} per line), written by scripts/export_vector_store.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from langchain_core.documents import Document

from src.hybrid_retrieval import matches_metadata_filter

VECTORS_FILE = "vectors.npy"
DOCUMENTS_FILE = "documents.jsonl"


class ExactVectorStore:
    def __init__(self, ids: list[str], texts: list[str], metadatas: list[dict], vectors: np.ndarray, embeddings: Any):
        if not (len(ids) == len(texts) == len(metadatas) == len(vectors)):
            raise ValueError("ids, texts, metadatas and vectors must have the same length")
        self.ids, self.texts, self.metadatas = ids, texts, metadatas
        self.vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        self.embeddings = embeddings
        self._filter_masks: dict[str, np.ndarray] = {}

    @classmethod
    def load(cls, directory: Path, embeddings: Any) -> "ExactVectorStore":
        directory = Path(directory)
        ids, texts, metadatas = [], [], []
        with (directory / DOCUMENTS_FILE).open(encoding="utf-8") as file:
            for line in file:
                row = json.loads(line)
                ids.append(row["id"])
                texts.append(row["text"])
                metadatas.append(row["metadata"])
        return cls(ids, texts, metadatas, np.load(directory / VECTORS_FILE), embeddings)

    def _mask(self, where: dict) -> np.ndarray:
        key = json.dumps(where, sort_keys=True, ensure_ascii=False)
        if key not in self._filter_masks:  # a handful of filter shapes; computed once each
            self._filter_masks[key] = np.array([matches_metadata_filter(m, where) for m in self.metadatas])
        return self._filter_masks[key]

    def similarity_search(self, query: str, k: int = 4, filter: dict | None = None) -> list[Document]:  # noqa: A002 - Chroma's name
        vector = np.asarray(self.embeddings.embed_query(query), dtype=np.float32)
        vector /= np.linalg.norm(vector) or 1.0
        scores = self.vectors @ vector
        if filter:
            scores = np.where(self._mask(filter), scores, -np.inf)
        top = np.argsort(-scores, kind="stable")[:k]
        return [Document(id=self.ids[i], page_content=self.texts[i], metadata=dict(self.metadatas[i]))
                for i in top if np.isfinite(scores[i])]

    def get(self, include: list[str] | None = None) -> dict:
        return {"ids": list(self.ids), "documents": list(self.texts), "metadatas": [dict(m) for m in self.metadatas]}


def write_store(directory: Path, ids: list[str], texts: list[str], metadatas: list[dict], vectors: np.ndarray) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / VECTORS_FILE, np.asarray(vectors, dtype=np.float32))
    with (directory / DOCUMENTS_FILE).open("w", encoding="utf-8") as file:
        for doc_id, text, metadata in zip(ids, texts, metadatas):
            file.write(json.dumps({"id": doc_id, "text": text, "metadata": metadata or {}}, ensure_ascii=False) + "\n")
