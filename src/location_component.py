"""Opt-in browser geolocation control. Coordinates stay in Streamlit session memory."""

import streamlit as st


_HTML = '<button type="button" id="dograg-location">현재 위치 사용</button>'
_JS = """
export default function(component) {
  const {parentElement, setStateValue} = component;
  const button = parentElement.querySelector('#dograg-location');
  const click = () => {
    if (!window.isSecureContext) { setStateValue('location', {status: 'insecure'}); return; }
    if (!navigator.geolocation) { setStateValue('location', {status: 'unsupported'}); return; }
    navigator.geolocation.getCurrentPosition(
      pos => setStateValue('location', {latitude: pos.coords.latitude, longitude: pos.coords.longitude}),
      error => setStateValue('location', {status: error.code === 1 ? 'denied' : error.code === 3 ? 'timeout' : 'unavailable'}),
      {enableHighAccuracy: false, timeout: 10000, maximumAge: 0}
    );
  };
  button.addEventListener('click', click);
  return () => button.removeEventListener('click', click);
}
"""
_CONTROL = st.components.v2.component("dograg_opt_in_location", html=_HTML, js=_JS)
_MESSAGES = {
    "denied": "위치 권한이 거부되었습니다.",
    "timeout": "위치 요청 시간이 초과되었습니다.",
    "unsupported": "브라우저에서 위치 기능을 지원하지 않습니다.",
    "insecure": "위치 기능은 HTTPS 환경에서 사용할 수 있습니다.",
    "unavailable": "현재 위치를 가져오지 못했습니다.",
}


def parse_location_result(value) -> tuple[tuple[float, float] | None, str | None]:
    if not isinstance(value, dict):
        return None, None
    if value.get("status"):
        return None, _MESSAGES.get(value["status"], _MESSAGES["unavailable"])
    try:
        latitude, longitude = float(value["latitude"]), float(value["longitude"])
        if not 33 <= latitude <= 39 or not 124 <= longitude <= 132:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return None, "유효하지 않은 위치입니다."
    return (latitude, longitude), None


def render_location_control(key: str) -> tuple[tuple[float, float] | None, str | None]:
    global _CONTROL
    try:
        result = _CONTROL(key=key, on_location_change=lambda: None)
    except ValueError as exc:
        if "is not registered" not in str(exc):
            raise
        # AppTest can reset the component registry while retaining imported modules.
        _CONTROL = st.components.v2.component("dograg_opt_in_location", html=_HTML, js=_JS)
        result = _CONTROL(key=key, on_location_change=lambda: None)
    return parse_location_result(result.location)
