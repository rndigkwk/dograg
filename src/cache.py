"""Process-wide cache for the heavy loaders, without importing Streamlit.

`st.cache_resource` used to do this job, which made the API import Streamlit (and its
dependencies) only for a decorator. A loaded resource is shared by every caller in the
process, as before; `.clear()` drops it, as `st.cache_resource` allowed.
"""

from __future__ import annotations

import functools
import threading


def cache_resource(function):
    """Call `function` once per argument tuple; concurrent first calls wait for the one loading."""
    values: dict = {}
    lock = threading.RLock()

    @functools.wraps(function)
    def wrapper(*args):
        try:
            return values[args]
        except KeyError:
            pass
        with lock:
            if args not in values:
                values[args] = function(*args)
            return values[args]

    def clear() -> None:
        with lock:
            values.clear()

    wrapper.clear = clear
    return wrapper
