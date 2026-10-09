"""Heavy shared resources (models, indexes, databases), loaded once per server process.

Paths and loaders live here so tests and scripts redirect them in one place,
e.g. `resources.CHROMA_DIR = copy` or `patch.object(resources, "load_chat_model", ...)`.
Callers use `resources.<name>()` rather than importing the functions, so such
patches reach every tool module.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import streamlit as st
from langchain_chroma import Chroma
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src import settings
from src.health_answers import load_health_answers
from src.onnx_embeddings import OnnxSentenceEmbeddings

DATA_DIR = settings.PROJECT_DIR / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"
SOURCE_CHROMA_DIR = CHROMA_DIR
# Chroma writes to chroma.sqlite3 even when only reading, so local runs use a copy here
# (output/ is ignored by git) and the committed database stays unchanged.
LOCAL_CHROMA_COPY = settings.PROJECT_DIR / "output" / "chroma_runtime"
DB_PATH = DATA_DIR / "places.db"
# Health answers live in the CSV, not in Chroma metadata (see src/health_answers.py).
HEALTH_CSV_PATH = DATA_DIR / "df.csv"
# Pre-tokenized health documents; rebuild with scripts/build_bm25_cache.py.
BM25_TOKEN_CACHE = DATA_DIR / "bm25_health_tokens.json.gz"
HEALTH_TOKENIZER_VERSION = "kiwi-nouns-sl-sn-v2"
# Health Q&A stays on local ko-sroberta: OpenAI embeddings lowered hybrid hit@3
# from 0.2674 to 0.2353 (docs/wiki/retrieval-experiments.md, experiment 5).
HEALTH_COLLECTION_NAME = "pet_care"
# ko-sroberta fine-tuned on synthetic guardian questions (docs/wiki/embedding-finetune.md):
# short questions get a directly useful case in the top 3 for 0.625 -> 0.800 of them. Private model
# repo (trained on AI Hub data), so it is downloaded with HF_TOKEN. The Chroma health collection
# holds this model's vectors (scripts/rebuild_health_collection.py); the two change together.
HEALTH_EMBEDDING_MODEL_NAME = "blanden77/ko-sroberta-dograg-b"
# int8 ONNX export (scripts/export_finetuned_onnx.py); questions are embedded with onnxruntime, not torch.
HEALTH_ONNX_FILE = "onnx/model_qint8.onnx"
# Reports use OpenAI text-embedding-3-small (built by scripts/ingest_openai_chroma.py);
# the hash suffix pins the exact source PDFs the vectors were built from.
EMBEDDING_MODEL_NAME = "text-embedding-3-small"
REPORT_COLLECTION_NAME = "pet_reports_openai3small_1536_3233577ba398"
CHAT_MODEL_NAME = "gpt-6-luna"


def _source_stamp(source: Path) -> str:
    stat = (source / "chroma.sqlite3").stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def chroma_dir() -> Path:
    """The folder Chroma opens. The deployed app and any redirected CHROMA_DIR (tests, scripts)
    use it as is; a local run gets a copy that is refreshed when the source database changes."""
    if settings.deployed() or CHROMA_DIR != SOURCE_CHROMA_DIR:
        return CHROMA_DIR
    stamp_file = LOCAL_CHROMA_COPY / "source_stamp.txt"
    stamp = _source_stamp(CHROMA_DIR)
    if stamp_file.exists() and stamp_file.read_text(encoding="utf-8") == stamp:
        return LOCAL_CHROMA_COPY / "chroma_db"
    staging = LOCAL_CHROMA_COPY.with_name(f"{LOCAL_CHROMA_COPY.name}.{os.getpid()}")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(CHROMA_DIR, staging / "chroma_db")
    (staging / "source_stamp.txt").write_text(stamp, encoding="utf-8")
    shutil.rmtree(LOCAL_CHROMA_COPY, ignore_errors=True)
    staging.rename(LOCAL_CHROMA_COPY)
    return LOCAL_CHROMA_COPY / "chroma_db"


@st.cache_resource(show_spinner=False)
def create_embedding_model():
    """Query embeddings must match the stored vectors; None when no API key is set."""
    api_key = settings.get_openai_api_key()
    if not api_key:
        return None
    return OpenAIEmbeddings(model=EMBEDDING_MODEL_NAME, api_key=api_key)


@st.cache_resource(show_spinner=False)
def load_vector_db():
    return Chroma(
        collection_name=HEALTH_COLLECTION_NAME,
        embedding_function=OnnxSentenceEmbeddings.from_hub(
            HEALTH_EMBEDDING_MODEL_NAME, HEALTH_ONNX_FILE, token=settings.get_setting("HF_TOKEN")),
        persist_directory=str(chroma_dir()),
    )


@st.cache_resource(show_spinner=False)
def load_health_answer_table():
    return load_health_answers(HEALTH_CSV_PATH)


# No spinner: a cached loader's spinner sends messages through the script run it was called
# from. Called from a background thread (the warm-up, or a team researcher) that breaks two
# ways: NoSessionContext with no run attached (#47), and StopException when the attached run is
# stopped by a rerun mid-load (the warm-up died with it on the deployed app, 2026-10-09).
# The chat page shows its own progress line, and the token cache makes the build quick.
@st.cache_resource(show_spinner=False)
def load_health_bm25_index():
    from src.hybrid_retrieval import HealthBM25Index

    return HealthBM25Index.from_chroma(
        load_vector_db(),
        make_health_tokenizer(),
        token_cache=BM25_TOKEN_CACHE,
        tokenizer_version=HEALTH_TOKENIZER_VERSION,
    )


def make_health_tokenizer():
    """Kiwi nouns, foreign words and numbers. Bump HEALTH_TOKENIZER_VERSION when this changes."""
    from kiwipiepy import Kiwi

    # 다어절 사전을 끄면 Kiwi 메모리가 약 480MB에서 290MB로 줄고 hit@3은 그대로입니다(문서 0.9%만 토큰이 달라짐).
    kiwi = Kiwi(load_multi_dict=False)

    def tokenize(text):
        normalized = text.replace("･", "·")
        return [
            token.form.lower()
            for token in kiwi.tokenize(normalized)
            if token.tag.startswith("N") or token.tag in {"SL", "SN"}
        ]

    return tokenize


@st.cache_resource(show_spinner=False)
def load_report_bm25_index():
    """BM25 over the report chunks (1,193). Uses the health index's tokenizer, so no second Kiwi
    (about 290MB) is loaded; tokenizing the chunks takes a few seconds once per process."""
    from src.hybrid_retrieval import HealthBM25Index

    db = load_report_vector_db()
    if db is None:
        return None
    return HealthBM25Index.from_chroma(db, load_health_bm25_index().tokenize)


@st.cache_resource(show_spinner=False)
def load_report_vector_db():
    embeddings = create_embedding_model()
    if embeddings is None:
        return None
    return Chroma(
        collection_name=REPORT_COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(chroma_dir()),
    )


# CRAG evidence review is a yes/no choice over a few candidates; without reasoning tokens its
# p90 dropped from 6.1s to 2.4s on the 40 health questions with no loss in answer/abstain
# decisions (docs/wiki/deployment-resources.md). CRAG_REVIEW_REASONING_EFFORT overrides it.
REVIEW_REASONING_EFFORT = "none"


@st.cache_resource(show_spinner=False)
def load_review_model():
    api_key = settings.get_openai_api_key()
    if not api_key:
        return None
    effort = settings.get_setting("CRAG_REVIEW_REASONING_EFFORT") or REVIEW_REASONING_EFFORT
    return ChatOpenAI(model=CHAT_MODEL_NAME, api_key=api_key, reasoning_effort=effort)


@st.cache_resource(show_spinner=False)
def load_chat_model():
    api_key = settings.get_openai_api_key()
    if not api_key:
        return None
    # CHAT_REASONING_EFFORT: "none", "low", "medium" (the model default when unset), "high".
    effort = settings.get_setting("CHAT_REASONING_EFFORT")
    return ChatOpenAI(model=CHAT_MODEL_NAME, api_key=api_key, **({"reasoning_effort": effort} if effort else {}))
