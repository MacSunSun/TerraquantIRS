"""Page 2 — 供应链地图 (Supply Chain Map)
Uses Vis.js (via st.components.v1.html) for:
  • Physics spring layout
  • Hover → highlight neighbourhood, dim others
  • Click → navigate to company overview (via window.parent query-param)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd

from core.supply_chain import (
    load_chain, save_chain,
    add_company, add_relationship, remove_company,
    TIER_COLORS, TIER_LABELS, RELATIONSHIP_LABELS,
)
from core.vis_graph import build_full_map_html

st.set_page_config(page_title="供应链地图", page_icon="🕸️", layout="wide")

# ── Detect click-navigation from Vis.js ───────────────────────────────────────
# Vis.js click sets window.parent.location.search = '?ticker=XXX'
# Streamlit reruns and we detect it here.
ticker_click = st.query_params.get("ticker", "")
if ticker_click:
    if "chain" not in st.session_state:
        st.session_state.chain = load_chain()
    if ticker_click in st.session_state.chain["companies"]:
        st.session_state["overview_ticker"] = ticker_click
        st.query_params.clear()
        st.switch_page("pages/1_公司概览.py")
    else:
        st.query_params.clear()

# ── Load chain ────────────────────────────────────────────────────────────────
if "chain" not in st.session_state:
    st.session_state.chain = load_chain()
chain = st.session_state.chain

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🕸️ 供应链地图")
    st.caption("悬停高亮 · 点击进入详情")
    st.divider()

    edit_mode = st.radio("操作模式", ["查看", "添加公司", "添加关系", "删除公司"])

    if edit_mode == "添加公司":
        st.markdown("#### ➕ 添加新公司")
        new_ticker = st.text_input("Ticker", placeholder="e.g. NVDA").strip().upper()
        new_name   = st.text_input("公司名称", placeholder="NVIDIA Corporation")
        new_cik    = st.text_input("SEC CIK", placeholder="CIK0001045810")
        new_tier   = st.selectbox("层级", list(TIER_LABELS.keys()),
                                  format_func=lambda k: TIER_LABELS[k])
        new_sector = st.text_input("行业", placeholder="Semiconductors")
        new_note   = st.text_input("备注", placeholder="简短描述")
        if st.button("添加", type="primary"):
            if new_ticker and new_name:
                chain = add_company(chain, new_ticker, new_name, new_cik,
                                    new_tier, new_sector, new_note)
                save_chain(chain)
                st.session_state.chain = chain
                st.success(f"已添加 {new_ticker}")
                st.rerun()
            else:
                st.error("Ticker 和公司名称为必填项")

    elif edit_mode == "添加关系":
        st.markdown("#### 🔗 添加关系")
        all_t = sorted(chain["companies"].keys())
        rel_from = st.selectbox("从", all_t, key="rel_from")
        rel_to   = st.selectbox("到", all_t, key="rel_to")
        rel_type = st.selectbox("关系类型", list(RELATIONSHIP_LABELS.keys()),
                                format_func=lambda k: RELATIONSHIP_LABELS[k])
        rel_note = st.text_input("备注说明", placeholder="例：供应 HBM3E 内存")
        if st.button("添加关系", type="primary"):
            if rel_from != rel_to:
                chain = add_relationship(chain, rel_from, rel_to, rel_type, rel_note)
                save_chain(chain)
                st.session_state.chain = chain
                st.success(f"{rel_from} → {rel_to}")
                st.rerun()
            else:
                st.error("起点和终点不能相同")

    elif edit_mode == "删除公司":
        st.markdown("#### 🗑️ 删除公司")
        to_delete = st.selectbox("选择要删除的公司", sorted(chain["companies"].keys()))
        if st.button("删除", type="primary"):
            if to_delete == chain.get("focal"):
                st.error("不能删除核心公司")
            else:
                chain = remove_company(chain, to_delete)
                save_chain(chain)
                st.session_state.chain = chain
                st.success(f"已删除 {to_delete}")
                st.rerun()

    st.divider()
    st.markdown("#### 显示层级")
    show_tiers = {
        k: st.checkbox(label, value=True, key=f"show_{k}")
        for k, label in TIER_LABELS.items()
    }

# ── Page header ───────────────────────────────────────────────────────────────
st.title("🕸️ 半导体供应链地图")
st.caption("**悬停**节点 → 高亮上下游关系 · **点击**节点 → 进入公司详情 · 滚轮缩放 · 拖拽移动")

# ── Build + render Vis.js map ─────────────────────────────────────────────────
active_tiers = {k for k, v in show_tiers.items() if v}
html = build_full_map_html(chain, active_tiers=active_tiers, height=620)
st.components.v1.html(html, height=634, scrolling=False)

# ── Legend ────────────────────────────────────────────────────────────────────
tier_cols = st.columns(len(TIER_LABELS) + 1)
for col, (key, label) in zip(tier_cols, TIER_LABELS.items()):
    color = TIER_COLORS.get(key, "#adb5bd")
    col.markdown(
        f"<span style='display:inline-block;width:11px;height:11px;"
        f"border-radius:50%;background:{color};vertical-align:middle;"
        f"margin-right:4px'></span><small>{label}</small>",
        unsafe_allow_html=True,
    )

from core.vis_graph import EDGE_COLORS
_fallback = "#adb5bd"
tier_cols[-1].markdown(
    "&nbsp;&nbsp;".join(
        f"<span style='background:{EDGE_COLORS.get(k, _fallback)};color:white;"
        f"padding:1px 7px;border-radius:3px;font-size:0.76em'>{v}</span>"
        for k, v in RELATIONSHIP_LABELS.items()
    ),
    unsafe_allow_html=True,
)

# ── Adjacency table ───────────────────────────────────────────────────────────
with st.expander("关系列表", expanded=False):
    rel_rows = []
    for rel in chain["relationships"]:
        f_name = chain["companies"].get(rel["from"], {}).get("name", rel["from"])
        t_name = chain["companies"].get(rel["to"],   {}).get("name", rel["to"])
        rel_rows.append({
            "起点":  rel["from"],
            "起点公司": f_name,
            "关系":  RELATIONSHIP_LABELS.get(rel["type"], rel["type"]),
            "终点":  rel["to"],
            "终点公司": t_name,
            "备注":  rel.get("note", ""),
        })
    st.dataframe(pd.DataFrame(rel_rows), use_container_width=True, hide_index=True)
