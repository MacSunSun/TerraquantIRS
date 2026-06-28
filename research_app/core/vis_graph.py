"""
core/vis_graph.py
Generates self-contained Vis.js HTML for:
  - build_full_map_html()  → full supply-chain map with hover-highlight + click-navigate
  - build_mini_map_html()  → LR mini-map for the company overview page (draggable, no physics)
"""
from __future__ import annotations
import json
from core.supply_chain import TIER_COLORS, TIER_LABELS, RELATIONSHIP_LABELS

# CDN URL pinned to a stable version
_VIS_CDN = "https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"

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

def build_full_map_html(chain: dict, active_tiers: set[str] | None = None, height: int = 620) -> str:
    """
    Full supply-chain map:
      • Physics-based spring layout
      • Hover → highlight neighbourhood, dim others
      • Click → window.parent.location.search = '?ticker=XXX'
                 (Streamlit detects query-param change and reruns)
    """
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
            "title":       (f"<b>{ticker}</b> — {meta['name']}<br>"
                           f"<span style='color:#aaa'>层级：</span>"
                           f"{TIER_LABELS.get(tier, tier)}<br>"
                           f"{meta.get('sector','')}<br>"
                           f"<i>{meta.get('note','')}</i>"),
            "color":       {"background": color, "border": border_color,
                            "hover": {"background": color, "border": "#000"}},
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
            "font": {"color": "#111", "size": 12},
        },
        "edges": {
            "color":          {"inherit": False},
            "selectionWidth": 3,
        },
    }

    j_nodes  = json.dumps(nodes_data,  ensure_ascii=False)
    j_edges  = json.dumps(edges_data,  ensure_ascii=False)
    j_orig   = json.dumps(orig_colors, ensure_ascii=False)
    j_nmeta  = json.dumps(node_meta,   ensure_ascii=False)
    j_opts   = json.dumps(options,     ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="{_VIS_CDN}"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#f8f9fa;font-family:-apple-system,sans-serif}}
#net{{width:100%;height:{height}px}}
#tip{{position:absolute;bottom:10px;right:14px;
  background:rgba(0,0,0,.52);color:#fff;padding:3px 10px;
  border-radius:4px;font-size:11px;pointer-events:none}}
</style></head>
<body>
<div id="net"></div>
<div id="tip">悬停高亮邻居 · 点击进入公司详情 · 滚轮缩放</div>
<script>
var ORIG   = {j_orig};
var NMETA  = {j_nmeta};
var nodesArr = {j_nodes};
var edgesArr = {j_edges};

// per-edge original color indexed by edge id
var eMeta = {{}};
edgesArr.forEach(function(e){{
  eMeta[e.id] = {{color: (e.color && e.color.color) ? e.color.color : '#aaa',
                  width: e.width || 1.8}};
}});

var nodes   = new vis.DataSet(nodesArr);
var edges   = new vis.DataSet(edgesArr);
var network = new vis.Network(
  document.getElementById('net'),
  {{nodes:nodes, edges:edges}},
  {j_opts}
);

// ── Helpers: direct font-color update (DataSet.update alone is unreliable) ───
function setFontColors(nbSet){{
  nodes.getIds().forEach(function(nid){{
    var bn = network.body.nodes[nid];
    if(!bn) return;
    if(nbSet.has(nid)){{
      bn.setOptions({{font:{{color:ORIG[nid],size:NMETA[nid].fontSize+2,bold:true}}}});
    }}else{{
      bn.setOptions({{font:{{color:'#bbb',size:10,bold:false}}}});
    }}
  }});
  network.redraw();
}}

function resetFontColors(){{
  nodes.getIds().forEach(function(nid){{
    var bn = network.body.nodes[nid];
    if(!bn) return;
    bn.setOptions({{font:{{color:'#111',size:NMETA[nid].fontSize,bold:false}}}});
  }});
  network.redraw();
}}

// ── Hover: hovered node → blue; neighbours → relationship colour ─────────────
network.on('hoverNode', function(p){{
  var id    = p.node;
  var ceSet = new Set(network.getConnectedEdges(id));
  var nbSet = new Set(network.getConnectedNodes(id));
  nbSet.add(id);

  // neighbour → relationship colour (from edge metadata)
  var nbColor = {{}};
  edges.get(Array.from(ceSet)).forEach(function(e){{
    var nb = (e.from === id) ? e.to : e.from;
    nbColor[nb] = eMeta[e.id].color;
  }});

  // node background + opacity
  nodes.update(nodes.get().map(function(n){{
    if(n.id === id){{
      return {{id:n.id,
              color:{{background:'#0d6efd',border:'#0a58ca',
                     hover:{{background:'#0d6efd',border:'#0a58ca'}}}},
              opacity:1}};
    }}else if(nbSet.has(n.id)){{
      var c = nbColor[n.id] || ORIG[n.id];
      return {{id:n.id,
              color:{{background:c,border:c,hover:{{background:c,border:c}}}},
              opacity:1}};
    }}else{{
      return {{id:n.id,
              color:{{background:'#e0e0ea',border:'#ccc',
                     hover:{{background:'#e0e0ea',border:'#ccc'}}}},
              opacity:0.18}};
    }}
  }}));

  // font colour (direct body-node access for reliability)
  nodes.getIds().forEach(function(nid){{
    var bn = network.body.nodes[nid];
    if(!bn) return;
    if(nid === id){{
      bn.setOptions({{font:{{color:'#0d6efd',size:NMETA[nid].fontSize+2,bold:true}}}});
    }}else if(nbSet.has(nid)){{
      var c = nbColor[nid] || ORIG[nid];
      bn.setOptions({{font:{{color:c,size:NMETA[nid].fontSize+1,bold:true}}}});
    }}else{{
      bn.setOptions({{font:{{color:'#ccc',size:10,bold:false}}}});
    }}
  }});
  network.redraw();

  // edge highlight
  edges.update(edges.get().map(function(e){{
    if(ceSet.has(e.id)){{
      return {{id:e.id,color:{{color:eMeta[e.id].color,inherit:false,opacity:1}},width:3.0}};
    }}else{{
      return {{id:e.id,color:{{color:'#e0e0ea',inherit:false,opacity:0.1}},width:0.5}};
    }}
  }}));
}});

