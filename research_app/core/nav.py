"""Page navigation helpers."""
from __future__ import annotations

import streamlit as st


def open_company(ticker: str) -> None:
    st.session_state["overview_ticker"] = ticker.upper()
    st.switch_page("pages/1_公司概览.py")


def map_component_key(prefix: str) -> str:
    """Stable key for vis_map; bump via handle_map_click after each navigation."""
    n = st.session_state.get(f"_{prefix}_map_n", 0)
    return f"{prefix}_{n}"


def handle_map_click(
    clicked: str | None,
    *,
    prefix: str,
    skip: str | None = None,
) -> None:
    """Navigate to company overview when the map reports a new click."""
    if not clicked or (skip and clicked.upper() == skip.upper()):
        return
    st.session_state[f"_{prefix}_map_n"] = st.session_state.get(f"_{prefix}_map_n", 0) + 1
    open_company(clicked)
