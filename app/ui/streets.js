// Ferramenta Ruas (U): ruas e avenidas como linhas de varios pontos.
//  - sem rua selecionada: cada clique poe um ponto; duplo clique ou Enter termina, Esc cancela
//  - com rua selecionada: arrastar um ponto move; arrastar a linha cria um ponto ali e arrasta;
//    Shift+arrastar a linha move a rua inteira; Alt+clique num ponto apaga o ponto; Delete apaga a rua
//  - clique em outra rua seleciona; clique no vazio tira a selecao
// O servidor rasteriza (asfalto, calcada, meio-fio, canto meio a meio nas diagonais) e guarda o chao de antes.
"use strict";
(() => {
  const { S, api, h, say, applyChanged } = window.PZMS;
  const R = {
    items: [], sel: null, draft: null, drag: null, key: null, proj: null, loading: false,
    opts: { name: "rua", width: 6, walk_on: true, side: 2, asph: 80, walk: 48, smooth: true, curbs: true,
            lanes: 1, dash: 3, line_color: 16, poles: false, pole_every: 12, pole: "lighting_outdoor_01_16" },
  };
  window.PZMS_STREETS = R;                                       // (depuracao)
  const FAMS = [0, 16, 32, 48, 64, 80, 96];
  const HIT = 9;                                                 // px

  const cur = () => R.items.find(i => i.id === R.sel) || null;
  const scr = (u, v) => S.gl.toScreen(u - 0.5, v - 0.5, 0);      // canto (u, v) -> tela (andar 0)
  const snap = f => [Math.round(f[0]), Math.round(f[1])];
  const tileOf = v => typeof v === "string" ? v : `blends_street_01_${v}`;

  function path(it) {
    const off = it.width % 2 ? 0.5 : 0;
    let P = it.pts.map(([x, y]) => [x + off, y + off]);
    if (it.smooth && P.length > 2) for (let n = 0; n < 3; n++) {
      const Q = [P[0]];
      for (let i = 0; i + 1 < P.length; i++) {
        const [ax, ay] = P[i], [bx, by] = P[i + 1];
        Q.push([0.75 * ax + 0.25 * bx, 0.75 * ay + 0.25 * by], [0.25 * ax + 0.75 * bx, 0.25 * ay + 0.75 * by]);
      }
      Q.push(P[P.length - 1]); P = Q;
    }
    return P;
  }
  function segDist(p, a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy || 1e-9;
    const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L));
    return [Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy), t];
  }
  function mouseScr() {
    if (!S.hoverF) return null;
    return scr(S.hoverF[0], S.hoverF[1]);
  }
  // ponto da rua sob o mouse (indice) ou trecho (indice do segmento de controle)
  function hitPoint(it, m) {
    for (let i = 0; i < it.pts.length; i++) { const p = scr(...it.pts[i]); if (Math.hypot(p[0] - m[0], p[1] - m[1]) < HIT) return i; }
    return -1;
  }
  function hitSeg(it, m) {                                       // dentro do asfalto (mundo) ou perto da linha (tela)
    let best = -1, bd = Infinity;
    const f = S.hoverF, half = it.width / 2 + 0.5;
    for (let i = 0; i + 1 < it.pts.length; i++) {
      const [dw] = f ? segDist(f, it.pts[i], it.pts[i + 1]) : [Infinity];
      const [ds] = segDist(m, scr(...it.pts[i]), scr(...it.pts[i + 1]));
      const d = dw < half ? dw : ds < HIT ? 0.01 : Infinity;
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }
  function hitStreet(m) {
    for (const it of [...R.items].reverse()) if (hitPoint(it, m) >= 0 || hitSeg(it, m) >= 0) return it;
    return null;
  }

  // ---- servidor
  async function reload() {
    if (!S.state || !S.state.project || R.loading) return;
    R.loading = true;
    try { const r = await api("/api/streets"); R.items = r.items; if (R.sel && !cur()) R.sel = null; } catch (e) { /* sem projeto */ }
    R.loading = false; refresh();
  }
  const keyOf = p => `${p.path}|${p.undo}|${p.redo}|${p.nu}|${p.nr}`;
  function watch(p) {
    const k = keyOf(p);
    if (p.path !== R.proj) { R.proj = p.path; R.key = k; R.items = []; R.sel = null; R.draft = null; reload(); return; }
    if (k !== R.key && !R.busy) { R.key = k; clearTimeout(R.t); R.t = setTimeout(reload, 80); }
  }
  async function send(body) {
    R.busy = true;
    try {
      const r = await api("/api/streets/set", body);
      R.items = r.items;
      if (body.delete) R.sel = null; else R.sel = r.id;
      await applyChanged(r);
      R.key = keyOf(S.state.project);
    } catch (e) { say(e.message, true); await reload(); }
    R.busy = false; refresh();
  }
  const save = (it, label) => send({ item: it, label });
  // mudancas do painel entram numa fila e cada uma parte da rua mais nova (antes, dois cliques seguidos
  // mandavam a rua velha e o 2o desfazia o 1o: "so aparecia quando mexia em outra coisa")
  R.chain = Promise.resolve();
  function patch(id, k, v) {
    R.chain = R.chain.then(async () => {
      const it = R.items.find(i => i.id === id);
      if (it && it[k] !== v) await save({ ...it, [k]: v }, `${it.name}: ${k}`);
    });
    return R.chain;
  }

  function refresh() { S.needDraw = true; if (S.tool === "street") window.PZMS.setTool("street"); }

  // ---- desenho
  window.PZMS_OVERLAYS = window.PZMS_OVERLAYS || [];
  window.PZMS_OVERLAYS.push((ctx, { project }) => {
    watch(project);
    if (S.tool !== "street") return;
    const m = mouseScr();
    const line = (P, color, w, dash) => {
      if (P.length < 2) return;
      ctx.strokeStyle = color; ctx.lineWidth = w; ctx.setLineDash(dash || []);
      ctx.beginPath(); ctx.moveTo(...scr(...P[0])); for (const p of P.slice(1)) ctx.lineTo(...scr(...p)); ctx.stroke();
      ctx.setLineDash([]);
    };
    const dot = (p, r, fill, stroke) => { const [x, y] = scr(...p); ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fillStyle = fill; ctx.fill(); ctx.strokeStyle = stroke; ctx.lineWidth = 1.5; ctx.stroke(); };
    for (const it of R.items) {
      const on = it.id === R.sel;
      const pts = on && R.drag && R.drag.pts ? R.drag.pts : it.pts;
      const shown = { ...it, pts };
      if (on) line(pts, "rgba(255,255,255,.35)", 1, [4, 4]);       // poligono de controle
      line(path(shown), on ? "#ffcf5a" : "rgba(243,215,154,.55)", on ? 3 : 2);
      if (on) {
        const hp = m && !R.drag ? hitPoint(shown, m) : -1;
        pts.forEach((p, i) => dot(p, i === hp ? 7 : 5, i === 0 || i === pts.length - 1 ? "#e05a47" : "#ffcf5a", "#111"));
        if (m && !R.drag && hp < 0) {                                  // onde um ponto novo entraria
          const s = hitSeg(shown, m);
          if (s >= 0) { const f = snap(S.hoverF); dot(f, 4, "rgba(255,255,255,.6)", "#111"); }
        }
      } else {
        const [x, y] = scr(...it.pts[0]); ctx.font = "11px system-ui"; ctx.fillStyle = "#f3d79a"; ctx.textAlign = "left"; ctx.fillText(it.name, x + 8, y - 6);
      }
    }
    if (R.draft) {
      const pts = S.hoverF ? [...R.draft, snap(S.hoverF)] : R.draft;
      line(path({ ...R.opts, pts, smooth: R.opts.smooth }), "#7fd0ff", 3);
      line(pts, "rgba(127,208,255,.4)", 1, [4, 4]);
      R.draft.forEach(p => dot(p, 5, "#7fd0ff", "#111"));
    }
    if (m) {                                                           // dica perto do cursor
      const t = R.draft ? `${R.draft.length} ponto(s) - duplo clique/Enter termina, Esc cancela`
        : cur() ? "arraste ponto/linha  -  Shift move a rua  -  Alt+clique tira ponto" : "clique para comecar uma rua";
      ctx.font = "12px system-ui, sans-serif"; ctx.textAlign = "left";
      const w = ctx.measureText(t).width;
      ctx.fillStyle = "rgba(15,17,20,.85)"; ctx.fillRect(m[0] + 12, m[1] + 10, w + 10, 18);
      ctx.fillStyle = "#e8e8e8"; ctx.fillText(t, m[0] + 17, m[1] + 23);
    }
  });

  // ---- painel
  function famPicker(val, set, extra) {
    const box = h("span", { class: "stfam" });
    for (const f of FAMS) {
      const c = h("canvas", { width: 34, height: 22 });
      try { S.atlas.thumb(c, [tileOf(f)], 34, 22); } catch (e) { /* atlas ainda carregando */ }
      const b = h("button", { class: val === f ? "on" : "", title: tileOf(f), onclick: () => set(f) }, c);
      box.append(b);
    }
    if (extra) box.append(extra);
    return box;
  }
  function fromCatalog(val, set, kind = "floor") {
    const t = S.item && (kind === "any" || S.item.kind === kind) && S.item.parts && S.item.parts[0] ? S.item.parts[0][2] : null;
    const custom = typeof val === "string";
    return h("button", { class: custom ? "on" : "", title: custom ? val : "usa o piso escolhido no catalogo (aba Tiles)",
      onclick: () => { if (!t) return say(kind === "floor" ? "escolha um piso no catalogo primeiro" : "escolha um objeto no catalogo primeiro", true); set(t); } },
      custom ? "catalogo: " + val.replace(/^.*?_(\d+_\d+)$/, "$1") : "do catalogo");
  }

  function opts() {
    const it = cur(), o = it || R.opts;
    const upd = (k, v) => {
      if (it) patch(it.id, k, v);
      else { R.opts[k] = v; window.PZMS.setTool("street"); }
    };
    const num = (k, min, max) => {
      const i = h("input", { type: "number", min, max, value: o[k], style: "width:3.6em", "data-k": k });
      i.addEventListener("change", () => upd(k, Math.max(min, Math.min(max, +i.value | 0))));
      i.dataset.live = "1";                                          // setas/teclado aplicam na hora (app.js)
      return i;
    };
    const tog = (k, label, title) => h("button", { class: o[k] ? "on" : "", title, onclick: () => upd(k, !o[k]) }, label);
    const list = h("select", { title: "ruas do mapa" },
      h("option", { value: "" }, R.items.length ? `(nova rua)  -  ${R.items.length} no mapa` : "(nova rua)"),
      ...R.items.map(i => h("option", { value: i.id, selected: i.id === R.sel ? "" : null }, i.name)));
    list.value = R.sel || "";
    list.addEventListener("change", () => { R.sel = list.value || null; R.draft = null; refresh(); });
    const name = h("input", { value: o.name, style: "width:9em", title: "nome (so para voce achar na lista)" });
    name.addEventListener("change", () => upd("name", name.value.trim() || "rua"));
    const grp = (...k) => h("span", { class: "stgrp" }, ...k);
    const dim = t => h("span", { style: "color:var(--dim)" }, t);
    const out = [list, name,
      grp(h("label", {}, "Pista"), num("width", 1, 40), dim("quadrados"),
        famPicker(o.asph, f => upd("asph", f), fromCatalog(o.asph, t => upd("asph", t)))),
      grp(tog("walk_on", "calcada", "liga/desliga a calcada dos dois lados"),
        ...(o.walk_on ? [num("side", 1, 10), dim("de cada lado"),
          famPicker(o.walk, f => upd("walk", f), fromCatalog(o.walk, t => upd("walk", t))),
          tog("curbs", "meio-fio", "meio-fio no asfalto encostado na calcada")] : [])),
      grp(h("label", {}, "Faixas"), num("lanes", 1, 8), dim(o.lanes > 1 ? `pistas (${o.lanes - 1} faixa${o.lanes > 2 ? "s" : ""})` : "pista (sem faixa)"),
        ...(o.lanes > 1 ? [dim("tracejado a cada"), num("dash", 0, 20), dim(o.dash ? "quadrados" : "(0 = continua)"),
          h("span", { class: "stfam" }, ...[[0, "cinza"], [8, "branca"], [16, "amarela gasta"], [24, "amarela"]].map(([v, t]) => {
            const c = h("canvas", { width: 34, height: 22 });
            try { S.atlas.thumb(c, ["blends_street_01_80", `street_trafficlines_01_${v + 1}`], 34, 22); } catch (e) { /* atlas */ }
            return h("button", { class: (o.line_color ?? 16) === v ? "on" : "", title: "faixa " + t, onclick: () => upd("line_color", v) }, c);
          }))] : [])),
      grp(tog("poles", "postes", "poste de luz na calcada, lados alternados"),
        ...(o.poles && o.walk_on ? [dim("a cada"), num("pole_every", 3, 80), dim("quadrados"),
          fromCatalog(o.pole && o.pole !== "lighting_outdoor_01_16" ? o.pole : null, t => upd("pole", t), "any")] : [])),
      tog("smooth", "curva suave", "arredonda a linha entre os pontos")];
    if (it) out.push(h("button", { title: "apaga a rua e devolve o chao de antes (Ctrl+Z desfaz)", onclick: () => send({ delete: it.id }) }, "apagar rua"),
      h("button", { onclick: () => { R.sel = null; refresh(); } }, "nova rua"));
    out.push(h("label", { style: "color:var(--dim)" }, it
      ? "arraste um ponto ou a linha  -  Shift+arrastar move a rua  -  Alt+clique tira um ponto  -  Delete apaga"
      : R.draft ? "cada clique poe um ponto  -  duplo clique ou Enter termina  -  Esc cancela" : "clique no mapa para comecar a rua  -  clique numa rua para editar"));
    return out;
  }

  async function finishDraft() {
    const d = R.draft; R.draft = null;
    if (!d || d.length < 2) { S.needDraw = true; if (d) say("a rua precisa de 2 pontos", true); return; }
    await save({ ...R.opts, pts: d }, `nova ${R.opts.name}`);
  }

  window.addEventListener("keydown", e => {
    if (S.tool !== "street" || e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.key === "Enter" && R.draft) { e.preventDefault(); finishDraft(); }
    else if (e.key === "Escape") { R.draft = null; R.drag = null; S.needDraw = true; }
    else if ((e.key === "Delete" || e.key === "Backspace") && cur() && !R.draft) { e.preventDefault(); send({ delete: R.sel }); }
  });

  window.PZMS_TOOLS = window.PZMS_TOOLS || {};
  window.PZMS_TOOLS.street = {
    key: "u",
    opts,
    down(sq, e) {
      const m = mouseScr(), f = snap(S.hoverF);
      if (R.draft) {
        if (e.detail >= 2) { finishDraft(); return; }
        const last = R.draft[R.draft.length - 1];
        if (!last || last[0] !== f[0] || last[1] !== f[1]) R.draft.push(f);
        refresh(); return;
      }
      const it = cur();
      if (it) {
        const i = hitPoint(it, m);
        if (i >= 0 && e.altKey) {
          if (it.pts.length <= 2) return say("a rua precisa de 2 pontos (Delete apaga a rua)", true);
          save({ ...it, pts: it.pts.filter((_, j) => j !== i) }, `${it.name}: tirar ponto`); return;
        }
        if (e.altKey) return;                                          // Alt so tira ponto; fora de ponto nao faz nada
        if (i >= 0) { R.drag = { i, pts: it.pts.map(p => [...p]) }; return; }
        const s = hitSeg(it, m);
        if (s >= 0 && e.shiftKey) { R.drag = { move: f, pts: it.pts.map(p => [...p]), orig: it.pts }; return; }
        if (s >= 0) { const pts = it.pts.map(p => [...p]); pts.splice(s + 1, 0, f); R.drag = { i: s + 1, pts, added: true }; S.needDraw = true; return; }
      }
      const other = hitStreet(m);
      if (other) { R.sel = other.id; refresh(); return; }
      if (it) { R.sel = null; refresh(); return; }
      R.draft = [f]; refresh();
    },
    move() {
      if (!R.drag || !S.hoverF) return;
      const f = snap(S.hoverF);
      if (R.drag.move) { const dx = f[0] - R.drag.move[0], dy = f[1] - R.drag.move[1]; R.drag.pts = R.drag.orig.map(([x, y]) => [x + dx, y + dy]); }
      else R.drag.pts[R.drag.i] = f;
      S.needDraw = true;
    },
    async up() {
      this.move();                                                     // posicao final do mouse (move so roda ao trocar de quadrado)
      const d = R.drag, it = cur(); R.drag = null;
      if (!d || !it) return;
      if (JSON.stringify(d.pts) === JSON.stringify(it.pts)) return;
      await save({ ...it, pts: d.pts }, `${it.name}: ${d.move ? "mover" : d.added ? "novo ponto" : "mover ponto"}`);
    },
  };
})();
