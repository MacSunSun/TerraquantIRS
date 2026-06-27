"""Build AMD quarterly model dataset — run once to validate pipeline."""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from sklearn.linear_model import RidgeCV
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.base import clone
from sklearn.metrics import mean_absolute_error, mean_squared_error
import xgboost as xgb

TICKER     = "AMD"
CIK        = "CIK0000002488"
USER_AGENT = "sunjialin sunjialin@terraquant.cn"
RANDOM_STATE = 42

# ── SEC XBRL helpers ──────────────────────────────────────────────────────────

def fetch_gaap(cik, user_agent):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/{cik}.json"
    r = requests.get(url, headers={"User-Agent": user_agent}, timeout=60)
    r.raise_for_status()
    return r.json()["facts"]["us-gaap"]


def flow_qtr(gaap, concept, col):
    """Income-stmt: standalone single-quarter values (duration 70–105 days)."""
    if concept not in gaap:
        return pd.Series(dtype=float, name=col)
    units = gaap[concept]["units"]
    uk = "USD" if "USD" in units else next(iter(units))
    df = pd.DataFrame(units[uk])
    if "start" not in df.columns:
        return pd.Series(dtype=float, name=col)
    df["start"] = pd.to_datetime(df["start"])
    df["end"]   = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    df["dur"]   = (df["end"] - df["start"]).dt.days
    q = df[df["form"].isin(["10-Q","10-K"]) & df["dur"].between(70, 105)].copy()
    q = q.sort_values("filed").drop_duplicates("end", keep="last")
    return q.set_index("end")["val"].rename(col).sort_index().astype(float)


def flow_ytd_to_qtr(gaap, concept, col):
    """Cash flow: convert YTD → standalone quarterly by differencing same fiscal year."""
    if concept not in gaap:
        return pd.Series(dtype=float, name=col)
    units = gaap[concept]["units"]
    uk = "USD" if "USD" in units else next(iter(units))
    df = pd.DataFrame(units[uk])
    if "start" not in df.columns:
        return pd.Series(dtype=float, name=col)
    df["start"] = pd.to_datetime(df["start"])
    df["end"]   = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    df["dur"]   = (df["end"] - df["start"]).dt.days
    ytd = df[df["form"].isin(["10-Q","10-K"]) & df["dur"].between(70, 380)].copy()
    ytd = ytd.sort_values("filed").drop_duplicates(["start","end"], keep="last")
    rows = []
    for _, row in ytd.iterrows():
        if row["dur"] <= 105:
            rows.append({"end": row["end"], "val": row["val"]})
        else:
            prev = ytd[(ytd["start"] == row["start"]) & (ytd["end"] < row["end"])]
            if not prev.empty:
                prev_val = prev.sort_values("end").iloc[-1]["val"]
                rows.append({"end": row["end"], "val": row["val"] - prev_val})
    if not rows:
        return pd.Series(dtype=float, name=col)
    rdf = pd.DataFrame(rows).drop_duplicates("end", keep="last")
    return rdf.set_index("end")["val"].rename(col).sort_index().astype(float)


def stock_qtr(gaap, concept, col):
    """Balance sheet: instantaneous values, deduplicate by period end."""
    if concept not in gaap:
        return pd.Series(dtype=float, name=col)
    units = gaap[concept]["units"]
    uk = "USD" if "USD" in units else next(iter(units))
    df = pd.DataFrame(units[uk])
    df["end"]   = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    q = df[df["form"].isin(["10-Q","10-K"])].copy()
    q = q.sort_values("filed").drop_duplicates("end", keep="last")
    return q.set_index("end")["val"].rename(col).sort_index().astype(float)


# ── 1. Download XBRL facts ────────────────────────────────────────────────────
print("Downloading AMD XBRL from SEC EDGAR ...")
gaap = fetch_gaap(CIK, USER_AGENT)
print(f"  {len(gaap)} GAAP concepts")

# Income statement
revenue      = flow_qtr(gaap, "RevenueFromContractWithCustomerExcludingAssessedTax", "revenue")\
               .combine_first(flow_qtr(gaap, "SalesRevenueNet", "revenue"))
