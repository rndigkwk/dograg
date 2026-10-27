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
from typing import Any

from langchain_core.runnables.fallbacks import RunnableWithFallbacks
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src import settings
from src.cache import cache_resource
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
# Supabase tables for SEARCH_BACKEND=supabase (scripts/export_supabase_store.py fills them).
SUPABASE_HEALTH_TABLE = "ragdog_health"
SUPABASE_REPORT_TABLE = "ragdog_report"


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


@cache_resource
def create_embedding_model():
    """Query embeddings must match the stored vectors; None when no API key is set."""
    api_key = settings.get_openai_api_key()
    if not api_key:
        return None
    return OpenAIEmbeddings(model=EMBEDDING_MODEL_NAME, api_key=api_key)


def search_backend() -> str:
    """Where the four search indexes live. "supabase" (SEARCH_BACKEND=supabase with SUPABASE_DB_URL
    set) searches the Supabase tables (docs/adr/0007) and falls back to the local stores when the
    database fails; anything else is "local": Chroma + Kiwi BM25 in this process."""
    if (settings.get_setting("SEARCH_BACKEND") or "").strip().lower() == "supabase" and settings.get_setting("SUPABASE_DB_URL"):
        return "supabase"
    return "local"


@cache_resource
def load_search_breaker():
    """One per process, shared by the four Supabase searches, so an outage costs one timeout."""
    from src.supabase_store import Breaker

    return Breaker()


def search_on_fallback() -> bool:
    """Whether the Supabase searches answer from the local stores right now (the breaker is open)."""
    return search_backend() == "supabase" and load_search_breaker().open


def _supabase(primary_class, table: str, load_local, *args):
    from src import supabase_store

    primary = primary_class(supabase_store.connector(settings.get_setting("SUPABASE_DB_URL")), table, *args)
    wrapper = supabase_store.FallbackVectorStore if primary_class is supabase_store.PgVectorStore else supabase_store.FallbackIndex
    return wrapper(primary, load_local, load_search_breaker())


def clear_vector_db_cache() -> None:
    """For scripts that point CHROMA_DIR or the health model elsewhere and load again."""
    for loader in (load_vector_db, load_local_vector_db, load_health_embeddings):
        loader.clear()


# The search Supabase falls back to (docs/adr/0007): the exact in-memory store (numpy, no chromadb)
# and no Kiwi. Health uses the vectors alone: dense useful@3 0.827 vs 0.809 with Kiwi BM25 on the 220
# judged questions. Reports add a character-bigram BM25 over their 1,193 chunks: gold page in the
# top 6 15/18 vs 16/18 with Kiwi and 12/18 without keywords (scripts/evaluate_light_fallback.py).
FALLBACK_STORE_DIR = DATA_DIR / "vector_store"


class NoKeywordIndex:
    """A keyword index that finds nothing, so the hybrid search returns the dense ranking."""

    def search(self, query, top_k, where=None):
        return []


@cache_resource
def load_fallback_vector_db():
    from src.vector_store import ExactVectorStore

    return ExactVectorStore.load(FALLBACK_STORE_DIR / "health", load_health_embeddings())


@cache_resource
def load_fallback_health_index():
    return NoKeywordIndex()


@cache_resource
def load_fallback_report_vector_db():
    embeddings = create_embedding_model()
    if embeddings is None:
        return None
    from src.vector_store import ExactVectorStore

    return ExactVectorStore.load(FALLBACK_STORE_DIR / "report", embeddings)


@cache_resource
def load_fallback_report_index():
    from src.hybrid_retrieval import HealthBM25Index, bigram_tokenize

    db = load_fallback_report_vector_db()
    return None if db is None else HealthBM25Index.from_chroma(db, bigram_tokenize)


@cache_resource
def load_health_embeddings():
    return OnnxSentenceEmbeddings.from_hub(HEALTH_EMBEDDING_MODEL_NAME, HEALTH_ONNX_FILE, token=settings.get_setting("HF_TOKEN"))


@cache_resource
def load_vector_db():
    if search_backend() == "supabase":
        from src.supabase_store import PgVectorStore

        return _supabase(PgVectorStore, SUPABASE_HEALTH_TABLE, load_fallback_vector_db, load_health_embeddings())
    return load_local_vector_db()


@cache_resource
def load_local_vector_db():
    # Imported here: chromadb is heavy, and a store that does not use it should not load it
    # (ADR-0003, scripts/measure_memory.py --store).
    from langchain_chroma import Chroma

    return Chroma(
        collection_name=HEALTH_COLLECTION_NAME,
        embedding_function=load_health_embeddings(),
        persist_directory=str(chroma_dir()),
    )


