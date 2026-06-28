"""
core/vis_graph.py — Vis.js graph payloads for the Streamlit custom component.
"""
from __future__ import annotations

import json
from core.supply_chain import TIER_COLORS, TIER_LABELS, RELATIONSHIP_LABELS

EDGE_COLORS: dict[str, str] = {
    "supplies_equipment": "#e8a838",   # amber — matches equipment tier colour
    "manufactures_for":   "#fd7e14",   # orange
    "supplies_component": "#fd7e14",
    "packages_for":       "#ff9f43",
    "sells_to":           "#198754",   # green
    "competes_with":      "#dc3545",   # red
}


def _spread(count: int, spacing: int = 90) -> list[float]:
    """Return evenly-spaced values centred on 0."""
    if count == 0:
        return []
    start = -(count - 1) * spacing / 2
    return [start + i * spacing for i in range(count)]


# ── Full Map ──────────────────────────────────────────────────────────────────

def build_full_map_payload(chain: dict, active_tiers: set[str] | None = None, height: int = 620) -> dict:
    """Payload for the full supply-chain map (physics + hover highlight)."""
    focal = chain.get("focal", "AMD")
    active_tiers = active_tiers or set(TIER_COLORS.keys())

    # ---- nodes ---------------------------------------------------------------
    nodes_data: list[dict] = []
    orig_colors: dict[str, str] = {}
    node_meta: dict[str, dict] = {}    # id → {fontSize, fontColor, borderColor}

    for ticker, meta in chain["companies"].items():
        tier = meta.get("tier", "")
        if tier not in active_tiers:
            continue
        is_focal = (ticker == focal)
        color = TIER_COLORS.get(tier, "#adb5bd")
        font_size = 17 if is_focal else 12
        border_color = "#222" if is_focal else "#ffffffcc"
        orig_colors[ticker] = color
        node_meta[ticker] = {"fontSize": font_size, "fontColor": "#111",
                              "borderColor": border_color}
        nodes_data.append({
            "id":          ticker,
            "label":       ticker,
            "color":       {"background": color, "border": border_color},
            "font":        {"color": "#111", "size": font_size, "bold": is_focal},
            "size":        38 if is_focal else 22,
            "shadow":      True,
            "borderWidth": 3 if is_focal else 1,
        })

    visible = {n["id"] for n in nodes_data}

    # ---- edges ---------------------------------------------------------------
    edges_data: list[dict] = []
    for rel in chain["relationships"]:
        if rel["from"] not in visible or rel["to"] not in visible:
            continue
        rt = rel.get("type", "")
        ec = EDGE_COLORS.get(rt, "#adb5bd")
        edges_data.append({
            "id":     f"{rel['from']}___{rel['to']}",
            "from":   rel["from"],
            "to":     rel["to"],
            "color":  {"color": ec, "inherit": False, "opacity": 1.0},
            "width":  1.8,
            "dashes": rt == "competes_with",
            "arrows": "" if rt == "competes_with" else "to",
            "smooth": {"type": "curvedCW", "roundness": 0.10},
            "title":  f"{RELATIONSHIP_LABELS.get(rt, rt)}: {rel.get('note','')}",
        })

    options = {
        "physics": {
            "enabled": True,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
                "gravitationalConstant": -90,
                "centralGravity": 0.004,
                "springLength": 165,
                "springConstant": 0.05,
                "damping": 0.5,
            },
            "stabilization": {"iterations": 280, "fit": True},
        },
        "interaction": {
            "hover": True,
            "tooltipDelay": 140,
            "hideEdgesOnDrag": False,
            "zoomView": True,
            "dragView": True,
            "navigationButtons": False,
        },
        "nodes": {
            "shape": "dot",
            "font":   {"color": "#111", "size": 12},
            "chosen": False,
        },
        "edges": {
            "color":          {"inherit": False},
            "selectionWidth": 3,
            "chosen":         False,
        },
    }

    return {
        "mode":    "full",
        "height":  height,
        "nodes":   nodes_data,
        "edges":   edges_data,
        "options": options,
        "orig":    orig_colors,
        "nmeta":   node_meta,
    }


