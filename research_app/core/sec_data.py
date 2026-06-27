"""SEC EDGAR XBRL data fetching with Streamlit caching."""
from __future__ import annotations

import requests
import pandas as pd
import streamlit as st

USER_AGENT = "sunjialin sunjialin@terraquant.cn"


@st.cache_data(ttl=3600 * 12, show_spinner=False)
def get_gaap_facts(cik: str) -> dict:
    """Download all GAAP XBRL facts from SEC EDGAR company-facts API."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/{cik}.json"
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        r.raise_for_status()
        return r.json().get("facts", {}).get("us-gaap", {})
    except Exception:
        return {}


def _flow_qtr(gaap: dict, concept: str) -> pd.Series:
    """Extract standalone single-quarter values (duration 70–105 days)."""
    if concept not in gaap:
        return pd.Series(dtype=float)
    uk = "USD" if "USD" in gaap[concept]["units"] else next(iter(gaap[concept]["units"]))
    df = pd.DataFrame(gaap[concept]["units"][uk])
    if "start" not in df.columns:
        return pd.Series(dtype=float)
    df["start"] = pd.to_datetime(df["start"])
    df["end"]   = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    df["dur"]   = (df["end"] - df["start"]).dt.days
    q = df[df["form"].isin(["10-Q", "10-K"]) & df["dur"].between(70, 105)].copy()
    return (q.sort_values("filed")
             .drop_duplicates("end", keep="last")
             .set_index("end")["val"]
             .sort_index()
             .astype(float))


def _stock_qtr(gaap: dict, concept: str) -> pd.Series:
    """Extract point-in-time balance-sheet values."""
    if concept not in gaap:
        return pd.Series(dtype=float)
    uk = "USD" if "USD" in gaap[concept]["units"] else next(iter(gaap[concept]["units"]))
    df = pd.DataFrame(gaap[concept]["units"][uk])
    df["end"]   = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    q = df[df["form"].isin(["10-Q", "10-K"])].copy()
    return (q.sort_values("filed")
             .drop_duplicates("end", keep="last")
             .set_index("end")["val"]
             .sort_index()
             .astype(float))


@st.cache_data(ttl=3600 * 12, show_spinner=False)
def get_quarterly_financials(cik: str) -> pd.DataFrame:
    """
    Return a quarterly DataFrame with key income-statement and balance-sheet metrics.
    Columns: revenue, gross_profit, op_income, net_income, eps_dil, rd_exp,
             cash, equity, total_assets, shares_dil
    """
    gaap = get_gaap_facts(cik)
    if not gaap:
        return pd.DataFrame()

    revenue = (
        _flow_qtr(gaap, "RevenueFromContractWithCustomerExcludingAssessedTax")
        .combine_first(_flow_qtr(gaap, "SalesRevenueNet"))
        .combine_first(_flow_qtr(gaap, "Revenues"))
    )

    df = pd.DataFrame({
        "revenue":      revenue,
        "gross_profit": _flow_qtr(gaap, "GrossProfit"),
        "op_income":    _flow_qtr(gaap, "OperatingIncomeLoss"),
        "net_income":   _flow_qtr(gaap, "NetIncomeLoss"),
        "eps_dil":      _flow_qtr(gaap, "EarningsPerShareDiluted"),
        "rd_exp":       _flow_qtr(gaap, "ResearchAndDevelopmentExpense"),
        "shares_dil":   _flow_qtr(gaap, "WeightedAverageNumberOfDilutedSharesOutstanding"),
        "cash":         _stock_qtr(gaap, "CashAndCashEquivalentsAtCarryingValue"),
        "equity":       _stock_qtr(gaap, "StockholdersEquity"),
        "total_assets": _stock_qtr(gaap, "Assets"),
    })
    df.index = pd.to_datetime(df.index)
    df = df[df["revenue"].notna()].sort_index()

    # Derived metrics
    df["gross_margin"] = df["gross_profit"] / df["revenue"]
    df["op_margin"]    = df["op_income"]    / df["revenue"]
    df["net_margin"]   = df["net_income"]   / df["revenue"]
    df["rev_yoy"]      = df["revenue"].pct_change(4)
    df["eps_yoy"]      = df["eps_dil"].pct_change(4)

    return df


@st.cache_data(ttl=3600 * 24, show_spinner=False)
def get_recent_filings(cik: str, n: int = 10) -> pd.DataFrame:
    """Return the most recent SEC filings for a company."""
    clean_cik = cik.replace("CIK", "").lstrip("0")
    url = f"https://data.sec.gov/submissions/CIK{clean_cik.zfill(10)}.json"
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        r.raise_for_status()
        data = r.json()
        recent = data.get("filings", {}).get("recent", {})
        df = pd.DataFrame({
            "form":   recent.get("form", []),
            "filed":  recent.get("filingDate", []),
            "period": recent.get("reportDate", []),
            "accession": recent.get("accessionNumber", []),
        })
        df = df[df["form"].isin(["10-K", "10-Q", "8-K"])].head(n)
        df["edgar_url"] = df["accession"].apply(
            lambda a: f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={clean_cik}&type={''}&dateb=&owner=include&count=10"
        )
        return df.reset_index(drop=True)
    except Exception:
        return pd.DataFrame()