network.on('blurNode', function(){{
  nodes.update(nodes.get().map(function(n){{
    return {{id:n.id,
            color:{{background:ORIG[n.id],border:NMETA[n.id].borderColor,
                   hover:{{background:ORIG[n.id],border:'#000'}}}},
            opacity:1}};
  }}));
  resetFontColors();
  edges.update(edges.get().map(function(e){{
    return {{id:e.id,color:{{color:eMeta[e.id].color,inherit:false,opacity:1}},width:eMeta[e.id].width}};
  }}));
}});

// ── Click: navigate parent to company detail ─────────────────────────────────
network.on('click', function(p){{
  if(p.nodes.length>0){{
    var ticker = p.nodes[0];
    try{{
      window.parent.location.search = '?ticker=' + encodeURIComponent(ticker);
    }}catch(e){{
      console.warn('parent nav failed',e);
    }}
  }}
}});
</script></body></html>"""


# ── Mini Map ──────────────────────────────────────────────────────────────────

def build_mini_map_html(focal_ticker: str, chain: dict, height: int = 360) -> str:
    """
    Compact LR mini-map for the company overview page.
    Layout (physics OFF, draggable):
      x = -380  upstream suppliers
      x =    0  focal company
      x = +380  downstream customers
      y = +260  competitors (spread horizontally below focal)
    """
    focal_meta = chain["companies"].get(focal_ticker, {})

    upstream_t:    list[str] = []
    downstream_t:  list[str] = []
    competitor_t:  list[str] = []

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

    nodes_data: list[dict] = []
    edges_data: list[dict] = []

    def _node(ticker: str, x: float, y: float, size: int = 22) -> dict:
        meta  = chain["companies"].get(ticker, {})
        tier  = meta.get("tier", "")
        color = TIER_COLORS.get(tier, "#adb5bd")
        is_f  = (ticker == focal_ticker)
        return {
            "id":    ticker,
            "label": ticker,
            "title": (f"<b>{ticker}</b> — {meta.get('name', ticker)}<br>"
                      f"{meta.get('note','')}"),
            "x": x, "y": y,
            "color":       {"background": color, "border": "#222" if is_f else "#fff"},
            "font":        {"color": "#111", "size": 16 if is_f else 12, "bold": is_f},
            "size":        size,
            "shadow":      True,
            "borderWidth": 3 if is_f else 1,
        }

    # Focal
    nodes_data.append(_node(focal_ticker, 0, 0, size=36))

    # Upstream (left column)
    uy = _spread(len(upstream_t), spacing=95)
    for i, t in enumerate(upstream_t):
        nodes_data.append(_node(t, -380, uy[i]))
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
            "font": {"color": "#111", "size": 12},
        },
        "edges": {
            "color":  {"inherit": False},
            "smooth": {"type": "curvedCW", "roundness": 0.12},
        },
        "layout": {"randomSeed": 42},
    }

    j_nodes = json.dumps(nodes_data, ensure_ascii=False)
    j_edges = json.dumps(edges_data, ensure_ascii=False)
    j_opts  = json.dumps(options,    ensure_ascii=False)

    # orig colors & meta for JS hover logic
    orig_colors: dict[str, str] = {}
    node_meta:   dict[str, dict] = {}
    for n in nodes_data:
        orig_colors[n["id"]] = n["color"]["background"]
        node_meta[n["id"]]   = {"fontSize": n["font"]["size"]}
    j_orig  = json.dumps(orig_colors, ensure_ascii=False)
    j_nmeta = json.dumps(node_meta,   ensure_ascii=False)

    # Section label colours
    upstream_c   = TIER_COLORS.get("upstream", "#fd7e14")
    downstream_c = TIER_COLORS.get("downstream", "#198754")
    competitor_c = TIER_COLORS.get("peer", "#dc3545")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="{_VIS_CDN}"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#fafafa;font-family:-apple-system,sans-serif;position:relative}}
#mini{{width:100%;height:{height}px}}
.lbl{{position:absolute;font-size:11px;font-weight:600;opacity:.65;pointer-events:none}}
#lb-up  {{top:6px;left:10px;color:{upstream_c}}}
#lb-dn  {{top:6px;right:10px;color:{downstream_c}}}
#lb-comp{{bottom:6px;left:50%;transform:translateX(-50%);color:{competitor_c}}}
#lb-tip {{bottom:6px;right:10px;color:#888;font-weight:400;font-size:10px}}
</style></head>
<body>
<div id="mini"></div>
<div class="lbl" id="lb-up">↑ 上游供应商</div>
<div class="lbl" id="lb-dn">下游客户 ↑</div>
<div class="lbl" id="lb-comp">-- 竞争对手 --</div>
<div class="lbl" id="lb-tip">可拖拽 · 滚轮缩放</div>
<script>
var ORIG  = {j_orig};
var NMETA = {j_nmeta};
var nodesArr = {j_nodes};
var edgesArr = {j_edges};

var eMeta = {{}};
edgesArr.forEach(function(e){{
  eMeta[e.id || (e.from+'___'+e.to)] = {{
    color: (e.color && e.color.color) ? e.color.color : '#aaa',
    width: e.width || 2.0
  }};
}});

var nodes   = new vis.DataSet(nodesArr);
var edges   = new vis.DataSet(edgesArr);
var network = new vis.Network(
  document.getElementById('mini'),
  {{nodes:nodes, edges:edges}},
  {j_opts}
);

network.on('hoverNode', function(p){{
  var id    = p.node;
  var ceArr = network.getConnectedEdges(id);
  var ceSet = new Set(ceArr);
  var nbSet = new Set(network.getConnectedNodes(id));
  nbSet.add(id);

  var nbColor = {{}};
  edges.get(ceArr).forEach(function(e){{
    var eid = e.id || (e.from+'___'+e.to);
    var nb  = (e.from === id) ? e.to : e.from;
    nbColor[nb] = (eMeta[eid] && eMeta[eid].color) || ORIG[nb];
  }});

  nodes.update(nodes.get().map(function(n){{
    if(n.id === id){{
      return {{id:n.id,
              color:{{background:'#0d6efd',border:'#0a58ca',
                     hover:{{background:'#0d6efd',border:'#0a58ca'}}}},
              opacity:1}};
    }}else if(nbSet.has(n.id)){{
      var c = nbColor[n.id] || ORIG[n.id];
      return {{id:n.id,
              color:{{background:c,border:c,hover:{{background:c,border:c}}}},
              opacity:1}};
    }}else{{
      return {{id:n.id,
              color:{{background:'#e0e0ea',border:'#ccc',
                     hover:{{background:'#e0e0ea',border:'#ccc'}}}},
              opacity:0.2}};
    }}
  }}));

  nodes.getIds().forEach(function(nid){{
    var bn = network.body.nodes[nid];
    if(!bn) return;
    if(nid === id){{
      bn.setOptions({{font:{{color:'#0d6efd',size:(NMETA[nid]&&NMETA[nid].fontSize||12)+2,bold:true}}}});
    }}else if(nbSet.has(nid)){{
      var c = nbColor[nid] || ORIG[nid];
      bn.setOptions({{font:{{color:c,size:(NMETA[nid]&&NMETA[nid].fontSize||12)+1,bold:true}}}});
    }}else{{
      bn.setOptions({{font:{{color:'#ccc',size:10,bold:false}}}});
    }}
  }});
  network.redraw();

  edges.update(edges.get().map(function(e){{
    var eid = e.id || (e.from+'___'+e.to);
    if(ceSet.has(e.id)){{
      return {{id:e.id,color:{{color:(eMeta[eid]&&eMeta[eid].color)||'#aaa',inherit:false,opacity:1}},width:3.0}};
    }}else{{
      return {{id:e.id,color:{{color:'#e0e0ea',inherit:false,opacity:0.1}},width:0.5}};
    }}
  }}));
}});

network.on('blurNode', function(){{
  nodes.update(nodes.get().map(function(n){{
    return {{id:n.id,
            color:{{background:ORIG[n.id],border: n.id==='{focal_ticker}' ? '#222':'#fff',
                   hover:{{background:ORIG[n.id],border:'#000'}}}},
            opacity:1}};
  }}));
  nodes.getIds().forEach(function(nid){{
    var bn = network.body.nodes[nid];
    if(!bn) return;
    bn.setOptions({{font:{{color:'#111',size:NMETA[nid]&&NMETA[nid].fontSize||12,bold:false}}}});
  }});
  network.redraw();
  edges.update(edges.get().map(function(e){{
    var eid = e.id || (e.from+'___'+e.to);
    return {{id:e.id,color:{{color:(eMeta[eid]&&eMeta[eid].color)||'#aaa',inherit:false,opacity:1}},
            width:(eMeta[eid]&&eMeta[eid].width)||2.0}};
  }}));
}});

network.fit({{animation:{{duration:400,easingFunction:'easeInOutQuad'}}}});
</script></body></html>"""
