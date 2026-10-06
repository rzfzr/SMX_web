// Interactive SMX predicate graph (after DPG_web's assets/graph.js; Cytoscape only, no dagre).
// mountSMXGraph(host, data) renders graph JSON as written by smx_sandbox.graph_data()
// (sandbox/smx_sandbox.py, also used by scripts/export_quickstart_graph.py). Elements with a
// data-smx-src attribute are mounted automatically; if that fails their content stays.
(() => {
  if (typeof cytoscape !== "function") return; // keep any static fallback content

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const fmt = (x) => (x == null ? "–" : x === 0 ? "0" : Math.abs(x) < 0.01 ? x.toExponential(2) : x.toFixed(3).replace(/0+$/, "").replace(/\.$/, ""));
  const FONT = "Outfit, system-ui, sans-serif";
  const touch = matchMedia("(hover: none)").matches;
  const measure = document.createElement("canvas").getContext("2d");
  const textWidth = (t, bold) => { measure.font = `${bold ? 700 : 500} 13px ${FONT}`; return measure.measureText(t).width; };

  // zones take the categorical colours in order (background zones stay neutral); class nodes are drawn in ink
  const PALETTE = ["--z1", "--z2", "--z3", "--z4", "--z5", "--z6", "--z7", "--z8"];
  const isBackground = (zone) => /^background/i.test(zone || ""); // building_spectral_zones() names them background1, …
  const textOn = (hex) => {
    const m = /^#?([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(hex); if (!m) return "#10142b";
    const [r, g, b] = m.slice(1).map((h) => { const c = parseInt(h, 16) / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.2 ? "#10142b" : "#ffffff";
  };
  const RAMP = ["#eef3ff", "#d4e2ff", "#b2c9ff", "#8eabfb", "#6a8af0", "#4a68dc", "#3049c0", "#1b2c96"];

  function mount(host, data, { label = "Interactive SMX predicate graph" } = {}) {
    if (host._smxDestroy) host._smxDestroy();
    const $ = (sel) => host.querySelector(sel);
    const weights = data.edges.map((e) => e.weight || 0);
    const wMin = weights.length ? Math.min(...weights) : 0, wMax = weights.length ? Math.max(...weights) : 1;
    const sMin = Math.sqrt(wMin), sMax = Math.max(Math.sqrt(wMax), sMin + 1e-12);
    // LRC is heavy-tailed: colour on a log scale between the smallest positive value and the largest
    const lrcs = data.nodes.filter((n) => !n.isClass && n.lrc > 0).map((n) => n.lrc);
    const lMax = lrcs.length ? Math.max(...lrcs) : 1, lMin = lrcs.length ? Math.min(...lrcs) : 1;
    const lrcT = (v) => (!(v > 0) ? 0 : lMax === lMin ? 1 : (Math.log(v) - Math.log(lMin)) / (Math.log(lMax) - Math.log(lMin)));
    const featureZones = data.zones.filter((z) => !isBackground(z));
    const zoneFill = (z) => {
      const i = featureZones.indexOf(z);
      return i >= 0 ? css(PALETTE[i % PALETTE.length]) : css("--g-bg-fill");
    };

    host.classList.add("live");
    host.innerHTML = `
      <div class="g-toolbar">
        <div class="seg" role="group" aria-label="Colour nodes by">
          <button type="button" data-mode="zone" aria-pressed="true">Zones</button>
          <button type="button" data-mode="lrc" aria-pressed="false">LRC</button>
          <button type="button" data-mode="plain" aria-pressed="false">Plain</button>
        </div>
        <div class="seg" role="group" aria-label="Layout">
          <button type="button" data-layout="tree" aria-pressed="true">Tree</button>
          <button type="button" data-layout="rings" aria-pressed="false">Rings</button>
        </div>
        <div class="g-zoom">
          <button type="button" data-zoom="out" aria-label="Zoom out">−</button>
          <button type="button" data-zoom="in" aria-label="Zoom in">+</button>
          <button type="button" data-zoom="fit">Fit</button>
        </div>
      </div>
      <div class="g-stage">
        <div class="g-cy" role="img" aria-label="${esc(label)}"></div>
        <div class="g-hint" aria-live="polite"></div>
        ${touch ? `<button type="button" class="g-cover"><span>Tap to explore the graph</span></button><button type="button" class="g-done" hidden>Done</button>` : ""}
        <aside class="g-side" hidden></aside>
      </div>
      <div class="g-legend"></div>`;

    const cyEl = $(".g-cy"), side = $(".g-side"), hint = $(".g-hint"), legend = $(".g-legend");
    let mode = "zone", pinned = null, active = false;
    // Tree: breadth-first from the predicates nothing points to, so paths run top to bottom into the
    // class nodes. Rings: concentric by LRC, the most central predicates in the middle.
    const layouts = {
      tree: (cy) => {
        let roots = cy.nodes("[isClass = 0]").filter((n) => n.indegree() === 0);
        if (!roots.length) roots = cy.nodes("[isClass = 0]").max((n) => n.data("lrc") || 0).ele;
        return { name: "breadthfirst", directed: true, roots, spacingFactor: 0.8, avoidOverlap: true };
      },
      rings: () => ({
        name: "concentric", minNodeSpacing: 6, spacingFactor: 0.9, levelWidth: () => 0.6,
        concentric: (n) => (n.data("isClass") ? -1 : Math.log10(n.data("lrc") || 1e-6)),
      }),
    };
    const elements = [
      ...data.nodes.map((n) => ({ data: { ...n, isClass: n.isClass ? 1 : 0, w: textWidth(n.label, n.isClass) + 22, ...colours(n) } })),
      ...data.edges.map((e, i) => ({ data: { id: `e${i}`, ...e, sw: Math.sqrt(e.weight || 0), wlabel: fmt(e.weight) } })),
    ];

    const style = () => {
      const lo = css("--g-edge-lo"), hi = css("--g-edge-hi");
      return [
        { selector: "node", style: {
          shape: "round-rectangle", width: "data(w)", height: 30, label: "data(label)",
          "font-family": FONT, "font-size": 13, "font-weight": 500, "text-valign": "center", "text-halign": "center",
          "background-color": "data(fill)", color: "data(text)", "border-width": 1.5, "border-color": css("--g-node-border"),
        } },
        { selector: "node[isClass = 1]", style: {
          "background-color": css("--g-class-fill"), color: css("--g-class-text"), "font-weight": 700,
          "border-width": 4, "border-color": css("--sky"), height: 34,
        } },
        { selector: "edge", style: {
          width: `mapData(sw, ${sMin}, ${sMax}, 1, 7)`, "curve-style": "bezier",
          "line-color": `mapData(sw, ${sMin}, ${sMax}, ${lo}, ${hi})`,
          "target-arrow-color": `mapData(sw, ${sMin}, ${sMax}, ${lo}, ${hi})`,
          "target-arrow-shape": "triangle", "arrow-scale": 0.8,
          "font-family": FONT, "font-size": 11, "font-weight": 600, color: css("--ink"),
          "text-background-color": css("--g-bg"), "text-background-opacity": 0.9, "text-background-padding": "2px",
        } },
        { selector: ".faded", style: { opacity: 0.1 } },
        { selector: "edge.hl", style: { "line-color": css("--g-accent"), "target-arrow-color": css("--g-accent"), label: "data(wlabel)", "z-index": 9 } },
        { selector: "node.focus", style: { "border-width": 4, "border-color": css("--g-accent") } },
      ];
    };

    function colours(d) {
      let fill = css("--g-plain-fill"), text = css("--ink");
      if (!d.isClass && mode === "zone") { fill = zoneFill(d.zone); text = textOn(fill); }
      if (!d.isClass && mode === "lrc") {
        fill = RAMP[Math.round(lrcT(d.lrc) * (RAMP.length - 1))];
        text = textOn(fill);
      }
      return { fill, text };
    }
    function paint() {
      cy.batch(() => cy.nodes().forEach((n) => n.data(colours(n.data()))));
      renderLegend();
    }

    function renderLegend() {
      const sw = (c) => `<span class="sw" style="background:${c}"></span>`;
      let html = "";
      if (mode === "zone") {
        html += data.zones.map((z) => {
          const k = data.nodes.filter((n) => !n.isClass && n.zone === z).length;
          return k ? `<span>${sw(zoneFill(z))}${esc(z)} <span class="muted">(${k})</span></span>` : "";
        }).join("");
      } else if (mode === "lrc") {
        html += `<span>LRC ${fmt(lMin)}<span class="ramp" style="background:linear-gradient(90deg,${RAMP.join(",")})"></span>${fmt(lMax)} <span class="muted">(log scale)</span></span>`;
      } else {
        html += `<span>${sw(css("--g-plain-fill"))}predicate</span>`;
      }
      html += `<span>${sw(css("--g-class-fill"))}class</span><span>edge width = accumulated perturbation impact (${fmt(wMin)}–${fmt(wMax)})</span>`;
      legend.innerHTML = html;
    }

    const cy = cytoscape({
      container: cyEl, elements, style: style(), minZoom: 0.06, maxZoom: 3,
      userZoomingEnabled: false, boxSelectionEnabled: false, autoungrabify: true,
    });
    cy.layout(layouts.tree(cy)).run();
    paint();
    host._cy = cy; // handy from the devtools console
    const fit = (animate) => (animate ? cy.animate({ fit: { padding: 24 }, duration: 250 }) : cy.fit(undefined, 24));
    // Big graphs are unreadable when fit whole: open them at a readable zoom on the top of the tree,
    // where the highest-ranked predicates are. "Fit" still shows everything.
    const MIN_OPEN_ZOOM = 0.6;
    function openView() {
      cy.fit(undefined, 24);
      if (cy.zoom() >= MIN_OPEN_ZOOM) return;
      const bb = cy.elements().boundingBox();
      cy.viewport({ zoom: MIN_OPEN_ZOOM, pan: { x: cy.width() / 2 - ((bb.x1 + bb.x2) / 2) * MIN_OPEN_ZOOM, y: 24 - bb.y1 * MIN_OPEN_ZOOM } });
    }
    openView();
    setHint();

    // ---- interaction ------------------------------------------------------
    function highlight(node) {
      cy.batch(() => {
        cy.elements().removeClass("faded hl focus");
        if (!node) return;
        const path = node.predecessors().union(node.successors()).union(node);
        cy.elements().not(path).addClass("faded");
        path.edges().addClass("hl");
        node.addClass("focus");
      });
    }

    function details(node) {
      if (!node) { side.hidden = true; return; }
      const d = node.data();
      const item = (e, other) => `<li><button type="button" data-id="${esc(other.id())}">${esc(other.data("label"))}</button><span>${e.data("wlabel")}</span></li>`;
      const ins = node.incomers("edge").sort((a, b) => b.data("weight") - a.data("weight"));
      const outs = node.outgoers("edge").sort((a, b) => b.data("weight") - a.data("weight"));
      const metrics = d.isClass ? "" : `<h5>Predicate</h5><dl>
          <dt>Zone</dt><dd><span class="sw" style="background:${zoneFill(d.zone)}"></span> ${esc(d.zone ?? "–")}</dd>
          <dt>Threshold (PC1 score)</dt><dd>${esc(d.op ?? "")} ${fmt(d.threshold)}</dd>
          ${d.natural != null ? `<dt>Natural-scale score</dt><dd>${esc(d.op ?? "")} ${fmt(d.natural)}</dd>` : ""}
        </dl>
        <h5>Local reaching centrality</h5><dl>
          <dt>This repetition</dt><dd>${fmt(d.lrc)}</dd>
          ${d.lrcMean != null ? `<dt>Mean over repetitions</dt><dd>${fmt(d.lrcMean)}</dd>` : ""}
          ${d.rank != null ? `<dt>Overall rank</dt><dd>#${d.rank}</dd>` : ""}
        </dl>`;
      side.innerHTML = `
        <button type="button" class="g-close" aria-label="Close details">×</button>
        <h4>${esc(d.label)}</h4>
        <p class="g-sub">${d.isClass ? "Class node: where the bags whose model output pointed to this class end" : "Predicate on a zone's PC1 score"}</p>
        ${metrics}
        <h5>Incoming (${ins.length})</h5><ul>${ins.map((e) => item(e, e.source())).join("") || "<li class='muted'>none, a starting predicate</li>"}</ul>
        <h5>Outgoing (${outs.length})</h5><ul>${outs.map((e) => item(e, e.target())).join("") || "<li class='muted'>none</li>"}</ul>`;
      side.hidden = false;
      side.scrollTop = 0;
      side.querySelector(".g-close").onclick = () => select(null);
      side.querySelectorAll("button[data-id]").forEach((b) => (b.onclick = () => select(cy.getElementById(b.dataset.id))));
    }

    // Centre the pinned node at a readable zoom in the area the details panel leaves free
    // (its paths stay highlighted; the panel lists its neighbours).
    const READABLE = 0.9;
    function focus(node) {
      const inset = getComputedStyle(side).position === "absolute" ? side.offsetWidth + 24 : 0;
      const z = Math.max(cy.zoom(), READABLE), p = node.position();
      cy.animate({ zoom: z, pan: { x: (cy.width() - inset) / 2 - p.x * z, y: cy.height() / 2 - p.y * z } }, { duration: 300 });
    }

    function select(node) {
      pinned = node && node.length ? node : null;
      highlight(pinned); details(pinned);
      if (pinned) focus(pinned);
    }

    cy.on("mouseover", "node", (e) => { if (!pinned) highlight(e.target); cyEl.style.cursor = "pointer"; });
    cy.on("mouseout", "node", () => { if (!pinned) highlight(null); cyEl.style.cursor = ""; });
    cy.on("tap", "node", (e) => select(pinned && pinned.same(e.target) ? null : e.target));
    cy.on("tap", (e) => { if (e.target === cy) select(null); });

    // Wheel zoom only once the graph is "active" (clicked) or with Ctrl/⌘, so page scrolling
    // over the graph keeps scrolling the page. On touch screens the cover does the same job.
    function setActive(on) {
      active = on;
      cy.userZoomingEnabled(on);
      host.classList.toggle("active", on);
      if (touch) { $(".g-cover").hidden = on; $(".g-done").hidden = !on; }
      setHint();
    }
    function setHint(msg) {
      hint.textContent = msg || (touch
        ? (active ? "Pinch to zoom · drag to pan · tap a node for details" : "")
        : (active ? "Scroll to zoom · drag to pan · hover a node to trace its paths · click for details"
          : `Click the graph to enable scroll-zoom · drag to pan${cy.zoom() > fitZoom() * 1.05 ? " · Fit shows the whole graph" : ""} · hover a node to trace its paths`));
    }
    function fitZoom() {
      const bb = cy.elements().boundingBox();
      return Math.min((cy.width() - 48) / Math.max(bb.w, 1), (cy.height() - 48) / Math.max(bb.h, 1));
    }
    let hintTimer = 0;
    cyEl.addEventListener("wheel", (e) => {
      if (active) return;
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const r = cyEl.getBoundingClientRect();
        const level = Math.min(cy.maxZoom(), Math.max(cy.minZoom(), cy.zoom() * Math.exp(-e.deltaY * 0.002)));
        cy.zoom({ level, renderedPosition: { x: e.clientX - r.left, y: e.clientY - r.top } });
        return;
      }
      setHint(`Click the graph first, or hold ${/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl"} while scrolling, to zoom`);
      host.classList.add("nudge");
      clearTimeout(hintTimer);
      hintTimer = setTimeout(() => { host.classList.remove("nudge"); setHint(); }, 1800);
    }, { passive: false });
    if (touch) {
      $(".g-cover").onclick = () => setActive(true);
      $(".g-done").onclick = () => { setActive(false); select(null); };
    } else {
      cyEl.addEventListener("mousedown", () => setActive(true));
      host.addEventListener("mouseleave", () => setActive(false));
    }

    host.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => {
      mode = b.dataset.mode;
      host.querySelectorAll("[data-mode]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      paint();
      if (pinned) details(pinned);
    }));
    host.querySelectorAll("[data-layout]").forEach((b) => (b.onclick = () => {
      host.querySelectorAll("[data-layout]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      cy.layout({ ...layouts[b.dataset.layout](cy), fit: false }).run();
      if (pinned) focus(pinned); else openView();
      setHint();
    }));
    host.querySelectorAll("[data-zoom]").forEach((b) => (b.onclick = () => {
      if (b.dataset.zoom === "fit") { fit(true); setTimeout(() => setHint(), 300); return; }
      const level = cy.zoom() * (b.dataset.zoom === "in" ? 1.35 : 1 / 1.35);
      cy.animate({ zoom: { level: Math.min(cy.maxZoom(), Math.max(cy.minZoom(), level)), renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } }, duration: 150 });
    }));

    // Re-read the theme colours when the light/dark toggle flips data-theme.
    const themeObserver = new MutationObserver(() => { cy.style(style()); paint(); if (pinned) details(pinned); });
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    let resizeTimer = 0;
    const onResize = () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { cy.resize(); if (!pinned) openView(); }, 150); };
    addEventListener("resize", onResize);

    host._smxDestroy = () => {
      themeObserver.disconnect();
      removeEventListener("resize", onResize);
      clearTimeout(resizeTimer); clearTimeout(hintTimer);
      cy.destroy();
      host._smxDestroy = null;
    };
    return cy;
  }

  window.mountSMXGraph = (host, data, opts) => (document.fonts ? document.fonts.ready : Promise.resolve()).then(() => mount(host, data, opts));

  document.querySelectorAll("[data-smx-src]").forEach((host) => {
    fetch(host.dataset.smxSrc)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => window.mountSMXGraph(host, data, { label: host.dataset.smxLabel }))
      .catch(() => {}); // the static fallback stays
  });
})();
