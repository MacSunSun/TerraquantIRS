"""
10-K text mining — extract supply-chain relationships from SEC filings.

Approach (no paid APIs, no heavy NLP):
  1. Strip HTML from the embedded main document
  2. Find key sections (Manufacturing, Customers, Risk Factors, Competition)
  3. Apply rule-based patterns to pull company names + relationship context
  4. Relationship type is determined by the company's default tier
     (upstream → supplier, downstream → customer, peer → competitor)
     with section used as confirmation context only.
  5. Score by frequency across filing years → confidence ranking.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

# ── Company name → (ticker, tier) mapping ────────────────────────────────────
# Keys: regex patterns (case-insensitive); Values: (ticker, tier)
COMPANY_PATTERNS: list[tuple[str, str, str]] = [
    # Foundries / Wafer Manufacturers  → AMD sources FROM them
    (r"Taiwan Semiconductor Manufacturing|TSMC",                 "TSM",       "upstream"),
    (r"GLOBALFOUNDRIES|GlobalFoundries|Global Foundries",        "GFS",       "upstream"),
    (r"United Microelectronics|UMC\b",                           "UMC",       "upstream"),
    (r"Samsung Electronics|Samsung Foundry|Samsung\b",           "005930.KS", "upstream"),
    # Equipment & Materials (tier-2 upstream)
    (r"ASML\b|ASML Holding",                                     "ASML",      "upstream_t2"),
    (r"Applied Materials|AMAT\b",                                "AMAT",      "upstream_t2"),
    (r"Lam Research|LRCX\b",                                     "LRCX",      "upstream_t2"),
    (r"KLA.{0,15}Corporation|KLA\b|KLAC\b",                      "KLAC",      "upstream_t2"),
    (r"Entegris",                                                "ENTG",      "upstream_t2"),
    (r"Synopsys",                                                "SNPS",      "upstream_t2"),
    (r"Cadence",                                                 "CDNS",      "upstream_t2"),
    (r"Arm Holdings|Arm Limited|\bARM\b|Arm architecture",       "ARM",       "upstream_t2"),
    # Memory / Components
    (r"Micron Technology|Micron\b",                              "MU",        "upstream"),
    (r"SK Hynix|SK\.Hynix",                                      "000660.KS", "upstream"),
    # Packaging (OSAT)  → AMD sources packaging FROM them
    (r"Amkor Technology|Amkor\b",                                "AMKR",      "upstream"),
    (r"ASE Technology|ASE Group|\bASE\b",                        "ASX",       "upstream"),
    # Hyperscalers / Cloud → AMD SELLS TO them
    (r"Microsoft\b|MSFT\b",                                      "MSFT",      "downstream"),
    (r"Meta Platforms|Meta\b|Facebook\b",                        "META",      "downstream"),
    (r"Amazon Web Services|Amazon\.com|Amazon\b|\bAWS\b",        "AMZN",      "downstream"),
    (r"Google\b|Alphabet\b|GCP\b",                               "GOOGL",     "downstream"),
    (r"Apple\b|AAPL\b",                                          "AAPL",      "downstream"),
    (r"Sony\b",                                                  "SONY",      "downstream"),
    (r"Dell Technologies|Dell\b",                                "DELL",      "downstream"),
    (r"Hewlett Packard Enterprise|HPE\b",                        "HPE",       "downstream"),
    (r"HP Inc|Hewlett.Packard|\bHPQ\b",                          "HPQ",       "downstream"),
    (r"Lenovo",                                                  "0992.HK",   "downstream"),
    (r"IBM\b",                                                   "IBM",       "downstream"),
    # Competitors → compete WITH AMD
    (r"NVIDIA|Nvidia",                                           "NVDA",      "peer"),
    (r"Intel\b|INTC\b",                                          "INTC",      "peer"),
    (r"Qualcomm|QCOM\b",                                         "QCOM",      "peer"),
    (r"Broadcom",                                                "AVGO",      "peer"),
    (r"Marvell Technology|Marvell\b",                            "MRVL",      "peer"),
    (r"MediaTek",                                                "2454.TW",   "peer"),
]

# Tier → default relationship (from AMD's perspective)
TIER_TO_REL: dict[str, str] = {
    "upstream":    "manufactures_for",   # they manufacture / supply TO AMD
    "upstream_t2": "supplies_equipment", # they supply equipment/IP/EDA to AMD's supply chain
    "downstream":  "sells_to",           # AMD sells products TO them
    "peer":        "competes_with",      # AMD competes WITH them
}

# Section heading keywords for context tagging
SECTION_PATTERNS = {
    "manufacturing": re.compile(
        r"Manufacturing|Third.Party Wafer|Foundry|Fabrication|Wafer Production|Assembly and Test",
        re.IGNORECASE,
    ),
    "customers": re.compile(
        r"Customers|Revenue Concentration|Customer Concentration|Major Customer",
        re.IGNORECASE,
    ),
    "risk": re.compile(
        r"Risk Factor|Risks Related|We depend|We rely|sole supplier|limited supplier",
        re.IGNORECASE,
    ),
    "competition": re.compile(
        r"Compet",
        re.IGNORECASE,
    ),
}


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;",  " ", text)
    text = re.sub(r"&amp;",   "&", text)
    text = re.sub(r"&lt;",    "<", text)
    text = re.sub(r"&gt;",    ">", text)
    text = re.sub(r"&#\d+;",  " ", text)
    text = re.sub(r"\s+",     " ", text)
    return text.strip()


def _extract_main_doc(raw: str) -> str:
    docs = re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", raw, re.DOTALL)
    if not docs:
        return _strip_html(raw)
    for doc in docs:
        if re.search(r"<TYPE>10-K", doc):
            return _strip_html(doc)
    return _strip_html(docs[0])


def _tag_section(chunk: str) -> str:
    """Return the first matching section name for this text chunk."""
    for sec_name, pat in SECTION_PATTERNS.items():
        if pat.search(chunk):
            return sec_name
    return "other"


def mine_one_filing(path: Path) -> list[dict]:
    """
    Extract supply-chain mentions from a single 10-K .txt file.
    Returns a list of dicts (one per matched company × context window).
    """
    raw     = path.read_text(encoding="utf-8", errors="ignore")
    year_m  = re.search(r"CONFORMED PERIOD OF REPORT:\s*(\d{4})", raw)
    year    = int(year_m.group(1)) if year_m else 0

    text    = _extract_main_doc(raw)
    rows: list[dict] = []

    window    = 3000
    step      = window // 2
    seen: set[tuple[str, str]] = set()   # (ticker, chunk_start) to avoid duplicates

    for i in range(0, len(text), step):
        chunk = text[i : i + window]
        sec   = _tag_section(chunk)
        if sec == "other":
            continue

        for pat_str, ticker, tier in COMPANY_PATTERNS:
            pat = re.compile(pat_str, re.IGNORECASE)
            if not pat.search(chunk):
                continue
            key = (ticker, str(i))
            if key in seen:
                continue
            seen.add(key)

            # Extract context around match
            m   = pat.search(chunk)
            ctx_start = max(0, m.start() - 250)
            ctx_end   = min(len(chunk), m.end() + 250)
            context   = re.sub(r"\s+", " ", chunk[ctx_start:ctx_end]).strip()

            # Relationship type driven by tier, not by section
            rel = TIER_TO_REL.get(tier, "related")

            rows.append({
                "ticker":   ticker,
                "name":     pat_str.split(r"|")[0].replace("\\b", "").replace("\\", "").strip(),
                "tier":     tier,
                "rel_type": rel,
                "section":  sec,
                "year":     year,
                "context":  context[:400],
            })

    return rows


def mine_all_filings(filing_dir: Path, form: str = "10-K") -> pd.DataFrame:
    """
    Process all 10-K files in a directory.
    Returns a raw DataFrame with one row per (ticker × filing × window).
    """
    all_rows: list[dict] = []
    files = sorted(filing_dir.glob("*.txt"))

    for path in files:
        header = path.read_text(encoding="utf-8", errors="ignore")[:1000]
        if form not in header:
            continue
        all_rows.extend(mine_one_filing(path))

    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse raw mentions to one row per (ticker, rel_type, section).
    Adds years_found, first_year, last_year, confidence.
    """
    if df.empty:
        return df

    agg = (df.groupby(["ticker", "name", "tier", "rel_type", "section"])
             .agg(
                 years_found=("year", "nunique"),
                 first_year=("year", "min"),
                 last_year=("year", "max"),
                 sample_context=("context", "first"),
             )
             .reset_index()
             .sort_values(["rel_type", "years_found"], ascending=[True, False]))
    return agg


def summarise(df: pd.DataFrame) -> pd.DataFrame:
    """One row per ticker with dominant section and confidence score."""
    if df.empty:
        return df
    agg = aggregate(df)
    idx = agg.groupby("ticker")["years_found"].idxmax()
    summary = agg.loc[idx].copy()
    summary["confidence"] = (summary["years_found"] /
                              summary["years_found"].max()).round(2)
    return summary.sort_values("confidence", ascending=False).reset_index(drop=True)
