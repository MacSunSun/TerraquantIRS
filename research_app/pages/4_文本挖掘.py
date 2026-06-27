"""Page 4 — 10-K 文本挖掘 (Supply-Chain Extraction from SEC Filings)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px

from core.text_mining import mine_all_filings, summarise
from core.supply_chain import (
    load_chain, save_chain, add_company, add_relationship,
    TIER_LABELS, TIER_COLORS,
)

st.set_page_config(page_title="10-K 文本挖掘", page_icon="📄", layout="wide")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📄 10-K 文本挖掘")
    st.divider()
    st.markdown("""
从本地已下载的 SEC 10-K 文件中自动提取：
- 代工厂 / 制造商
- 封装商
- 主要客户（≥10% 营收）
- 设备供应商
- 竞争对手

**结果可一键加入供应链地图。**
""")

# ── Path config ───────────────────────────────────────────────────────────────
DEFAULT_DIR = Path(r"e:\Quant\Quant\Investment Research\AMD\10Q_10K\amd\10-K")

st.title("📄 10-K 文本挖掘 — 自动提取供应链关系")
st.caption("从 SEC 原始文件中提取公司名称，按出现频次排序，可直接加入供应链地图。")
st.divider()

# ── Directory selector ────────────────────────────────────────────────────────
col_path, col_btn = st.columns([4, 1])
with col_path:
    filing_dir = st.text_input(
        "10-K 文件目录",
        value=str(DEFAULT_DIR),
        help="包含 *.txt SEC 文件的文件夹路径",
    )
with col_btn:
    st.write("")
    run = st.button("🔍 开始提取", type="primary", use_container_width=True)

# ── Cache path for results ────────────────────────────────────────────────────
CACHE_KEY = f"mining_results_{filing_dir}"

if run or CACHE_KEY in st.session_state:
    if run:
        path_obj = Path(filing_dir)
        if not path_obj.exists():
            st.error(f"目录不存在：{filing_dir}")
            st.stop()

        files = list(path_obj.glob("*.txt"))
        if not files:
            st.error("该目录下没有 .txt 文件")
            st.stop()

        with st.spinner(f"正在解析 {len(files)} 份 10-K 文件…（约需 20–60 秒）"):
            df_raw = mine_all_filings(path_obj, form="10-K")
            df_sum = summarise(df_raw)

        st.session_state[CACHE_KEY] = (df_raw, df_sum)
        st.success(f"完成！共发现 {len(df_sum)} 家公司的关联关系")

    df_raw, df_sum = st.session_state[CACHE_KEY]

    if df_sum.empty:
        st.warning("未提取到任何关系，请检查文件内容")
        st.stop()

    # ── Filters ──────────────────────────────────────────────────────────────
    st.subheader("提取结果")

    f1, f2, f3 = st.columns(3)
    with f1:
        min_conf = st.slider("最低置信度（出现年份占比）", 0.0, 1.0, 0.2, 0.05)
    with f2:
        filter_tier = st.multiselect(
            "筛选层级",
        options=list(TIER_LABELS.keys()),
        default=list(TIER_LABELS.keys()),
        format_func=lambda k: TIER_LABELS[k],
        )
    with f3:
        filter_section = st.multiselect(
            "筛选来源段落",
            options=["manufacturing", "customers", "risk", "competition"],
            default=["manufacturing", "customers", "risk", "competition"],
        )

    # Apply filters
    mask = (
        (df_sum["confidence"] >= min_conf) &
        (df_sum["tier"].isin(filter_tier)) &
        (df_sum["section"].isin(filter_section))
    )
    df_view = df_sum[mask].copy()

    # Human-readable column names
    df_display = df_view[[
        "ticker", "tier", "rel_type", "section",
        "years_found", "first_year", "last_year", "confidence",
    ]].copy()
    df_display.columns = [
        "Ticker", "层级", "关系类型", "发现段落",
        "出现年数", "首次年份", "最近年份", "置信度",
    ]
    df_display["层级"]   = df_display["层级"].map(TIER_LABELS).fillna(df_display["层级"])
    df_display["关系类型"] = df_display["关系类型"].map({
        "manufactures_for":   "代工制造",
        "supplies_component": "供应零部件",
        "sells_to":           "销售给",
        "competes_with":      "竞争关系",
    }).fillna(df_display["关系类型"])
    df_display["发现段落"] = df_display["发现段落"].map({
        "manufacturing": "制造/代工",
        "customers":     "客户",
        "risk":          "风险因素",
        "competition":   "竞争",
    }).fillna(df_display["发现段落"])

    st.dataframe(df_display, use_container_width=True, hide_index=True)

    # ── Timeline chart ────────────────────────────────────────────────────────
    st.subheader("各公司被提及年份分布")
    df_timeline = df_raw[df_raw["ticker"].isin(df_view["ticker"].tolist())].copy()
    if not df_timeline.empty:
        pivot = df_timeline.groupby(["year", "ticker"]).size().reset_index(name="mentions")
        fig = px.scatter(
            pivot, x="year", y="ticker", size="mentions", color="ticker",
            size_max=18, height=max(350, len(df_view) * 22),
            labels={"year": "财年", "ticker": "公司", "mentions": "提及次数"},
            title="在历年 10-K 中的提及频率",
        )
        fig.update_layout(
            showlegend=False,
            plot_bgcolor="white", paper_bgcolor="#f8f9fa",
            margin=dict(l=10, r=10, t=50, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Context viewer ────────────────────────────────────────────────────────
    st.subheader("原文上下文")
    ticker_sel = st.selectbox(
        "查看某公司的原文片段",
        options=df_view["ticker"].tolist(),
    )
    if ticker_sel:
        ctx_rows = (df_raw[df_raw["ticker"] == ticker_sel]
                    .sort_values("year", ascending=False)
                    .drop_duplicates(subset=["year", "section"]))
        for _, row in ctx_rows.head(6).iterrows():
            tier_label = TIER_LABELS.get(row["tier"], row["tier"])
            with st.expander(f"[{row['year']}] {tier_label} — {row['section']} 段落"):
                st.markdown(f"**关系类型：** `{row['rel_type']}`")
                st.info(row["context"])

    st.divider()

    # ── Add to supply chain ───────────────────────────────────────────────────
    st.subheader("加入供应链地图")
    chain = load_chain()
    existing_tickers = set(chain["companies"].keys())

    # Show only companies not already in the chain
    new_tickers = df_view[~df_view["ticker"].isin(existing_tickers)]["ticker"].tolist()
    already_in  = df_view[ df_view["ticker"].isin(existing_tickers)]["ticker"].tolist()

    if already_in:
        st.success(f"已在供应链地图中：{', '.join(already_in)}")

    if not new_tickers:
        st.info("所有提取到的公司均已在供应链地图中")
    else:
        st.markdown(f"**以下 {len(new_tickers)} 家公司未在地图中，可选择加入：**")
        # Show a preview table of what will be added
        preview = df_view[df_view["ticker"].isin(new_tickers)][
            ["ticker", "name", "tier", "rel_type", "years_found", "confidence"]
        ].copy()
        preview.columns = ["Ticker", "名称", "层级", "关系类型", "出现年数", "置信度"]
        preview["层级"] = preview["层级"].map(TIER_LABELS).fillna(preview["层级"])
        st.dataframe(preview, use_container_width=True, hide_index=True)

        to_add = st.multiselect(
            "选择要加入的公司（默认选置信度最高的前 5 个）",
            options=new_tickers,
            default=new_tickers[:5],
        )

        focal_ticker = chain.get("focal", "AMD")

        if to_add and st.button("➕ 加入供应链地图", type="primary"):
            added = []
            for ticker in to_add:
                row = df_view[df_view["ticker"] == ticker].iloc[0]
                # Add company node
                chain = add_company(
                    chain,
                    ticker=ticker,
                    name=row["name"],
                    cik="",           # user can fill in later
                    tier=row["tier"],
                    sector="",
                    note=f"从 10-K 文本挖掘提取 (置信度 {row['confidence']:.0%}，出现 {row['years_found']} 个财年)",
                )
                # Add relationship
                rel = row["rel_type"]
                if rel in ("manufactures_for", "supplies_component"):
                    from_t, to_t = ticker, focal_ticker
                elif rel == "sells_to":
                    from_t, to_t = focal_ticker, ticker
                elif rel == "competes_with":
                    from_t, to_t = focal_ticker, ticker
                else:
                    from_t, to_t = ticker, focal_ticker

                chain = add_relationship(
                    chain,
                    from_t=from_t, to_t=to_t,
                    rel_type=rel,
                    note=f"10-K 文本挖掘 — 出现于 {row['first_year']}–{row['last_year']}",
                )
                added.append(ticker)

            save_chain(chain)
            st.success(f"✅ 已加入：{', '.join(added)}  — 前往「供应链地图」查看")
            st.rerun()
else:
    st.info("点击「🔍 开始提取」开始从 10-K 文件中挖掘供应链关系。")
    st.markdown("""
**提取逻辑说明：**

| 段落 | 提取的关系 |
|------|-----------|
| Manufacturing / Third-Party Foundry | 代工制造商（TSMC、GF、UMC、Samsung…） |
| Customers / Revenue Concentration | 收入集中度 ≥10% 的客户 |
| Risk Factors | 关键依赖供应商 |
| Competition | 竞争对手 |

置信度 = 该公司在多少个财年中出现 / 总财年数。
""")
