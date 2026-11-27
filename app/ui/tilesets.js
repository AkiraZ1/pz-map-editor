// Tiles extras: usar tiles de mods instalados e criar folhas novas a partir de um PNG.
//  - os mods que fornecem tiles que o mapa aberto ja usa entram sozinhos
//  - as folhas PNG do projeto vao junto no export (pack + .tiles do mod)
//  - quando o servidor termina de montar o atlas novo, a pagina recarrega com os tiles na paleta (categoria "Tiles de mods")
"use strict";
(() => {
  const { S, api, h, say, modal, closeModal } = window.PZMS;
  const TYPE_LABEL = { floor: "piso", overlay: "sobre o piso", wallW: "parede W", wallN: "parede N", wallNW: "canto NW",
    attachW: "na parede W", attachN: "na parede N", object: "objeto", solid: "objeto solido" };
  let poll = null;

  function watch() {                       // espera o atlas novo e recarrega a pagina
    clearInterval(poll);
    poll = setInterval(async () => {
      let st;
      try { st = await api("/api/tilesets/status"); } catch (e) { return; }
      if (st.busy) { say(st.msg || "montando tiles extras..."); return; }
      clearInterval(poll); poll = null;
      if (st.error) { say("tiles extras: " + st.error, true); return; }
      if (S.atlas && st.sig !== (S.atlas.meta.sig || "")) {
        say("tiles extras prontos: recarregando...");
        try { await window.PZMS.flush(); } catch (e) { /* */ }
        if (S.state && S.state.project && S.state.project.dirty) { try { await api("/api/project/save", {}); } catch (e) { /* */ } }
        location.reload();
      }
    }, 700);
  }

  const help = () => h("div", { class: "note", style: "line-height:1.5" },
    h("b", {}, "Folha PNG nova: "),
    "cada tile ocupa 128x256 px (tamanho 2x do jogo), em grade de 8 colunas: a folha tem 1024 px de largura e altura multipla de 256 ",
    "(1 a 8 linhas = 8 a 64 tiles). PNG RGBA com fundo transparente. O losango do piso fica no pe da celula (faixa y 192-256, 128x64). ",
    "Folha 1x (64x128 por tile, 512 px de largura) tambem serve: ela e ampliada 2x. ",
    "Nome da folha: letras/numeros/_ terminando em _01 (ex.: meumapa_placas_01); cada tile vira meumapa_placas_01_0, _1... ",
    "(linha x 8 + coluna).");

  async function open() {
    if (!S.state || !S.state.project) { say("abra um projeto primeiro", true); return; }
    let v;
    try { v = await api("/api/tilesets"); } catch (e) { say(e.message, true); return; }
    render(v);
  }

  function render(v) {
    // ---- mods instalados
    const boxes = v.mods.map(m => ({ m, cb: h("input", { type: "checkbox", checked: m.on ? "" : null }) }));
    const mods = v.mods.length
      ? h("div", { style: "max-height:180px;overflow:auto;border:1px solid var(--line);border-radius:6px;padding:4px 8px" },
          ...boxes.map(({ m, cb }) => h("label", { style: "display:flex;gap:6px;align-items:center;padding:2px 0", title: m.dir },
            cb, h("span", {}, m.name), h("small", { class: "note" }, m.id))))
      : h("p", { class: "note" }, "Nenhum mod com tiles (.pack + .tiles) achado na Workshop, em ~/Zomboid/mods nem na Steam.");
    const saveMods = h("button", { onclick: async () => {
      try { render(await api("/api/tilesets/use", { ids: boxes.filter(b => b.cb.checked).map(b => b.m.id) })); say("montando tiles dos mods..."); watch(); }
      catch (e) { say(e.message, true); }
    } }, "Usar mods marcados");
    const miss = v.missing && v.missing.length
      ? h("p", { style: "color:var(--warn,#e0a040)" }, `O mapa usa folhas que nenhum mod instalado tem (aparecem vazias): ${v.missing.slice(0, 12).join(", ")}${v.missing.length > 12 ? "..." : ""}`)
      : "";

    // ---- folhas PNG do projeto
    const typeSel = (val, onchange) => h("select", { onchange },
      ...v.types.map(t => h("option", { value: t, selected: t === val ? "" : null }, TYPE_LABEL[t] || t)));
    const rows = v.sheets.map(s => h("div", { class: "row", style: "align-items:center;gap:6px;margin:3px 0" },
      h("img", { src: `/api/tilesets/png?name=${encodeURIComponent(s.name)}&t=${Date.now()}`, style: "height:40px;max-width:120px;object-fit:contain;background:var(--bg);border:1px solid var(--line)" }),
      h("code", { style: "flex:1" }, `${s.name} (${s.cols * s.rows} tiles)`),
      typeSel(s.default, async e => { try { await api("/api/tilesets/sheet", { name: s.name, default: e.target.value }); say("tipo salvo"); watch(); } catch (er) { say(er.message, true); } }),
      h("button", { onclick: async () => { try { render(await api("/api/tilesets/sheet_rm", { name: s.name })); watch(); } catch (e) { say(e.message, true); } } }, "Remover")));
    const file = h("input", { type: "file", accept: "image/png" });
    const name = h("input", { placeholder: "meumapa_placas_01", spellcheck: "false" });
    let def = "object";
    const defSel = typeSel(def, e => { def = e.target.value; });
    file.addEventListener("change", () => {
      const f = file.files[0];
      if (f && !name.value) name.value = f.name.replace(/\.png$/i, "").replace(/[^A-Za-z0-9_]/g, "_").replace(/^([^A-Za-z])/, "t$1").replace(/(_\d\d)?$/, m => m || "_01");
    });
    const add = h("button", { class: "primary", onclick: async () => {
      const f = file.files[0];
      if (!f) { say("escolha o PNG", true); return; }
      const png = await new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = no; r.readAsDataURL(f); });
      try {
        const r = await api("/api/tilesets/sheet", { name: name.value.trim(), png, default: def });
        render(r); say(r.note || "folha adicionada: montando..."); watch();
      } catch (e) { say(e.message, true); }
    } }, "Adicionar folha");

    modal("Tiles extras", [
      h("h4", { style: "margin:4px 0" }, "Tiles de mods instalados"),
      h("p", { class: "note" }, "Marque os mods cujos tiles voce quer na paleta. Os que o mapa aberto ja usa entram sozinhos. No jogo, esses mods precisam estar ativos junto com o seu mapa."),
      mods, miss,
      h("h4", { style: "margin:12px 0 4px" }, "Folhas PNG do projeto (tiles novos)"),
      ...(rows.length ? rows : [h("p", { class: "note" }, "Nenhuma ainda.")]),
      h("div", { class: "row", style: "gap:6px;align-items:center;flex-wrap:wrap;margin-top:6px" }, file, name, h("span", { class: "note" }, "tipo"), defSel, add),
      help(),
      v.status && v.status.busy ? h("p", { class: "note" }, v.status.msg || "montando...") : "",
    ], [v.mods.length ? saveMods : "", h("button", { onclick: closeModal }, "Fechar")]);
  }

  window.PZMS_TILESETS = { open, watch };
  window.PZMS_INIT = window.PZMS_INIT || [];
  window.PZMS_INIT.push(() => watch());     // ao abrir o app/projeto: se o servidor ainda monta extras, recarrega quando pronto
  document.addEventListener("click", e => { if (e.target.closest("[data-act=tilesets]")) open(); });
})();
