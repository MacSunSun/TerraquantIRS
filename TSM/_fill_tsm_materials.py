"""Fill TSM research materials toward NVDA/AMD/SNDK parity.
Secrets: MASSIVE_API_KEY from C:\\MegaQuant\\.env only — never hardcode.
TSM is a foreign private issuer (20-F / IFRS); quarterly KPIs come from IR earnings PDFs.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from pypdf import PdfReader

ROOT = Path(r"C:\MegaQuant\Investment Research")
TSM = ROOT / "TSM"
ENV_PATH = Path(r"C:\MegaQuant\.env")
USER_AGENT = "sunjialin sunjialin@terraquant.cn"
CIK = "CIK0001046179"
TICKER = "TSM"

EARNINGS_PDFS = [
    ("2024-04-18", "TSM_Reports_First_Quarter_2024_Financial",
     "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2024-04/e19914dd320b6386af51d5ed27fa5c51af9c441e/1Q24EarningsRelease.pdf"),
    ("2024-07-18", "TSM_Reports_Second_Quarter_2024_Financial",
     "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2024-07/a152eded224aa1b83fdf342ed71d4c42af013915/2Q24EarningsRelease.pdf"),
    ("2024-10-17", "TSM_Reports_Third_Quarter_2024_Financial",
     "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2024-10/d00bfb55ffe01e36f56863f975e88d827f9943e8/3Q24EarningsRelease.pdf"),
    ("2025-01-16", "TSM_Reports_Fourth_Quarter_2024_Financial",
     "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2025-01/cc4e1dec3474f69109d5455fbf8939c3e3cd5a71/4Q24EarningsRelease.pdf"),
    ("2025-04-17", "TSM_Reports_First_Quarter_2025_Financial",
     "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2025-04/6580235c47b7b8f1056b071faa44d958c2c3ba04/1Q25EarningsRelease.pdf"),
    ("2025-07-17", "TSM_Reports_Second_Quarter_2025_Financial",
     "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2025-07/d9d294ed46ca22c560a17eb060373bc35f2d464a/2Q25EarningsRelease.pdf"),
    ("2025-10-16", "TSM_Reports_Third_Quarter_2025_Financial",
     "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2025-10/ff1cf977182dad2178b6d158e61d375ac98ff517/3Q25EarningsRelease.pdf"),
    ("2026-01-15", "TSM_Reports_Fourth_Quarter_2025_Financial",
     "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2026-01/3e49621566a3ca53bdf8aee2586929b666c17fd6/4Q25EarningsRelease.pdf"),
    ("2026-04-16", "TSM_Reports_First_Quarter_2026_Financial",
     "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2026-04/e85216eea8dccd8ca75d7e040e8d57be3ccd618b/1Q26%20EarningsRelease.pdf"),
    ("2026-07-16", "TSM_Reports_Second_Quarter_2026_Financial",
     "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2026-07/a80d7933be643644081584087731f73b22ea5a2c/2Q26%20EarningsRelease.pdf"),
    ("2026-10-15", "TSM_Reports_Third_Quarter_2026_Financial",
     "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2026-10/526b65af7305df2dde6b9ece6812b1fdf1e49f9b/3Q26%20EarningsRelease.pdf"),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def download_earnings_pdfs() -> list[str]:
    added = []
    sess = requests.Session()
    base_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    sess.headers.update(base_headers)
    for date, slug, url in EARNINGS_PDFS:
        out = TSM / f"{date}_{slug}.pdf"
        if out.exists() and out.stat().st_size > 5_000:
            log(f"[pdf] skip exists {out.name}")
            continue
        warm = "https://investor.tsmc.com/english/"
        m = re.search(r"([1234])Q(\d{2})", url)
        if m:
            q, yy = m.group(1), m.group(2)
            year = 2000 + int(yy)
            warm = f"https://investor.tsmc.com/english/quarterly-results/{year}/q{q}"
            try:
                sess.get(warm, timeout=60)
            except Exception as e:
                log(f"[pdf] warm warn {warm}: {e}")
        headers = {
            **base_headers,
            "Referer": warm,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        }
        log(f"[pdf] GET {url}")
        r = sess.get(url, headers=headers, timeout=120, allow_redirects=True)
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            ctype = r.headers.get("Content-Type", "")
            raise RuntimeError(f"Not PDF for {date}: ctype={ctype} bytes={len(r.content)}")
        out.write_bytes(r.content)
        added.append(out.name)
        log(f"[pdf] wrote {out.name} ({len(r.content)} bytes)")
        time.sleep(0.6)
    return added


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_earnings_pdf(path: Path) -> dict:
    reader = PdfReader(str(path))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    text_n = re.sub(r"[ \t]+", " ", text)

    m_end = re.search(
        r"for the (?:first|second|third|fourth) quarter ended ([A-Za-z]+ \d{1,2}, \d{4})",
        text_n, re.I,
    )
    period_end = None
    if m_end:
        period_end = datetime.strptime(m_end.group(1), "%B %d, %Y").date().isoformat()

    m_ann = re.search(r"^([A-Za-z]+ \d{1,2}, \d{4})\s+TSMC", text_n, re.M)
    announce = None
    if m_ann:
        announce = datetime.strptime(m_ann.group(1), "%B %d, %Y").date().isoformat()

    m_rev_nt = re.search(
        r"consolidated revenue of NT\$([0-9,.]+)\s*billion.*?net income of NT\$([0-9,.]+)\s*billion.*?diluted earnings per share of NT\$([0-9,.]+)\s*\(US\$([0-9,.]+)\s*per ADR",
        text_n, re.I | re.S,
    )
    m_rev_us = re.search(
        r"In US dollars,? (?:first|second|third|fourth) quarter revenue was \$([0-9,.]+)\s*billion",
        text_n, re.I,
    )
    m_margins = re.search(
        r"Gross margin for the quarter was ([0-9.]+)%,\s*operating margin was ([0-9.]+)%,\s*and net profit margin was ([0-9.]+)%",
        text_n, re.I,
    )
    m_fq = re.search(r"([1234])Q(\d{2})", path.name)
    fiscal_label = f"Q{m_fq.group(1)} FY20{m_fq.group(2)}" if m_fq else path.stem

    return {
        "Earnings Release Date": announce or path.name[:10],
        "Fiscal Quarter": fiscal_label,
        "Reporting Period End": period_end,
        "Revenue_NTbn": _num(m_rev_nt.group(1)) if m_rev_nt else None,
        "Net_Income_NTbn": _num(m_rev_nt.group(2)) if m_rev_nt else None,
        "EPS_NT": _num(m_rev_nt.group(3)) if m_rev_nt else None,
        "EPS_USD_ADR": _num(m_rev_nt.group(4)) if m_rev_nt else None,
        "Revenue_USDbn": _num(m_rev_us.group(1)) if m_rev_us else None,
        "Gross_Margin_pct": float(m_margins.group(1)) if m_margins else None,
        "Operating_Margin_pct": float(m_margins.group(2)) if m_margins else None,
        "Net_Margin_pct": float(m_margins.group(3)) if m_margins else None,
        "Source": path.name,
        "Accounting": "TIFRS consolidated (earnings release)",
    }


def fetch_sec_annual_ifrs() -> pd.DataFrame | None:
    log("[sec] fetching IFRS companyfacts (annual 20-F)...")
    r = requests.get(
        f"https://data.sec.gov/api/xbrl/companyfacts/{CIK}.json",
        headers={"User-Agent": USER_AGENT},
        timeout=90,
    )
    r.raise_for_status()
    ifrs = r.json()["facts"].get("ifrs-full", {})

    def annual(concept: str, unit: str = "TWD") -> pd.Series:
        if concept not in ifrs or unit not in ifrs[concept]["units"]:
            return pd.Series(dtype=float)
        df = pd.DataFrame(ifrs[concept]["units"][unit])
        if "end" not in df.columns:
            return pd.Series(dtype=float)
        df["end"] = pd.to_datetime(df["end"])
        df["filed"] = pd.to_datetime(df["filed"])
        if "start" in df.columns:
            df["start"] = pd.to_datetime(df["start"])
            df["dur"] = (df["end"] - df["start"]).dt.days
            df = df[df["dur"].between(350, 380) | df["start"].isna()]
        df = df[df["form"].isin(["20-F", "6-K"])]
        df = df.sort_values("filed").drop_duplicates("end", keep="last")
        return df.set_index("end")["val"].astype(float).sort_index()

    rev_twd = annual("Revenue", "TWD")
    rev_usd = annual("Revenue", "USD")
    gp = annual("GrossProfit", "TWD")
    pl = annual("ProfitLoss", "TWD")
    if rev_twd.empty:
        log("[sec] no annual Revenue TWD")
        return None
    out = pd.DataFrame({
        "period_end": rev_twd.index,
        "Revenue_TWD": rev_twd.values,
        "Revenue_USD": rev_usd.reindex(rev_twd.index).values if not rev_usd.empty else None,
        "GrossProfit_TWD": gp.reindex(rev_twd.index).values if not gp.empty else None,
        "ProfitLoss_TWD": pl.reindex(rev_twd.index).values if not pl.empty else None,
    })
    out["Gross_Margin_pct"] = (out["GrossProfit_TWD"] / out["Revenue_TWD"] * 100).round(2)
    out["Source"] = "SEC XBRL ifrs-full (mostly 20-F annual)"
    log(f"[sec] annual rows={len(out)} {out['period_end'].min().date()} -> {out['period_end'].max().date()}")
    return out


def build_financials_from_pdfs() -> dict:
    rows = []
    for pdf in sorted(TSM.glob("*_TSM_Reports_*.pdf")):
        row = parse_earnings_pdf(pdf)
        rows.append(row)
        log(f"[parse] {pdf.name}: rev_usd={row['Revenue_USDbn']} eps_adr={row['EPS_USD_ADR']} gm={row['Gross_Margin_pct']}")
    qdf = pd.DataFrame(rows)
    qdf["Reporting Period End"] = pd.to_datetime(qdf["Reporting Period End"])
    qdf["Earnings Release Date"] = pd.to_datetime(qdf["Earnings Release Date"])
    qdf = qdf.sort_values("Reporting Period End").reset_index(drop=True)

    overview = pd.DataFrame({
        "Earnings Release Date": qdf["Earnings Release Date"],
        "Fiscal Quarter and Fiscal Year": qdf["Fiscal Quarter"],
        "Reporting Period End": qdf["Reporting Period End"],
        "Revenue (US$ bn)": qdf["Revenue_USDbn"],
        "Revenue (NT$ bn)": qdf["Revenue_NTbn"],
        "Gross Margin %": qdf["Gross_Margin_pct"],
        "Operating Margin %": qdf["Operating_Margin_pct"],
        "Net Margin %": qdf["Net_Margin_pct"],
        "Net Income (NT$ bn)": qdf["Net_Income_NTbn"],
        "Diluted EPS (NT$)": qdf["EPS_NT"],
        "Diluted EPS (US$ per ADR)": qdf["EPS_USD_ADR"],
        "Source": qdf["Source"],
        "Accounting": qdf["Accounting"],
    })

    y = qdf.copy()
    y["year"] = y["Reporting Period End"].dt.year
    yearly = y.groupby("year", as_index=False).agg(
        Quarters=("Fiscal Quarter", "count"),
        Revenue_USDbn=("Revenue_USDbn", "sum"),
        Revenue_NTbn=("Revenue_NTbn", "sum"),
        Net_Income_NTbn=("Net_Income_NTbn", "sum"),
        Avg_Gross_Margin_pct=("Gross_Margin_pct", "mean"),
    )
    yearly["Revenue_USDbn"] = yearly["Revenue_USDbn"].round(2)
    yearly["Revenue_NTbn"] = yearly["Revenue_NTbn"].round(2)
    yearly["Net_Income_NTbn"] = yearly["Net_Income_NTbn"].round(2)
    yearly["Avg_Gross_Margin_pct"] = yearly["Avg_Gross_Margin_pct"].round(1)
    yearly["Note"] = "Sum of available quarters in folder (may be incomplete year)"

    annual_sec = fetch_sec_annual_ifrs()

    overview_path = TSM / "TSM_Reports_Fiscal_Overview.xlsx"
    metrics_path = TSM / "tsm_financial_metrics.xlsx"
    extracted_path = TSM / "tsm_earnings_extracted.csv"

    with pd.ExcelWriter(overview_path, engine="openpyxl") as w:
        overview.to_excel(w, sheet_name="Quarterly Summary", index=False)
        yearly.to_excel(w, sheet_name="Yearly Summary (from qtrs)", index=False)
        if annual_sec is not None and not annual_sec.empty:
            annual_sec.to_excel(w, sheet_name="SEC 20-F Annual IFRS", index=False)

    with pd.ExcelWriter(metrics_path, engine="openpyxl") as w:
        qdf.to_excel(w, sheet_name="Quarterly_IR", index=False)
        if annual_sec is not None and not annual_sec.empty:
            annual_sec.to_excel(w, sheet_name="Annual_SEC_IFRS", index=False)

    qdf.to_csv(extracted_path, index=False)
    log(f"[fin] wrote overview/metrics/csv quarters={len(qdf)}")
    return {
        "overview": overview_path.name,
        "metrics": metrics_path.name,
        "extracted": extracted_path.name,
        "quarters": int(len(qdf)),
        "sec_annual_rows": int(len(annual_sec)) if annual_sec is not None else 0,
    }


def massive_get(path: str, params: dict | None = None) -> dict:
    load_dotenv(ENV_PATH)
    key = os.environ.get("MASSIVE_API_KEY")
    if not key:
        raise RuntimeError("MASSIVE_API_KEY missing in C:\\MegaQuant\\.env")
    url = f"https://api.massive.com{path}"
    r = requests.get(url, headers={"Authorization": f"Bearer {key}"}, params=params or {}, timeout=120)
    if r.status_code == 401:
        params = dict(params or {})
        params["apiKey"] = key
        r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def pull_massive() -> dict:
    out_dir = TSM / "tsm_massive_data"
    out_dir.mkdir(parents=True, exist_ok=True)
    added = []

    log("[massive] daily aggs TSM...")
    data = massive_get(
        f"/v2/aggs/ticker/{TICKER}/range/1/day/2019-01-01/2026-10-21",
        {"adjusted": "true", "sort": "asc", "limit": 50000},
    )
    results = data.get("results") or []
    rows = []
    for b in results:
        rows.append({
            "date": datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc).date().isoformat(),
            "open": b.get("o"), "high": b.get("h"), "low": b.get("l"),
            "close": b.get("c"), "volume": b.get("v"), "vwap": b.get("vw"),
            "transactions": b.get("n"),
        })
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
        "note": "NYSE ADR (each ADS = 5 common shares)",
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
    nb_path = TSM / "TSM_price_prediction_model.ipynb"
    if nb_path.exists():
        log(f"[nb] exists {nb_path.name}")
        return nb_path.name
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# TSM Price Prediction Model (scaffold)\n",
                "\n",
                "Foreign issuer (20-F / TIFRS). Prefer IR quarterly extracts + Massive ADR prices.\n",
                "- `tsm_massive_data/history_daily.csv`\n",
                "- `tsm_earnings_extracted.csv`\n",
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
                "ROOT = Path(r'C:\\MegaQuant\\Investment Research\\TSM')\n",
                "price = pd.read_csv(ROOT / 'tsm_massive_data' / 'history_daily.csv', parse_dates=['date'])\n",
                "fins = pd.read_csv(ROOT / 'tsm_earnings_extracted.csv', parse_dates=['Reporting Period End'])\n",
                "print(price.tail()); print(fins.tail())\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# TODO: map quarterly Revenue_USDbn / margins to forward ADR returns\n",
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
    pull = TSM / "_pull_massive_data.py"
    pull.write_text(
        '''"""Pull TSM OHLCV from Massive. Reads MASSIVE_API_KEY from C:\\\\MegaQuant\\\\.env."""
import os
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import requests
from dotenv import load_dotenv

ENV = Path(r"C:\\MegaQuant\\.env")
OUT = Path(__file__).resolve().parent / "tsm_massive_data"
OUT.mkdir(exist_ok=True)
load_dotenv(ENV)
key = os.environ["MASSIVE_API_KEY"]
url = "https://api.massive.com/v2/aggs/ticker/TSM/range/1/day/2019-01-01/2026-10-21"
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
    return [pull.name]


def main():
    TSM.mkdir(parents=True, exist_ok=True)
    report = {"ticker": "TSM", "started": datetime.now().isoformat()}
    report["pdfs_added"] = download_earnings_pdfs()
    report["financials"] = build_financials_from_pdfs()
    report["massive"] = pull_massive()
    report["notebook"] = scaffold_notebook()
    report["helpers"] = write_helpers()
    report["finished"] = datetime.now().isoformat()
    items = []
    for p in sorted(TSM.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if p.is_dir():
            n = sum(1 for f in p.rglob("*") if f.is_file())
            items.append(f"DIR {p.name}/ files={n}")
        else:
            items.append(f"FILE {p.name} size={p.stat().st_size}")
    report["inventory_after"] = items
    (TSM / "_fill_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
