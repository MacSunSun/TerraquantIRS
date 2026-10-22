"""Pull INTC OHLCV from Massive. Reads MASSIVE_API_KEY from C:\\MegaQuant\\.env."""
import os
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import requests
from dotenv import load_dotenv

ENV = Path(r"C:\MegaQuant\.env")
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
