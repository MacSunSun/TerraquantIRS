"""Supply-chain data loading, graph construction, and persistence helpers."""
from __future__ import annotations

import json
from pathlib import Path
import networkx as nx

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "supply_chain.json"

TIER_COLORS = {
    "upstream_t2": "#e8a838",   # amber — indirect upstream (equipment layer)
    "upstream":    "#fd7e14",   # orange — direct upstream
    "focal":       "#0d6efd",
    "peer":        "#dc3545",
    "downstream":  "#198754",
}

TIER_LABELS = {
    "upstream_t2": "设备层 (间接上游)",
    "upstream":    "直接上游",
    "focal":       "核心公司",
    "peer":        "竞争对手",
    "downstream":  "下游客户",
}

RELATIONSHIP_LABELS = {
    "supplies_equipment": "供应设备",
    "manufactures_for":   "代工制造",
    "supplies_component": "供应零部件",
    "packages_for":       "封装服务",
    "sells_to":           "销售给",
    "competes_with":      "竞争关系",
}


def load_chain() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def save_chain(chain: dict) -> None:
    DATA_PATH.write_text(json.dumps(chain, ensure_ascii=False, indent=2), encoding="utf-8")


def build_graph(chain: dict) -> nx.DiGraph:
    G = nx.DiGraph()
    for ticker, meta in chain["companies"].items():
        G.add_node(
            ticker,
            name=meta["name"],
            tier=meta["tier"],
            sector=meta["sector"],
            note=meta["note"],
            cik=meta.get("cik", ""),
            color=TIER_COLORS.get(meta["tier"], "#adb5bd"),
        )
    for rel in chain["relationships"]:
        G.add_edge(
            rel["from"], rel["to"],
            rel_type=rel["type"],
            note=rel["note"],
            label=RELATIONSHIP_LABELS.get(rel["type"], rel["type"]),
        )
    return G


def get_neighbors(ticker: str, chain: dict) -> dict[str, list[dict]]:
    """Return upstream and downstream neighbors for a given ticker."""
    upstream, downstream, peers = [], [], []
    for rel in chain["relationships"]:
        if rel["to"] == ticker and rel["type"] != "competes_with":
            meta = chain["companies"].get(rel["from"], {})
            upstream.append({**meta, "ticker": rel["from"], "note": rel["note"]})
        elif rel["from"] == ticker and rel["type"] == "sells_to":
            meta = chain["companies"].get(rel["to"], {})
            downstream.append({**meta, "ticker": rel["to"], "note": rel["note"]})
        elif (rel["from"] == ticker or rel["to"] == ticker) and rel["type"] == "competes_with":
            other = rel["to"] if rel["from"] == ticker else rel["from"]
            meta = chain["companies"].get(other, {})
            peers.append({**meta, "ticker": other, "note": rel["note"]})
    return {"upstream": upstream, "downstream": downstream, "peers": peers}


def add_company(chain: dict, ticker: str, name: str, cik: str,
                tier: str, sector: str, note: str) -> dict:
    chain["companies"][ticker] = {
        "name": name, "cik": cik, "tier": tier,
        "sector": sector, "note": note,
    }
    return chain


def add_relationship(chain: dict, from_t: str, to_t: str,
                     rel_type: str, note: str) -> dict:
    chain["relationships"].append({
        "from": from_t, "to": to_t, "type": rel_type, "note": note,
    })
    return chain


def remove_company(chain: dict, ticker: str) -> dict:
    chain["companies"].pop(ticker, None)
    chain["relationships"] = [
        r for r in chain["relationships"]
        if r["from"] != ticker and r["to"] != ticker
    ]
    return chain
