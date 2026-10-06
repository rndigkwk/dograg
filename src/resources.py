"""Heavy shared resources (models, indexes, databases), loaded once per server process.

Paths and loaders live here so tests and scripts redirect them in one place,
e.g. `resources.CHROMA_DIR = copy` or `patch.object(resources, "load_chat_model", ...)`.
Callers use `resources.<name>()` rather than importing the functions, so such
patches reach every tool module.
"""

from __future__ import annotations

import streamlit as st
from langchain_chroma import Chroma
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src import settings
from src.health_answers import load_health_answers
from src.onnx_embeddings import OnnxSentenceEmbeddings

DATA_DIR = settings.PROJECT_DIR / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"
DB_PATH = DATA_DIR / "hospital.db"
# Health answers live in the CSV, not in Chroma metadata (see src/health_answers.py).
HEALTH_CSV_PATH = DATA_DIR / "df.csv"
# Pre-tokenized health documents; rebuild with scripts/build_bm25_cache.py.
BM25_TOKEN_CACHE = DATA_DIR / "bm25_health_tokens.json.gz"
HEALTH_TOKENIZER_VERSION = "kiwi-nouns-sl-sn-v2"
# Health Q&A stays on local ko-sroberta: OpenAI embeddings lowered hybrid hit@3
# from 0.2674 to 0.2353 (docs/wiki/retrieval-experiments.md, experiment 5).
HEALTH_COLLECTION_NAME = "pet_care"
HEALTH_EMBEDDING_MODEL_NAME = "jhgan/ko-sroberta-multitask"
# 같은 가중치의 ONNX 내보내기(모델 저장소 제공). torch 없이 onnxruntime으로 질문을 임베딩합니다.
HEALTH_ONNX_FILE = "onnx/model_qint8_avx512_vnni.onnx"
# Reports use OpenAI text-embedding-3-small (built by scripts/ingest_openai_chroma.py);
# the hash suffix pins the exact source PDFs the vectors were built from.
EMBEDDING_MODEL_NAME = "text-embedding-3-small"
REPORT_COLLECTION_NAME = "pet_reports_openai3small_1536_3233577ba398"
CHAT_MODEL_NAME = "gpt-6-luna"


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
        embedding_function=OnnxSentenceEmbeddings.from_hub(HEALTH_EMBEDDING_MODEL_NAME, HEALTH_ONNX_FILE),
        persist_directory=str(CHROMA_DIR),
    )


@st.cache_resource(show_spinner=False)
def load_health_answer_table():
    return load_health_answers(HEALTH_CSV_PATH)


@st.cache_resource(
    show_spinner="건강 Q&A BM25 색인을 준비합니다. 최초 실행은 수 분 걸릴 수 있습니다."
)
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
def load_report_vector_db():
    embeddings = create_embedding_model()
    if embeddings is None:
        return None
    return Chroma(
        collection_name=REPORT_COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(CHROMA_DIR),
    )


@st.cache_resource(show_spinner=False)
def load_chat_model():
    api_key = settings.get_openai_api_key()
    if not api_key:
        return None
    return ChatOpenAI(model=CHAT_MODEL_NAME, api_key=api_key)
