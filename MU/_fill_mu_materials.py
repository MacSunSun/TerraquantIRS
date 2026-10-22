"""Fill MU research materials (NVDA-style pipeline).
Secrets: MASSIVE_API_KEY from C:\\MegaQuant\\.env only — never hardcode.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(r"C:\MegaQuant\Investment Research")
MU = ROOT / "MU"
ENV_PATH = Path(r"C:\MegaQuant\.env")
USER_AGENT = "sunjialin sunjialin@terraquant.cn"
CIK = "CIK0000723125"
CIK_N = "723125"
TICKER = "MU"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# (announce_date, accession, exhibit_filename, slug)
EARNINGS_EXHIBITS = [
    ("2023-12-20", "0000723125-23-000071", "a2024q1ex991-pressrelease.htm", "MU_Reports_First_Quarter_2024_Financial"),
    ("2024-03-20", "0000723125-24-000004", "a2024q2ex991-pressrelease.htm", "MU_Reports_Second_Quarter_2024_Financial"),
    ("2024-06-26", "0000723125-24-000016", "a2024q3ex991-pressrelease.htm", "MU_Reports_Third_Quarter_2024_Financial"),
    ("2024-09-25", "0000723125-24-000023", "a2024q4ex991-pressrelease.htm", "MU_Reports_Fourth_Quarter_and_Full_Year_2024"),
    ("2024-12-18", "0000723125-24-000046", "a2025q1ex991-pressrelease.htm", "MU_Reports_First_Quarter_2025_Financial"),
    ("2025-03-20", "0000723125-25-000006", "a2025q2ex991-pressrelease.htm", "MU_Reports_Second_Quarter_2025_Financial"),
    ("2025-06-25", "0000723125-25-000019", "a2025q3ex991-pressrelease.htm", "MU_Reports_Third_Quarter_2025_Financial"),
    ("2025-09-23", "0000723125-25-000024", "a2025q4ex991-pressrelease.htm", "MU_Reports_Fourth_Quarter_and_Full_Year_2025"),
    ("2025-12-17", "0000723125-25-000044", "a2026q1ex991-pressrelease.htm", "MU_Reports_First_Quarter_2026_Financial"),
    ("2026-03-18", "0000723125-26-000004", "a2026q2ex991-pressrelease.htm", "MU_Reports_Second_Quarter_2026_Financial"),
    ("2026-06-24", "0000723125-26-000013", "a2026q3ex991-pressrelease.htm", "MU_Reports_Third_Quarter_2026_Financial"),
    ("2026-09-30", "0000723125-26-000018", "a2026q4ex991-pressrelease.htm", "MU_Reports_Fourth_Quarter_and_Full_Year_2026"),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def download_earnings_pdfs() -> list[str]:
    added = []
    sess = requests.Session()
    sess.headers.update({"User-Agent": USER_AGENT})
    html_dir = MU / "_earnings_html"
    html_dir.mkdir(parents=True, exist_ok=True)

    for date, acc, exhibit, slug in EARNINGS_EXHIBITS:
        out_pdf = MU / f"{date}_{slug}.pdf"
        if out_pdf.exists() and out_pdf.stat().st_size > 5_000:
            log(f"[pdf] skip exists {out_pdf.name}")
            continue
        acc_nodash = acc.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{CIK_N}/{acc_nodash}/{exhibit}"
        log(f"[html] GET {url}")
        r = sess.get(url, timeout=120)
        r.raise_for_status()
        html_path = html_dir / f"{date}_{slug}.htm"
        html_path.write_bytes(r.content)
        # Edge headless print to PDF
        file_url = html_path.resolve().as_uri()
        cmd = [
            EDGE,
            "--headless",
            "--disable-gpu",
            f"--print-to-pdf={out_pdf}",
            "--no-pdf-header-footer",
            file_url,
        ]
        log(f"[pdf] edge print {out_pdf.name}")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if not out_pdf.exists() or out_pdf.stat().st_size < 1000:
            raise RuntimeError(f"PDF failed for {slug}: rc={proc.returncode} stderr={proc.stderr[-400:]}")
        added.append(out_pdf.name)
        log(f"[pdf] wrote {out_pdf.name} ({out_pdf.stat().st_size} bytes)")
        time.sleep(0.4)
    return added


def fetch_gaap():
    r = requests.get(
        f"https://data.sec.gov/api/xbrl/companyfacts/{CIK}.json",
        headers={"User-Agent": USER_AGENT},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()["facts"]["us-gaap"]


def flow_qtr(gaap, concept, col, unit_pref=None):
    if concept not in gaap:
        return pd.Series(dtype=float, name=col)
    units = gaap[concept]["units"]
    if unit_pref and unit_pref in units:
        uk = unit_pref
    elif "USD" in units:
        uk = "USD"
    elif "USD/shares" in units:
        uk = "USD/shares"
    else:
        uk = next(iter(units))
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


def flow_annual(gaap, concept, col, unit_pref=None):
    if concept not in gaap:
        return pd.Series(dtype=float, name=col)
    units = gaap[concept]["units"]
    if unit_pref and unit_pref in units:
        uk = unit_pref
    elif "USD" in units:
        uk = "USD"
    elif "USD/shares" in units:
        uk = "USD/shares"
    else:
        uk = next(iter(units))
    df = pd.DataFrame(units[uk])
    if "start" not in df.columns:
        return pd.Series(dtype=float, name=col)
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    df["dur"] = (df["end"] - df["start"]).dt.days
    # Micron FY ~365 days (sometimes 52/53 week)
    a = df[df["form"].isin(["10-K"]) & df["dur"].between(350, 380)].copy()
    a = a.sort_values("filed").drop_duplicates("end", keep="last")
    return a.set_index("end")["val"].rename(col).sort_index().astype(float)


def stock(gaap, concept, col):
    if concept not in gaap:
        return pd.Series(dtype=float, name=col)
    units = gaap[concept]["units"]
    uk = "USD" if "USD" in units else next(iter(units))
    df = pd.DataFrame(units[uk])
    df["end"] = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    q = df[df["form"].isin(["10-Q", "10-K"])].copy()
    q = q.sort_values("filed").drop_duplicates("end", keep="last")
    return q.set_index("end")["val"].rename(col).sort_index().astype(float)


def build_financials() -> dict:
    log("[sec] fetching companyfacts…")
    gaap = fetch_gaap()
    # MU prefers RevenueFromContractWithCustomerExcludingAssessedTax
    rev = flow_qtr(gaap, "RevenueFromContractWithCustomerExcludingAssessedTax", "revenue")
    if rev.empty:
        rev = flow_qtr(gaap, "Revenues", "revenue")
    gp = flow_qtr(gaap, "GrossProfit", "gross_profit")
    oi = flow_qtr(gaap, "OperatingIncomeLoss", "op_income")
    ni = flow_qtr(gaap, "NetIncomeLoss", "net_income")
    opex = flow_qtr(gaap, "OperatingExpenses", "op_expenses")
    eps = flow_qtr(gaap, "EarningsPerShareDiluted", "eps_diluted", unit_pref="USD/shares")
    assets = stock(gaap, "Assets", "total_assets")
    cash = stock(gaap, "CashAndCashEquivalentsAtCarryingValue", "cash")

    df = pd.concat([rev, gp, oi, ni, eps, opex], axis=1, sort=True).sort_index()
    df = df.dropna(subset=["revenue"])
    df["gross_margin"] = df["gross_profit"] / df["revenue"]
    df = df.reset_index()
    df = df.rename(columns={df.columns[0]: "period_end"})
    df["derived_q4"] = False

    # Derive missing Q4 = annual - sum(Q1..Q3)
    concepts = {
        "revenue": "RevenueFromContractWithCustomerExcludingAssessedTax",
        "gross_profit": "GrossProfit",
        "op_income": "OperatingIncomeLoss",
        "net_income": "NetIncomeLoss",
        "op_expenses": "OperatingExpenses",
        "eps_diluted": "EarningsPerShareDiluted",
    }
    qtr = {k: flow_qtr(gaap, c, k, unit_pref=("USD/shares" if k == "eps_diluted" else None)) for k, c in concepts.items()}
    # annual revenue concept same
    ann = {}
    for k, c in concepts.items():
        s = flow_annual(gaap, c, k, unit_pref=("USD/shares" if k == "eps_diluted" else None))
        if s.empty and k == "revenue":
            s = flow_annual(gaap, "Revenues", k)
        ann[k] = s

    derived_rows = []
    for end, aval in ann["revenue"].items():
        window_start = end - pd.Timedelta(days=400)
        qs = qtr["revenue"][(qtr["revenue"].index > window_start) & (qtr["revenue"].index < end)].sort_index().tail(3)
        if len(qs) < 3:
            continue
        # skip if a quarterly row already ends near annual FY end
        if any(abs((pd.Timestamp(e) - end).days) <= 10 for e in df["period_end"]):
            continue
        row = {"period_end": end, "derived_q4": True, "gross_margin": None}
        ok = True
        for k in concepts:
            if end not in ann[k].index:
                ok = False
                break
            qsum = qtr[k].reindex(qs.index).sum()
            if pd.isna(qsum):
                ok = False
                break
            row[k] = float(ann[k].loc[end] - qsum)
        if ok:
            if row.get("revenue"):
                row["gross_margin"] = row["gross_profit"] / row["revenue"] if row.get("gross_profit") is not None else None
            derived_rows.append(row)
            log(f"[sec] derived Q4 {end.date()} rev={row['revenue']/1e9:.2f}B")

    if derived_rows:
        ddf = pd.DataFrame(derived_rows)
        df = pd.concat([df, ddf], ignore_index=True, sort=False)
        df = df.sort_values("period_end").drop_duplicates("period_end", keep="last")

    qdf = df.sort_values("period_end").tail(44).copy()
    qdf["revenue_musd"] = (qdf["revenue"] / 1e6).round(1)
    qdf["gross_profit_musd"] = (qdf["gross_profit"] / 1e6).round(1)
    qdf["op_income_musd"] = (qdf["op_income"] / 1e6).round(1)
    qdf["net_income_musd"] = (qdf["net_income"] / 1e6).round(1)
    qdf["op_expenses_musd"] = (qdf["op_expenses"] / 1e6).round(1)
    qdf["gross_margin_pct"] = (qdf["gross_margin"] * 100).round(2)

    overview = pd.DataFrame({
        "Earnings Release Date": pd.NaT,
        "Fiscal Quarter and Fiscal Year": pd.to_datetime(qdf["period_end"]).dt.strftime("%Y-%m-%d"),
        "Reporting Period End": qdf["period_end"],
        "GAAP Revenue": qdf["revenue_musd"],
        "Non-GAAP Revenue": pd.NA,
        "GAAP Gross Margin": qdf["gross_margin_pct"],
        "Non-GAAP Gross Margin": pd.NA,
        "GAAP Operating Expenses": qdf["op_expenses_musd"],
        "Non-GAAP Operating Expenses": pd.NA,
        "GAAP Operating Income": qdf["op_income_musd"],
        "Non-GAAP Operating Income": pd.NA,
        "GAAP Net Income": qdf["net_income_musd"],
        "Non-GAAP Net Income": pd.NA,
        "GAAP Diluted EPS": qdf["eps_diluted"].round(4),
        "Non-GAAP Diluted EPS": pd.NA,
        "Source": qdf["derived_q4"].map(
            lambda x: "SEC XBRL Q4 derived from 10-K minus Q1-Q3" if x else "SEC XBRL companyfacts"
        ),
    })

    y = qdf.copy()
    y["year"] = pd.to_datetime(y["period_end"]).dt.year
    yearly = y.groupby("year", as_index=False).agg(
        GAAP_Revenue=("revenue", "sum"),
        GAAP_Net_Income=("net_income", "sum"),
        GAAP_Op_Income=("op_income", "sum"),
    )
    for c in ["GAAP_Revenue", "GAAP_Net_Income", "GAAP_Op_Income"]:
        yearly[c] = (yearly[c] / 1e6).round(1)

    overview_path = MU / "MU_Reports_Fiscal_Overview.xlsx"
    metrics_path = MU / "mu_financial_metrics.xlsx"
    extracted_path = MU / "mu_10q_extracted.csv"

    with pd.ExcelWriter(overview_path, engine="openpyxl") as w:
        overview.to_excel(w, sheet_name="Quarterly Summary", index=False)
        yearly.to_excel(w, sheet_name="Yearly Summary", index=False)

    with pd.ExcelWriter(metrics_path, engine="openpyxl") as w:
        qdf.to_excel(w, sheet_name="Quarterly_GAAP", index=False)
        bal = pd.concat([assets, cash], axis=1, sort=True).sort_index().reset_index()
        bal = bal.rename(columns={bal.columns[0]: "period_end"})
        bal.tail(40).to_excel(w, sheet_name="Balance_Snapshot", index=False)

    qdf.to_csv(extracted_path, index=False)
    log(f"[sec] wrote financials quarters={len(qdf)} max={qdf['period_end'].max()}")
    return {
        "overview": overview_path.name,
        "metrics": metrics_path.name,
        "extracted": extracted_path.name,
        "quarters": int(len(qdf)),
    }


def massive_get(path: str, params: dict | None = None) -> dict:
    load_dotenv(ENV_PATH)
    key = os.environ.get("MASSIVE_API_KEY")
    if not key:
        raise RuntimeError("MASSIVE_API_KEY missing")
    url = f"https://api.massive.com{path}"
    r = requests.get(url, headers={"Authorization": f"Bearer {key}"}, params=params or {}, timeout=120)
    if r.status_code == 401:
        params = dict(params or {})
        params["apiKey"] = key
        r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def pull_massive() -> dict:
    out_dir = MU / "mu_massive_data"
    out_dir.mkdir(parents=True, exist_ok=True)
    added = []
    log("[massive] daily aggs MU…")
    data = massive_get(
        f"/v2/aggs/ticker/{TICKER}/range/1/day/2019-01-01/2026-10-21",
        {"adjusted": "true", "sort": "asc", "limit": 50000},
    )
    rows = [{
        "date": datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc).date().isoformat(),
        "open": b.get("o"), "high": b.get("h"), "low": b.get("l"),
        "close": b.get("c"), "volume": b.get("v"), "vwap": b.get("vw"),
        "transactions": b.get("n"),
    } for b in (data.get("results") or [])]
    daily = pd.DataFrame(rows)
    daily.to_csv(out_dir / "history_daily.csv", index=False)
    added.append("history_daily.csv")
    log(f"[massive] daily bars={len(daily)}")
    if not daily.empty:
        cutoff = (pd.Timestamp.today() - pd.Timedelta(days=370)).date().isoformat()
        daily[daily["date"] >= cutoff].to_csv(out_dir / "history_1y.csv", index=False)
        added.append("history_1y.csv")
    wdata = massive_get(
        f"/v2/aggs/ticker/{TICKER}/range/1/week/2019-01-01/2026-10-21",
        {"adjusted": "true", "sort": "asc", "limit": 50000},
    )
    wrows = [{
        "date": datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc).date().isoformat(),
        "open": b.get("o"), "high": b.get("h"), "low": b.get("l"),
        "close": b.get("c"), "volume": b.get("v"), "vwap": b.get("vw"),
    } for b in (wdata.get("results") or [])]
    pd.DataFrame(wrows).to_csv(out_dir / "history_weekly.csv", index=False)
    added.append("history_weekly.csv")
    for label, path in [
        ("ticker_details", f"/v3/reference/tickers/{TICKER}"),
        ("dividends", "/v3/reference/dividends"),
        ("splits", "/v3/reference/splits"),
    ]:
        try:
            params = {"ticker": TICKER, "limit": 100} if label != "ticker_details" else None
            payload = massive_get(path, params)
            (out_dir / f"{label}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            added.append(f"{label}.json")
            log(f"[massive] wrote {label}.json")
        except Exception as e:
            log(f"[massive] optional {label} skipped: {type(e).__name__}: {e}")
    meta = {
        "ticker": TICKER,
        "source": "Massive API (api.massive.com)",
        "auth": "MASSIVE_API_KEY via C:/MegaQuant/.env (not stored here)",
        "pulled_at_utc": datetime.now(timezone.utc).isoformat(),
        "daily_bars": int(len(daily)),
        "weekly_bars": int(len(wrows)),
        "files": added,
    }
    (out_dir / "pull_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def scaffold_notebook() -> str:
    nb_path = MU / "MU_price_prediction_model.ipynb"
    if nb_path.exists():
        return nb_path.name
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# MU Price Prediction Model (scaffold)\n",
                "\n",
                "Memory peer to SNDK. Inputs:\n",
                "- `mu_massive_data/history_daily.csv`\n",
                "- `mu_10q_extracted.csv` / `mu_financial_metrics.xlsx`\n",
                "- Optional: adapt SNDK segment model for DRAM/NAND later\n",
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
                "ROOT = Path(r'C:\\MegaQuant\\Investment Research\\MU')\n",
                "price = pd.read_csv(ROOT/'mu_massive_data'/'history_daily.csv', parse_dates=['date'])\n",
                "fins = pd.read_csv(ROOT/'mu_10q_extracted.csv', parse_dates=['period_end'])\n",
                "print(price.tail()); print(fins.tail())\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
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


def write_helpers() -> list[str]:
    pull = MU / "_pull_massive_data.py"
    pull.write_text(
        '''"""Pull MU OHLCV from Massive. Reads MASSIVE_API_KEY from C:\\\\MegaQuant\\\\.env."""
import os
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import requests
from dotenv import load_dotenv

ENV = Path(r"C:\\MegaQuant\\.env")
OUT = Path(__file__).resolve().parent / "mu_massive_data"
OUT.mkdir(exist_ok=True)
load_dotenv(ENV)
key = os.environ["MASSIVE_API_KEY"]
url = "https://api.massive.com/v2/aggs/ticker/MU/range/1/day/2019-01-01/2026-10-21"
r = requests.get(url, headers={"Authorization": f"Bearer {key}"},
                 params={"adjusted": "true", "sort": "asc", "limit": 50000}, timeout=120)
r.raise_for_status()
rows = [{
    "date": datetime.fromtimestamp(b["t"]/1000, tz=timezone.utc).date().isoformat(),
    "open": b.get("o"), "high": b.get("h"), "low": b.get("l"),
    "close": b.get("c"), "volume": b.get("v"), "vwap": b.get("vw"),
} for b in (r.json().get("results") or [])]
pd.DataFrame(rows).to_csv(OUT / "history_daily.csv", index=False)
print("bars", len(rows))
''',
        encoding="utf-8",
    )
    return [pull.name]


def main():
    MU.mkdir(parents=True, exist_ok=True)
    report = {"ticker": "MU", "started": datetime.now().isoformat()}
    report["pdfs_added"] = download_earnings_pdfs()
    report["financials"] = build_financials()
    report["massive"] = pull_massive()
    report["notebook"] = scaffold_notebook()
    report["helpers"] = write_helpers()
    report["finished"] = datetime.now().isoformat()
    items = []
    for p in sorted(MU.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if p.is_dir():
            n = sum(1 for f in p.rglob("*") if f.is_file())
            items.append(f"DIR {p.name}/ files={n}")
        else:
            items.append(f"FILE {p.name} size={p.stat().st_size}")
    report["inventory_after"] = items
    (MU / "_fill_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
