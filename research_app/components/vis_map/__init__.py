"""Streamlit v2 component — Vis.js map with click events back to Python."""
from __future__ import annotations

import os

import streamlit as st

_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_DIR, "vis_map.js"), encoding="utf-8") as f:
    _JS = f.read()

_HTML = """
<div class="vis-map-root mode-full">
  <div id="labels"></div>
  <div id="net"></div>
  <div id="tip"></div>
</div>
"""

_CSS = """
.vis-map-root {
  position: relative;
  width: 100%;
}
.vis-map-root.mode-full { background: #f8f9fa; }
.vis-map-root.mode-mini { background: #fafafa; }
#net { width: 100%; }
.lbl {
  position: absolute; font-size: 11px; font-weight: 600;
  opacity: 0.65; pointer-events: none;
}
#tip {
  position: absolute; bottom: 10px; right: 14px;
  background: rgba(0,0,0,.52); color: #fff; padding: 3px 10px;
  border-radius: 4px; font-size: 11px; pointer-events: none;
}
"""

_VIS_MAP = st.components.v2.component(
    "vis_map",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def render_vis_map(payload: dict, *, height: int = 620, key: str | None = None) -> str | None:
    """Render interactive map; returns clicked ticker (str) or None."""
    result = _VIS_MAP(
        key=key,
        data={"payload": payload, "height": height},
        height=height + 8,
        on_clicked_change=lambda: None,
    )
    return result.clicked
