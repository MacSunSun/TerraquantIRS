# TerraquantRIS — 半导体供应链投研系统

A Streamlit-based investment research application for semiconductor supply chain analysis, built around AMD as the focal company with extensible support for any publicly listed company.

**Live demo:** [terraquantirs.streamlit.app](https://terraquantirs.streamlit.app)

---

## Features

### 🕸️ Supply Chain Map
- Interactive physics-based network graph (Vis.js) showing upstream suppliers, downstream customers, and competitors
- **Hover** over any node to highlight its direct connections; all unrelated nodes fade out
- **Click** any node to navigate to that company's detail page
- Filter by tier (equipment layer, direct upstream, focal company, competitors, downstream)
- Edit mode: add/remove companies and relationships on the fly

### 🔍 Company Overview
- Key market metrics (price, market cap, PE, PB, EPS, 52-week range)
- Interactive stock price chart with adjustable time range (1Y / 3Y / 5Y / 10Y / MAX)
- Quarterly financials: revenue, gross profit, operating income, net income, EPS, YoY growth
- **Mini supply chain map** embedded in the page — left = upstream, right = downstream, bottom = competitors; draggable and zoomable

### 🎯 Business Concentration
- Segment revenue breakdown extracted from SEC 10-K filings (pie chart + 3-year trend bar)
- Customer concentration percentages mined from 10-K risk disclosures
- Geographic revenue distribution
- Supply chain partner relationship map

### 📊 Multi-Company Comparison
- Side-by-side comparison of any companies in the supply chain
- Revenue, margins, EPS, and YoY growth across periods

### 📄 10-K Text Mining
- Automatically identifies upstream/downstream company mentions in SEC 10-K filings
- Extracts relationship context, sections, and year of mention
- Timeline of mentions per company per year
- One-click to add discovered companies to the supply chain map

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Streamlit |
| Graph visualization | Vis.js (via `st.components.v1.html`) |
| Financial data | SEC EDGAR XBRL API (free) + yfinance |
| Local price data | Futu OpenD (optional, auto-detected) |
| Graph data structure | NetworkX |
| Charts | Plotly |
| Supply chain storage | JSON (`research_app/data/supply_chain.json`) |

---

## Project Structure

```
Investment Research/
├── research_app/               # Main Streamlit application
│   ├── app.py                  # Entry point & page navigation
│   ├── requirements.txt
│   ├── core/
│   │   ├── supply_chain.py     # Supply chain data model & helpers
│   │   ├── vis_graph.py        # Vis.js HTML generator (full map + mini map)
│   │   ├── price_data.py       # Market data (Futu OpenD → yfinance fallback)
│   │   ├── sec_data.py         # SEC EDGAR XBRL data pipeline
│   │   ├── concentration.py    # Segment revenue & customer concentration extractor
│   │   └── text_mining.py      # 10-K text mining for supply chain mentions
│   ├── pages/
│   │   ├── 1_公司概览.py       # Company overview
│   │   ├── 2_供应链地图.py     # Supply chain map
│   │   ├── 3_多公司对比.py     # Multi-company comparison
│   │   ├── 4_文本挖掘.py       # 10-K text mining
│   │   └── 5_业务集中度.py     # Business concentration analysis
│   └── data/
│       └── supply_chain.json   # Supply chain company & relationship definitions
├── AMD/                        # AMD-specific research files (local only)
│   ├── 10Q_10K/                # Downloaded SEC filings (gitignored)
│   ├── AMD_price_prediction_model.ipynb
│   └── amd_sec_workflow.py
├── .gitignore
├── runtime.txt                 # Python version for Streamlit Cloud
└── README.md
```

---

## Getting Started

### Run Locally

**Requirements:** Python 3.11+

```bash
# Clone the repository
git clone https://github.com/SJL111/TerraquantRIS.git
cd TerraquantRIS

# Install dependencies
pip install -r research_app/requirements.txt

# Launch the app
streamlit run research_app/app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

### Optional: Real-time Price Data via Futu OpenD

By default the app uses **yfinance** for price data (works everywhere, no setup needed).

If you have **Futu OpenD** installed and running on `localhost:11111`, the app automatically switches to Futu data for real-time prices and richer metrics. No configuration required — it detects the connection on startup.

---

## Data Sources

| Data | Source | Notes |
|---|---|---|
| Stock prices | yfinance / Futu OpenD | yfinance used on cloud; Futu locally |
| Quarterly financials | SEC EDGAR XBRL API | Free, no API key needed |
| Segment revenue | SEC 10-K text parsing | Regex extraction from MD&A section |
| Customer concentration | SEC 10-K text parsing | Extracted from risk factor disclosures |
| Supply chain relationships | `supply_chain.json` | Manually curated, editable in-app |
| 10-K filings (AMD) | SEC EDGAR download | Local files, gitignored |

---

## Adding a New Company

1. Open the app → **供应链地图** page
2. Switch to **"添加公司"** mode in the sidebar
3. Fill in Ticker, company name, SEC CIK, tier, and sector
4. Add relationships using **"添加关系"** mode

The supply chain JSON is updated automatically and persists across sessions.

---

## Deployment

This app is deployed on **Streamlit Community Cloud** (free tier).

To deploy your own instance:
1. Fork this repository
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app
3. Select your fork, branch `master`, main file `research_app/app.py`
4. Click Deploy

No server rental or environment configuration needed.

---

## Current Supply Chain Coverage (AMD-centric)

| Company | Ticker | Role |
|---|---|---|
| TSMC | TSM | Primary foundry (N3/N4 process) |
| Micron | MU | HBM3E / GDDR7 memory |
| Amkor | AMKR | Advanced chip packaging |
| ASML | ASML | EUV lithography (equipment) |
| Applied Materials | AMAT | CVD/PVD deposition (equipment) |
| Lam Research | LRCX | Etch tools (equipment) |
| KLA Corp | KLAC | Process control (equipment) |
| Microsoft | MSFT | Azure cloud + Xbox APU |
| Meta | META | AI infrastructure (MI300X) |
| Amazon | AMZN | AWS EC2 (EPYC CPUs) |
| Alphabet | GOOGL | GCP (EPYC + Instinct GPUs) |
| Dell | DELL | Server & workstation OEM |
| HPE | HPE | ProLiant servers |
| NVIDIA | NVDA | GPU competitor |
| Intel | INTC | CPU & data-center competitor |
| Qualcomm | QCOM | Mobile/edge competitor |

---

## License

For internal research use. Not financial advice.
