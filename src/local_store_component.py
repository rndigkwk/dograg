"""Bridge between the session's LocalSnapshot and the browser's localStorage.

Python -> browser: `data = {request, version, values?}`. The browser writes
`values` when `version` is newer than what it last wrote for this `request`.
Browser -> Python: once per `request` it reports the stored strings as the
`snapshot` state, or `{"status": "unavailable"}` when storage is blocked
(private mode, disabled site data). A new session sends a new `request`, so a
reconnect after a server restart reloads the snapshot.
"""

from __future__ import annotations

import streamlit as st

from src.storage.snapshot import STORAGE_KEYS

_JS = """
export default function(component) {
  const {data, setStateValue} = component;
  if (!data || !data.request) return;
  const state = (window.__ragdogStore = window.__ragdogStore || {answered: null, written: {}});
  try {
    const written = state.written[data.request] || 0;
    if (data.values && data.version > written) {
      for (const [key, value] of Object.entries(data.values)) {
        if (!key.startsWith("ragdog:")) continue;
        if (value) localStorage.setItem(key, value); else localStorage.removeItem(key);
      }
      state.written[data.request] = data.version;
    }
    if (state.answered !== data.request) {
      const values = {};
      for (const key of data.keys || []) values[key] = localStorage.getItem(key);
      state.answered = data.request;
      setStateValue("snapshot", {request: data.request, status: "ok", values});
    }
  } catch (error) {
    if (state.answered !== data.request) {
      state.answered = data.request;
      setStateValue("snapshot", {request: data.request, status: "unavailable"});
    }
  }
}
"""
_COMPONENT = st.components.v2.component("dograg_local_store", html="<span></span>", js=_JS)


def sync_local_store(key: str, *, request: str, version: int, values: dict[str, str] | None) -> dict | None:
    """Mount the invisible bridge; returns the browser's report for this request, if any."""
    global _COMPONENT
    data = {"request": request, "version": version, "keys": list(STORAGE_KEYS)}
    if values is not None:
        data["values"] = values
    try:
        result = _COMPONENT(key=key, data=data, on_snapshot_change=lambda: None)
    except ValueError as exc:
        if "is not registered" not in str(exc):
            raise
        # AppTest can reset the component registry while retaining imported modules.
        _COMPONENT = st.components.v2.component("dograg_local_store", html="<span></span>", js=_JS)
        result = _COMPONENT(key=key, data=data, on_snapshot_change=lambda: None)
    report = result.snapshot
    if isinstance(report, dict) and report.get("request") == request:
        return report
    return None
