// Aba Exportar: grava o mod pronto direto na pasta de mods do jogo (sem WorldEd)
"use strict";
(() => {
  const { api, h, $, say } = window.PZMS;
  let busy = false;

  function field(label, inp, note) {
    return h("label", { class: "fld" }, h("span", {}, label), inp, note ? h("small", { class: "note" }, note) : "");
  }

  async function render(tab) {
    tab = tab || $("#tab-export");
    tab.innerHTML = "";
    let info;
    try { info = await api("/api/export"); } catch (e) { tab.append(h("p", { class: "note" }, e.message)); return; }
    const o = info.opts;
    const id = h("input", { value: o.modid, spellcheck: "false" });
    const title = h("input", { value: o.title || "" });
    const desc = h("textarea", { rows: 3 }, o.description || "");
    const author = h("input", { value: o.author || "" });
    const dir = h("input", { value: o.mods_dir, spellcheck: "false" });
    const pick = h("button", { onclick: async () => { try { const r = await api("/api/pick_folder", {}); if (r.path) dir.value = r.path; } catch (e) { say(e.message, true); } } }, "Escolher...");
    // ---- Steam Workshop: capa, workshop.txt, .vdf e comando do steamcmd
    const wsOn = h("input", { type: "checkbox", checked: !!o.workshop });
    const img = h("img", { style: "width:128px;height:128px;object-fit:cover;border:1px solid var(--line);border-radius:6px;background:var(--bg)", alt: "" });
    const imgNote = h("small", { class: "note" });
    const showCover = c => {
      img.style.display = c ? "" : "none";
      if (c) img.src = c.data;
      imgNote.textContent = c ? `capa 512x512, ${Math.round(c.bytes / 1024)} KB (tambem vira o poster do mod)` :
        "sem capa: usa a miniatura do mapa. Qualquer imagem; ela e cortada no centro em quadrado 512x512.";
    };
    showCover(info.cover);
    const file = h("input", { type: "file", accept: "image/*", style: "display:none" });
    file.addEventListener("change", () => {
      const f = file.files && file.files[0]; if (!f) return;
      const rd = new FileReader();
      rd.onload = async () => {
        try { const r = await api("/api/export/cover", { data: rd.result }); showCover(r.cover); say("capa salva no projeto"); }
        catch (e) { say(e.message, true); }
        file.value = "";
      };
      rd.readAsDataURL(f);
    });
    const coverBtns = h("div", { class: "row" }, h("button", { onclick: () => file.click() }, "Escolher imagem..."),
      h("button", { onclick: async () => { try { showCover((await api("/api/export/cover", { delete: true })).cover); } catch (e) { say(e.message, true); } } }, "Tirar"), file);
    const vis = h("select", {}, ...[["public", "publico"], ["unlisted", "nao listado"], ["friends", "so amigos"], ["private", "privado"]]
      .map(([v, t]) => h("option", { value: v }, t)));
    vis.value = o.visibility || "public";
    const tags = h("input", { value: o.tags || "Build 42;Map", spellcheck: "false" });
    const note = h("input", { value: o.changenote || "", placeholder: "o que mudou nesta versao" });
    const pid = h("input", { value: o.published_id || "", placeholder: "vazio = item novo", spellcheck: "false", style: "width:14em" });
    const user = h("input", { value: o.steam_user || "", placeholder: "so o usuario; a senha o steamcmd pede", spellcheck: "false", autocomplete: "off" });
    const wsBox = h("div", { class: "fld-group" },
      field("Capa (preview.png)", h("div", { class: "row", style: "align-items:flex-start;gap:10px" }, img, h("div", {}, coverBtns, imgNote))),
      field("Visibilidade", vis), field("Tags", tags, "separadas por ; (as do Workshop do PZ: Build 42, Map...)"),
      field("Nota da versao", note), field("ID publicado", pid, "depois do 1o envio, o ID do item (fica no .vdf); assim os proximos envios atualizam o mesmo item"),
      field("Usuario Steam", user, "so para montar o comando; senha e Steam Guard voce digita no steamcmd"),
      info.ws_foreign ? h("p", { class: "warn" }, `Ja existe ${info.ws_path} que nao foi feito por este app: troque o ID.`) : "",
      h("small", { class: "note" }, `pasta: ${info.ws_path}`));
    const syncWs = () => { wsBox.style.display = wsOn.checked ? "" : "none"; };
    wsOn.addEventListener("change", syncWs); syncWs();

    const out = h("div", { class: "note" });
    const copyBtn = txt => h("button", { onclick: async () => { try { await navigator.clipboard.writeText(txt); say("copiado"); } catch (e) { say("nao deu para copiar: selecione o texto", true); } } }, "Copiar");
    const showLast = r => {
      out.innerHTML = "";
      if (!r) return;
      out.append(h("p", {}, `Ultimo export: ${r.cells} celula(s) em ${r.secs}s`), h("code", {}, r.path),
        h("p", {}, "No jogo: Mods -> ative o mod -> Novo jogo -> escolha o mapa na lista de locais de inicio."));
      const w = r.workshop;
      if (w) {
        if (w.published_id && !pid.value) pid.value = w.published_id;
        out.append(h("h4", { style: "margin:10px 0 4px" }, "Enviar para a Workshop"),
          h("p", {}, "Pasta pronta (Contents/mods, preview.png, workshop.txt, workshop_build.vdf):"), h("code", {}, w.path),
          h("p", {}, "Com o steamcmd instalado, rode no terminal:"),
          h("div", { class: "row", style: "align-items:center;gap:6px" },
            h("code", { class: "ws-cmd", style: "user-select:all;white-space:pre-wrap;word-break:break-all;flex:1" }, w.cmd), copyBtn(w.cmd)),
          h("p", {}, w.published_id ? `Atualiza o item ${w.published_id}.` :
            "1o envio cria um item novo: depois copie o ID (saida do steamcmd ou URL do item) para o campo ID publicado."),
          h("p", {}, "Ou pelo jogo: menu principal -> Workshop -> a pasta aparece na lista."));
      }
    };
    showLast(info.last);
    const go = h("button", { class: "primary", onclick: () => run(false) }, "Exportar mod");
    async function run(overwrite) {
      if (busy) return;
      busy = true; go.disabled = true;
      const body = { modid: id.value.trim(), title: title.value.trim(), description: desc.value.trim(), author: author.value.trim(), mods_dir: dir.value.trim(), overwrite,
        workshop: wsOn.checked, visibility: vis.value, tags: tags.value.trim(), changenote: note.value.trim(),
        published_id: pid.value.trim(), steam_user: user.value.trim() };
      try {
        await api("/api/export", body);
        window.PZMS.progress.watch("export");
        const t = setInterval(async () => {
          const s = await api("/api/state").catch(() => null);
          const j = s && s.jobs && s.jobs.export;
          if (!j || !j.done) return;
          clearInterval(t); busy = false; go.disabled = false;
          if (j.error) say(j.error, true); else { say(`mod exportado: ${j.result.path}`); showLast(j.result); }
        }, 800);
      } catch (e) {
        busy = false; go.disabled = false;
        say(e.message, true);
      }
    }
    tab.append(
      h("h3", {}, "Exportar para mod"),
      h("p", { class: "note" }, "Gera a pasta do mod pronta para o Build 42 (lotheader, lotpack, chunkdata, map.info, spawnpoints, objects.lua, worldmap e spawns). So celulas alteradas sao copiadas de novo."),
      field("ID do mod", id, "letras, numeros, _ ou - (tambem e o nome da pasta do mapa)"),
      field("Titulo", title), field("Descricao", desc), field("Autor", author),
      field("Pasta de mods", h("div", { class: "row" }, dir, pick), "padrao: ~/Zomboid/mods"),
      h("label", { class: "fld", style: "flex-direction:row;gap:8px;align-items:center" }, wsOn, h("span", {}, "Preparar para a Steam Workshop (capa, workshop.txt, .vdf e comando do steamcmd)")),
      wsBox,
      info.exists && !info.ours ? h("p", { class: "warn" }, "Ja existe um mod com esse ID que nao foi feito por este app. Troque o ID.") : "",
      h("div", { class: "row" }, go), out);
  }

  (window.PZMS_TABS = window.PZMS_TABS || {}).export = render;
})();