gross_profit = flow_qtr(gaap, "GrossProfit", "gross_profit")
op_income    = flow_qtr(gaap, "OperatingIncomeLoss", "op_income")
net_income   = flow_qtr(gaap, "NetIncomeLoss", "net_income")
eps_dil      = flow_qtr(gaap, "EarningsPerShareDiluted", "eps_dil")
rd_exp       = flow_qtr(gaap, "ResearchAndDevelopmentExpense", "rd_exp")
shares_dil   = flow_qtr(gaap, "WeightedAverageNumberOfDilutedSharesOutstanding", "shares_dil")

# Cash flow
op_cf = flow_ytd_to_qtr(gaap, "NetCashProvidedByUsedInOperatingActivities", "op_cf")
capex = flow_ytd_to_qtr(gaap, "PaymentsToAcquirePropertyPlantAndEquipment", "capex")

# Balance sheet
cash         = stock_qtr(gaap, "CashAndCashEquivalentsAtCarryingValue", "cash")
inventory    = stock_qtr(gaap, "InventoryNet", "inventory")
equity       = stock_qtr(gaap, "StockholdersEquity", "equity")
total_assets = stock_qtr(gaap, "Assets", "total_assets")

fund = pd.concat([
    revenue, gross_profit, op_income, net_income, eps_dil, rd_exp, shares_dil,
    op_cf, capex, cash, inventory, equity, total_assets
], axis=1)
fund.index = pd.to_datetime(fund.index)
fund = fund[fund["revenue"].notna()].sort_index()
print(f"  Fundamental data: {len(fund)} quarters ({fund.index[0].date()} → {fund.index[-1].date()})")

# ── 2. Price data ─────────────────────────────────────────────────────────────
print("Downloading AMD price history ...")
amd_tk  = yf.Ticker(TICKER)
px_raw  = amd_tk.history(period="max", interval="1d")[["Close"]]
px_raw.index = pd.to_datetime(px_raw.index.tz_localize(None).date)
print(f"  Price: {px_raw.index[0]} → {px_raw.index[-1]}")

def price_on(date):
    mask = px_raw.index <= date
    return float(px_raw.loc[px_raw.index[mask].max(), "Close"]) if mask.any() else np.nan

fund["price"] = [price_on(d) for d in fund.index]

def qtr_vol(date):
    lo = date - pd.Timedelta(days=120)
    mask = (px_raw.index >= lo) & (px_raw.index < date)
    r = px_raw["Close"][mask].pct_change().dropna()
    return float(r.std() * np.sqrt(252)) if len(r) >= 15 else np.nan

fund["vol"] = [qtr_vol(d) for d in fund.index]

# ── 3. Feature engineering ────────────────────────────────────────────────────
fund["gross_margin"]  = fund["gross_profit"] / fund["revenue"]
fund["op_margin"]     = fund["op_income"]    / fund["revenue"]
fund["net_margin"]    = fund["net_income"]   / fund["revenue"]
fund["rd_intensity"]  = fund["rd_exp"]       / fund["revenue"]
fund["fcf"]           = fund["op_cf"] - fund["capex"].abs()
fund["fcf_margin"]    = fund["fcf"]  / fund["revenue"]
fund["cash_to_rev"]   = fund["cash"] / fund["revenue"]
fund["inv_to_rev"]    = fund["inventory"] / fund["revenue"]
fund["asset_turns"]   = (fund["revenue"] * 4) / fund["total_assets"]

fund["rev_qoq"]      = fund["revenue"].pct_change(1)
fund["rev_yoy"]      = fund["revenue"].pct_change(4)
fund["eps_yoy"]      = fund["eps_dil"].pct_change(4)
fund["opinc_yoy"]    = fund["op_income"].pct_change(4)
fund["gm_qoq"]       = fund["gross_margin"].diff(1)
fund["gm_yoy"]       = fund["gross_margin"].diff(4)

