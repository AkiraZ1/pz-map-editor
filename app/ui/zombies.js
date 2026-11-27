// Ferramenta Zumbis: densidade por chunk (8x8). Modos pintar / somar / tirar / conta-gotas (Alt+clique),
// pincel redondo com borda suave opcional (tamanho no painel ou [ ]), retangulo (Shift+arrastar), preencher/limpar tudo.
"use strict";
(() => {
  const { S, api, h, $, say } = window.PZMS;
  const CH = 8, NCH = 32;
  const LEVELS = [["nenhuma", 0], ["baixa", 1], ["media", 3], ["alta", 6]];
  const VANILLA_MAX = 10;
  const Z = {
    level: "media", num: 3, cells: new Map(), // "cx,cy" -> Uint8Array(1024)
    stroke: null, key: null, proj: null, loading: false, show: false,
    mode: "pintar", soft: false, base: null,
  };
  try {
    Z.show = localStorage.getItem("pzms.zombies.show") === "1";
    Z.soft = localStorage.getItem("pzms.zombies.soft") === "1";
  } catch (e) { /* sem storage */ }
  const keep = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* sem storage */ } };

  const value = () => Math.max(0, Math.min(255, Z.num | 0));
  const levelName = v => (LEVELS.find(l => l[1] === v) || [String(v)])[0];
  function chunkVal(a, b) {
    const cx = Math.floor(a / NCH), cy = Math.floor(b / NCH), d = Z.cells.get(cx + "," + cy);
    return d ? d[(a - cx * NCH) * NCH + (b - cy * NCH)] : 0;
  }
  function inCells(a, b) {
    return S.state.project.cells.some(c => c[0] === Math.floor(a / NCH) && c[1] === Math.floor(b / NCH));
  }
  // valor final de um chunk tocado com forca f (0..1, 1 no centro do pincel)
  function target(old, f) {
    const v = value();
    if (Z.mode === "somar") return Math.min(255, old + Math.max(1, Math.round(v * f)));
    if (Z.mode === "tirar") return Math.max(0, old - Math.max(1, Math.round(v * f)));
    return Math.round(old + (v - old) * f);
  }
  const b64 = s => { const r = atob(s), a = new Uint8Array(1024); for (let i = 0; i < r.length && i < 1024; i++) a[i] = r.charCodeAt(i); return a; };
  function setCells(obj, replaceAll) {
    if (replaceAll) Z.cells.clear();
    for (const [k, v] of Object.entries(obj || {})) { if (v) Z.cells.set(k, b64(v)); else Z.cells.delete(k); }
    S.needDraw = true;
    const el = document.querySelector("#toolopts .zsum");
    if (el) el.textContent = summary();
  }
  async function reload() {
    if (!S.state || !S.state.project || Z.loading) return;
    Z.loading = true;
    try { setCells((await api("/api/zombies")).cells, true); } catch (e) { /* sem projeto */ }
    Z.loading = false;
  }
  // undo/redo/abrir projeto: o app.js nao avisa densidade (-2) a modulos; detecta pela pilha e recarrega
  const keyOf = p => `${p.path}|${p.undo}|${p.redo}|${p.nu}|${p.nr}|${p.cells.length}`;
  function watch(p) {
    const key = keyOf(p);
    if (p.path !== Z.proj) { Z.proj = p.path; Z.key = key; Z.cells.clear(); reload(); return; }
    if (key !== Z.key && !Z.stroke) { Z.key = key; clearTimeout(Z.t); Z.t = setTimeout(reload, 80); }
  }
  window.PZMS_onDensity = reload;   // gancho opcional: applyChanged pode chamar quando vier -2

  // pincel redondo (1-2 = quadrado); cada chunk com a forca f: 1, ou caindo ate ~0,25 na borda (suave)
  function brushChunks(sq) {
    const n = Math.max(1, S.brush | 0), r = n >> 1, a = Math.floor(sq[0] / CH) - r, b = Math.floor(sq[1] / CH) - r, out = [];
    const c = (n - 1) / 2, R = n / 2;
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
      const d = Math.hypot(i - c, j - c);
      if (n > 2 && d > R) continue;
      out.push([a + i, b + j, Z.soft && n > 2 ? Math.max(0.25, 1 - d / R) : 1]);
    }
    return out;
  }
  function localPaint(chunks, v) {
    const cellset = new Set(S.state.project.cells.map(c => c[0] + "," + c[1]));
    for (const [a, b] of chunks) {
      const cx = Math.floor(a / NCH), cy = Math.floor(b / NCH), k = cx + "," + cy;
      if (!cellset.has(k)) continue;
      let d = Z.cells.get(k); if (!d) { d = new Uint8Array(1024); Z.cells.set(k, d); }
      d[(a - cx * NCH) * NCH + (b - cy * NCH)] = v;
    }
    S.needDraw = true;
  }
  // traco: cada chunk guarda o valor de antes (Z.base) e a maior forca que recebeu; somar/tirar conta 1x por traco
  function addStroke(sq) {
    const c0 = [Math.floor(sq[0] / CH), Math.floor(sq[1] / CH)], l = Z.last || c0, cs = [];
    const n = Math.max(Math.abs(c0[0] - l[0]), Math.abs(c0[1] - l[1]), 1);   // sem buracos com mouse rapido
    for (let i = 1; i <= n; i++) cs.push(...brushChunks([Math.round(l[0] + (c0[0] - l[0]) * i / n) * CH, Math.round(l[1] + (c0[1] - l[1]) * i / n) * CH]));
    Z.last = c0;
    for (const [a, b, f] of cs) {
      if (!inCells(a, b)) continue;
      const k = a + "," + b;
      if (!Z.base.has(k)) Z.base.set(k, chunkVal(a, b));
      const prev = Z.stroke.get(k);
      if (prev && prev[2] >= f) continue;
      const t = [a, b, f, target(Z.base.get(k), f)];
      Z.stroke.set(k, t);
      localPaint([[a, b]], t[3]);
    }
  }
  const label = extra => `zumbis ${Z.mode === "pintar" ? levelName(value()) : (Z.mode === "somar" ? "+" : "-") + value()}${extra ? ` (${extra})` : ""}`;
  async function send(body) {
    try {
      const r = await api("/api/zombies/paint", { value: value(), label: label(), ...body });
      setCells(r.cells);
      S.state.project.undo = r.undo; S.state.project.redo = r.redo; S.state.project.nu = r.nu; S.state.project.nr = r.nr;
      S.state.project.dirty = true;
      window.PZMS.afterState();
      Z.key = keyOf(S.state.project);
      if (!r.changed.length) say("nada mudou (fora das celulas ou mesmo valor)");
    } catch (e) { say(e.message, true); reload(); }
  }

  function color(v, a) {
    const t = Math.min(1, v / VANILLA_MAX);                     // amarelo -> laranja -> vermelho; acima de 10 roxo
    if (v > VANILLA_MAX) return `rgba(190,60,220,${a})`;
    return `rgba(${235},${Math.round(215 - 175 * t)},${Math.round(70 - 40 * t)},${a})`;
  }
  const visible = () => S.tool === "zombie" || Z.show;

  window.PZMS_OVERLAYS = window.PZMS_OVERLAYS || [];
  window.PZMS_OVERLAYS.push((ctx, { diamond, toScreen, z, CS, project }) => {
    watch(project);
    if (!visible()) return;
    const W = ctx.canvas.width / (window.devicePixelRatio || 1), H = ctx.canvas.height / (window.devicePixelRatio || 1);
    for (const [k, d] of Z.cells) {
      const [cx, cy] = k.split(",").map(Number);
      const P = [[0, 0], [CS, 0], [0, CS], [CS, CS]].map(([a, b]) => toScreen(cx * CS + a, cy * CS + b, z));
      const xs = P.map(p => p[0]), ys = P.map(p => p[1]);
      if (Math.max(...xs) < 0 || Math.min(...xs) > W || Math.max(...ys) < 0 || Math.min(...ys) > H) continue;
      for (let ci = 0; ci < 1024; ci++) {
        const v = d[ci]; if (!v) continue;
        ctx.fillStyle = color(v, 0.18 + 0.32 * Math.min(1, v / VANILLA_MAX));
        diamond(ctx, cx * CS + (ci >> 5) * CH, cy * CS + (ci & 31) * CH, CH, CH); ctx.fill();
      }
    }
    if (S.tool === "zombie" && S.hover && !(S.drag && S.drag.shift)) {   // contorno do pincel (chunks dele)
      ctx.strokeStyle = Z.mode === "tirar" ? "rgba(140,200,255,.9)" : color(value() || 1, 0.95); ctx.lineWidth = 1.5;
      if (Z.mode !== "conta-gotas") for (const [a, b, f] of brushChunks(S.hover)) {
        ctx.globalAlpha = 0.35 + 0.65 * f; diamond(ctx, a * CH, b * CH, CH, CH); ctx.stroke();
      }
      ctx.globalAlpha = 1;
      const a = Math.floor(S.hover[0] / CH), b = Math.floor(S.hover[1] / CH), v = chunkVal(a, b);
      const [sx, sy] = toScreen(S.hover[0] + 0.5, S.hover[1] + 0.5, z);
      const t = `chunk ${a},${b}: ${v}${v > VANILLA_MAX ? " (acima do vanilla)" : ""}`;
      ctx.font = "12px system-ui, sans-serif"; ctx.textAlign = "left";
      const w = ctx.measureText(t).width;
      ctx.fillStyle = "rgba(15,17,20,.85)"; ctx.fillRect(sx + 12, sy + 10, w + 10, 18);
      ctx.fillStyle = "#e8e8e8"; ctx.fillText(t, sx + 17, sy + 23);
    }
  });

  function legend() {
    const box = h("span", { class: "zlegend" });
    for (const [n, v] of [["1", 1], ["3", 3], ["6", 6], ["10", 10], [">10", 11]]) {
      const sw = h("span", { title: `densidade ${n}` }, n);
      sw.style.cssText = `display:inline-block;padding:0 5px;margin-right:2px;border-radius:3px;color:#111;background:${color(v, 0.9)}`;
      box.append(sw);
    }
    return box;
  }

  function summary() {
    let n = 0, hot = 0, mx = 0, sum = 0;
    for (const d of Z.cells.values()) for (const v of d) if (v) { n++; sum += v; if (v > VANILLA_MAX) hot++; if (v > mx) mx = v; }
    const tot = S.state && S.state.project ? S.state.project.cells.length * 1024 : 0;
    return n ? `${n} de ${tot} chunks com zumbis (${(100 * n / Math.max(1, tot)).toFixed(1)}%), media ${(sum / n).toFixed(1)}, max ${mx}` +
      (hot ? `, ${hot} acima do vanilla` : "") : "mapa sem zumbis pintados";
  }
  function pick(sq) {
    Z.num = chunkVal(Math.floor(sq[0] / CH), Math.floor(sq[1] / CH));
    if (Z.mode === "conta-gotas") Z.mode = "pintar";
    say(`densidade ${Z.num} (${levelName(Z.num)})`);
    window.PZMS.setTool("zombie");
  }

  window.PZMS_TOOLS = window.PZMS_TOOLS || {};
  window.PZMS_TOOLS.zombie = {
    key: "z",
    get rect() { return !!(S.drag && S.drag.shift); },
    opts() {
      const re = () => window.PZMS.setTool("zombie");
      const modes = ["pintar", "somar", "tirar", "conta-gotas"].map(m => h("button", {
        class: Z.mode === m ? "on" : "", title: { pintar: "define a densidade", somar: "soma ao que ja tem", tirar: "subtrai do que ja tem",
          "conta-gotas": "pega a densidade de um chunk (ou Alt+clique em qualquer modo)" }[m], onclick: () => { Z.mode = m; re(); } }, m));
      const val = h("input", { type: "range", min: 0, max: 20, value: Math.min(20, Z.num), style: "width:110px" });
      const num = h("input", { type: "number", min: 0, max: 255, value: Z.num, style: "width:4.2em" });
      const presets = LEVELS.map(([k, v]) => h("button", { class: Z.num === v ? "on" : "", "data-v": v, title: `${k} = ${v}`, onclick: () => { Z.num = v; re(); } }, k));
      const sync = v => { Z.num = Math.max(0, Math.min(255, v | 0)); num.value = Z.num; val.value = Math.min(20, Z.num); presets.forEach(b => b.classList.toggle("on", +b.dataset.v === Z.num)); S.needDraw = true; };
      val.addEventListener("input", () => sync(+val.value));
      num.addEventListener("input", () => sync(+num.value));
      const bs = h("input", { type: "range", min: 1, max: 24, value: Math.max(1, S.brush | 0), style: "width:90px" });
      const bl = h("span", {}, `${Math.max(1, S.brush | 0)}`);
      bs.addEventListener("input", () => { S.brush = +bs.value; bl.textContent = bs.value; S.needDraw = true; });
      const soft = h("button", { class: Z.soft ? "on" : "", title: "borda do pincel vai sumindo (transicao entre areas)", onclick: () => {
        Z.soft = !Z.soft; keep("pzms.zombies.soft", Z.soft ? "1" : "0"); re(); } }, "borda suave");
      const show = h("button", { class: Z.show ? "on" : "", title: "mostrar o calor com outras ferramentas", onclick: () => {
        Z.show = !Z.show; keep("pzms.zombies.show", Z.show ? "1" : "0"); re(); } }, "calor sempre");
      const all = h("button", { title: "aplica a densidade atual no mapa inteiro (Ctrl+Z desfaz)", onclick: () =>
        send({ all: true, value: value(), label: `zumbis: mapa inteiro ${value()}` }) }, "preencher tudo");
      const clr = h("button", { title: "zera todo o mapa (Ctrl+Z desfaz)", onclick: () => send({ all: true, value: 0, label: "zumbis: limpar tudo" }) }, "limpar tudo");
      return [h("label", {}, "Modo"), ...modes,
        h("label", {}, "Densidade"), ...presets, val, num,
        h("label", {}, "Pincel"), bs, bl, h("span", { class: "zdim", style: "color:var(--dim)" }, "chunks  [ ]"), soft,
        legend(), show, all, clr,
        h("label", { class: "zsum", title: "valores medidos nos lotheaders vanilla do B42: cidade 3-4, centro 6-10" }, summary()),
        h("label", { class: "zdim", style: "color:var(--dim)" }, "Shift+arrastar = retangulo  -  Alt+clique = conta-gotas")];
    },
    down(sq, e) {
      if (e.altKey || Z.mode === "conta-gotas") { S.drag = null; return pick(sq); }
      if (e.shiftKey) return;                        // retangulo: decide no up
      Z.stroke = new Map(); Z.base = new Map(); Z.last = null; addStroke(sq);
    },
    move(sq) { if (Z.stroke) addStroke(sq); },
    async up(a, b, e) {
      if (Z.stroke) {
        const values = [...Z.stroke.values()].map(([x, y, , v]) => [x, y, v]); Z.stroke = null; Z.base = null;
        if (values.length) await send({ values, label: label("pincel") });
      } else if (Z.mode !== "conta-gotas" && !(e && e.altKey)) {
        const r = window.PZMS.rectOf(a, b), values = [];
        for (let x = r[0] >> 3; x <= r[2] >> 3; x++) for (let y = r[1] >> 3; y <= r[3] >> 3; y++)
          if (inCells(x, y)) values.push([x, y, target(chunkVal(x, y), 1)]);
        for (const [x, y, v] of values) localPaint([[x, y]], v);
        if (values.length) await send({ values, label: label("area") });
      }
    },
  };
})();
