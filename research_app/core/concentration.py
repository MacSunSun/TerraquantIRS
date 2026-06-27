"""
core/concentration.py
Extract from SEC 10-K filings:
  1. Segment revenue breakdown  (regex on MD&A table)
  2. Customer / supplier concentration %  (regex on risk / notes)

Works with:
  - Local .txt files already downloaded (e.g. AMD)
  - Any company with a CIK: fetches latest 10-K from SEC EDGAR on-the-fly
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from core.text_mining import _extract_main_doc

USER_AGENT = "research-app contact@example.com"

# ── Known segment name sets (add more companies here) ────────────────────────
KNOWN_SEGMENTS: dict[str, list[str]] = {
    "AMD":  ["Data Center", "Client", "Gaming", "Embedded"],
    "NVDA": ["Data Center", "Gaming", "Professional Visualization",
             "Automotive", "OEM & Other"],
    "INTC": ["CCG", "DCG", "IOTG", "Mobileye", "PSG", "NEX", "Intel Foundry"],
    "QCOM": ["QCT", "QTL"],
    "AVGO": ["Semiconductor Solutions", "Infrastructure Software"],
    "TSM":  ["Advanced", "Specialty Technology"],
}


# ── SEC EDGAR helpers ─────────────────────────────────────────────────────────

def _cik_padded(cik: str) -> str:
    return cik.replace("CIK", "").lstrip("0").zfill(10)


@st.cache_data(ttl=3600 * 24, show_spinner=False)
def _fetch_latest_10k_text(cik: str) -> str:
    """Download the most recent 10-K filing text from SEC EDGAR."""
    cik_pad = _cik_padded(cik)
    url = f"https://data.sec.gov/submissions/CIK{cik_pad}.json"
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    if r.status_code != 200:
        return ""
    sub = r.json()

    # Find the most recent 10-K accession number
    filings = sub.get("filings", {}).get("recent", {})
    forms   = filings.get("form", [])
    accns   = filings.get("accessionNumber", [])
    docs    = filings.get("primaryDocument", [])
    for form, accn, doc in zip(forms, accns, docs):
        if form == "10-K":
            accn_fmt = accn.replace("-", "")
            cik_num  = cik.replace("CIK", "").lstrip("0")
            doc_url  = (f"https://www.sec.gov/Archives/edgar/data/"
                        f"{cik_num}/{accn_fmt}/{doc}")
            try:
                time.sleep(0.25)
                resp = requests.get(doc_url, headers={"User-Agent": USER_AGENT},
                                    timeout=30)
                if resp.status_code == 200:
                    return resp.text
            except Exception:
                pass
            break
    return ""


def _get_10k_text(cik: str, local_dir: Path | None = None) -> str:
    """
    Get 10-K text: prefer local files, fall back to SEC EDGAR download.
    local_dir: folder containing *.txt SEC filings for this company.
    """
    if local_dir and local_dir.exists():
        def _accn_year(f: Path) -> int:
            # Accession format: XXXXXXXXXX-YY-NNNNNN  (YY = 2-digit year)
            parts = f.stem.split("-")
            if len(parts) >= 2:
                yy = int(parts[1])
                return (1900 + yy) if yy >= 93 else (2000 + yy)
            return 0

        files = sorted(local_dir.glob("*.txt"), key=_accn_year)
        if files:
            return files[-1].read_text(encoding="utf-8", errors="ignore")
    if cik:
        return _fetch_latest_10k_text(cik)
    return ""


# ── Segment revenue extraction ────────────────────────────────────────────────

def _parse_segments(text: str, segments: list[str]) -> pd.DataFrame:
    """
    Find the annual segment revenue table in MD&A.
    Returns DataFrame: segment | fy_current | fy_prev1 | fy_prev2 (all in $M)
    """
    rows = []
    seen: set[str] = set()
    for seg in segments:
        # Match: "Data Center   $ 16,635   $ 12,579   $ 6,496"
        # or    "Data Center     16,635    12,579     6,496"
        pat = re.compile(
            rf'{re.escape(seg)}\s+\$?\s*([\d,]+)\s+\$?\s*([\d,]+)\s+\$?\s*([\d,]+)',
            re.IGNORECASE,
        )
        m = pat.search(text)
        if m and seg not in seen:
            seen.add(seg)
            vals = [int(v.replace(",", "")) for v in m.groups()]
            rows.append({"segment": seg, "fy0": vals[0], "fy1": vals[1], "fy2": vals[2]})

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _infer_fy_years(text: str) -> tuple[int, int, int]:
    """
    Return the three fiscal years covered by this 10-K (most-recent first).
    Prioritises 'year(s) ended … YYYY' which uniquely identifies data years.
    """
    import datetime
    from collections import Counter

    candidates: set[int] = set()

    # Most reliable: "year ended December 27, 2025"  /  "years ended Dec 28, 2024"
    for m in re.finditer(
        r'years?\s+ended\s+\w+\.?\s+\d{1,2},\s+(20[012]\d)', text[:400_000], re.IGNORECASE
    ):
        candidates.add(int(m.group(1)))

    if len(candidates) >= 3:
        unique = sorted(candidates, reverse=True)
        return unique[0], unique[1], unique[2]

    # Second priority: "fiscal year 2025" but filter out forward-looking > filing year
    # (filing year ≈ max year seen in "year ended" + 1)
    filing_yr = max(candidates) + 1 if candidates else datetime.date.today().year
    for m in re.finditer(r'fiscal\s+years?\s+(20[012]\d)', text[:400_000], re.IGNORECASE):
        yr = int(m.group(1))
        if yr < filing_yr:          # exclude forward-guidance years
            candidates.add(yr)

    if len(candidates) >= 3:
        unique = sorted(candidates, reverse=True)
        return unique[0], unique[1], unique[2]

    # Final fallback: three most common years in first 200k chars
    all_years = [int(y) for y in re.findall(r'20[012]\d', text[:200_000])
                 if 2000 <= int(y) < filing_yr]
    common_sorted = sorted(set(y for y, _ in Counter(all_years).most_common(8)), reverse=True)
    if len(common_sorted) >= 3:
        return common_sorted[0], common_sorted[1], common_sorted[2]
    return 2025, 2024, 2023


# ── Customer concentration extraction ────────────────────────────────────────

# Patterns that capture a percentage and context
_CONC_PATTERNS = [
    # "One Client and Gaming segment customer accounted for 18% of consolidated net revenue in FY2023"
    re.compile(
        r'((?:one|two|three|a\s+single)\s+[\w\s&,]{3,100}?)\s+accounted\s+for\s+'
        r'(?:approximately\s+)?(\d+(?:\.\d+)?)\s*%\s+of\s+(?:\w+\s+){0,5}'
        r'(?:net\s+)?(?:consolidated\s+)?revenue'
        r'(?:[^.]{0,60}fiscal\s+(?:year\s+)?(20\d{2}))?',
        re.IGNORECASE,
    ),
    # "No customer accounted for at least 10% of … net revenue in fiscal years 2025 and 2024"
    re.compile(
        r'(No\s+(?:single\s+)?customer)\s+accounted\s+for\s+(?:at\s+least\s+)?'
        r'(\d+(?:\.\d+)?)\s*%'
        r'(?:[^.]{0,120}fiscal\s+(?:years?\s+)?(20\d{2})(?:\s+and\s+(20\d{2}))?)?',
        re.IGNORECASE,
    ),
    # "Revenue recognized over time … accounted for approximately 9%, 8% and 25% of revenue in 2025…"
    re.compile(
        r'(Revenue\s+recognized[^.]{0,100}?)\s+accounted\s+for\s+(?:approximately\s+)?'
        r'(\d+(?:\.\d+)?)\s*%[^.]{0,60}revenue\s+in\s+(20\d{2})',
        re.IGNORECASE,
    ),
    # Accounts receivable concentration: "One customer accounted for approximately 11%…accounts receivable"
    re.compile(
        r'((?:one|two|another)\s+customer)\s+accounted\s+for\s+(?:approximately\s+)?'
        r'(\d+(?:\.\d+)?)\s*%\s+of\s+[^.]{0,80}accounts\s+receivable',
        re.IGNORECASE,
    ),
]

_SEGMENT_HINT = re.compile(
    r'(Data Center|Client|Gaming|Embedded|QCT|QTL|CCG|DCG|Semiconductor|Infrastructure)',
    re.IGNORECASE,
)


def _parse_concentration(text: str) -> list[dict]:
    results = []
    for pat in _CONC_PATTERNS:
        for m in pat.finditer(text):
            subject = m.group(1).strip()[-120:]
            pct_raw = m.group(2)
            year    = m.group(3) if m.lastindex and m.lastindex >= 3 else None

            # Try to infer segment from surrounding text
            window  = text[max(0, m.start() - 200): m.end() + 200]
            seg_m   = _SEGMENT_HINT.search(window)
            segment = seg_m.group(1) if seg_m else "总体"

            # Clean up percentage string
            try:
                pct = float(re.search(r'\d+(?:\.\d+)?', pct_raw).group())
            except Exception:
                pct = None

            results.append({
                "描述":    subject,
                "占比%":   pct,
                "所属分部": segment,
                "财年":    int(year) if year else None,
                "原文":    m.group(0)[:300],
            })
    return results


# ── Geographic revenue extraction ─────────────────────────────────────────────

_GEO_REGIONS = [
    "United States", "China", "Taiwan", "Singapore",
    "Europe", "Japan", "Korea", "Other regions",
]


def _parse_geo_revenue(text: str) -> pd.DataFrame:
    rows = []
    seen: set[str] = set()
    for region in _GEO_REGIONS:
        pat = re.compile(
            rf'{re.escape(region)}\s+\$?\s*([\d,]+)\s+\$?\s*([\d,]+)',
            re.IGNORECASE,
        )
        m = pat.search(text)
        if m and region not in seen:
            seen.add(region)
            rows.append({
                "地区":   region,
                "fy0":  int(m.group(1).replace(",", "")),
                "fy1":  int(m.group(2).replace(",", "")),
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── Main public API ───────────────────────────────────────────────────────────

@st.cache_data(ttl=3600 * 12, show_spinner=False)
def get_concentration_data(
    ticker: str,
    cik: str,
    local_dir: str = "",
) -> dict:
    """
    Return a dict with keys:
      segments      pd.DataFrame  — segment revenue (FY0/FY1/FY2, in $M)
      fy_years      tuple[int,int,int]
      concentration list[dict]    — customer/supplier % mentions
      geo           pd.DataFrame  — geographic revenue
    """
    local_path = Path(local_dir) if local_dir else None
    raw_text   = _get_10k_text(cik, local_path)
    if not raw_text:
        return {"segments": pd.DataFrame(), "fy_years": (), "concentration": [], "geo": pd.DataFrame()}

    text         = _extract_main_doc(raw_text)
    seg_names    = KNOWN_SEGMENTS.get(ticker.upper(), [])
    segments_df  = _parse_segments(text, seg_names) if seg_names else pd.DataFrame()
    fy_years     = _infer_fy_years(text)
    conc_list    = _parse_concentration(text)
    geo_df       = _parse_geo_revenue(text)

    return {
        "segments":      segments_df,
        "fy_years":      fy_years,
        "concentration": conc_list,
        "geo":           geo_df,
    }
