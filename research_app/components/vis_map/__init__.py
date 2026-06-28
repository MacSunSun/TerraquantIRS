"""Streamlit custom component — Vis.js map with click events back to Python."""
from __future__ import annotations

import os

import streamlit.components.v1 as components

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
_vis_map = components.declare_component("vis_map", path=_DIR)


def render_vis_map(payload: dict, *, height: int = 620, key: str | None = None) -> str | None:
    """Render interactive map; returns clicked ticker (str) or None."""
    return _vis_map(payload=payload, height=height, key=key, default=None)
