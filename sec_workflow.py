"""Generic SEC filing workflow — download 10-Q and 10-K for any ticker.

Usage:
    python sec_workflow.py NVDA
    python sec_workflow.py AMD
    python sec_workflow.py TSMC
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
from secedgar import FilingType, filings

USER_AGENT = "sunjialin sunjialin@terraquant.cn"
BASE_DIR = Path(__file__).resolve().parent


def _company_dir(ticker: str) -> Path:
    return BASE_DIR / ticker.upper()


def download_filings(ticker: str) -> None:
    """Download all 10-Q and 10-K filings from SEC EDGAR."""
    import nest_asyncio
    nest_asyncio.apply()

    filings_dir = _company_dir(ticker) / "10Q_10K"
    filings_dir.mkdir(parents=True, exist_ok=True)

    for filing_type in (FilingType.FILING_10Q, FilingType.FILING_10K):
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
    """Scan local filings and write filing_index.csv."""
    filings_dir = _company_dir(ticker) / "10Q_10K"
    rows: list[dict] = []

    for form_dir in ("10-Q", "10-K"):
        folder = filings_dir / ticker.lower() / form_dir
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.txt")):
            rows.append(_parse_header(path, ticker))

    index = (pd.DataFrame(rows)
               .sort_values(["form", "period_end"])
               .reset_index(drop=True))

    out = _company_dir(ticker) / "filing_index.csv"
    index.to_csv(out, index=False)
    print(f"[{ticker}] Index saved: {out}")
    return index


def summarize(ticker: str, index: pd.DataFrame) -> None:
    for form in ("10-Q", "10-K"):
        subset = index[index["form"] == form]
        if subset.empty:
            print(f"[{ticker}] {form}: 0 files")
            continue
        latest = subset.iloc[-1]
        print(f"[{ticker}] {form}: {len(subset)} files | "
              f"latest period {latest['period_end'].date()} "
              f"(filed {latest['filed_date'].date()})")


def run(ticker: str) -> None:
    print(f"\n=== {ticker.upper()} SEC Workflow ===")
    download_filings(ticker)
    index = build_filing_index(ticker)
    summarize(ticker, index)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sec_workflow.py <TICKER> [TICKER2 ...]")
        print("Example: python sec_workflow.py AMD NVDA TSMC")
        sys.exit(1)

    for t in sys.argv[1:]:
        run(t)
