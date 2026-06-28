export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  if (!parentElement) return;

  const args = (data && data.payload) || {};
  const height = (data && data.height) || args.height || 620;
  const mode = args.mode || "full";

  const rootEl = parentElement.querySelector(".vis-map-root");
  const netEl = parentElement.querySelector("#net");
  const tipEl = parentElement.querySelector("#tip");
  const labelsEl = parentElement.querySelector("#labels");
  if (!rootEl || !netEl) return;

  rootEl.classList.toggle("mode-mini", mode === "mini");
  rootEl.classList.toggle("mode-full", mode !== "mini");
  netEl.style.height = height + "px";

  function renderGraph(vis) {
    const focal = args.focal || "";
    const ORIG = args.orig || {};
    const NMETA = args.nmeta || {};
    const eMeta = {};
    (args.edges || []).forEach(function (e) {
      eMeta[e.id] = {
        color: (e.color && e.color.color) ? e.color.color : "#aaa",
        width: e.width || 1.8,
      };
    });

    const nodes = new vis.DataSet(args.nodes || []);
    const edges = new vis.DataSet(args.edges || []);
    const network = new vis.Network(netEl, { nodes: nodes, edges: edges }, args.options || {});

    function resetFontColors() {
      nodes.getIds().forEach(function (nid) {
        const bn = network.body.nodes[nid];
        if (!bn || !NMETA[nid]) return;
        bn.setOptions({ font: { color: "#111", size: NMETA[nid].fontSize, bold: false } });
      });
      network.redraw();
    }

    function extendEquipment(nbSet, ceSet) {
      const EQUIP = "#e8a838";
      Array.from(nbSet).forEach(function (nid) {
        network.getConnectedEdges(nid).forEach(function (eid) {
          const e = edges.get(eid);
          if (e && eMeta[eid] && eMeta[eid].color === EQUIP) {
            ceSet.add(eid);
            nbSet.add(e.from === nid ? e.to : e.from);
          }
        });
      });
    }

    network.on("hoverNode", function (p) {
      const id = p.node;
      const ceSet = new Set(network.getConnectedEdges(id));
      const nbSet = new Set(network.getConnectedNodes(id));
      nbSet.add(id);
      extendEquipment(nbSet, ceSet);

      const nbColor = {};
      edges.get(Array.from(ceSet)).forEach(function (e) {
        [e.from, e.to].forEach(function (nid) {
          if (nid !== id && nbSet.has(nid) && !nbColor[nid]) {
            nbColor[nid] = eMeta[e.id].color;
          }
        });
      });

      nodes.update(nodes.get().map(function (n) {
        if (n.id === id) {
          return { id: n.id, color: { background: "#0d6efd", border: "#0a58ca" }, opacity: 1 };
        }
        if (nbSet.has(n.id)) {
          const c = nbColor[n.id] || ORIG[n.id];
          return { id: n.id, color: { background: c, border: c }, opacity: 1 };
        }
        return { id: n.id, color: { background: "#e0e0ea", border: "#ccc" }, opacity: mode === "mini" ? 0.2 : 0.18 };
      }));

      nodes.getIds().forEach(function (nid) {
        const bn = network.body.nodes[nid];
        if (!bn || !NMETA[nid]) return;
        if (nid === id) {
          bn.setOptions({ font: { color: "#0d6efd", size: NMETA[nid].fontSize + 2, bold: true } });
        } else if (nbSet.has(nid)) {
          const c = nbColor[nid] || ORIG[nid];
          bn.setOptions({ font: { color: c, size: NMETA[nid].fontSize + 1, bold: true } });
        } else {
          bn.setOptions({ font: { color: "#ccc", size: 10, bold: false } });
        }
      });
      network.redraw();

      setTimeout(function () {
        edges.update(edges.get().map(function (e) {
          if (ceSet.has(e.id)) {
            return { id: e.id, color: { color: eMeta[e.id].color, inherit: false, opacity: 1 }, width: 3.0 };
          }
          return { id: e.id, color: { color: "#e0e0ea", inherit: false, opacity: 0.1 }, width: 0.5 };
        }));
      }, 30);
    });

    network.on("blurNode", function () {
      nodes.update(nodes.get().map(function (n) {
        let border = (mode === "mini" && n.id === focal) ? "#222" : (NMETA[n.id] ? NMETA[n.id].borderColor : "#fff");
        if (mode === "mini" && n.id !== focal) border = "#fff";
        return { id: n.id, color: { background: ORIG[n.id], border: border }, opacity: 1 };
      }));
      resetFontColors();
      edges.update(edges.get().map(function (e) {
        return { id: e.id, color: { color: eMeta[e.id].color, inherit: false, opacity: 1 }, width: eMeta[e.id].width };
      }));
    });

    network.on("click", function (p) {
      if (p.nodes.length > 0) {
        setTriggerValue("clicked", p.nodes[0]);
      }
    });

    if (labelsEl) {
      labelsEl.innerHTML = "";
      if (mode === "mini" && args.labels && args.labels.length) {
        args.labels.forEach(function (lb) {
          const el = document.createElement("div");
          el.className = "lbl";
          el.textContent = lb.text;
          el.style.color = lb.color || "#666";
          if (lb.top) el.style.top = lb.top;
          if (lb.bottom) el.style.bottom = lb.bottom;
          if (lb.left) el.style.left = lb.left;
          if (lb.right) el.style.right = lb.right;
          if (lb.transform) el.style.transform = lb.transform;
          labelsEl.appendChild(el);
        });
      }
    }

    if (tipEl) {
      if (mode === "mini") {
        tipEl.textContent = "";
        tipEl.style.display = "none";
        network.fit({ animation: { duration: 400, easingFunction: "easeInOutQuad" } });
      } else {
        tipEl.textContent = "悬停高亮邻居 · 点击进入公司详情 · 滚轮缩放";
        tipEl.style.display = "block";
      }
    }
  }

  function ensureVis(cb) {
    if (window.vis && window.vis.Network) {
      cb(window.vis);
      return;
    }
    const existing = document.querySelector('script[data-vis-map-lib="1"]');
    if (existing) {
      existing.addEventListener("load", function () { cb(window.vis); });
      return;
    }
    const s = document.createElement("script");
    s.src = "https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js";
    s.dataset.visMapLib = "1";
    s.onload = function () { cb(window.vis); };
    s.onerror = function () {
      if (tipEl) {
        tipEl.textContent = "地图库加载失败，请检查网络连接";
        tipEl.style.display = "block";
      }
    };
    document.head.appendChild(s);
  }

  ensureVis(renderGraph);
}