fund["mktcap"]   = fund["price"] * fund["shares_dil"]
fund["ps_ratio"] = fund["mktcap"] / (fund["revenue"] * 4)
fund["pe_ratio"] = fund["price"] / (fund["eps_dil"] * 4).where(fund["eps_dil"] > 0, other=np.nan)
fund["pb_ratio"] = fund["mktcap"] / fund["equity"].abs()

fund["mom_1q"] = fund["price"].pct_change(1)
fund["mom_2q"] = fund["price"].pct_change(2)
fund["mom_4q"] = fund["price"].pct_change(4)

fund["next_q_return"] = fund["price"].pct_change(1).shift(-1)

# ── 4. Clean dataset ──────────────────────────────────────────────────────────
FEATURE_COLS = [
    "gross_margin", "op_margin", "net_margin", "rd_intensity",
    "rev_qoq", "rev_yoy", "eps_yoy", "opinc_yoy", "gm_qoq", "gm_yoy",
    "cash_to_rev", "inv_to_rev", "asset_turns",
    "ps_ratio", "pe_ratio", "pb_ratio",
    "mom_1q", "mom_2q", "mom_4q", "vol",
]

# Add FCF if enough data
if fund["fcf_margin"].notna().sum() >= 25:
    FEATURE_COLS.append("fcf_margin")

TARGET = "next_q_return"
data   = fund[FEATURE_COLS + [TARGET, "price", "revenue"]].dropna().copy()

# Clip extremes
for col in FEATURE_COLS:
    lo, hi = data[col].quantile([0.02, 0.98])
    data[col] = data[col].clip(lower=lo, upper=hi)

print(f"\nClean model dataset: {len(data)} quarters ({data.index[0].date()} → {data.index[-1].date()})")
print(f"Features: {len(FEATURE_COLS)}")

# ── 5. Walk-forward evaluation ────────────────────────────────────────────────
MIN_TRAIN = 20
X  = data[FEATURE_COLS].values
y  = data[TARGET].values
dt = data.index

MODELS = {
    "Naive_Mean": None,
    "Ridge": Pipeline([
        ("sc", StandardScaler()),
        ("m",  RidgeCV(alphas=[0.1, 1, 10, 100, 1000])),
    ]),
    "RandomForest": Pipeline([
        ("sc", StandardScaler()),
        ("m",  RandomForestRegressor(
            n_estimators=300, max_depth=4, min_samples_leaf=4,
            max_features=0.6, random_state=RANDOM_STATE)),
    ]),
    "XGBoost": Pipeline([
        ("sc", StandardScaler()),
        ("m",  xgb.XGBRegressor(
            n_estimators=150, max_depth=3, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.7,
            min_child_weight=5, reg_lambda=2.0,
            random_state=RANDOM_STATE, verbosity=0)),
    ]),
}

records = {n: [] for n in MODELS}

for i in range(MIN_TRAIN, len(data) - 1):
    Xtr, ytr = X[:i], y[:i]
    Xte, yte = X[i:i+1], y[i]
    date_i   = dt[i]

    records["Naive_Mean"].append({"date": date_i, "y_true": yte, "y_pred": ytr.mean()})

    for name, pipe in MODELS.items():
        if pipe is None:
            continue
        p = clone(pipe)
        p.fit(Xtr, ytr)
        records[name].append({"date": date_i, "y_true": yte, "y_pred": p.predict(Xte)[0]})

print(f"\n{'Model':<15} {'MAE':>8} {'RMSE':>8} {'DirAcc':>8} {'IC':>8}")
print("-" * 52)
for name in MODELS:
    df_r  = pd.DataFrame(records[name])
    mae   = mean_absolute_error(df_r["y_true"], df_r["y_pred"])
    rmse  = mean_squared_error(df_r["y_true"],  df_r["y_pred"]) ** 0.5
    da    = (np.sign(df_r["y_true"]) == np.sign(df_r["y_pred"])).mean()
    ic    = df_r["y_true"].corr(df_r["y_pred"])
    print(f"{name:<15} {mae:8.4f} {rmse:8.4f} {da:8.2%} {ic:8.3f}")

print("\nDone — pipeline validated.")
