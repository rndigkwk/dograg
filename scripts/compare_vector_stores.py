"""Compare vector stores for the health search the way Day 58 does (accuracy, latency, cost, storage).

    uv run --with faiss-cpu --with "psycopg[binary]" --with psutil python scripts/compare_vector_stores.py [--keep]

The same 19,206 document vectors (fine-tuned ko-sroberta, normalized, ADR-0001) go into each
store; queries are the 561 validation questions embedded the way the app does (ONNX int8).
Because the vectors are the same, accuracy differs only by what an approximate index misses:
recall@12 against an exact numpy search (12 = candidates per retriever, ADR-0002), without a
filter and with the app's metadata filter shape (meta.lifeCycle = 성견).

Stores: Chroma (the app's, HNSW), FAISS exact (IndexFlatIP) and HNSW, pgvector on Supabase
(SUPABASE_DB_URL in .env; exact scan and an HNSW index). Only ids, vectors and the three labels
are uploaded (no consultation text); the table is dropped afterwards unless --keep.
Latency is per query from this PC (Seoul). Memory is the process RSS increase while loading
each in-process store, measured in a fresh subprocess. Results: output/experiments/vector_stores.json.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

K = 12
FILTER_KEY, FILTER_VALUE = "meta.lifeCycle", "성견"
TABLE = "ragdog_health_vectors_eval"
HNSW_M, HNSW_EF_CONSTRUCTION, HNSW_EF_SEARCH = 16, 64, 40  # pgvector defaults; FAISS set to match


def percentile(values: list[float], q: float) -> float:
    return round(float(np.percentile(values, q)) * 1000, 1)


def recall(found: list[list[str]], exact: list[list[str]]) -> float:
    return round(statistics.mean(len(set(f) & set(e)) / len(e) for f, e in zip(found, exact) if e), 4)


def rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 2**20


def memory_probe(store: str) -> None:
    """Child process: RSS before and after loading the store and running one query."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    data = np.load(os.environ["PROBE_NPZ"], allow_pickle=True)
    query = data["queries"][0]
    before = rss_mb()
    if store == "chroma":
        import chromadb

        from src import resources

        collection = chromadb.PersistentClient(path=str(resources.chroma_dir())).get_collection(resources.HEALTH_COLLECTION_NAME)
        collection.query(query_embeddings=[query.tolist()], n_results=K)
    else:
        import faiss

        vectors = data["vectors"]
        index = faiss.IndexHNSWFlat(vectors.shape[1], HNSW_M, faiss.METRIC_INNER_PRODUCT) if store == "faiss_hnsw" \
            else faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        del vectors
        index.search(query[None, :], K)
    print(json.dumps({"store": store, "rss_increase_mb": round(rss_mb() - before)}))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep the Supabase table")
    parser.add_argument("--probe")
    args = parser.parse_args()
    if args.probe:
        memory_probe(args.probe)
        return 0
    os.environ["HF_HUB_OFFLINE"] = "1"
    import chromadb
    import faiss
    import pandas as pd
    from dotenv import dotenv_values

    from src import resources

    collection = chromadb.PersistentClient(path=str(resources.chroma_dir())).get_collection(resources.HEALTH_COLLECTION_NAME)
    got = collection.get(include=["embeddings", "metadatas"])
    ids = list(got["ids"])
    vectors = np.asarray(got["embeddings"], dtype=np.float32)
    labels = [m.get(FILTER_KEY) for m in got["metadatas"]]
    norms = np.linalg.norm(vectors, axis=1)
    print(f"documents {len(ids)}, dim {vectors.shape[1]}, norm {norms.min():.3f}~{norms.max():.3f}")
    embedder = resources.load_vector_db()._embedding_function
    questions = pd.read_csv(PROJECT_DIR / "data" / "df_val.csv")["qa.input"].astype(str).tolist()
    queries = np.asarray([embedder.embed_query(q) for q in questions], dtype=np.float32)
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)
    filtered = np.array([label == FILTER_VALUE for label in labels])
    print(f"queries {len(queries)}, filter {FILTER_KEY}={FILTER_VALUE} keeps {filtered.sum()} documents")

    def exact(mask=None):
        scores = queries @ vectors.T
        if mask is not None:
            scores[:, ~mask] = -np.inf
        return [[ids[i] for i in np.argsort(-row)[:K]] for row in scores]

    reference, reference_filtered = exact(), exact(filtered)
    results = {}

    def timed(search, items):
        found, seconds = [], []
        for item in items:
            started = time.perf_counter()
            found.append(search(item))
            seconds.append(time.perf_counter() - started)
        return found, seconds

    # Chroma, as the app has it
    found, seconds = timed(lambda q: collection.query(query_embeddings=[q.tolist()], n_results=K)["ids"][0], queries)
    found_f, _ = timed(lambda q: collection.query(query_embeddings=[q.tolist()], n_results=K,
                                                  where={FILTER_KEY: FILTER_VALUE})["ids"][0], queries)
    size = sum(p.stat().st_size for p in resources.chroma_dir().rglob("*") if p.is_file())
    results["chroma_hnsw"] = {"recall@12": recall(found, reference), "recall@12_filter": recall(found_f, reference_filtered),
                              "p50_ms": percentile(seconds, 50), "p95_ms": percentile(seconds, 95),
                              "storage_mb": round(size / 2**20, 1), "storage_note": "whole Chroma dir (health + report collections, FTS, metadata)"}

    # FAISS exact and HNSW (in-process); the filter goes through an id selector
    for name, index in (("faiss_flat", faiss.IndexFlatIP(vectors.shape[1])),
                        ("faiss_hnsw", faiss.IndexHNSWFlat(vectors.shape[1], HNSW_M, faiss.METRIC_INNER_PRODUCT))):
        if name == "faiss_hnsw":
            index.hnsw.efConstruction = HNSW_EF_CONSTRUCTION
        started = time.perf_counter()
        index.add(vectors)
        build_s = time.perf_counter() - started
        if name == "faiss_hnsw":
            index.hnsw.efSearch = HNSW_EF_SEARCH
        found, seconds = timed(lambda q: [ids[i] for i in index.search(q[None, :], K)[1][0] if i >= 0], queries)
        selector = faiss.IDSelectorBatch(np.flatnonzero(filtered).astype("int64"))
        params = faiss.SearchParametersHNSW(sel=selector, efSearch=HNSW_EF_SEARCH) if name == "faiss_hnsw" \
            else faiss.SearchParameters(sel=selector)
        found_f, _ = timed(lambda q: [ids[i] for i in index.search(q[None, :], K, params=params)[1][0] if i >= 0], queries)
        results[name] = {"recall@12": recall(found, reference), "recall@12_filter": recall(found_f, reference_filtered),
                         "p50_ms": percentile(seconds, 50), "p95_ms": percentile(seconds, 95),
                         "build_s": round(build_s, 2), "storage_mb": round(faiss.serialize_index(index).nbytes / 2**20, 1)}

    # pgvector on Supabase
    import psycopg

    url = dotenv_values(PROJECT_DIR / ".env").get("SUPABASE_DB_URL") or os.environ.get("SUPABASE_DB_URL")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("create extension if not exists vector")
        conn.execute(f"drop table if exists {TABLE}")
        conn.execute(f"create table {TABLE} (id text primary key, life_cycle text, embedding vector({vectors.shape[1]}))")
        started = time.perf_counter()
        with conn.cursor().copy(f"copy {TABLE} (id, life_cycle, embedding) from stdin") as copy:
            for doc_id, label, vector in zip(ids, labels, vectors):
                copy.write_row((doc_id, label, "[" + ",".join(f"{x:.6f}" for x in vector) + "]"))
        upload_s = time.perf_counter() - started
        sql = f"select id from {TABLE} {{where}} order by embedding <=> %s::vector limit {K}"

        def pg_search(q, where=""):
            return [row[0] for row in conn.execute(sql.format(where=where), ("[" + ",".join(f"{x:.6f}" for x in q) + "]",))]

        conn.execute("select 1")
        for name in ("pgvector_exact", "pgvector_hnsw"):
            build_s = 0.0
            if name == "pgvector_hnsw":
                started = time.perf_counter()
                conn.execute(f"create index on {TABLE} using hnsw (embedding vector_cosine_ops) "
                             f"with (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})")
                build_s = time.perf_counter() - started
                conn.execute(f"set hnsw.ef_search = {HNSW_EF_SEARCH}")
            found, seconds = timed(pg_search, queries)
            found_f, _ = timed(lambda q: pg_search(q, f"where life_cycle = '{FILTER_VALUE}'"), queries)
            size = conn.execute(f"select pg_total_relation_size('{TABLE}')").fetchone()[0]
            results[name] = {"recall@12": recall(found, reference), "recall@12_filter": recall(found_f, reference_filtered),
                             "p50_ms": percentile(seconds, 50), "p95_ms": percentile(seconds, 95),
                             "build_s": round(build_s, 2), "upload_s": round(upload_s, 1), "storage_mb": round(size / 2**20, 1)}
        round_trip = []
        for _ in range(30):
            started = time.perf_counter()
            conn.execute("select 1").fetchone()
            round_trip.append(time.perf_counter() - started)
        results["pgvector_round_trip_ms"] = percentile(round_trip, 50)
        if not args.keep:
            conn.execute(f"drop table if exists {TABLE}")

    # memory, each in a fresh process
    probe = PROJECT_DIR / "output" / "experiments" / "vector_store_probe.npz"
    probe.parent.mkdir(parents=True, exist_ok=True)
    np.savez(probe, vectors=vectors, queries=queries[:1])
    for store in ("chroma", "faiss_flat", "faiss_hnsw"):
        reply = subprocess.run([sys.executable, __file__, "--probe", store], capture_output=True, text=True,
                               env={**os.environ, "PROBE_NPZ": str(probe)}, cwd=PROJECT_DIR)
        line = [x for x in reply.stdout.splitlines() if x.startswith("{")]
        key = "chroma_hnsw" if store == "chroma" else store
        results[key]["rss_increase_mb"] = json.loads(line[-1])["rss_increase_mb"] if line else None
    probe.unlink(missing_ok=True)

    print(json.dumps(results, ensure_ascii=False, indent=1))
    output = PROJECT_DIR / "output" / "experiments" / "vector_stores.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
