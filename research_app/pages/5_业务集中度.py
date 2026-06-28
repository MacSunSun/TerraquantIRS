"""Page 5 — 业务集中度分析
Shows for any company:
  • Segment revenue breakdown (3-year trend + latest pie)
  • Customer / supplier concentration % from 10-K text
  • Geographic revenue
  • Supply chain partner → segment mapping
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from core.supply_chain import load_chain, TIER_LABELS, TIER_COLORS
from core.concentration import get_concentration_data, KNOWN_SEGMENTS
from core.filing_paths import local_annual_dirs

st.set_page_config(page_title="业务集中度", page_icon="📊", layout="wide")

# ── Sidebar ───────────────────────────────────────────────────────────────────
chain   = load_chain()
tickers = sorted(chain["companies"].keys())

with st.sidebar:
    st.markdown("## 📊 业务集中度分析")
    st.caption("分部营收 · 客户集中度 · 供应链关联分析")
    st.divider()

    selected = st.selectbox(
        "选择公司",
        tickers,
        index=tickers.index("AMD") if "AMD" in tickers else 0,
    )
    meta       = chain["companies"][selected]
    tier       = meta.get("tier", "")
    tier_color = TIER_COLORS.get(tier, "#0d6efd")

    LOCAL_10K_DIRS = local_annual_dirs()
    local_dir = LOCAL_10K_DIRS.get(selected, "")
    if local_dir:
        st.caption(f"📁 本地年报: `{local_dir}`")

    st.divider()
    if selected not in KNOWN_SEGMENTS:
        st.info(f"**{selected}** 的分部名称尚未配置。\n将尝试从 SEC 文本中提取。")

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(
    f"<h2 style='margin-bottom:4px'>{selected} &nbsp;"
    f"<span style='font-size:0.55em;background:{tier_color}22;color:{tier_color};"
    f"border:1px solid {tier_color};border-radius:4px;padding:2px 8px'>"
    f"{TIER_LABELS.get(tier, tier)}</span></h2>",
    unsafe_allow_html=True,
)
st.caption(f"**{meta['name']}** · {meta['sector']}")
st.divider()

# ── Fetch data ────────────────────────────────────────────────────────────────
cik = meta.get("cik", "")
if not cik and not local_dir:
    st.warning("该公司没有 CIK，无法从 SEC EDGAR 获取数据。请在供应链地图中补充 CIK。")
    st.stop()

with st.spinner("正在解析 10-K 文件…"):
    data = get_concentration_data(
        ticker=selected,
        cik=cik,
        local_dir=local_dir,
    )

seg_df  = data["segments"]
fy      = data["fy_years"]
conc    = data["concentration"]
geo_df  = data["geo"]

if seg_df.empty and not conc and geo_df.empty:
    st.error("未能提取到数据。请确认 CIK 正确，或检查 10-K 文件路径。")
    st.stop()

fy_labels = list(fy) if fy else ["FY0", "FY1", "FY2"]

# ── Section 1: Segment Revenue ────────────────────────────────────────────────
if not seg_df.empty:
    st.subheader("📦 分部营收构成")

    total_fy0 = seg_df["fy0"].sum()
    seg_df    = seg_df.copy()
    seg_df["pct_fy0"] = (seg_df["fy0"] / total_fy0 * 100).round(1)

    col_pie, col_bar = st.columns([1, 1.6])

    with col_pie:
        st.markdown(f"**{fy_labels[0]} 分部占比**")
        fig_pie = px.pie(
            seg_df, names="segment", values="fy0",
            color_discrete_sequence=px.colors.qualitative.Set2,
            hole=0.42,
        )
        fig_pie.update_traces(
            textinfo="label+percent",
            textfont_size=12,
            hovertemplate="<b>%{label}</b><br>营收: $%{value:,.0f}M<br>占比: %{percent}<extra></extra>",
        )
        fig_pie.update_layout(
            height=320, margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False,
            paper_bgcolor="#f8f9fa", plot_bgcolor="#f8f9fa",
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_bar:
        st.markdown("**历年分部营收趋势 ($M)**")
        fig_bar = go.Figure()
        colors  = px.colors.qualitative.Set2
        for i, row in seg_df.iterrows():
            seg  = row["segment"]
            vals = [row["fy0"], row["fy1"], row["fy2"]]
            fig_bar.add_trace(go.Bar(
                name=seg,
                x=[str(y) for y in fy_labels],
                y=vals,
                marker_color=colors[i % len(colors)],
                text=[f"${v:,.0f}" for v in vals],
                textposition="auto",
                hovertemplate=f"<b>{seg}</b><br>%{{x}}: $%{{y:,.0f}}M<extra></extra>",
            ))
        fig_bar.update_layout(
            barmode="stack", height=320,
            margin=dict(l=10, r=10, t=10, b=30),
            legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
            paper_bgcolor="#f8f9fa", plot_bgcolor="white",
            yaxis_title="$M",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # Segment table
    tbl = seg_df[["segment", "fy0", "fy1", "fy2", "pct_fy0"]].copy()
    tbl.columns = ["分部", f"{fy_labels[0]}($M)", f"{fy_labels[1]}($M)",
                   f"{fy_labels[2]}($M)", f"{fy_labels[0]}占比%"]
    tbl[f"{fy_labels[0]}占比%"] = tbl[f"{fy_labels[0]}占比%"].map("{:.1f}%".format)
    st.dataframe(tbl, use_container_width=True, hide_index=True)

    st.divider()

# ── Section 2: Customer / Supplier Concentration ─────────────────────────────
st.subheader("🎯 客户 / 供应商集中度")

if conc:
    df_conc = pd.DataFrame(conc)

    # Show bar for concentration % where available
    pct_rows = df_conc[df_conc["占比%"].notna()].copy()
    if not pct_rows.empty:
        fig_conc = px.bar(
            pct_rows,
            x="占比%", y="描述",
            color="所属分部",
            orientation="h",
            text="占比%",
            hover_data=["财年", "原文"],
            height=max(200, len(pct_rows) * 55),
            labels={"占比%": "营收占比 (%)", "描述": ""},
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig_conc.update_traces(
            texttemplate="%{x:.1f}%",
            textposition="outside",
        )
        fig_conc.add_vline(x=10, line_dash="dash", line_color="red",
                           annotation_text="10% 披露门槛", annotation_position="top right")
        fig_conc.update_layout(
            margin=dict(l=10, r=40, t=10, b=30),
            paper_bgcolor="#f8f9fa", plot_bgcolor="white",
            showlegend=True,
        )
        st.plotly_chart(fig_conc, use_container_width=True)

    # Full table
    disp = df_conc[["描述", "占比%", "所属分部", "财年"]].copy()
    disp["占比%"] = disp["占比%"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
    disp["财年"]  = disp["财年"].apply(lambda x: str(int(x)) if pd.notna(x) else "—")
    st.dataframe(disp, use_container_width=True, hide_index=True)

    # Supply chain map visual
    st.markdown("---")
    st.markdown("**供应链伙伴关系图**")
    st.caption("左：上游供应商 · 右：下游客户 · 下方：竞争对手 · 可拖拽 · 滚轮缩放")
    from core.vis_graph import build_mini_map_payload
    from components.vis_map import render_vis_map
    from core.nav import handle_map_click, map_component_key
    mini_payload = build_mini_map_payload(selected, chain, height=340)
    clicked = render_vis_map(mini_payload, height=340, key=map_component_key(f"conc_{selected}"))
    handle_map_click(clicked, prefix=f"conc_{selected}", skip=selected)
else:
    st.info("未从 10-K 文本中提取到客户/供应商集中度信息。")

st.divider()

# ── Section 3: Geographic Revenue ─────────────────────────────────────────────
if not geo_df.empty:
    st.subheader("🌍 地区营收分布")
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        fig_geo = px.pie(
            geo_df, names="地区", values="fy0",
            title=f"{fy_labels[0]} 营收地区分布",
            hole=0.35,
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig_geo.update_layout(
            height=320, margin=dict(l=0, r=0, t=40, b=0),
            paper_bgcolor="#f8f9fa",
        )
        st.plotly_chart(fig_geo, use_container_width=True)
    with col_g2:
        geo_tbl = geo_df.copy()
        geo_total = geo_tbl["fy0"].sum()
        geo_tbl["占比%"] = (geo_tbl["fy0"] / geo_total * 100).round(1).map("{:.1f}%".format)
        geo_tbl.columns = ["地区", f"{fy_labels[0]}($M)", f"{fy_labels[1]}($M)", "占比%"]
        st.dataframe(geo_tbl, use_container_width=True, hide_index=True)