@cache_resource
def load_health_answer_table():
    return load_health_answers(HEALTH_CSV_PATH)


# No spinner: a cached loader's spinner sends messages through the script run it was called
# from. Called from a background thread (the warm-up, or a team researcher) that breaks two
# ways: NoSessionContext with no run attached (#47), and StopException when the attached run is
# stopped by a rerun mid-load (the warm-up died with it on the deployed app, 2026-10-09).
# The chat page shows its own progress line, and the token cache makes the build quick.
@cache_resource
def load_health_bm25_index():
    if search_backend() == "supabase":
        # Dense only, as the fallback already was: with the fine-tuned query model, PGroonga's keyword
        # half put unrelated consultations into the top 3 (precision@3 0.73 -> 0.94 without it,
        # Wilcoxon p=5e-9; useful@3 0.81 -> 0.84, p=0.58), on the fully judged relevance set
        # (2026-10-20, docs/wiki/retrieval-experiments.md). The local mode keeps Kiwi BM25.
        return load_fallback_health_index()
    return load_local_health_bm25_index()


@cache_resource
def load_local_health_bm25_index():
    from src.hybrid_retrieval import HealthBM25Index

    return HealthBM25Index.from_chroma(
        load_local_vector_db(),
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


@cache_resource
def load_report_bm25_index():
    if search_backend() == "supabase":
        if create_embedding_model() is None:
            return None
        # The report keyword half is the in-memory bigram BM25 over the exact store, not PGroonga: the
        # reports are 1,340 chunks (1.5 s to build, 34 MB, 5 ms a query), and PGroonga's &@* ranked
        # other survey tables first where BM25 found the page (h04: 산업 조사체계 p.50; holdout
        # 16 -> 17/17, dev 17/18 kept; docs/wiki/retrieval-experiments.md). Dense stays on Supabase.
        return load_fallback_report_index()
    return load_local_report_bm25_index()


@cache_resource
def load_local_report_bm25_index():
    """BM25 over the report chunks (1,193). Uses the health index's tokenizer, so no second Kiwi
    (about 290MB) is loaded; tokenizing the chunks takes a few seconds once per process."""
    from src.hybrid_retrieval import HealthBM25Index

    db = load_local_report_vector_db()
    if db is None:
        return None
    return HealthBM25Index.from_chroma(db, load_local_health_bm25_index().tokenize)


@cache_resource
def load_report_vector_db():
    if search_backend() == "supabase":
        embeddings = create_embedding_model()
        if embeddings is None:
            return None
        from src.supabase_store import PgVectorStore

        return _supabase(PgVectorStore, SUPABASE_REPORT_TABLE, load_fallback_report_vector_db, embeddings)
    return load_local_report_vector_db()


@cache_resource
def load_local_report_vector_db():
    embeddings = create_embedding_model()
    if embeddings is None:
        return None
    from langchain_chroma import Chroma

    return Chroma(
        collection_name=REPORT_COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(chroma_dir()),
    )


# CRAG evidence review is a yes/no choice over a few candidates; without reasoning tokens its
# p90 dropped from 6.1s to 2.4s on the 40 health questions with no loss in answer/abstain
# decisions (docs/wiki/deployment-resources.md). CRAG_REVIEW_REASONING_EFFORT overrides it.
REVIEW_REASONING_EFFORT = "none"

# How long one model request may take before it is given up, and one retry (the client's default
# was 600 seconds and two retries, so a stalled provider held a guardian for minutes). Generous next
# to what the calls take (2026-10-23): the grader and the crisis check p90 2.4s, a whole health
# answer p90 11.4s. For the streamed answer the limit is per wait between pieces, not the whole
# answer. A timed-out request shows the search without an answer (src/model_outage.py).
REVIEW_TIMEOUT_SECONDS = 20
CHAT_TIMEOUT_SECONDS = 30
ANSWER_TIMEOUT_SECONDS = 45
MODEL_MAX_RETRIES = 1

# When OpenAI does not answer, the same call goes once to Claude. The OpenAI key is the academy's and
# its limit ran out on 2026-10-19: four rate-limit errors that week, the weekly SLO's only errors.
# Only the provider's own failures switch (rate limit or quota, timeout, no connection, 5xx); a
# request of ours that OpenAI rejects stays an error. When Claude fails too (any Anthropic API error,
# a bad key included), OpenAI's error is raised, so src/model_outage.py still shows the search.
# No ANTHROPIC_API_KEY: OpenAI alone.
# Thinking off: the grader runs without reasoning on OpenAI too, and Haiku 5.5 rejects the forced
# tool call of with_structured_output while thinking is on.
FALLBACK_MODEL_NAME = "claude-haiku-5-5"
FALLBACK_MAX_TOKENS = 4096
# The outage drill (deploy-cloud-run.yml, fault=openai, a candidate that never gets traffic): the
# chat models send to an address nothing listens on, so every call fails to connect and the canary
# health question passes only when Claude answers it.
OPENAI_FAULT = "openai"
UNREACHABLE_OPENAI_URL = "http://127.0.0.1:9/v1"


def openai_max_retries() -> int:
    """No retry of OpenAI when Claude is behind it: a failed call takes 6.6 s with its retry (the
    drill, 2026-10-27), and a health question makes 8-10 calls (73 s in all)."""
    return 0 if settings.get_setting("ANTHROPIC_API_KEY") else MODEL_MAX_RETRIES


def openai_base_url() -> str | None:
    """None (OpenAI) except in the drill."""
    return UNREACHABLE_OPENAI_URL if settings.get_setting("RAGDOG_FAULT") == OPENAI_FAULT else None


def fallback_errors() -> tuple[type[BaseException], ...]:
    """OpenAI's errors that go to Claude, and Claude's own: LangChain raises the first error only
    when every error on the way is one of these (APITimeoutError is an APIConnectionError)."""
    import anthropic
    import openai

    return openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError, anthropic.APIError


# After an OpenAI call fails over to Claude, the next calls go to Claude alone for this long. A timed
# out call waits its whole limit (20-45 s) before Claude answers, and without the breaker every call
# of a health question (8-10) would wait again while OpenAI stalls.
OPENAI_BREAKER_SECONDS = 120


@cache_resource
def load_openai_breaker():
    """One per process, shared by the chat, review and answer models: one provider, one state."""
    from src.supabase_store import Breaker

    return Breaker(cooldown=OPENAI_BREAKER_SECONDS, name="OpenAI call", instead="Claude alone")


class BreakerFallbacks(RunnableWithFallbacks):
    """with_fallbacks that skips OpenAI while the breaker is open. Every LangChain call (invoke,
    stream, their async forms, batch) walks `runnables` and asks for the next one only after the one
    before raised a handled error, so asking past OpenAI is the failure that trips it.
    with_structured_output and bind_tools copy the breaker over (RunnableWithFallbacks.__getattr__)."""

    breaker: Any = None

    @property
    def runnables(self):
        if not self.breaker.open:
            yield self.runnable
            self.breaker.trip()
        yield from self.fallbacks


def with_claude_fallback(model, timeout: float):
    """`model` that hands a failed call to Claude, or `model` itself without an Anthropic key."""
    api_key = settings.get_setting("ANTHROPIC_API_KEY")
    if not api_key:
        return model
    from langchain_anthropic import ChatAnthropic

    workspace = settings.get_setting("ANTHROPIC_WORKSPACE_ID")
    claude = ChatAnthropic(
        model=FALLBACK_MODEL_NAME, api_key=api_key, timeout=timeout, max_retries=MODEL_MAX_RETRIES,
        max_tokens=FALLBACK_MAX_TOKENS, thinking={"type": "disabled"},
        default_headers={"anthropic-workspace-id": workspace} if workspace else None,
    )
    return BreakerFallbacks(runnable=model, fallbacks=[claude], exceptions_to_handle=fallback_errors(),
                            breaker=load_openai_breaker())


@cache_resource
def load_review_model():
    api_key = settings.get_openai_api_key()
    if not api_key:
        return None
    effort = settings.get_setting("CRAG_REVIEW_REASONING_EFFORT") or REVIEW_REASONING_EFFORT
    return with_claude_fallback(ChatOpenAI(model=CHAT_MODEL_NAME, api_key=api_key, reasoning_effort=effort,
                                           timeout=REVIEW_TIMEOUT_SECONDS, max_retries=openai_max_retries(),
                                           base_url=openai_base_url()),
                                REVIEW_TIMEOUT_SECONDS)


@cache_resource
def load_chat_model():
    api_key = settings.get_openai_api_key()
    if not api_key:
        return None
    # CHAT_REASONING_EFFORT: "none", "low", "medium" (the model default when unset), "high".
    effort = settings.get_setting("CHAT_REASONING_EFFORT")
    return with_claude_fallback(
        ChatOpenAI(model=CHAT_MODEL_NAME, api_key=api_key, timeout=CHAT_TIMEOUT_SECONDS, max_retries=openai_max_retries(),
                   base_url=openai_base_url(), **({"reasoning_effort": effort} if effort else {})),
        CHAT_TIMEOUT_SECONDS)
