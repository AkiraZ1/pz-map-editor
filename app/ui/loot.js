// Ferramenta Spawn (L): o que nasce em cada sala/area e container.
// Mistura grupos vanilla (ProceduralDistributions / Distributions), itens avulsos e grupos personalizados
// (do projeto ou do perfil). Clique numa sala do mapa para editar as regras dela.
"use strict";
// nome do jogador (EN / PT, traducao vanilla) ao lado do nome base; preenchido pelas buscas de item
const NAMES = {};
function itemLabel(n) {
  const [en, pt] = NAMES[n] || [];
  const t = [pt, en && en !== pt ? en : ""].filter(Boolean).join(" / ");
  const e = document.createElement("span");
  e.append(n);
  if (t) { const d = document.createElement("span"); d.className = "lt-dim"; d.textContent = "  " + t; e.append(d); }
  return e;
}
(() => {
  const { S, api, h, $, say, modal, closeModal } = window.PZMS;
  const L = { loot: { custom: {}, rules: [] }, user: {}, van: null, key: null, proj: null, loading: false, again: false };
  const clone = o => JSON.parse(JSON.stringify(o));
  const uid = () => "r" + Date.now().toString(36) + Math.random().toString(36).slice(2, 5);

  // ---------------------------------------------------------------- estilo proprio (so desta ferramenta)
  document.head.append(h("style", {}, `
#modalbox.lootbox { max-width: min(94vw, 980px); width: 980px; max-height: 90vh; overflow: auto; }
.lt-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.lt-sec { border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.lt-sec h4 { margin: 0; font-size: 13px; color: var(--acc); }
.lt-chips { display: flex; flex-wrap: wrap; gap: 4px; min-height: 22px; }
.lt-chip { background: var(--panel2); border: 1px solid var(--line); border-radius: 10px; padding: 1px 4px 1px 8px; font-size: 12px; display: inline-flex; gap: 4px; align-items: center; }
.lt-chip button { padding: 0 5px; border: 0; background: none; color: var(--dim); cursor: pointer; }
.lt-res { max-height: 170px; overflow: auto; border: 1px solid var(--line); border-radius: 4px; background: var(--bg); }
.lt-res div { padding: 2px 8px; cursor: pointer; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lt-res div:hover { background: var(--sel); }
.lt-res div small { color: var(--dim); margin-left: 6px; }
.lt-items { width: 100%; border-collapse: collapse; font-size: 12px; }
.lt-items td { padding: 1px 3px; }
.lt-items input { width: 4.2em; }
.lt-items td:first-child { width: 100%; word-break: break-all; }
.lt-rule { display: flex; gap: 8px; align-items: center; border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; }
.lt-rule .sum { flex: 1; color: var(--dim); font-size: 12px; }
.lt-rule b { color: var(--text); }
.lt-dim { color: var(--dim); font-size: 12px; }
.lt-lua { white-space: pre; font: 11px/1.35 ui-monospace, Menlo, monospace; max-height: 60vh; overflow: auto; background: var(--bg); padding: 8px; border-radius: 4px; }
`));
  // modal grande so enquanto o nosso estiver aberto
  new MutationObserver(() => { if ($("#modal").classList.contains("hidden")) $("#modalbox").classList.remove("lootbox"); })
    .observe($("#modal"), { attributes: true, attributeFilter: ["class"] });
  function big(title, body, actions) { modal(title, body, actions); $("#modalbox").classList.add("lootbox"); }

  // ---------------------------------------------------------------- dados
  async function load() {
    if (!S.state || !S.state.project) return;
    if (L.loading) { L.again = true; return; }   // pedido durante outro: refaz no fim (Ctrl+Z repetido)
    L.loading = true; L.again = false;
    try {
      const r = await api("/api/loot");
      L.loot = r.loot; L.user = r.user || {};
      if (S.state.project.meta) S.state.project.meta.loot = r.loot;
      S.needDraw = true;
      if (S.tool === "loot") window.PZMS.setTool("loot");
    } catch (e) { /* sem projeto */ }
    L.loading = false;
    if (L.again) load();
  }
  async function vanilla() {
    if (!L.van) { try { L.van = await api("/api/loot/vanilla"); } catch (e) { L.van = { procedural: [], rooms: {}, containers: [], nitems: 0 }; } }
    return L.van;
  }
  const keyOf = p => `${p.path}|${p.undo}|${p.redo}|${p.nu}|${p.nr}`;   // nu/nr: rotulos repetidos nao escondem o desfazer
  function watch(p) {                       // undo/redo/abrir projeto: recarrega as regras
    const k = keyOf(p);
    if (p.path !== L.proj) { L.proj = p.path; L.key = k; load(); return; }
    if (k !== L.key) { L.key = k; clearTimeout(L.t); L.t = setTimeout(load, 60); }
  }
  async function commit(loot, label) {
    try {
      const r = await api("/api/loot/set", { loot, label });
      L.loot = r.loot;
      if (S.state.project.meta) S.state.project.meta.loot = r.loot;
      S.state.project.undo = r.undo; S.state.project.redo = r.redo; S.state.project.nu = r.nu; S.state.project.nr = r.nr;
      if (!r.same) S.state.project.dirty = true;
      window.PZMS.afterState();
      L.key = keyOf(S.state.project);
      say(r.same ? "nada mudou" : label);
      S.needDraw = true;
      if (S.tool === "loot") window.PZMS.setTool("loot");
      return true;
    } catch (e) { say(e.message, true); return false; }
  }
  async function saveUser(name, group) {
    try { L.user = (await api("/api/loot/usergroup", { name, group })).user; say(group ? `grupo "${name}" salvo no perfil` : `grupo "${name}" removido do perfil`); return true; }
    catch (e) { say(e.message, true); return false; }
  }

  function roomAt(sq) {
    const [x, y] = sq;
    return (S.rooms || []).find(r => (r.z | 0) === S.z && r.rects.some(([a, b, w, hh]) => x >= a && x < a + w && y >= b && y < b + hh));
  }
  const rulesFor = room => L.loot.rules.filter(r => r.room === room);
  function summary(g) {
    const p = [];
    if (g.vanilla && g.vanilla.length) p.push(`${g.vanilla.length} vanilla`);
    if (g.items && g.items.length) p.push(`${g.items.length} item(ns)`);
    if (g.custom && g.custom.length) p.push(`grupos: ${g.custom.join(", ")}`);
    const s = p.join(" + ") || "vazio";
    return (g.replace ? "SUBSTITUI o vanilla: " : "") + s + (g.pick === "one" ? " (1 lista por rolagem)" : "");
  }

  // ---------------------------------------------------------------- editor de grupo (vanilla + itens + grupos)
  function stopEnter(inp, fn) {             // o app.js aperta o botao primario no Enter: aqui Enter escolhe o 1o resultado
    inp.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); fn(); } });
  }
  function groupEditor(g, opt = {}) {
    g = { vanilla: [...(g.vanilla || [])], items: clone(g.items || []), custom: [...(g.custom || [])] };
    const V = L.van || { procedural: [], rooms: {} };
    const distRefs = Object.entries(V.rooms).flatMap(([r, cs]) => cs.map(c => `${r}/${c}`));

    // vanilla
    const vchips = h("div", { class: "lt-chips" });
    const drawV = () => {
      vchips.innerHTML = "";
      if (!g.vanilla.length) vchips.append(h("span", { class: "lt-dim" }, "nenhum"));
      for (const v of g.vanilla) vchips.append(h("span", { class: "lt-chip", title: v.includes("/") ? "sala/container de Distributions.lua" : "lista de ProceduralDistributions.lua" },
        v, h("button", { title: "tirar", onclick: () => { g.vanilla = g.vanilla.filter(x => x !== v); drawV(); } }, "x")));
      if (opt.onV) opt.onV(g.vanilla);
    };
    const vq = h("input", { placeholder: `buscar entre ${V.procedural.length} listas e ${distRefs.length} sala/container`, style: "width:100%" });
    const vres = h("div", { class: "lt-res" });
    const addV = v => { if (v && !g.vanilla.includes(v)) { g.vanilla.push(v); drawV(); } };
    const searchV = () => {
      const s = vq.value.trim().toLowerCase(); vres.innerHTML = "";
      const pool = s ? V.procedural.filter(n => n.toLowerCase().includes(s)).concat(distRefs.filter(n => n.toLowerCase().includes(s))) : V.procedural;
      for (const n of pool.slice(0, 80)) vres.append(h("div", { onclick: () => addV(n) }, n, n.includes("/") ? h("small", {}, "Distributions") : null));
      if (pool.length > 80) vres.append(h("div", { class: "lt-dim" }, `... mais ${pool.length - 80}`));
      return pool;
    };
    vq.addEventListener("input", searchV);
    stopEnter(vq, () => { const p = searchV(); if (p.length) addV(p[0]); });

    // itens avulsos
    const tbl = h("table", { class: "lt-items" });
    const num = (it, k, min, max, ph) => {
      const i = h("input", { type: "number", min, max, step: k === "chance" ? "any" : 1, value: it[k] ?? "", placeholder: ph || "" });
      i.addEventListener("input", () => { it[k] = i.value === "" ? (k === "cond" ? null : min) : +i.value; });
      return i;
    };
    const drawI = () => {
      tbl.innerHTML = "";
      if (!g.items.length) { tbl.append(h("tr", {}, h("td", { class: "lt-dim" }, "nenhum item avulso"))); return; }
      tbl.append(h("tr", { class: "lt-dim" }, h("td", {}, "item"), h("td", {}, "chance %"), h("td", {}, "qtd"), h("td", {}, "cond %"), h("td", {})));
      g.items.forEach((it, i) => tbl.append(h("tr", {}, h("td", {}, itemLabel(it.item)), h("td", {}, num(it, "chance", 0, 100)), h("td", {}, num(it, "count", 1, 100)),
        h("td", {}, num(it, "cond", 1, 100, "jogo")), h("td", {}, h("button", { title: "tirar", onclick: () => { g.items.splice(i, 1); drawI(); } }, "x")))));
    };
    const iq = h("input", { placeholder: `buscar item: nome base, ingles ou portugues (${(L.van && L.van.nitems) || 0} no jogo)`, style: "width:100%" });
    const ires = h("div", { class: "lt-res" });
    const addI = name => { if (name) { g.items.push({ item: name, chance: 100, count: 1, cond: null }); drawI(); } };
    let iT = 0, last = [];
    const searchI = async () => {
      const s = iq.value.trim();
      if (!s) { ires.innerHTML = ""; last = []; return; }
      try {
        const r = await api(`/api/loot/items?q=${encodeURIComponent(s)}&limit=120`);
        if (iq.value.trim() !== s) return;
        last = r.items; ires.innerHTML = "";
        Object.assign(NAMES, r.names || {});
        for (const n of r.items) ires.append(h("div", { onclick: () => addI(n) }, itemLabel(n)));
        if (r.total > r.items.length) ires.append(h("div", { class: "lt-dim" }, `... ${r.total} no total`));
        if (!r.items.length) ires.append(h("div", { class: "lt-dim", onclick: () => addI(s.includes(".") ? s : "Base." + s) }, `nenhum; usar "${s}" assim mesmo`));
      } catch (e) { say(e.message, true); }
    };
    iq.addEventListener("input", () => { clearTimeout(iT); iT = setTimeout(searchI, 150); });
    stopEnter(iq, async () => { await searchI(); if (last.length) addI(last[0]); });

    // grupos personalizados (so em regras)
    let csec = null;
    if (opt.custom) {
      const box = h("div", { class: "lt-chips" });
      const drawC = () => {
        box.innerHTML = "";
        const names = [...new Set([...Object.keys(L.loot.custom), ...Object.keys(L.user)])].sort();
        if (!names.length) box.append(h("span", { class: "lt-dim" }, "nenhum grupo criado (botao Grupos)"));
        for (const n of names) {
          const on = g.custom.includes(n), where = L.loot.custom[n] ? "projeto" : "perfil";
          const b = h("button", { class: on ? "on" : "", title: `${where}: ${summary(L.loot.custom[n] || L.user[n])}`, onclick: () => {
            g.custom = on ? g.custom.filter(x => x !== n) : [...g.custom, n]; drawC();
          } }, n + (where === "perfil" ? " *" : ""));
          box.append(b);
        }
      };
      drawC();
      csec = h("div", { class: "lt-sec" }, h("h4", {}, "Grupos personalizados"), box,
        h("span", { class: "lt-dim" }, "* = do perfil (vale para todos os mapas; ao salvar a regra ele e copiado para o projeto)"));
    }
    drawV(); drawI(); searchV();
    const el = h("div", { style: "display:flex;flex-direction:column;gap:10px" },
      h("div", { class: "lt-cols" },
        h("div", { class: "lt-sec" }, h("h4", {}, "Grupos vanilla"), vchips, vq, vres,
          h("span", { class: "lt-dim" }, "cada grupo e sorteado com as regras do jogo, por cima do loot normal")),
        h("div", { class: "lt-sec" }, h("h4", {}, "Itens avulsos"), tbl, iq, ires,
          h("span", { class: "lt-dim" }, "chance exata por container; cond vazia = condicao normal do jogo"))),
      csec);
    return { el, get: () => clone(g) };
  }

  // ---------------------------------------------------------------- regra
  async function ruleEditor(rule, back) {
    await vanilla();
    const isNew = !rule.id;
    const r = clone(rule);
    const mapRooms = [...new Set((S.rooms || []).map(x => x.name))].sort();
    const room = h("input", { value: r.room || "all", list: "lt-rooms", style: "width:14em" });
    const rdl = h("datalist", { id: "lt-rooms" }, ["all", ...mapRooms, ...Object.keys(L.van.rooms)].filter((v, i, a) => a.indexOf(v) === i).map(v => h("option", { value: v })));
    const cont = h("input", { value: r.container || "all", list: "lt-conts", style: "width:12em" });
    const cdl = h("datalist", { id: "lt-conts" });
    const fillC = () => {
      const own = L.van.rooms[room.value.trim()] || [];
      cdl.innerHTML = "";
      for (const v of ["all", ...own, ...L.van.containers.filter(c => !own.includes(c))]) cdl.append(h("option", { value: v }));
      hint.textContent = own.length ? `containers desta sala no vanilla: ${own.join(", ")}` :
        (room.value.trim() === "all" ? "todas as salas do mapa (e containers fora de sala)" : "sala sem loot vanilla (area propria): so recebe o que voce definir aqui");
    };
    const hint = h("span", { class: "lt-dim" });
    room.addEventListener("input", fillC);
    const rolls = h("input", { type: "number", min: 1, max: 20, value: r.rolls || 1, style: "width:4em", title: "quantas vezes cada grupo vanilla e sorteado" });
    const note = h("input", { value: r.note || "", placeholder: "nota (opcional)", style: "flex:1" });
    const repl = h("input", { type: "checkbox", checked: !!r.replace });
    const pick = h("input", { type: "checkbox", checked: r.pick === "one" });
    const W = { ...(r.weights || {}) };
    const wrow = h("div", { class: "lt-chips" });
    let curV = r.vanilla || [];
    const drawW = () => {
      wrow.innerHTML = "";
      wrow.style.display = pick.checked && curV.length ? "" : "none";
      if (!pick.checked) return;
      wrow.append(h("span", { class: "lt-dim" }, "pesos (chance relativa de cada lista):"));
      for (const v of curV) {
        const i = h("input", { type: "number", min: 1, max: 1000, value: W[v] || 100, style: "width:4.5em", title: v });
        i.addEventListener("input", () => { W[v] = Math.max(1, Math.min(1000, +i.value || 100)); });
        wrow.append(h("span", { class: "lt-chip" }, v.includes("/") ? `${v} (pesos do jogo)` : v, v.includes("/") ? null : i));
      }
    };
    pick.addEventListener("change", drawW);
    const warnR = h("span", { style: "color:var(--bad);font-size:12px" });
    const chkR = () => { warnR.textContent = repl.checked && (room.value.trim() === "all" || cont.value.trim() === "all") ?
      "atencao: com sala ou container \"all\" isso apaga o loot vanilla de muitos containers" : ""; };
    repl.addEventListener("change", chkR); room.addEventListener("input", chkR); cont.addEventListener("input", chkR);
    const ge = groupEditor(r, { custom: true, onV: v => { curV = v; drawW(); } });
    fillC(); chkR(); drawW();
    const save = async () => {
      const g = ge.get(), rn = room.value.trim() || "all", cn = cont.value.trim() || "all";
      if (!/^[\w-]+$/.test(rn) || !/^[\w-]+$/.test(cn)) return say("sala/container: so letras, numeros, _ e -", true);
      if (!g.vanilla.length && !g.items.length && !g.custom.length) return say("a regra esta vazia", true);
      const loot = clone(L.loot);
      for (const n of g.custom) if (!loot.custom[n] && L.user[n]) loot.custom[n] = clone(L.user[n]);   // projeto autossuficiente
      const nr = { id: r.id || uid(), room: rn, container: cn, rolls: +rolls.value || 1, vanilla: g.vanilla, items: g.items, custom: g.custom };
      if (note.value.trim()) nr.note = note.value.trim();
      if (repl.checked) nr.replace = true;
      if (pick.checked) { nr.pick = "one"; nr.weights = {}; for (const v of g.vanilla) if (!v.includes("/")) nr.weights[v] = W[v] || 100; }
      const i = loot.rules.findIndex(x => x.id === nr.id);
      if (i >= 0) loot.rules[i] = nr; else loot.rules.push(nr);
      if (await commit(loot, `spawn ${rn}/${cn}`)) { closeModal(); if (back) back(); }
    };
    const del = async () => {
      const loot = clone(L.loot); loot.rules = loot.rules.filter(x => x.id !== r.id);
      if (await commit(loot, `spawn: remover regra ${r.room}/${r.container}`)) { closeModal(); if (back) back(); }
    };
    const asGroup = () => {
      const g = ge.get(); delete g.custom;
      groupEditorModal(null, g, "projeto", () => ruleEditor({ ...r, ...ge.get(), room: room.value, container: cont.value,
        replace: repl.checked, pick: pick.checked ? "one" : undefined, weights: W }, back));
    };
    big(isNew ? "Nova regra de spawn" : "Regra de spawn", [
      h("div", { class: "row" }, h("label", {}, "Sala / area"), room, rdl, h("label", { style: "min-width:0" }, "Container"), cont, cdl,
        h("label", { style: "min-width:0" }, "Rolagens"), rolls),
      hint,
      h("div", { class: "row" }, h("label", { style: "min-width:0;display:flex;gap:6px;align-items:center" }, repl, "Substituir o loot vanilla deste container"),
        h("label", { style: "min-width:0;display:flex;gap:6px;align-items:center", title: "como o jogo: cada rolagem sorteia UMA das listas, pelo peso; desligado = cada lista rola" },
          pick, "Sortear 1 lista por rolagem (como o vanilla)")),
      warnR, wrow, ge.el, h("div", { class: "row" }, note)],
      [!isNew ? h("button", { onclick: del }, "Excluir") : null, h("button", { onclick: asGroup, title: "transformar em grupo reutilizavel" }, "Salvar como grupo..."),
        h("span", { style: "flex:1" }), h("button", { onclick: () => { closeModal(); if (back) back(); } }, "Cancelar"),
        h("button", { class: "primary", onclick: save }, "Salvar regra")].filter(Boolean));
  }

  function ruleRow(r, back) {
    return h("div", { class: "lt-rule" },
      h("span", {}, h("b", {}, r.room), " / ", h("b", {}, r.container), r.rolls > 1 ? ` x${r.rolls}` : ""),
      h("span", { class: "sum" }, summary(r) + (r.note ? `  -  ${r.note}` : "")),
      h("button", { onclick: () => ruleEditor(r, back) }, "Editar"));
  }

  async function roomModal(name) {
    await vanilla();
    const back = () => roomModal(name);
    const own = rulesFor(name), all = rulesFor("all");
    const van = L.van.rooms[name];
    const dist = (L.van.dist || {})[name] || {};
    const vsec = Object.keys(dist).length ? h("div", { class: "lt-sec" },
      h("h4", {}, "Loot vanilla desta sala (o que o jogo ja poe)"),
      h("span", { class: "lt-dim" }, "Editar cria uma regra ja preenchida com as listas do jogo, que substitui o vanilla daquele container. Listas so de certos moveis (ex.: pia) ficam de fora."),
      ...Object.entries(dist).map(([c, d]) => {
        const mine = own.find(r => r.container === c && r.replace);
        const free = d.lists.filter(x => !x[2]), forced = d.lists.filter(x => x[2]);
        const txt = d.lists.length ? free.map(([n, w]) => `${n} (${w})`).join(", ") + (forced.length ? `  +${forced.length} so p/ certos moveis` : "")
          : "itens fixos (sem procList)";
        const pre = () => ruleEditor(mine || { room: name, container: c, rolls: 1, replace: true,
          ...(free.length ? { pick: "one", vanilla: free.map(x => x[0]), weights: Object.fromEntries(free.map(x => [x[0], x[1]])) }
            : { vanilla: [`${name}/${c}`] }), note: "copia editavel do vanilla" }, back);
        return h("div", { class: "lt-rule" }, h("span", {}, h("b", {}, c)),
          h("span", { class: "sum" }, mine ? `substituido pela regra: ${summary(mine)}` : txt),
          h("button", { onclick: pre }, mine ? "Editar regra" : "Editar"));
      })) : null;
    big(`Spawn de itens: sala "${name}"`, [
      h("span", { class: "lt-dim" }, van ? `sala vanilla: containers ${van.join(", ") || "(nenhum)"}; o loot normal continua, as regras somam (a nao ser as marcadas para substituir)` :
        "nome proprio (area): sem loot vanilla; so nasce o que estiver nas regras"),
      vsec,
      ...(own.length ? own.map(r => ruleRow(r, back)) : [h("span", { class: "lt-dim" }, "nenhuma regra para esta sala")]),
      all.length ? h("h4", { style: "margin:6px 0 0" }, "Tambem valem aqui (sala all)") : null,
      ...all.map(r => ruleRow(r, back))].filter(Boolean),
    [h("button", { onclick: () => listModal() }, "Todas as regras"), h("button", { onclick: closeModal }, "Fechar"),
      h("button", { class: "primary", onclick: () => ruleEditor({ room: name, container: "all", rolls: 1 }, back) }, "Nova regra")]);
  }

  async function listModal() {
    await vanilla();
    const back = () => listModal();
    const rs = L.loot.rules;
    big("Spawn de itens: todas as regras", [
      L.van.media === false ? h("span", { style: "color:var(--bad)" }, "pasta do jogo nao encontrada: sem listas vanilla nem busca de itens") : null,
      ...(rs.length ? rs.map(r => ruleRow(r, back)) : [h("span", { class: "lt-dim" }, "nenhuma regra. Clique numa sala do mapa ou crie uma regra aqui.")])].filter(Boolean),
    [h("button", { onclick: () => groupsModal() }, "Grupos..."), h("button", { onclick: luaModal }, "Ver Lua"),
      h("span", { style: "flex:1" }), h("button", { onclick: closeModal }, "Fechar"),
      h("button", { class: "primary", onclick: () => ruleEditor({ room: "all", container: "all", rolls: 1 }, back) }, "Nova regra")]);
  }

  // ---------------------------------------------------------------- grupos personalizados
  function groupEditorModal(name, g, where, back) {
    const nm = h("input", { value: name || "", placeholder: "nome do grupo", style: "width:18em" });
    const wh = h("select", {}, h("option", { value: "projeto" }, "neste projeto (com desfazer)"), h("option", { value: "perfil" }, "no meu perfil (todos os mapas)"));
    wh.value = where || "projeto";
    const ge = groupEditor(g || {}, {});
    const save = async () => {
      const n = nm.value.trim();
      if (!/^[\w .\-/]{1,80}$/.test(n)) return say("nome: letras, numeros, espaco . - _ /, ate 80", true);
      const gg = ge.get(); delete gg.custom;
      if (!gg.vanilla.length && !gg.items.length) return say("o grupo esta vazio", true);
      let ok;
      if (wh.value === "perfil") ok = await saveUser(n, gg);
      else {
        const loot = clone(L.loot);
        if (name && name !== n && where === "projeto") {   // renomear: troca nas regras tambem
          delete loot.custom[name];
          for (const r of loot.rules) r.custom = (r.custom || []).map(c => c === name ? n : c);
        }
        loot.custom[n] = gg; ok = await commit(loot, `grupo de spawn ${n}`);
      }
      if (ok) { closeModal(); (back || groupsModal)(); }
    };
    big(name ? `Grupo "${name}"` : "Novo grupo de spawn", [h("div", { class: "row" }, h("label", {}, "Nome"), nm, wh), ge.el],
      [h("button", { onclick: () => { closeModal(); (back || groupsModal)(); } }, "Cancelar"), h("button", { class: "primary", onclick: save }, "Salvar grupo")]);
  }

  async function groupsModal() {
    await vanilla();
    const used = n => L.loot.rules.filter(r => (r.custom || []).includes(n)).length;
    const rows = [];
    for (const [n, g] of Object.entries(L.loot.custom).sort()) {
      rows.push(h("div", { class: "lt-rule" }, h("b", {}, n), h("span", { class: "sum" }, `projeto  -  ${summary(g)}  -  usado em ${used(n)} regra(s)`),
        h("button", { onclick: () => groupEditorModal(n, g, "projeto") }, "Editar"),
        h("button", { title: "copiar para o perfil", onclick: async () => { await saveUser(n, g); groupsModal(); } }, "-> perfil"),
        h("button", { onclick: async () => {
          const loot = clone(L.loot); delete loot.custom[n];
          for (const r of loot.rules) r.custom = (r.custom || []).filter(c => c !== n);
          loot.rules = loot.rules.filter(r => r.vanilla.length || r.items.length || r.custom.length);
          if (await commit(loot, `remover grupo de spawn ${n}`)) groupsModal();
        } }, "Excluir")));
    }
    for (const [n, g] of Object.entries(L.user).sort()) {
      rows.push(h("div", { class: "lt-rule" }, h("b", {}, n), h("span", { class: "sum" }, `perfil  -  ${summary(g)}`),
        h("button", { onclick: () => groupEditorModal(n, g, "perfil") }, "Editar"),
        h("button", { title: "copiar para este projeto", onclick: async () => {
          const loot = clone(L.loot); loot.custom[n] = clone(g); if (await commit(loot, `importar grupo ${n}`)) groupsModal();
        } }, "-> projeto"),
        h("button", { onclick: async () => { if (await saveUser(n, null)) groupsModal(); } }, "Excluir")));
    }
    big("Grupos de spawn", [
      h("span", { class: "lt-dim" }, "Grupo = conjunto reutilizavel de grupos vanilla + itens. Use nas regras de qualquer sala."),
      ...(rows.length ? rows : [h("span", { class: "lt-dim" }, "nenhum grupo ainda")])],
    [h("button", { onclick: () => listModal() }, "Regras"), h("span", { style: "flex:1" }), h("button", { onclick: closeModal }, "Fechar"),
      h("button", { class: "primary", onclick: () => groupEditorModal(null, {}, "projeto") }, "Novo grupo")]);
  }

  async function luaModal() {
    try {
      const r = await api("/api/loot/lua");
      big("Lua gerado no export", [h("span", { class: "lt-dim" }, r.path), h("div", { class: "lt-lua" }, r.lua || "-- sem regras: o export nao grava o arquivo")],
        [h("button", { onclick: () => listModal() }, "Voltar"), h("button", { class: "primary", onclick: closeModal }, "Fechar")]);
    } catch (e) { say(e.message, true); }
  }

  // ---------------------------------------------------------------- overlay: salas com regra
  window.PZMS_OVERLAYS = window.PZMS_OVERLAYS || [];
  window.PZMS_OVERLAYS.push((ctx, { diamond, toScreen, z, project }) => {
    watch(project);
    if (S.tool !== "loot") return;
    const allR = rulesFor("all").length;
    const hov = S.hover && roomAt(S.hover);
    for (const r of S.rooms || []) {
      if ((r.z | 0) !== z) continue;
      const n = rulesFor(r.name).length, isH = hov && hov === r;
      if (!n && !isH) continue;
      ctx.fillStyle = isH ? "rgba(217,164,65,.22)" : "rgba(90,170,220,.16)";
      ctx.strokeStyle = isH ? "#f3d79a" : "rgba(120,190,240,.8)"; ctx.lineWidth = 1.5;
      for (const [x, y, w, hh] of r.rects) { diamond(ctx, x, y, w, hh); ctx.fill(); ctx.stroke(); }
      const [x, y, w, hh] = r.rects[0], [sx, sy] = toScreen(x + w / 2 - .5, y + hh / 2 - .5, z);
      ctx.fillStyle = "#bfe3ff"; ctx.textAlign = "center";
      ctx.fillText(n ? `${n} regra(s)` : "clique: spawns", sx, sy + 13);
    }
    if (allR && S.hover) { const [sx, sy] = toScreen(S.hover[0], S.hover[1], z); ctx.fillStyle = "#bfe3ff"; ctx.textAlign = "left"; ctx.fillText(`+${allR} regra(s) all`, sx + 10, sy - 10); }
  });

  // ---------------------------------------------------------------- ferramenta
  window.PZMS_TOOLS = window.PZMS_TOOLS || {};
  window.PZMS_TOOLS.loot = {
    key: "l",
    opts() {
      const n = L.loot.rules.length, g = Object.keys(L.loot.custom).length + Object.keys(L.user).length;
      return [h("label", {}, "Spawn de itens: clique numa sala (ou area da ferramenta Sala)"),
        h("button", { onclick: listModal }, `Regras (${n})`), h("button", { onclick: groupsModal }, `Grupos (${g})`),
        h("button", { onclick: luaModal, title: "previa do Lua do export" }, "Lua")];
    },
    down(sq) {
      S.drag = null;
      const r = roomAt(sq);
      if (r) roomModal(r.name);
      else { say("fora de sala: use uma regra com sala all ou crie a sala com a ferramenta Sala (M)"); listModal(); }
    },
  };
})();
