"""Fill INTC research materials + backfill missing 10-Ks.
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
INTC = ROOT / "INTC"
ENV_PATH = Path(r"C:\MegaQuant\.env")
USER_AGENT = "sunjialin sunjialin@terraquant.cn"
CIK = "CIK0000050863"
CIK_N = "50863"
TICKER = "INTC"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
FILINGS_10K_DIR = INTC / "10Q_10K" / "intc" / "10-K"

# Missing recent 10-Ks vs SEC submissions (local currently has 2018,2019,2023,2025,2026 only)
MISSING_10K = [
    # (accession, primary_doc_hint for logging)
    ("0000050863-20-000011", "FY2019"),
    ("0000050863-21-000010", "FY2020"),
    ("0000050863-22-000007", "FY2021"),
    ("0000050863-24-000010", "FY2023"),
]

# Prefer official Intel PDFs when known; else SEC 8-K Ex.99.1 -> Edge PDF
# (announce_date, slug, kind, url_or_acc_exhibit)
# kind: 'pdf_url' | 'sec_ex99'
EARNINGS = [
    ("2023-10-26", "INTC_Reports_Third_Quarter_2023_Financial", "sec", "0000050863-23-000066"),
    ("2024-01-25", "INTC_Reports_Fourth_Quarter_and_Full_Year_2023", "sec", "0000050863-24-000007"),
    ("2024-04-25", "INTC_Reports_First_Quarter_2024_Financial", "sec", "0000050863-24-000054"),
    ("2024-08-01", "INTC_Reports_Second_Quarter_2024_Financial", "sec", "0000050863-24-000105"),
    ("2024-10-31", "INTC_Reports_Third_Quarter_2024_Financial", "sec", "0000050863-24-000135"),
    ("2025-01-30", "INTC_Reports_Fourth_Quarter_and_Full_Year_2024", "pdf",
     "https://download.intel.com/newsroom/2025/c8e6h3a2/intel-q4-2024y-earnings.pdf"),
    ("2025-04-24", "INTC_Reports_First_Quarter_2025_Financial", "pdf",
     "https://download.intel.com/newsroom/2025/corporate/67s2p/Intel-1Q2025-Earnings.pdf"),
    ("2025-07-24", "INTC_Reports_Second_Quarter_2025_Financial", "pdf",
     "https://download.intel.com/newsroom/2025/corporate/29r29Xn/Intel-2Q2025-Earnings.pdf"),
    ("2025-10-23", "INTC_Reports_Third_Quarter_2025_Financial", "sec", "0000050863-25-000169"),
    ("2026-01-22", "INTC_Reports_Fourth_Quarter_and_Full_Year_2025", "sec", "0000050863-26-000009"),
    ("2026-04-23", "INTC_Reports_First_Quarter_2026_Financial", "sec", "0000050863-26-000077"),
    ("2026-07-23", "INTC_Reports_Second_Quarter_2026_Financial", "sec", "0000050863-26-000155"),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def sess() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def backfill_10k() -> dict:
    """Download missing 10-K full-submission .txt into 10Q_10K/intc/10-K/."""
    FILINGS_10K_DIR.mkdir(parents=True, exist_ok=True)
    s = sess()
    added, skipped = [], []
    for acc, label in MISSING_10K:
        out = FILINGS_10K_DIR / f"{acc}.txt"
        if out.exists() and out.stat().st_size > 50_000:
            skipped.append(out.name)
            log(f"[10k] skip exists {out.name} ({label})")
            continue
        accn = acc.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{CIK_N}/{accn}/{acc}.txt"
        log(f"[10k] GET {url} ({label})")
        r = s.get(url, timeout=180)
        r.raise_for_status()
        out.write_bytes(r.content)
        added.append({"file": out.name, "label": label, "bytes": len(r.content)})
        log(f"[10k] wrote {out.name} ({len(r.content)} bytes)")
        time.sleep(0.4)
    # rebuild filing_index
    index = rebuild_filing_index()
    return {"added": added, "skipped": skipped, "index_rows": len(index), "index_10k": int((index["form"] == "10-K").sum())}


def _parse_header(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")[:8000]

    def grab(pattern: str):
        m = re.search(pattern, text)
        return m.group(1).strip() if m else None

    period = grab(r"CONFORMED PERIOD OF REPORT:\s*(\d+)")
    filed = grab(r"FILED AS OF DATE:\s*(\d+)")
    return {
        "ticker": "INTC",
        "accession": grab(r"ACCESSION NUMBER:\s*(\S+)"),
        "form": grab(r"CONFORMED SUBMISSION TYPE:\s*(\S+)"),
        "period_end": pd.to_datetime(period, format="%Y%m%d") if period else pd.NaT,
        "filed_date": pd.to_datetime(filed, format="%Y%m%d") if filed else pd.NaT,
        "file_path": str(path),
    }


def rebuild_filing_index() -> pd.DataFrame:
    base = INTC / "10Q_10K" / "intc"
    rows = []
    if base.exists():
        for form_dir in sorted(base.iterdir()):
            if not form_dir.is_dir():
                continue
            for path in sorted(form_dir.glob("*.txt")):
                rows.append(_parse_header(path))
    index = pd.DataFrame(rows)
    if not index.empty:
        index = index.sort_values(["form", "filed_date", "accession"], na_position="last").reset_index(drop=True)
    out = INTC / "filing_index.csv"
    index.to_csv(out, index=False)
    log(f"[index] wrote {out.name} rows={len(index)} 10-K={(index['form']=='10-K').sum() if len(index) else 0}")
    return index


def find_ex99(acc: str, s: requests.Session) -> str | None:
    accn = acc.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{CIK_N}/{accn}/{acc}-index.htm"
    r = s.get(url, timeout=60)
    r.raise_for_status()
    # prefer press release / earnings exhibit 99.1
    cands = re.findall(r'href="(/Archives/edgar/data/%s/[^"]+)"' % CIK_N, r.text, re.I)
    # also relative hrefs
    rel = re.findall(r'href="([^"]+\.(?:htm|html|pdf))"', r.text, re.I)
    names = []
    for h in cands + rel:
        name = h.split("/")[-1]
        low = name.lower()
        if "99" in low or "ex99" in low or "exhibit99" in low or "earnings" in low or "press" in low:
            if h.startswith("/"):
                names.append("https://www.sec.gov" + h)
            elif h.startswith("http"):
                names.append(h)
            else:
                names.append(f"https://www.sec.gov/Archives/edgar/data/{CIK_N}/{accn}/{name}")
    # prioritize 99.1
    names = sorted(set(names), key=lambda u: (0 if "991" in u.lower() or "99-1" in u.lower() or "99_1" in u.lower() else 1, u))
    return names[0] if names else None


def download_earnings_pdfs() -> list[str]:
    added = []
    s = sess()
    html_dir = INTC / "_earnings_html"
    html_dir.mkdir(parents=True, exist_ok=True)

    # verify/adjust SEC accessions against submissions by date
    sub = s.get(f"https://data.sec.gov/submissions/{CIK}.json", timeout=60).json()
    rec = sub["filings"]["recent"]
    by_date = {}
    for i, form in enumerate(rec["form"]):
        if form in ("8-K", "8-K/A"):
            by_date.setdefault(rec["filingDate"][i], []).append(rec["accessionNumber"][i])

    for date, slug, kind, ref in EARNINGS:
        out_pdf = INTC / f"{date}_{slug}.pdf"
        if out_pdf.exists() and out_pdf.stat().st_size > 5_000:
            log(f"[pdf] skip exists {out_pdf.name}")
            continue

        if kind == "pdf":
            log(f"[pdf] GET {ref}")
            r = s.get(ref, timeout=120, headers={**s.headers, "Accept": "application/pdf,*/*"})
            r.raise_for_status()
            if not r.content.startswith(b"%PDF"):
                raise RuntimeError(f"Not PDF: {ref} ctype={r.headers.get('Content-Type')} bytes={len(r.content)}")
            out_pdf.write_bytes(r.content)
            added.append(out_pdf.name)
            log(f"[pdf] wrote {out_pdf.name} ({len(r.content)} bytes)")
            time.sleep(0.3)
            continue

        # sec 8-K exhibit
        acc = ref
        if date in by_date and acc not in by_date[date]:
            # prefer accession from that date if our guess wrong
            acc = by_date[date][0]
            log(f"[pdf] accession adjusted for {date}: {acc}")
        ex_url = find_ex99(acc, s)
        if not ex_url:
            raise RuntimeError(f"No ex99 for {date} {acc}")
        log(f"[html] GET {ex_url}")
        r = s.get(ex_url, timeout=120)
        r.raise_for_status()
        if ex_url.lower().endswith(".pdf") and r.content.startswith(b"%PDF"):
            out_pdf.write_bytes(r.content)
        else:
            html_path = html_dir / f"{date}_{slug}.htm"
            html_path.write_bytes(r.content)
            cmd = [
                EDGE, "--headless", "--disable-gpu",
                f"--print-to-pdf={out_pdf}", "--no-pdf-header-footer",
                html_path.resolve().as_uri(),
            ]
            log(f"[pdf] edge print {out_pdf.name}")
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if not out_pdf.exists() or out_pdf.stat().st_size < 1000:
                raise RuntimeError(f"PDF failed {slug}: rc={proc.returncode} {proc.stderr[-300:]}")
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

    concepts = {
        "revenue": "RevenueFromContractWithCustomerExcludingAssessedTax",
        "gross_profit": "GrossProfit",
        "op_income": "OperatingIncomeLoss",
        "net_income": "NetIncomeLoss",
        "eps_diluted": "EarningsPerShareDiluted",
    }
    # only include opex if present
    if "OperatingExpenses" in gaap:
        concepts["op_expenses"] = "OperatingExpenses"

    qtr = {k: flow_qtr(gaap, c, k, unit_pref=("USD/shares" if k == "eps_diluted" else None)) for k, c in concepts.items()}
    ann = {k: flow_annual(gaap, c, k, unit_pref=("USD/shares" if k == "eps_diluted" else None)) for k, c in concepts.items()}

    derived_rows = []
    existing = set(pd.to_datetime(df["period_end"]).dt.normalize())
    for end, _ in ann.get("revenue", pd.Series(dtype=float)).items():
        if any(abs((e - end).days) <= 10 for e in existing):
            continue
        qs = qtr["revenue"][(qtr["revenue"].index > end - pd.Timedelta(days=400)) & (qtr["revenue"].index < end)].sort_index().tail(3)
        if len(qs) < 3:
            continue
        row = {"period_end": end, "derived_q4": True}
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
        if not ok:
            continue
        row["gross_margin"] = row["gross_profit"] / row["revenue"] if row.get("revenue") else None
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
    qdf["op_expenses_musd"] = (pd.to_numeric(qdf.get("op_expenses"), errors="coerce") / 1e6).round(1)
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
            lambda x: "SEC XBRL Q4 derived from 10-K minus Q1-Q3" if bool(x) else "SEC XBRL companyfacts"
        ),
    })

    overview_path = INTC / "INTC_Reports_Fiscal_Overview.xlsx"
    metrics_path = INTC / "intc_financial_metrics.xlsx"
    extracted_path = INTC / "intc_10q_extracted.csv"

    with pd.ExcelWriter(overview_path, engine="openpyxl") as w:
        overview.to_excel(w, sheet_name="Quarterly Summary", index=False)

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
    out_dir = INTC / "intc_massive_data"
    out_dir.mkdir(parents=True, exist_ok=True)
    added = []
    log("[massive] daily aggs INTC…")
    data = massive_get(
        f"/v2/aggs/ticker/{TICKER}/range/1/day/2019-01-01/2026-10-22",
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
        f"/v2/aggs/ticker/{TICKER}/range/1/week/2019-01-01/2026-10-22",
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
    nb_path = INTC / "INTC_price_prediction_model.ipynb"
    if nb_path.exists():
        return nb_path.name
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# INTC Price Prediction Model (scaffold)\n",
                "\n",
                "- `intc_massive_data/history_daily.csv`\n",
                "- `intc_10q_extracted.csv`\n",
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
                "ROOT = Path(r'C:\\MegaQuant\\Investment Research\\INTC')\n",
                "price = pd.read_csv(ROOT/'intc_massive_data'/'history_daily.csv', parse_dates=['date'])\n",
                "fins = pd.read_csv(ROOT/'intc_10q_extracted.csv', parse_dates=['period_end'])\n",
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
    pull = INTC / "_pull_massive_data.py"
    pull.write_text(
        '''"""Pull INTC OHLCV from Massive. Reads MASSIVE_API_KEY from C:\\\\MegaQuant\\\\.env."""
import os
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import requests
from dotenv import load_dotenv

ENV = Path(r"C:\\MegaQuant\\.env")
OUT = Path(__file__).resolve().parent / "intc_massive_data"
OUT.mkdir(exist_ok=True)
load_dotenv(ENV)
key = os.environ["MASSIVE_API_KEY"]
url = "https://api.massive.com/v2/aggs/ticker/INTC/range/1/day/2019-01-01/2026-10-22"
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
    INTC.mkdir(parents=True, exist_ok=True)
    report = {"ticker": "INTC", "started": datetime.now().isoformat()}
    report["10k_backfill"] = backfill_10k()
    report["pdfs_added"] = download_earnings_pdfs()
    report["financials"] = build_financials()
    report["massive"] = pull_massive()
    report["notebook"] = scaffold_notebook()
    report["helpers"] = write_helpers()
    report["finished"] = datetime.now().isoformat()
    items = []
    for p in sorted(INTC.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if p.is_dir():
            n = sum(1 for f in p.rglob("*") if f.is_file())
            items.append(f"DIR {p.name}/ files={n}")
        else:
            items.append(f"FILE {p.name} size={p.stat().st_size}")
    report["inventory_after"] = items
    k10 = list((INTC / "10Q_10K" / "intc" / "10-K").glob("*.txt"))
    report["10k_count_after"] = len(k10)
    report["10k_files_after"] = sorted(x.name for x in k10)
    (INTC / "_fill_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
