"""Generic SEC filing workflow — download filings for any ticker.

US issuers (AMD, NVDA):  10-Q + 10-K
Foreign issuers (TSM):   6-K + 20-F  (ADR / FPI)

Usage:
    python sec_workflow.py NVDA
    python sec_workflow.py TSM
    python sec_workflow.py AMD NVDA TSM
    python sec_workflow.py TSM --no-interim   # skip 6-K (700+ files)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
from secedgar import FilingType, filings

USER_AGENT = "sunjialin sunjialin@terraquant.cn"
BASE_DIR = Path(__file__).resolve().parent

# Foreign private issuers file 20-F / 6-K instead of 10-K / 10-Q
FOREIGN_TICKERS = {"TSM"}

FILING_SETS: dict[str, tuple] = {
    "us":      (FilingType.FILING_10Q, FilingType.FILING_10K),
    "foreign": (FilingType.FILING_6K, FilingType.FILING_20F),
}


def _profile(ticker: str) -> str:
    return "foreign" if ticker.upper() in FOREIGN_TICKERS else "us"


def _company_dir(ticker: str) -> Path:
    return BASE_DIR / ticker.upper()


def download_filings(ticker: str, *, include_interim: bool = True) -> None:
    """Download SEC filings from EDGAR."""
    import nest_asyncio
    nest_asyncio.apply()

    filings_dir = _company_dir(ticker) / "10Q_10K"
    filings_dir.mkdir(parents=True, exist_ok=True)

    types = list(FILING_SETS[_profile(ticker)])
    if not include_interim:
        types = [types[-1]]  # annual only (10-K or 20-F)

    for filing_type in types:
        batch = filings(
            cik_lookup=ticker.lower(),
            filing_type=filing_type,
            user_agent=USER_AGENT,
        )
        batch.save(str(filings_dir))
        print(f"[{ticker}] Downloaded {filing_type}")


def _parse_header(path: Path, ticker: str) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")[:8000]

    def grab(pattern: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1).strip() if m else None

    period = grab(r"CONFORMED PERIOD OF REPORT:\s*(\d+)")
    filed  = grab(r"FILED AS OF DATE:\s*(\d+)")
    return {
        "ticker":     ticker.upper(),
        "accession":  grab(r"ACCESSION NUMBER:\s*(\S+)"),
        "form":       grab(r"CONFORMED SUBMISSION TYPE:\s*(\S+)"),
        "period_end": pd.to_datetime(period, format="%Y%m%d") if period else pd.NaT,
        "filed_date": pd.to_datetime(filed,  format="%Y%m%d") if filed  else pd.NaT,
        "file_path":  str(path),
    }


def build_filing_index(ticker: str) -> pd.DataFrame:
    """Scan all downloaded form folders and write filing_index.csv."""
    filings_dir = _company_dir(ticker) / "10Q_10K" / ticker.lower()
    rows: list[dict] = []

    if filings_dir.exists():
        for form_dir in sorted(filings_dir.iterdir()):
            if not form_dir.is_dir():
                continue
            for path in sorted(form_dir.glob("*.txt")):
                rows.append(_parse_header(path, ticker))

    index = (pd.DataFrame(rows)
               .sort_values(["form", "period_end"])
               .reset_index(drop=True))

    out = _company_dir(ticker) / "filing_index.csv"
    index.to_csv(out, index=False)
    print(f"[{ticker}] Index saved: {out} ({len(index)} files)")
    return index


def summarize(ticker: str, index: pd.DataFrame) -> None:
    profile = _profile(ticker)
    annual  = "20-F" if profile == "foreign" else "10-K"
    interim = "6-K"  if profile == "foreign" else "10-Q"

    for form in (interim, annual):
        subset = index[index["form"] == form]
        if subset.empty:
            print(f"[{ticker}] {form}: 0 files")
            continue
        latest = subset.iloc[-1]
        print(f"[{ticker}] {form}: {len(subset)} files | "
              f"latest period {latest['period_end'].date()} "
              f"(filed {latest['filed_date'].date()})")


def run(ticker: str, *, include_interim: bool = True) -> None:
    print(f"\n=== {ticker.upper()} SEC Workflow ({_profile(ticker)}) ===")
    download_filings(ticker, include_interim=include_interim)
    index = build_filing_index(ticker)
    summarize(ticker, index)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    include_interim = "--no-interim" not in sys.argv

    if not args:
        print("Usage: python sec_workflow.py <TICKER> [TICKER2 ...] [--no-interim]")
        print("Example: python sec_workflow.py AMD NVDA TSM")
        print("         python sec_workflow.py TSM --no-interim   # 20-F only")
        sys.exit(1)

    for t in args:
        run(t, include_interim=include_interim)