def build_mini_map_payload(focal_ticker: str, chain: dict, height: int = 400) -> dict:
    """Payload for LR mini-map on company overview / concentration pages."""
    upstream_t:    list[str] = []
    downstream_t:  list[str] = []
    competitor_t:  list[str] = []
    equipment_by_hub: dict[str, list[str]] = {}

    for rel in chain["relationships"]:
        rt  = rel.get("type", "")
        frm = rel["from"]
        to_ = rel["to"]
        if rt == "competes_with":
            if frm == focal_ticker and to_ not in competitor_t:
                competitor_t.append(to_)
            elif to_ == focal_ticker and frm not in competitor_t:
                competitor_t.append(frm)
        elif to_ == focal_ticker and frm not in upstream_t:
            upstream_t.append(frm)
        elif frm == focal_ticker and to_ not in downstream_t:
            downstream_t.append(to_)

    # Indirect upstream: equipment suppliers of direct upstream (e.g. ASML → TSM → NVDA)
    for rel in chain["relationships"]:
        if rel.get("type") == "supplies_equipment" and rel["to"] in upstream_t:
            hub = rel["to"]
            equip = rel["from"]
            if equip not in equipment_by_hub.setdefault(hub, []):
                equipment_by_hub[hub].append(equip)

    nodes_data: list[dict] = []
    edges_data: list[dict] = []
    placed: set[str] = set()

    def _node(ticker: str, x: float, y: float, size: int = 22) -> dict:
        meta  = chain["companies"].get(ticker, {})
        tier  = meta.get("tier", "")
        color = TIER_COLORS.get(tier, "#adb5bd")
        is_f  = (ticker == focal_ticker)
        return {
            "id":    ticker,
            "label": ticker,
            "x": x, "y": y,
            "color":       {"background": color, "border": "#222" if is_f else "#fff"},
            "font":        {"color": "#111", "size": 16 if is_f else 12, "bold": is_f},
            "size":        size,
            "shadow":      True,
            "borderWidth": 3 if is_f else 1,
        }

    # Focal
    nodes_data.append(_node(focal_ticker, 0, 0, size=36))
    placed.add(focal_ticker)

    # Direct upstream (middle-left column)
    uy = _spread(len(upstream_t), spacing=95)
    hub_y: dict[str, float] = {}
    for i, t in enumerate(upstream_t):
        hub_y[t] = uy[i]
        nodes_data.append(_node(t, -380, uy[i]))
        placed.add(t)
        rt_up = next(
            (r["type"] for r in chain["relationships"]
             if r["from"] == t and r["to"] == focal_ticker), "manufactures_for"
        )
        ec = EDGE_COLORS.get(rt_up, "#fd7e14")
        edges_data.append({
            "id":    f"{t}___{focal_ticker}",
            "from":  t, "to": focal_ticker,
            "color": {"color": ec, "inherit": False}, "width": 2.0,
            "arrows": "to",
            "smooth": {"type": "curvedCW", "roundness": 0.12},
            "title": RELATIONSHIP_LABELS.get(rt_up, rt_up),
        })

    # Equipment layer (far-left column, grouped by hub)
    for hub, eq_list in equipment_by_hub.items():
        hy = hub_y.get(hub, 0)
        eq_y = _spread(len(eq_list), spacing=65)
        for j, eq in enumerate(eq_list):
            if eq not in placed:
                nodes_data.append(_node(eq, -720, hy + eq_y[j], size=18))
                placed.add(eq)
            edges_data.append({
                "id":    f"{eq}___{hub}",
                "from":  eq, "to": hub,
                "color": {"color": EDGE_COLORS["supplies_equipment"], "inherit": False},
                "width": 1.6,
                "arrows": "to",
                "smooth": {"type": "curvedCW", "roundness": 0.12},
                "title": RELATIONSHIP_LABELS["supplies_equipment"],
            })

    # Downstream (right column)
    dy = _spread(len(downstream_t), spacing=95)
    for i, t in enumerate(downstream_t):
        nodes_data.append(_node(t, 380, dy[i]))
        rt_dn = next(
            (r["type"] for r in chain["relationships"]
             if r["from"] == focal_ticker and r["to"] == t), "sells_to"
        )
        ec = EDGE_COLORS.get(rt_dn, "#198754")
        edges_data.append({
            "id":    f"{focal_ticker}___{t}",
            "from":  focal_ticker, "to": t,
            "color": {"color": ec, "inherit": False}, "width": 2.0,
            "arrows": "to",
            "smooth": {"type": "curvedCW", "roundness": 0.12},
            "title": RELATIONSHIP_LABELS.get(rt_dn, rt_dn),
        })

    # Competitors (bottom row, spread horizontally)
    cx = _spread(len(competitor_t), spacing=130)
    for i, t in enumerate(competitor_t):
        nodes_data.append(_node(t, cx[i] if cx else 0, 270))
        edges_data.append({
            "id":    f"{focal_ticker}___{t}___peer",
            "from":  focal_ticker, "to": t,
            "color": {"color": "#dc3545", "inherit": False}, "width": 1.5,
            "dashes": True, "arrows": "",
            "smooth": {"type": "dynamic"},
            "title": "竞争对手",
        })

    options = {
        "physics":     {"enabled": False},
        "interaction": {
            "dragNodes": True,
            "dragView":  True,
            "zoomView":  True,
            "hover":     True,
            "tooltipDelay": 150,
        },
        "nodes": {
            "shape": "dot",
            "font":   {"color": "#111", "size": 12},
            "chosen": False,
        },
        "edges": {
            "color":  {"inherit": False},
            "smooth": {"type": "curvedCW", "roundness": 0.12},
            "chosen": False,
        },
        "layout": {"randomSeed": 42},
    }

    orig_colors: dict[str, str] = {}
    node_meta:   dict[str, dict] = {}
    for n in nodes_data:
        orig_colors[n["id"]] = n["color"]["background"]
        node_meta[n["id"]]   = {
            "fontSize": n["font"]["size"],
            "borderColor": n["color"].get("border", "#fff"),
        }

    equipment_c  = TIER_COLORS.get("upstream_t2", "#e8a838")
    upstream_c   = TIER_COLORS.get("upstream", "#fd7e14")
    downstream_c = TIER_COLORS.get("downstream", "#198754")
    competitor_c = TIER_COLORS.get("peer", "#dc3545")

    return {
        "mode":    "mini",
        "height":  height,
        "focal":   focal_ticker,
        "nodes":   nodes_data,
        "edges":   edges_data,
        "options": options,
        "orig":    orig_colors,
        "nmeta":   node_meta,
        "labels": [
            {"text": "↑ 设备层", "color": equipment_c, "top": "6px", "left": "4%"},
            {"text": "直接上游", "color": upstream_c, "top": "6px", "left": "28%"},
            {"text": "下游客户 ↑", "color": downstream_c, "top": "6px", "right": "10px"},
            {"text": "-- 竞争对手 --", "color": competitor_c,
             "bottom": "6px", "left": "50%", "transform": "translateX(-50%)"},
        ],
    }
