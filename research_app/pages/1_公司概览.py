"""Page 1 — 公司概览 (Company Overview)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from core.supply_chain import load_chain, TIER_LABELS, TIER_COLORS
from core.price_data import get_price_history, get_info, key_metrics
from core.sec_data import get_quarterly_financials, get_recent_filings


def _rgba(hex_color: str, alpha: float = 0.13) -> str:
    """Convert a 6-digit hex color to rgba() for Plotly fillcolor."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

st.set_page_config(page_title="公司概览", page_icon="🔍", layout="wide")

# ── Pre-selected ticker (may come from supply chain map click) ────────────────
_preselect = st.session_state.pop("overview_ticker", None)

# ── Sidebar ───────────────────────────────────────────────────────────────────
chain = load_chain()
tickers = sorted(chain["companies"].keys())

def _default_index() -> int:
    if _preselect and _preselect in tickers:
        return tickers.index(_preselect)
    return tickers.index("AMD") if "AMD" in tickers else 0

with st.sidebar:
    st.markdown("## 🔍 公司概览")
    selected = st.selectbox("选择公司", tickers, index=_default_index())
    meta = chain["companies"][selected]
    tier = meta["tier"]
    st.divider()
    st.markdown("#### 📅 时间范围")
    PERIOD_OPTIONS = {
        "1 年":  ("1y",  4),
        "3 年":  ("3y",  12),
        "5 年":  ("5y",  20),
        "10 年": ("10y", 40),
        "全部":  ("max", 999),
    }
    period_label = st.select_slider(
        "显示历史长度",
        options=list(PERIOD_OPTIONS.keys()),
        value="3 年",
    )
    price_period, fin_quarters = PERIOD_OPTIONS[period_label]
    st.divider()
    st.markdown(f"""
**{meta['name']}**
- 层级：{TIER_LABELS.get(tier, tier)}
- 行业：{meta['sector']}
- 备注：{meta['note']}
""")
    if meta.get("cik"):
        edgar_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={meta['cik'].replace('CIK','')}&type=10-K&dateb=&owner=include&count=10"
        st.markdown(f"[🔗 SEC EDGAR 原始文件]({edgar_url})")

# ── Header ────────────────────────────────────────────────────────────────────
info = get_info(selected)
company_name = info.get("longName") or meta["name"]
tier_color   = TIER_COLORS.get(tier, "#adb5bd")

st.markdown(
    f"<h2 style='margin-bottom:0'>{selected} &nbsp;"
    f"<span style='font-size:0.55em; background:{tier_color}22; color:{tier_color}; "
    f"border:1px solid {tier_color}; border-radius:4px; padding:2px 8px;'>"
    f"{TIER_LABELS.get(tier, tier)}</span></h2>",
    unsafe_allow_html=True,
)
st.markdown(f"**{company_name}** · {meta['sector']} · {meta['note']}")
st.divider()

# ── Key metrics row ───────────────────────────────────────────────────────────
st.subheader("关键指标")
km = key_metrics(selected)
cols = st.columns(6)
for i, (label, val) in enumerate(list(km.items())[:12]):
    cols[i % 6].metric(label, val)

st.divider()

# ── Price chart ───────────────────────────────────────────────────────────────
st.subheader("股价走势（近 3 年）")
px_hist = get_price_history(selected, period=price_period)

if not px_hist.empty:
    fig_price = go.Figure()
    fig_price.add_trace(go.Scatter(
        x=px_hist.index, y=px_hist["Close"],
        mode="lines", name="收盘价",
        line=dict(color=tier_color, width=1.8),
        fill="tozeroy",
        fillcolor=_rgba(tier_color, 0.13),
    ))
    fig_price.update_layout(
        height=320, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="日期", yaxis_title="价格 (USD)",
        hovermode="x unified",
        plot_bgcolor="white", paper_bgcolor="#f8f9fa",
    )
    st.plotly_chart(fig_price, use_container_width=True)
else:
    st.info("价格数据暂不可用")

st.divider()

# ── Quarterly financials ──────────────────────────────────────────────────────
st.subheader("季度财报数据")
cik = meta.get("cik", "")

