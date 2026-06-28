"""
Entry point — defines page navigation and launches the supply chain map by default.
app.py itself is invisible in the sidebar when using st.navigation().
"""
import streamlit as st

from core.supply_chain import load_chain


def _navigate_to_ticker() -> None:
    """Handle ?ticker=XXX from Vis.js map clicks (must run before pg.run())."""
    ticker = st.query_params.get("ticker", "")
    if not ticker:
        return
    ticker = ticker.upper()
    chain = load_chain()
    if ticker in chain["companies"]:
        st.session_state["overview_ticker"] = ticker
    st.query_params.clear()
    st.switch_page("pages/1_公司概览.py")


_navigate_to_ticker()

pages = [
    st.Page("pages/2_供应链地图.py", title="供应链地图",   icon="🕸️", default=True),
    st.Page("pages/1_公司概览.py",   title="公司概览",     icon="🔍"),
    st.Page("pages/5_业务集中度.py", title="业务集中度",   icon="🎯"),
    st.Page("pages/3_多公司对比.py", title="多公司对比",   icon="📊"),
    st.Page("pages/4_文本挖掘.py",   title="10-K 文本挖掘", icon="📄"),
]

pg = st.navigation(pages)
pg.run()
