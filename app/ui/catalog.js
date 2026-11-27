// Aba Predios: catalogo de predios vanilla por tipo (miniaturas), colocar com um clique, R/Shift+R gira
"use strict";
(() => {
  const { S, api, h, $, say, setTool, applyChanged } = window.PZMS;
  const C = { idx: null, type: null, q: "", sel: null, o: 0, pref: new Map(), shift: false, loading: false };
  const ONAMES = { 0: "original", 4: "espelhado" };

  async function load(force) {
    if (C.idx && !force) return C.idx;
    const r = await api("/api/catalog");
    C.idx = r.ready ? r : null;
    if (C.idx) C.byid = new Map(C.idx.items.map(i => [i.id, i]));
    return C.idx;
  }

  function render() {
    const cats = $("#bcats"), grid = $("#bitems"), st = $("#bstatus");
    cats.innerHTML = ""; grid.innerHTML = "";
    if (!C.idx) {
      st.innerHTML = "";
      st.append(h("p", {}, "O catalogo e montado a partir dos predios do mapa vanilla da sua instalacao do jogo (leva cerca de 1 minuto, so na primeira vez)."),
        h("button", { class: "primary", onclick: build }, "Montar catalogo"));
      return;
    }
    const types = C.idx.types.filter(t => t.count);
    cats.append(h("button", { class: C.type == null ? "on" : "", onclick: () => { C.type = null; render(); } }, "Todos", h("small", {}, C.idx.items.length + " predios")));
    for (const t of types)
      cats.append(h("button", { class: C.type === t.key ? "on" : "", onclick: () => { C.type = t.key; render(); } }, t.name, h("small", {}, t.count + " predios")));
    const q = C.q.trim().toLowerCase();
    let items = C.idx.items.filter(i => (C.type == null || i.type === C.type) &&
      (!q || i.label.toLowerCase().includes(q) || (i.rooms || []).some(r => r.includes(q))));
    st.textContent = `${items.length} predio(s)` + (items.length > 300 ? " - mostrando 300, use a busca" : "");
    for (const it of items.slice(0, 300)) {
      const img = h("img", { loading: "lazy", src: `/api/catalog/thumb?id=${it.id}`, alt: it.label });
      grid.append(h("div", { class: "card" + (C.sel && C.sel.id === it.id ? " on" : ""), title: `${it.label}\n${it.w}x${it.h}  -  aparece ${it.count}x no mapa vanilla\n${(it.rooms || []).join(", ")}`, onclick: () => choose(it) },
        img, h("b", {}, it.label), h("span", {}, `${it.w}x${it.h}  -  ${it.count}x`)));
    }
  }

  async function build() {
    try {
      await api("/api/catalog/build", {});
      window.PZMS.progress.watch("catalog");
      $("#bstatus").textContent = "montando catalogo...";
      const t = setInterval(async () => {
        const s = await api("/api/state").catch(() => null);
        const j = s && s.jobs && s.jobs.catalog;
        if (j && j.done) { clearInterval(t); if (j.error) say(j.error, true); await load(true); render(); }
      }, 1500);
    } catch (e) { say(e.message, true); }
  }

  async function prefab(id, o) {
    const k = id + "|" + o;
    if (!C.pref.has(k)) C.pref.set(k, await api(`/api/catalog/prefab?id=${id}&o=${o}`));
    return C.pref.get(k);
  }

  async function choose(it, o = 0) {
    C.sel = it; C.o = o;
    try { C.cur = await prefab(it.id, o); } catch (e) { return say(e.message, true); }
    if (C.pref.size > 24) C.pref.delete(C.pref.keys().next().value);
    $$card();
    const sb = $("#selbox"); sb.innerHTML = "";
    sb.append(h("img", { src: `/api/catalog/thumb?id=${it.id}`, style: "width:64px;height:48px;object-fit:contain" }),
      h("div", { class: "t" }, it.label, h("small", {}, `${C.cur.w}x${C.cur.h}  -  ${ONAMES[o] ?? "girado (aproximado)"}  -  R espelha, Shift+R gira`)));
    setTool("place");
    if (C.cur.approx) say(`orientacao aproximada: ${C.cur.approx} telhado(s)/fachada(s) ajustados`);
  }
  function $$card() { document.querySelectorAll("#bitems .card").forEach(c => c.classList.toggle("on", c.querySelector("img")?.src.endsWith(C.sel.id))); }

  const origin = (x, y) => [x - Math.floor(C.cur.w / 2), y - Math.floor(C.cur.h / 2)];

  window.PZMS_ghost = (x, y, z) => {
    if (!C.cur) return [];
    const [x0, y0] = origin(x, y);
    return C.cur.sq.filter(s => s[2] <= 0 || s[2] + z <= S.z + 1).map(([a, b, c, n]) => [x0 + a, y0 + b, c + z, n]);
  };
  window.PZMS_place = async (x, y, z) => {
    if (!C.cur || C.loading) return say("escolha um predio na aba Predios", !C.cur);
    const [x0, y0] = origin(x, y);
    C.loading = true;
    try { await applyChanged(await api("/api/catalog/place", { id: C.sel.id, o: C.o, x: x0, y: y0, z })); say(`colocado: ${C.sel.label}`); }
    catch (e) { say(e.message, true); }
    finally { C.loading = false; }
  };
  window.PZMS_rotatePrefab = () => {
    if (!C.sel) return;
    const o = C.shift ? [0, 1, 2, 3, 4, 5, 6, 7][([0, 1, 2, 3, 4, 5, 6, 7].indexOf(C.o) + 1) % 8] : (C.o === 4 ? 0 : 4);
    choose(C.sel, o);
  };
  window.PZMS_placeOpts = () => C.sel
    ? [h("label", {}, C.sel.label), h("button", { class: C.o === 0 ? "on" : "", onclick: () => choose(C.sel, 0) }, "original"),
       h("button", { class: C.o === 4 ? "on" : "", onclick: () => choose(C.sel, 4) }, "espelhado"),
       h("label", {}, "clique coloca  -  R espelha  -  Shift+R gira 90 graus (aproximado)")]
    : [h("label", {}, "Escolha um predio na aba Predios")];
  window.addEventListener("keydown", e => { if (e.key === "r" || e.key === "R") C.shift = e.shiftKey; }, true);
  window.addEventListener("keyup", e => { if (e.key === "r" || e.key === "R") C.shift = false; }, true);

  $("#bsearch").addEventListener("input", e => { C.q = e.target.value; clearTimeout(C.t); C.t = setTimeout(render, 160); });
  (window.PZMS_TABS = window.PZMS_TABS || {}).build = async () => {
    try { await load(); } catch (e) { say(e.message, true); }
    render();
  };
})();
