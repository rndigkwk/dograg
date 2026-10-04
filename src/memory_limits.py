"""Keep the app inside Streamlit Community Cloud's memory limit (2.7 GB).

Cloud containers report the host's CPU count, so torch and BLAS start one thread per
host core, and glibc gives busy threads their own malloc arenas. Both inflate memory
without making a 2-core app faster.
"""

from __future__ import annotations

import ctypes
import os
import sys

THREAD_LIMIT = 2
M_ARENA_MAX = -8  # glibc mallopt parameter
THREAD_ENV_VARS = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")


def _glibc():
    if not sys.platform.startswith("linux"):
        return None
    try:
        return ctypes.CDLL("libc.so.6")
    except OSError:
        return None


def limit_native_memory(threads: int = THREAD_LIMIT, arenas: int = 2) -> None:
    """Cap native threads and malloc arenas. Call before torch is imported."""
    for name in THREAD_ENV_VARS:
        os.environ.setdefault(name, str(threads))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    libc = _glibc()
    if libc is not None:
        libc.mallopt(M_ARENA_MAX, arenas)


def release_free_memory() -> None:
    """Return freed heap pages to the OS after a large load (no-op off glibc)."""
    libc = _glibc()
    if libc is not None:
        libc.malloc_trim(0)
