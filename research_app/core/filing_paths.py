"""Resolve local SEC filing directories for each ticker."""
from __future__ import annotations

from pathlib import Path

ANNUAL_FORMS = ("10-K", "20-F")
INTERIM_FORMS = ("10-Q", "6-K")


def research_root() -> Path:
    here = Path(__file__).resolve().parent.parent.parent
    win = Path(r"e:\Quant\Quant\Investment Research")
    for p in (here, win):
        if (p / "research_app").exists():
            return p
    return here


def _filings_base(ticker: str) -> Path:
    return research_root() / ticker.upper() / "10Q_10K" / ticker.lower()


def local_annual_dir(ticker: str) -> Path | None:
    """Return local folder with annual filings (10-K or 20-F), if any."""
    base = _filings_base(ticker)
    for form in ANNUAL_FORMS:
        folder = base / form
        if folder.is_dir() and any(folder.glob("*.txt")):
            return folder
    return None


def local_interim_dir(ticker: str) -> Path | None:
    """Return local folder with interim filings (10-Q or 6-K), if any."""
    base = _filings_base(ticker)
    for form in INTERIM_FORMS:
        folder = base / form
        if folder.is_dir() and any(folder.glob("*.txt")):
            return folder
    return None


def local_annual_dirs() -> dict[str, str]:
    """All tickers with downloaded annual filings → path string."""
    root = research_root()
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for company_dir in sorted(root.iterdir()):
        if not company_dir.is_dir():
            continue
        ticker = company_dir.name
        annual = local_annual_dir(ticker)
        if annual:
            out[ticker] = str(annual)
    return out
