"""
core/price_data.py — market data via Futu OpenD (富途本地行情网关)

Requirements:
  • Futu OpenD desktop app running on localhost:11111
  • pip install futu-api

Ticker format mapping:
  AMD, NVDA, TSM … → US.AMD, US.NVDA, US.TSM
  0992.HK          → HK.00992
  005930.KS        → not supported (Korean exchange)
  2454.TW          → not supported (Taiwan exchange)
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from futu import AuType, KLType, OpenQuoteContext, RET_OK

FUTU_HOST = "127.0.0.1"
FUTU_PORT = 11111


# ── Ticker conversion ─────────────────────────────────────────────────────────

def to_futu_code(ticker: str) -> str | None:
    """Convert a standard ticker symbol to Futu code format."""
    ticker = ticker.strip()
    if ticker.endswith(".HK"):
        num = ticker[: -3]
        return f"HK.{num.zfill(5)}"
    if ticker.endswith(".KS") or ticker.endswith(".TW"):
        return None   # KRX / TWSE not supported
    if "." in ticker:
        return None   # Unknown exchange suffix
    return f"US.{ticker}"


def _open() -> OpenQuoteContext | None:
    """Open a Futu quote context; return None if OpenD is unavailable."""
    try:
        return OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
    except Exception:
        return None


# ── Price history ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_price_history(ticker: str, period: str = "3y") -> pd.DataFrame:
    """
    Daily OHLCV history (前复权 QFQ) from Futu OpenD.
    Returns a DataFrame indexed by date with columns Open/High/Low/Close/Volume.
    """
    code = to_futu_code(ticker)
    if not code:
        return pd.DataFrame()

    years = int(period.replace("y", "")) if period.endswith("y") else 3
    start = (datetime.today() - timedelta(days=years * 366)).strftime("%Y-%m-%d")
    end   = datetime.today().strftime("%Y-%m-%d")

    ctx = _open()
    if ctx is None:
        return pd.DataFrame()

    try:
        chunks = []
        page_key = None
        while True:
            if page_key is None:
                ret, data, page_key = ctx.request_history_kline(
                    code, start=start, end=end,
                    ktype=KLType.K_DAY,
                    autype=AuType.QFQ,
                    max_count=1000,
                )
            else:
                ret, data, page_key = ctx.request_history_kline(
                    code, start=start, end=end,
                    ktype=KLType.K_DAY,
                    autype=AuType.QFQ,
                    max_count=1000,
                    page_req_key=page_key,
                )
            if ret != RET_OK or data is None or data.empty:
                break
            chunks.append(data)
            if page_key is None:
                break

        if not chunks:
            return pd.DataFrame()

        df = pd.concat(chunks, ignore_index=True)
        df["time_key"] = pd.to_datetime(df["time_key"])
        df = df.set_index("time_key").sort_index()
        df.index.name = "Date"
        df = df.rename(columns={
            "open": "Open", "high": "High",
            "low":  "Low",  "close": "Close", "volume": "Volume",
        })
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna()

    except Exception:
        return pd.DataFrame()
    finally:
        ctx.close()


# ── Real-time snapshot & company info ─────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def get_snapshot(ticker: str) -> dict:
    """Return a single-row dict from Futu market snapshot."""
    code = to_futu_code(ticker)
    if not code:
        return {}
    ctx = _open()
    if ctx is None:
        return {}
    try:
        ret, data = ctx.get_market_snapshot([code])
        if ret != RET_OK or data is None or data.empty:
            return {}
        return data.iloc[0].to_dict()
    except Exception:
        return {}
    finally:
        ctx.close()


@st.cache_data(ttl=3600, show_spinner=False)
def get_info(ticker: str) -> dict:
    """Mimic the yfinance info dict shape for backward compatibility."""
    snap = get_snapshot(ticker)
    if not snap:
        return {}
    return {
        "longName":        snap.get("name", ticker),
        "symbol":          ticker,
        "marketCap":       snap.get("total_market_val"),
        "trailingPE":      snap.get("pe_ttm_ratio"),
        "priceToBook":     snap.get("pb_ratio"),
        "trailingEps":     snap.get("earning_per_share"),
        "dividendYield":   snap.get("dividend_ratio_ttm"),
        "fiftyTwoWeekHigh": snap.get("highest52weeks_price"),
        "fiftyTwoWeekLow":  snap.get("lowest52weeks_price"),
        "currentPrice":    snap.get("last_price"),
        "beta":            None,   # not provided by Futu snapshot
    }


# ── Quarterly returns (derived from daily prices) ────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_quarterly_returns(ticker: str) -> pd.Series:
    """Quarterly close-to-close price returns derived from daily history."""
    px = get_price_history(ticker, period="5y")
    if px.empty:
        return pd.Series(dtype=float)
    q = px["Close"].resample("QE").last()
    return q.pct_change().dropna()


# ── Key metrics display dict ──────────────────────────────────────────────────

def _fmt(val, fmt: str = "{:.2f}", suffix: str = "") -> str:
    if val is None:
        return "N/A"
    try:
        return fmt.format(float(val)) + suffix
    except Exception:
        return "N/A"


def _fmt_bn(val) -> str:
    """Format a large number in billions."""
    if val is None:
        return "N/A"
    try:
        v = float(val)
        if abs(v) >= 1e12:
            return f"{v/1e12:.2f} T"
        if abs(v) >= 1e9:
            return f"{v/1e9:.2f} B"
        if abs(v) >= 1e6:
            return f"{v/1e6:.2f} M"
        return str(v)
    except Exception:
        return "N/A"


def key_metrics(ticker: str) -> dict:
    """Return a formatted dict of key metrics for display as st.metric cards."""
    snap = get_snapshot(ticker)
    if not snap:
        return {"状态": "Futu OpenD 未连接或数据不可用"}

    return {
        "最新价":        _fmt(snap.get("last_price"), "{:.2f}", " USD"),
        "市值":          _fmt_bn(snap.get("total_market_val")),
        "PE (TTM)":      _fmt(snap.get("pe_ttm_ratio"), "{:.1f}"),
        "PB":            _fmt(snap.get("pb_ratio"), "{:.2f}"),
        "EPS":           _fmt(snap.get("earning_per_share"), "{:.2f}", " USD"),
        "股息率 (TTM)":  _fmt(snap.get("dividend_ratio_ttm"), "{:.2f}", "%"),
        "52W 高":        _fmt(snap.get("highest52weeks_price"), "{:.2f}", " USD"),
        "52W 低":        _fmt(snap.get("lowest52weeks_price"), "{:.2f}", " USD"),
        "换手率":        _fmt(snap.get("turnover_rate"), "{:.2f}", "%"),
        "量比":          _fmt(snap.get("volume_ratio"), "{:.2f}"),
        "每股净资产":    _fmt(snap.get("net_asset_per_share"), "{:.2f}", " USD"),
        "涨跌幅":        _fmt(snap.get("change_rate",
                             snap.get("amplitude")), "{:.2f}", "%"),
    }
