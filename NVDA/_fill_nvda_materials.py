"""Fill NVDA research materials toward AMD/SNDK parity.
Secrets: load MASSIVE_API_KEY from C:\\MegaQuant\\.env only — never hardcode.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(r"C:\MegaQuant\Investment Research")
NVDA = ROOT / "NVDA"
ENV_PATH = Path(r"C:\MegaQuant\.env")
USER_AGENT = "sunjialin sunjialin@terraquant.cn"
CIK = "CIK0001045810"
TICKER = "NVDA"

# Press-release PDF gallery IDs from nvidianews (ObjectId-dated)
EARNINGS_PDFS = [
    # (announce_date, filename_slug, gallery_id)
    ("2026-08-26", "NVDA_Reports_Second_Quarter_2027_Financial", "6a8f4ad73d6332b41f76ab70"),
    ("2026-05-20", "NVDA_Reports_First_Quarter_2027_Financial", "6a0e17dc3d633295d45282e6"),
    ("2026-02-25", "NVDA_Reports_Fourth_Quarter_and_Full_Year_2026", "699f6ab43d6332ccaa689907"),
    ("2025-11-19", "NVDA_Reports_Third_Quarter_2026_Financial", "691e34d93d633290a88deeef"),
    ("2025-08-27", "NVDA_Reports_Second_Quarter_2026_Financial", "68af69043d6332f1d02dec91"),
    ("2025-05-28", "NVDA_Reports_First_Quarter_2026_Financial", "6837703d3d63320fddb3a9ee"),
    ("2025-02-26", "NVDA_Reports_Fourth_Quarter_and_Full_Year_2025", "67bf85d73d633281c6875f57"),
    ("2024-11-20", "NVDA_Reports_Third_Quarter_2025_Financial", "673e52d63d6332ce4bb72f56"),
    ("2024-08-28", "NVDA_Reports_Second_Quarter_2025_Financial", "66cf872bed6ae51c7417f273"),
    ("2024-05-22", "NVDA_Reports_First_Quarter_2025_Financial", "664e53fe3d63322459a5eff6"),
    ("2024-02-21", "NVDA_Reports_Fourth_Quarter_and_Full_Year_2024", "65d669a33d63329bbf62672a"),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def download_earnings_pdfs() -> list[str]:
    added = []
    sess = requests.Session()
    sess.headers.update({"User-Agent": USER_AGENT})
    for date, slug, gid in EARNINGS_PDFS:
        out = NVDA / f"{date}_{slug}.pdf"
        if out.exists() and out.stat().st_size > 10_000:
            log(f"[pdf] skip exists {out.name}")
            continue
        url = f"https://nvidianews.nvidia.com/_gallery/download_pdf/{gid}/"
        log(f"[pdf] GET {url}")
        r = sess.get(url, timeout=120, allow_redirects=True)
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "pdf" not in ctype and not r.content.startswith(b"%PDF"):
            raise RuntimeError(f"Not a PDF for {gid}: ctype={ctype} bytes={len(r.content)}")
        out.write_bytes(r.content)
        added.append(out.name)
        log(f"[pdf] wrote {out.name} ({len(r.content)} bytes)")
        time.sleep(0.4)
    return added


def fetch_gaap():
    url = f"https://data.sec.gov/api/xbrl/companyfacts/{CIK}.json"
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=90)
    r.raise_for_status()
    return r.json()["facts"]["us-gaap"]


def flow_qtr(gaap, concept, col):
    if concept not in gaap:
        return pd.Series(dtype=float, name=col)
    units = gaap[concept]["units"]
    uk = "USD" if "USD" in units else next(iter(units))
    df = pd.DataFrame(units[uk])
    if "start" not in df.columns:
        return pd.Series(dtype=float, name=col)
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    df["dur"] = (df["end"] - df["start"]).dt.days
    q = df[df["form"].isin(["10-Q", "10-K"]) & df["dur"].between(70, 105)].copy()
    q = q.sort_values("filed").drop_duplicates("end", keep="last")
    return q.set_index("end")["val"].rename(col).sort_index().astype(float)


def stock_qtr(gaap, concept, col):
    """Balance-sheet / instant concepts."""
    if concept not in gaap:
        return pd.Series(dtype=float, name=col)
    units = gaap[concept]["units"]
    uk = "USD" if "USD" in units else ("shares" if "shares" in units else next(iter(units)))
    df = pd.DataFrame(units[uk])
    if "end" not in df.columns:
        return pd.Series(dtype=float, name=col)
    df["end"] = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    q = df[df["form"].isin(["10-Q", "10-K"])].copy()
    q = q.sort_values("filed").drop_duplicates("end", keep="last")
    return q.set_index("end")["val"].rename(col).sort_index().astype(float)


def build_financials() -> dict:
    log("[sec] fetching companyfacts XBRL…")
    gaap = fetch_gaap()
    # Revenue concepts (NVIDIA uses Revenues / RevenueFromContractWithCustomerExcludingAssessedTax)
    rev = flow_qtr(gaap, "RevenueFromContractWithCustomerExcludingAssessedTax", "revenue")
    if rev.empty:
        rev = flow_qtr(gaap, "Revenues", "revenue")
    gp = flow_qtr(gaap, "GrossProfit", "gross_profit")
    oi = flow_qtr(gaap, "OperatingIncomeLoss", "op_income")
    ni = flow_qtr(gaap, "NetIncomeLoss", "net_income")
    # EPS diluted — unit may be USD/shares
    eps = None
    for concept in ("EarningsPerShareDiluted",):
        if concept in gaap:
            units = gaap[concept]["units"]
            uk = "USD/shares" if "USD/shares" in units else next(iter(units))
            df = pd.DataFrame(units[uk])
            if "start" in df.columns:
                df["start"] = pd.to_datetime(df["start"])
                df["end"] = pd.to_datetime(df["end"])
                df["filed"] = pd.to_datetime(df["filed"])
                df["dur"] = (df["end"] - df["start"]).dt.days
                q = df[df["form"].isin(["10-Q", "10-K"]) & df["dur"].between(70, 105)].copy()
                q = q.sort_values("filed").drop_duplicates("end", keep="last")
                eps = q.set_index("end")["val"].rename("eps_diluted").sort_index().astype(float)
                break
    if eps is None:
        eps = pd.Series(dtype=float, name="eps_diluted")

    opex = flow_qtr(gaap, "OperatingExpenses", "op_expenses")
    assets = stock_qtr(gaap, "Assets", "total_assets")
    cash = stock_qtr(gaap, "CashAndCashEquivalentsAtCarryingValue", "cash")

    df = pd.concat([rev, gp, oi, ni, eps, opex], axis=1).sort_index()
    df = df.dropna(subset=["revenue"], how="all")
    df["gross_margin"] = (df["gross_profit"] / df["revenue"]).where(df["revenue"] != 0)
    df.index.name = "period_end"
    df = df.reset_index()
    # keep last ~24 quarters for overview
    qdf = df.tail(24).copy()

    # Overview sheet matching AMD column names (GAAP-focused; Non-GAAP left blank)
    overview = pd.DataFrame({
        "Earnings Release Date": pd.NaT,
        "Fiscal Quarter and Fiscal Year": qdf["period_end"].dt.strftime("%Y-%m-%d"),
        "Reporting Period Start": pd.NaT,
        "Reporting Period End": qdf["period_end"],
        "GAAP Revenue": (qdf["revenue"] / 1e6).round(1),  # $ millions
        "Non-GAAP Revenue": pd.NA,
        "GAAP Gross Margin": (qdf["gross_margin"] * 100).round(1),
        "Non-GAAP Gross Margin": pd.NA,
        "GAAP Operating Expenses": (qdf["op_expenses"] / 1e6).round(1),
        "Non-GAAP Operating Expenses": pd.NA,
        "GAAP Operating Income": (qdf["op_income"] / 1e6).round(1),
        "Non-GAAP Operating Income": pd.NA,
        "GAAP Net Income": (qdf["net_income"] / 1e6).round(1),
        "Non-GAAP Net Income": pd.NA,
        "GAAP Diluted EPS": qdf["eps_diluted"].round(4),
        "Non-GAAP Diluted EPS": pd.NA,
        "Source": "SEC XBRL companyfacts",
    })

    metrics = qdf.copy()
    metrics["revenue_musd"] = (metrics["revenue"] / 1e6).round(1)
    metrics["gross_profit_musd"] = (metrics["gross_profit"] / 1e6).round(1)
    metrics["op_income_musd"] = (metrics["op_income"] / 1e6).round(1)
    metrics["net_income_musd"] = (metrics["net_income"] / 1e6).round(1)
    metrics["gross_margin_pct"] = (metrics["gross_margin"] * 100).round(2)

    overview_path = NVDA / "NVDA_Reports_Fiscal_Overview.xlsx"
    metrics_path = NVDA / "nvda_financial_metrics.xlsx"
    extracted_path = NVDA / "nvda_10q_extracted.csv"

    with pd.ExcelWriter(overview_path, engine="openpyxl") as w:
        overview.to_excel(w, sheet_name="Quarterly Summary", index=False)
        # Yearly rollup from quarterly
        y = qdf.copy()
        y["fy"] = y["period_end"].dt.year  # approximate calendar year bucket
        # NVIDIA FY ends late January — better: fiscal year = year of Jan period_end for Q4
        # Keep simple yearly sum by calendar year of period_end for now + note
        yearly = y.groupby(y["period_end"].dt.to_period("Y").astype(str)).agg(
            GAAP_Revenue=("revenue", "sum"),
            GAAP_Net_Income=("net_income", "sum"),
            GAAP_Op_Income=("op_income", "sum"),
        ).reset_index().rename(columns={"period_end": "Calendar Year of Period Ends"})
        for c in ("GAAP_Revenue", "GAAP_Net_Income", "GAAP_Op_Income"):
            yearly[c] = (yearly[c] / 1e6).round(1)
        yearly.to_excel(w, sheet_name="Yearly Summary", index=False)

    with pd.ExcelWriter(metrics_path, engine="openpyxl") as w:
        metrics.to_excel(w, sheet_name="Quarterly_GAAP", index=False)
        if not assets.empty:
            bal = pd.concat([assets, cash], axis=1).reset_index().rename(columns={"index": "period_end", "end": "period_end"})
            # fix column
            if "period_end" not in bal.columns:
                bal = bal.rename(columns={bal.columns[0]: "period_end"})
            bal.tail(24).to_excel(w, sheet_name="Balance_Snapshot", index=False)

    metrics.to_csv(extracted_path, index=False)
    log(f"[sec] wrote {overview_path.name}, {metrics_path.name}, {extracted_path.name} rows={len(metrics)}")
    return {
        "overview": overview_path.name,
        "metrics": metrics_path.name,
        "extracted": extracted_path.name,
        "quarters": int(len(metrics)),
    }


def massive_get(path: str, params: dict | None = None) -> dict:
    load_dotenv(ENV_PATH)
    key = os.environ.get("MASSIVE_API_KEY")
    if not key:
        raise RuntimeError("MASSIVE_API_KEY missing in C:\\MegaQuant\\.env")
    url = f"https://api.massive.com{path}"
    headers = {"Authorization": f"Bearer {key}"}
    r = requests.get(url, headers=headers, params=params or {}, timeout=120)
    if r.status_code == 401:
        # try query param style
        params = dict(params or {})
        params["apiKey"] = key
        r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def pull_massive() -> dict:
    out_dir = NVDA / "nvda_massive_data"
    out_dir.mkdir(parents=True, exist_ok=True)
    added = []

    # Daily bars ~5y
    log("[massive] daily aggs…")
    data = massive_get(
        f"/v2/aggs/ticker/{TICKER}/range/1/day/2019-01-01/2026-10-20",
        {"adjusted": "true", "sort": "asc", "limit": 50000},
    )
    results = data.get("results") or []
    rows = []
    for b in results:
        rows.append({
            "date": datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc).date().isoformat(),
            "open": b.get("o"),
            "high": b.get("h"),
            "low": b.get("l"),
            "close": b.get("c"),
            "volume": b.get("v"),
            "vwap": b.get("vw"),
            "transactions": b.get("n"),
        })
    daily = pd.DataFrame(rows)
    daily_path = out_dir / "history_daily.csv"
    daily.to_csv(daily_path, index=False)
    added.append(daily_path.name)
    log(f"[massive] daily bars={len(daily)} -> {daily_path.name}")

    # 1y slice
    if not daily.empty:
        cutoff = (pd.Timestamp.today() - pd.Timedelta(days=370)).date().isoformat()
        y1 = daily[daily["date"] >= cutoff]
        y1_path = out_dir / "history_1y.csv"
        y1.to_csv(y1_path, index=False)
        added.append(y1_path.name)

    # Weekly bars
    log("[massive] weekly aggs…")
    wdata = massive_get(
        f"/v2/aggs/ticker/{TICKER}/range/1/week/2019-01-01/2026-10-20",
        {"adjusted": "true", "sort": "asc", "limit": 50000},
    )
    wrows = []
    for b in wdata.get("results") or []:
        wrows.append({
            "date": datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc).date().isoformat(),
            "open": b.get("o"), "high": b.get("h"), "low": b.get("l"),
            "close": b.get("c"), "volume": b.get("v"), "vwap": b.get("vw"),
        })
    weekly = pd.DataFrame(wrows)
    weekly_path = out_dir / "history_weekly.csv"
    weekly.to_csv(weekly_path, index=False)
    added.append(weekly_path.name)

    # Ticker details / snapshot-ish reference
    for label, path in [
        ("ticker_details", f"/v3/reference/tickers/{TICKER}"),
        ("dividends", "/v3/reference/dividends"),
        ("splits", "/v3/reference/splits"),
    ]:
        try:
            params = {"ticker": TICKER, "limit": 100} if label != "ticker_details" else None
            payload = massive_get(path, params)
            fp = out_dir / f"{label}.json"
            fp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            added.append(fp.name)
            log(f"[massive] wrote {fp.name}")
        except Exception as e:
            log(f"[massive] optional {label} skipped: {type(e).__name__}: {e}")

    meta = {
        "ticker": TICKER,
        "source": "Massive API (api.massive.com)",
        "auth": "MASSIVE_API_KEY via C:/MegaQuant/.env (not stored here)",
        "pulled_at_utc": datetime.now(timezone.utc).isoformat(),
        "daily_bars": int(len(daily)),
        "weekly_bars": int(len(weekly)),
        "files": added,
    }
    (out_dir / "pull_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def scaffold_notebook() -> str:
    nb_path = NVDA / "NVDA_price_prediction_model.ipynb"
    if nb_path.exists():
        log(f"[nb] exists {nb_path.name}")
        return nb_path.name
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# NVDA Price Prediction Model (scaffold)\n",
                "\n",
                "Modeled after AMD/SNDK notebooks. Data inputs expected:\n",
                "- `nvda_massive_data/history_daily.csv` (Massive OHLCV)\n",
                "- `nvda_10q_extracted.csv` / `nvda_financial_metrics.xlsx` (SEC XBRL GAAP)\n",
                "- Earnings PDFs in this folder for qualitative checks\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "from pathlib import Path\n",
                "import pandas as pd\n",
                "\n",
                "ROOT = Path(r'C:\\MegaQuant\\Investment Research\\NVDA')\n",
                "price = pd.read_csv(ROOT / 'nvda_massive_data' / 'history_daily.csv', parse_dates=['date'])\n",
                "fins = pd.read_csv(ROOT / 'nvda_10q_extracted.csv', parse_dates=['period_end'])\n",
                "print(price.tail())\n",
                "print(fins.tail())\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# TODO: align quarterly fundamentals to forward returns (see AMD_price_prediction_model.ipynb)\n",
                "# TODO: Ridge / RF / XGB baselines; walk-forward validation\n",
                "price = price.sort_values('date')\n",
                "price['ret_21d'] = price['close'].pct_change(21).shift(-21)\n",
                "print(price[['date','close','ret_21d']].dropna().tail())\n",
            ],
        },
    ]
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }
    nb_path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    log(f"[nb] wrote {nb_path.name}")
    return nb_path.name


def write_helper_script() -> str:
    """Reusable puller that loads env — no secrets inline."""
    helper = NVDA / "_pull_massive_data.py"
    helper.write_text(
        '''"""Pull NVDA OHLCV from Massive API. Reads MASSIVE_API_KEY from C:\\\\MegaQuant\\\\.env."""
from pathlib import Path
import runpy
# Re-run the fill script's massive section if needed, or:
import os, json, requests, pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv

ENV = Path(r"C:\\MegaQuant\\.env")
OUT = Path(__file__).resolve().parent / "nvda_massive_data"
OUT.mkdir(exist_ok=True)
load_dotenv(ENV)
key = os.environ["MASSIVE_API_KEY"]
url = "https://api.massive.com/v2/aggs/ticker/NVDA/range/1/day/2019-01-01/2026-10-20"
r = requests.get(url, headers={"Authorization": f"Bearer {key}"},
                 params={"adjusted": "true", "sort": "asc", "limit": 50000}, timeout=120)
r.raise_for_status()
rows = []
for b in r.json().get("results") or []:
    rows.append({
        "date": datetime.fromtimestamp(b["t"]/1000, tz=timezone.utc).date().isoformat(),
        "open": b.get("o"), "high": b.get("h"), "low": b.get("l"),
        "close": b.get("c"), "volume": b.get("v"), "vwap": b.get("vw"),
    })
pd.DataFrame(rows).to_csv(OUT / "history_daily.csv", index=False)
print("bars", len(rows))
''',
        encoding="utf-8",
    )
    return helper.name


def main():
    NVDA.mkdir(parents=True, exist_ok=True)
    report = {"ticker": "NVDA", "started": datetime.now().isoformat()}
    report["pdfs_added"] = download_earnings_pdfs()
    report["financials"] = build_financials()
    report["massive"] = pull_massive()
    report["notebook"] = scaffold_notebook()
    report["helper"] = write_helper_script()
    report["finished"] = datetime.now().isoformat()
    # inventory
    items = []
    for p in sorted(NVDA.iterdir(), key=lambda x: x.name.lower()):
        if p.is_dir():
            n = sum(1 for _ in p.rglob("*") if _.is_file())
            items.append(f"DIR {p.name}/ files={n}")
        else:
            items.append(f"FILE {p.name} size={p.stat().st_size}")
    report["inventory_after"] = items
    (NVDA / "_fill_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
