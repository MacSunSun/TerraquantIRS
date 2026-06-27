"""AMD SEC filing workflow — 10-Q and 10-K only."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from edgar import Company, set_identity
from secedgar import FilingType, filings

TICKER = "AMD"
CIK_LOOKUP = "amd"
USER_AGENT = "sunjialin sunjialin@terraquant.cn"
SEC_IDENTITY = "sunjialin sunjialin@terraquant.cn"

BASE_DIR = Path(__file__).resolve().parent
FILINGS_DIR = BASE_DIR / "10Q_10K"
OUTPUT_DIR = BASE_DIR / "extracted"


def download_filings() -> None:
    import nest_asyncio

    nest_asyncio.apply()
    FILINGS_DIR.mkdir(parents=True, exist_ok=True)

    for filing_type in (FilingType.FILING_10Q, FilingType.FILING_10K):
        batch = filings(
            cik_lookup=CIK_LOOKUP,
            filing_type=filing_type,
            user_agent=USER_AGENT,
        )
        batch.save(str(FILINGS_DIR))


def _parse_header(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")[:8000]

    def grab(pattern: str) -> str | None:
        match = re.search(pattern, text)
        return match.group(1).strip() if match else None

    period = grab(r"CONFORMED PERIOD OF REPORT:\s*(\d+)")
    filed = grab(r"FILED AS OF DATE:\s*(\d+)")

    return {
        "ticker": TICKER,
        "accession": grab(r"ACCESSION NUMBER:\s*(\S+)"),
        "form": grab(r"CONFORMED SUBMISSION TYPE:\s*(\S+)"),
        "period_end": pd.to_datetime(period, format="%Y%m%d") if period else pd.NaT,
        "filed_date": pd.to_datetime(filed, format="%Y%m%d") if filed else pd.NaT,
        "file_path": str(path),
    }


def build_filing_index() -> pd.DataFrame:
    rows: list[dict] = []
    for form_dir in ("10-Q", "10-K"):
        folder = FILINGS_DIR / "amd" / form_dir
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.txt")):
            rows.append(_parse_header(path))

    index = pd.DataFrame(rows).sort_values(["form", "period_end"]).reset_index(drop=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    index.to_csv(OUTPUT_DIR / "filing_index.csv", index=False)
    return index


def _save_statements(company: Company, *, annual: bool) -> Path:
    label = "annual" if annual else "quarterly"
    if annual:
        bundle = company.get_financials()
    else:
        bundle = company.get_quarterly_financials()

    out_path = OUTPUT_DIR / f"AMD_{label}_financials.xlsx"
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        bundle.income_statement().to_dataframe().to_excel(
            writer, sheet_name="Income Statement", index=False
        )
        bundle.balance_sheet().to_dataframe().to_excel(
            writer, sheet_name="Balance Sheet", index=False
        )
        bundle.cashflow_statement().to_dataframe().to_excel(
            writer, sheet_name="Cash Flow", index=False
        )
    return out_path


def extract_financials() -> tuple[Path, Path]:
    set_identity(SEC_IDENTITY)
    company = Company(TICKER)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    quarterly_path = _save_statements(company, annual=False)
    annual_path = _save_statements(company, annual=True)
    return quarterly_path, annual_path


def summarize(index: pd.DataFrame) -> None:
    print(f"Ticker: {TICKER}")
    print(f"Filings directory: {FILINGS_DIR}")
    print(f"Output directory: {OUTPUT_DIR}")
    for form in ("10-Q", "10-K"):
        subset = index[index["form"] == form]
        if subset.empty:
            print(f"{form}: 0 files")
            continue
        latest = subset.iloc[-1]
        print(
            f"{form}: {len(subset)} files | "
            f"latest period {latest['period_end'].date()} "
            f"(filed {latest['filed_date'].date()})"
        )


def main(download: bool = False) -> None:
    if download:
        print("Downloading 10-Q and 10-K filings...")
        download_filings()

    index = build_filing_index()
    summarize(index)

    print("Extracting financial statements via edgartools...")
    quarterly_path, annual_path = extract_financials()
    print(f"Saved: {quarterly_path}")
    print(f"Saved: {annual_path}")
    print(f"Saved: {OUTPUT_DIR / 'filing_index.csv'}")


if __name__ == "__main__":
    main(download=False)
