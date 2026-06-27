"""Page 3 — 多公司对比 (Multi-Company Comparison)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np

from core.supply_chain import load_chain, TIER_LABELS, TIER_COLORS
from core.price_data import get_info, key_metrics, get_quarterly_returns
from core.sec_data import get_quarterly_financials

st.set_page_config(page_title="多公司对比", page_icon="📊", layout="wide")

# ── Load data ─────────────────────────────────────────────────────────────────
chain   = load_chain()
all_tickers = sorted(chain["companies"].keys())

with st.sidebar:
    st.markdown("## 📊 多公司对比")
    st.divider()
    selected = st.multiselect(
        "选择公司（最多 8 家）",
        all_tickers,
        default=["AMD", "NVDA", "INTC", "TSM"],
        max_selections=8,
    )
    st.divider()
    st.markdown("**选中公司层级：**")
    for t in selected:
        tier  = chain["companies"].get(t, {}).get("tier", "")
        color = TIER_COLORS.get(tier, "#adb5bd")
        st.markdown(
            f"<span style='background:{color};color:white;padding:1px 6px;"
            f"border-radius:3px;font-size:0.78em'>{t}</span> "
            f"{chain['companies'].get(t,{}).get('name','')}",
            unsafe_allow_html=True,
        )

if not selected:
    st.warning("请在左侧至少选择一家公司")
    st.stop()

st.title("📊 多公司对比")
st.caption(f"对比：{' · '.join(selected)}")
st.divider()

# ── 1. Key metrics table ──────────────────────────────────────────────────────
st.subheader("关键指标对比")
with st.spinner("拉取 yfinance 数据…"):
    metrics_rows = {}
    for t in selected:
        km = key_metrics(t)
        metrics_rows[t] = km

metrics_df = pd.DataFrame(metrics_rows).T
metrics_df.index.name = "Ticker"
st.dataframe(metrics_df, use_container_width=True)
st.divider()

# ── 2. Revenue comparison ─────────────────────────────────────────────────────
st.subheader("季度营收对比（最近 12 季）")

@st.cache_data(ttl=3600 * 12, show_spinner=False)
def load_fin(cik: str) -> pd.DataFrame:
    return get_quarterly_financials(cik)

rev_data: dict[str, pd.Series] = {}
gm_data:  dict[str, pd.Series] = {}
om_data:  dict[str, pd.Series] = {}
eps_data: dict[str, pd.Series] = {}

with st.spinner("拉取 SEC EDGAR 财报数据…"):
    for t in selected:
        cik = chain["companies"].get(t, {}).get("cik", "")
        if not cik:
            continue
        fin = load_fin(cik)
        if fin.empty:
            continue
        last12 = fin.tail(12)
        rev_data[t] = last12["revenue"]       / 1e9
        gm_data[t]  = last12["gross_margin"]  * 100
        om_data[t]  = last12["op_margin"]     * 100
        eps_data[t] = last12["eps_dil"]

col1, col2 = st.columns(2)

with col1:
    fig_rev = go.Figure()
    for t, s in rev_data.items():
        color = TIER_COLORS.get(chain["companies"][t]["tier"], "#0d6efd")
        fig_rev.add_trace(go.Scatter(
            x=s.index.astype(str), y=s.values,
            name=t, mode="lines+markers",
            line=dict(color=color, width=2), marker=dict(size=5),
        ))
    fig_rev.update_layout(
        title="季度营收 (十亿美元)", height=340,
        plot_bgcolor="white", paper_bgcolor="#f8f9fa",
        margin=dict(l=10, r=10, t=40, b=10),
        yaxis_title="B$", hovermode="x unified",
        legend=dict(orientation="h", y=1.12),
    )
    st.plotly_chart(fig_rev, use_container_width=True)

with col2:
    fig_gm = go.Figure()
    for t, s in gm_data.items():
        color = TIER_COLORS.get(chain["companies"][t]["tier"], "#0d6efd")
        fig_gm.add_trace(go.Scatter(
            x=s.index.astype(str), y=s.values,
            name=t, mode="lines+markers",
            line=dict(color=color, width=2), marker=dict(size=5),
        ))
    fig_gm.update_layout(
        title="毛利率 (%)", height=340,
        plot_bgcolor="white", paper_bgcolor="#f8f9fa",
        margin=dict(l=10, r=10, t=40, b=10),
        yaxis_title="%", yaxis_ticksuffix="%",
        hovermode="x unified",
        legend=dict(orientation="h", y=1.12),
    )
    st.plotly_chart(fig_gm, use_container_width=True)

col3, col4 = st.columns(2)

with col3:
    fig_om = go.Figure()
    for t, s in om_data.items():
        color = TIER_COLORS.get(chain["companies"][t]["tier"], "#0d6efd")
        fig_om.add_trace(go.Scatter(
            x=s.index.astype(str), y=s.values,
            name=t, mode="lines+markers",
            line=dict(color=color, width=2), marker=dict(size=5),
        ))
    fig_om.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
    fig_om.update_layout(
        title="营业利润率 (%)", height=300,
        plot_bgcolor="white", paper_bgcolor="#f8f9fa",
        margin=dict(l=10, r=10, t=40, b=10),
        yaxis_title="%", yaxis_ticksuffix="%",
        hovermode="x unified",
        legend=dict(orientation="h", y=1.12),
    )
    st.plotly_chart(fig_om, use_container_width=True)

with col4:
    fig_eps = go.Figure()
    for t, s in eps_data.items():
        color = TIER_COLORS.get(chain["companies"][t]["tier"], "#0d6efd")
        fig_eps.add_trace(go.Scatter(
            x=s.index.astype(str), y=s.values,
            name=t, mode="lines+markers",
            line=dict(color=color, width=2), marker=dict(size=5),
        ))
    fig_eps.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
    fig_eps.update_layout(
        title="EPS（稀释）", height=300,
        plot_bgcolor="white", paper_bgcolor="#f8f9fa",
        margin=dict(l=10, r=10, t=40, b=10),
        yaxis_title="USD",
        hovermode="x unified",
        legend=dict(orientation="h", y=1.12),
    )
    st.plotly_chart(fig_eps, use_container_width=True)

st.divider()

# ── 3. Quarterly return correlation ──────────────────────────────────────────
st.subheader("季度收益率相关性")
with st.spinner("计算相关性…"):
    ret_dict: dict[str, pd.Series] = {}
    for t in selected:
        s = get_quarterly_returns(t)
        if not s.empty:
            ret_dict[t] = s

if len(ret_dict) >= 2:
    ret_df = pd.DataFrame(ret_dict).dropna()
    corr   = ret_df.corr()
    fig_corr = px.imshow(
        corr, text_auto=".2f", color_continuous_scale="RdBu_r",
        zmin=-1, zmax=1,
        title="季度收益率相关性矩阵",
        height=max(350, len(ret_dict) * 60),
    )
    fig_corr.update_layout(margin=dict(l=10, r=10, t=50, b=10),
                           paper_bgcolor="#f8f9fa")
    st.plotly_chart(fig_corr, use_container_width=True)
else:
    st.info("需要至少 2 家有价格数据的公司才能计算相关性")

st.divider()

# ── 4. Latest-quarter snapshot table ──────────────────────────────────────────
st.subheader("最新季报快照")
snapshot_rows = []
for t in selected:
    cik = chain["companies"].get(t, {}).get("cik", "")
    if not cik:
        continue
    fin = load_fin(cik)
    if fin.empty:
        continue
    latest = fin.iloc[-1]
    info   = get_info(t)
    snapshot_rows.append({
        "Ticker":       t,
        "公司":         chain["companies"][t]["name"],
        "层级":         TIER_LABELS.get(chain["companies"][t]["tier"], ""),
        "期末日期":     fin.index[-1].strftime("%Y-%m-%d"),
        "营收(B$)":    round(latest.get("revenue", 0) / 1e9, 2),
        "毛利率":       f"{latest.get('gross_margin',0)*100:.1f}%",
        "营业利润率":   f"{latest.get('op_margin',0)*100:.1f}%",
        "净利率":       f"{latest.get('net_margin',0)*100:.1f}%",
        "EPS(dil)":     round(latest.get("eps_dil", 0), 3),
        "营收YoY":      f"{latest.get('rev_yoy',0)*100:.1f}%"
                         if pd.notna(latest.get("rev_yoy")) else "—",
        "市值":         get_info(t).get("marketCap", None),
    })

if snapshot_rows:
    snap_df = pd.DataFrame(snapshot_rows)
    # Format market cap
    def fmt_cap(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "—"
        if v >= 1e12: return f"${v/1e12:.2f}T"
        if v >= 1e9:  return f"${v/1e9:.1f}B"
        return f"${v/1e6:.0f}M"
    snap_df["市值"] = snap_df["市值"].apply(fmt_cap)
    st.dataframe(snap_df.set_index("Ticker"), use_container_width=True)