if cik:
    with st.spinner("正在从 SEC EDGAR 拉取 XBRL 数据…"):
        fin = get_quarterly_financials(cik)

    if not fin.empty:
        # Show last 12 quarters
        fin_show = fin.tail(fin_quarters).copy()

        # Revenue & Gross Margin chart
        col_left, col_right = st.columns(2)

        with col_left:
            fig_rev = go.Figure()
            fig_rev.add_bar(
                x=fin_show.index.strftime("%Y-Q%q") if hasattr(fin_show.index, "strftime") else fin_show.index.astype(str),
                y=fin_show["revenue"] / 1e9,
                name="Revenue (B$)",
                marker_color=tier_color,
            )
            fig_rev.update_layout(
                title="季度营收 (B$)", height=300,
                margin=dict(l=10, r=10, t=40, b=10),
                plot_bgcolor="white", paper_bgcolor="#f8f9fa",
                yaxis_title="十亿美元",
            )
            st.plotly_chart(fig_rev, use_container_width=True)

        with col_right:
            fig_margin = go.Figure()
            for col_name, label, color in [
                ("gross_margin", "毛利率", "#198754"),
                ("op_margin",    "营业利润率", "#0d6efd"),
                ("net_margin",   "净利率", "#fd7e14"),
            ]:
                if col_name in fin_show:
                    fig_margin.add_trace(go.Scatter(
                        x=fin_show.index.astype(str),
                        y=fin_show[col_name] * 100,
                        name=label, mode="lines+markers",
                        line=dict(color=color, width=2),
                    ))
            fig_margin.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
            fig_margin.update_layout(
                title="利润率 (%)", height=300,
                margin=dict(l=10, r=10, t=40, b=10),
                plot_bgcolor="white", paper_bgcolor="#f8f9fa",
                yaxis_title="%", yaxis_ticksuffix="%",
            )
            st.plotly_chart(fig_margin, use_container_width=True)

        # EPS & Revenue YoY
        col3, col4 = st.columns(2)

        with col3:
            fig_eps = go.Figure()
            fig_eps.add_bar(
                x=fin_show.index.astype(str),
                y=fin_show["eps_dil"],
                name="Diluted EPS",
                marker_color=[tier_color if v >= 0 else "#dc3545" for v in fin_show["eps_dil"].fillna(0)],
            )
            fig_eps.update_layout(
                title="季度 EPS (稀释)", height=280,
                margin=dict(l=10, r=10, t=40, b=10),
                plot_bgcolor="white", paper_bgcolor="#f8f9fa",
                yaxis_title="USD",
            )
            st.plotly_chart(fig_eps, use_container_width=True)

        with col4:
            fig_yoy = go.Figure()
            yoy_vals = fin_show["rev_yoy"].dropna() * 100
            fig_yoy.add_bar(
                x=yoy_vals.index.astype(str),
                y=yoy_vals,
                name="Revenue YoY",
                marker_color=["#198754" if v >= 0 else "#dc3545" for v in yoy_vals],
            )
            fig_yoy.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
            fig_yoy.update_layout(
                title="营收同比增长率 (%)", height=280,
                margin=dict(l=10, r=10, t=40, b=10),
                plot_bgcolor="white", paper_bgcolor="#f8f9fa",
                yaxis_title="%", yaxis_ticksuffix="%",
            )
            st.plotly_chart(fig_yoy, use_container_width=True)

        # Raw data table
        with st.expander("查看原始季报数据"):
            display = fin_show[["revenue","gross_profit","op_income","net_income",
                                "eps_dil","gross_margin","op_margin","net_margin","rev_yoy"]].copy()
            display["revenue"]      = (display["revenue"]      / 1e9).round(3)
            display["gross_profit"] = (display["gross_profit"] / 1e9).round(3)
            display["op_income"]    = (display["op_income"]    / 1e9).round(3)
            display["net_income"]   = (display["net_income"]   / 1e9).round(3)
            display["eps_dil"]      = display["eps_dil"].round(3)
            for c in ["gross_margin","op_margin","net_margin","rev_yoy"]:
                display[c] = (display[c] * 100).round(1).astype(str) + "%"
            display.columns = ["Revenue(B)","GrossProfit(B)","OpIncome(B)","NetIncome(B)",
                                "EPS(dil)","GrossMargin","OpMargin","NetMargin","RevYoY"]
            st.dataframe(display, use_container_width=True)
    else:
        st.info("未找到该公司的 XBRL 数据（SEC 未收录或 CIK 有误）")
else:
    st.info("该公司暂无 CIK，无法拉取 SEC 财报数据")

st.divider()

# ── Mini supply-chain map ─────────────────────────────────────────────────────
st.subheader("供应链关系图")
st.caption("左：上游供应商 · 右：下游客户 · 下方：竞争对手 · 可拖拽 · 滚轮缩放")

from core.vis_graph import build_mini_map_html
mini_html = build_mini_map_html(selected, chain, height=370)
st.components.v1.html(mini_html, height=385, scrolling=False)

# ── Supply chain neighbors (text fallback) ────────────────────────────────────
from core.supply_chain import get_neighbors
neighbors = get_neighbors(selected, chain)

with st.expander("供应链关联列表", expanded=False):
    cols_n = st.columns(3)
    for col_n, (direction, label, emoji) in zip(cols_n, [
        ("upstream",   "上游供应商", "⬆️"),
        ("downstream", "下游客户",   "⬇️"),
        ("peers",      "竞争对手",   "⚔️"),
    ]):
        with col_n:
            st.markdown(f"**{emoji} {label}**")
            items = neighbors[direction]
            if items:
                for item in items:
                    t    = item.get("ticker", "")
                    n    = item.get("name", t)
                    note = item.get("note", "")
                    st.markdown(
                        f"- **{t}** {n}<br><small style='color:gray'>{note}</small>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("无")
