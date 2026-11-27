// Aba Gerar: tutorial de como obter o arquivo OSM, validacao, escolha da area e geracao do projeto
"use strict";
(() => {
  const { S, api, h, $, say, afterState, resetView } = window.PZMS;
  const G = { path: "", info: null, bbox: null, name: "", foot: "", busy: false, step: 0, vt: 0 };
  const M_PER_DEG = 111320;

  const TUTORIAL = [
    ["Area pequena (um bairro)", [
      "Abra openstreetmap.org e va ate o lugar.",
      "Clique em Exportar (barra de cima) e depois em \"Selecionar manualmente uma area diferente\".",
      "Ajuste o retangulo e clique em Exportar: baixa um arquivo map.osm.",
      "Limite do site: cerca de 50 mil nos (um bairro). Para mais, use as opcoes abaixo."]],
    ["Area maior (varios bairros)", [
      "Abra extract.bbbike.org.",
      "Desenhe a area no mapa (ou digite os limites).",
      "Em Format escolha \"Protocolbuffer (PBF)\", informe um e-mail e clique em extract.",
      "Em alguns minutos chega um link para baixar o .osm.pbf.",
      "Alternativa: Overpass API (overpass-turbo.eu) com a consulta pronta \"(nwr({{bbox}});); out meta;\" e Exportar -> raw OSM data."]],
    ["Cidade ou estado inteiro", [
      "Abra download.geofabrik.de.",
      "Clique no continente, depois no pais e na regiao.",
      "Baixe o arquivo .osm.pbf (o de um estado tem de 100 MB a 1 GB).",
      "Arquivos grandes sao lidos so na area escolhida, mas a leitura inicial demora mais."]],
    ["Fontes extras (opcional)", [
      "Contornos de predio com altura melhoram as alturas e os formatos dos predios.",
      "Exemplo: GeoSampa em Sao Paulo (edificacoes com numero de pavimentos).",
      "Informe o arquivo em \"Fonte extra\" abaixo; sem ela, a altura vem das tags building:levels do OSM."]],
    ["Criar o mapa", [
      "Abra o arquivo no J' PZ MAP STUDIO (botao Escolher arquivo).",
      "Arraste no mapa para escolher a area (cada quadradinho e uma celula de 256 m).",
      "Confira a estimativa de celulas e tempo e clique em Criar mapa do lugar."]],
  ];

  function tutorial() {
    const box = h("div", { class: "tut" });
    const draw = () => {
      box.innerHTML = "";
      const nav = h("div", { class: "row tutnav" }, ...TUTORIAL.map(([t], i) =>
        h("button", { class: i === G.step ? "on" : "", onclick: () => { G.step = i; draw(); } }, `${i + 1}. ${t}`)));
      const [t, lines] = TUTORIAL[G.step];
      box.append(nav, h("ol", {}, ...lines.map(l => h("li", {}, l))));
    };
    draw();
    return h("details", { class: "tutbox", open: !G.path }, h("summary", {}, "Como conseguir o arquivo do OpenStreetMap"), box);
  }

  // ---------------------------------------------------------------- mapa de escolha da area
  function areaMap(info) {
    const W = 360, H = 260;
    const c = h("canvas", { width: W, height: H, class: "osmarea" });
    const b = info.bounds; // [lat0, lon0, lat1, lon1]
    const lat0 = b[0], lon0 = b[1], lat1 = b[2], lon1 = b[3];
    const kx = Math.cos(((lat0 + lat1) / 2) * Math.PI / 180);
    const wm = (lon1 - lon0) * kx, hm = lat1 - lat0;
    const s = Math.min((W - 20) / wm, (H - 20) / hm);
    const ox = (W - wm * s) / 2, oy = (H - hm * s) / 2;
    const toXY = (lat, lon) => [ox + (lon - lon0) * kx * s, oy + (lat1 - lat) * s];
    const toLL = (x, y) => [lat1 - (y - oy) / s, lon0 + (x - ox) / (kx * s)];
    const ctx = c.getContext("2d");
    function draw() {
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = "#1a1c20"; ctx.fillRect(0, 0, W, H);
      const [x0, y0] = toXY(lat1, lon0), [x1, y1] = toXY(lat0, lon1);
      ctx.fillStyle = "#24282e"; ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
      ctx.strokeStyle = "#555"; ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      if (info.preview) {
        ctx.fillStyle = "rgba(217,164,65,.55)";
        for (const [la, lo] of info.preview) { const [x, y] = toXY(la, lo); ctx.fillRect(x, y, 1, 1); }
      }
      if (G.bbox) {
        const [a, bb, cc, d] = G.bbox;
        const [p0, q0] = toXY(cc, bb), [p1, q1] = toXY(a, d);
        ctx.fillStyle = "rgba(217,164,65,.18)"; ctx.fillRect(p0, q0, p1 - p0, q1 - q0);
        ctx.strokeStyle = "#d9a441"; ctx.lineWidth = 2; ctx.strokeRect(p0, q0, p1 - p0, q1 - q0); ctx.lineWidth = 1;
        // grade de celulas (256 m)
        const step = 256 / M_PER_DEG * s;
        if (step > 3) {
          ctx.strokeStyle = "rgba(217,164,65,.35)";
          for (let x = p0 + step; x < p1; x += step) { ctx.beginPath(); ctx.moveTo(x, q0); ctx.lineTo(x, q1); ctx.stroke(); }
          for (let y = q0 + step; y < q1; y += step) { ctx.beginPath(); ctx.moveTo(p0, y); ctx.lineTo(p1, y); ctx.stroke(); }
        }
      }
    }
    let drag = null;
    const pos = e => { const r = c.getBoundingClientRect(); return [(e.clientX - r.left) * W / r.width, (e.clientY - r.top) * H / r.height]; };
    const clampLL = ([la, lo]) => [Math.min(lat1, Math.max(lat0, la)), Math.min(lon1, Math.max(lon0, lo))];
    c.addEventListener("pointerdown", e => { drag = clampLL(toLL(...pos(e))); c.setPointerCapture(e.pointerId); });
    c.addEventListener("pointermove", e => {
      if (!drag) return;
      const p = clampLL(toLL(...pos(e)));
      G.bbox = [Math.min(drag[0], p[0]), Math.min(drag[1], p[1]), Math.max(drag[0], p[0]), Math.max(drag[1], p[1])];
      draw(); showBox();
    });
    c.addEventListener("pointerup", () => { if (drag) { drag = null; revalidate(); } });
    draw();
    G.redraw = draw;
    return c;
  }

  function cellsOf(bb) {
    if (!bb) return 0;
    const kx = Math.cos(((bb[0] + bb[2]) / 2) * Math.PI / 180);
    return Math.ceil((bb[3] - bb[1]) * kx * M_PER_DEG / 256) * Math.ceil((bb[2] - bb[0]) * M_PER_DEG / 256);
  }

  function showBox() {
    const el = $("#genbbox"); if (!el) return;
    if (!G.bbox) { el.textContent = "arraste no mapa para escolher a area"; return; }
    const f = v => v.toFixed(5);
    const kx = Math.cos(((G.bbox[0] + G.bbox[2]) / 2) * Math.PI / 180);
    const wm = (G.bbox[3] - G.bbox[1]) * kx * M_PER_DEG, hm = (G.bbox[2] - G.bbox[0]) * M_PER_DEG;
    el.textContent = `S ${f(G.bbox[0])}  O ${f(G.bbox[1])}  N ${f(G.bbox[2])}  L ${f(G.bbox[3])}  -  ${(wm / 1000).toFixed(2)} x ${(hm / 1000).toFixed(2)} km  -  ~${cellsOf(G.bbox)} celula(s)`;
  }

  function revalidate() {
    clearTimeout(G.vt);
    G.vt = setTimeout(async () => {
      try {
        const v = await api("/api/osm/validate", { path: G.path, bbox: G.bbox, name: G.name });
        G.check = v; renderCheck();
      } catch (e) { G.check = { ok: false, avisos: [e.message] }; renderCheck(); }
    }, 250);
  }

  function fmtSecs(s) {
    if (s == null) return "?";
    s = Math.round(s);
    return s < 90 ? `${s}s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;
  }

  function renderCheck() {
    const el = $("#gencheck"); if (!el) return;
    el.innerHTML = "";
    const v = G.check; if (!v) return;
    const ok = v.ok && (!G.bbox || v.cobre_bbox !== false);
    el.append(h("div", { class: ok ? "okbox" : "warn" },
      h("b", {}, ok ? "Arquivo valido" : "Atencao"),
      v.formato ? h("div", {}, `formato ${v.formato}  -  ${(v.nodes || 0).toLocaleString("pt-BR")} nos  -  ${(v.ways || 0).toLocaleString("pt-BR")} ways`) : "",
      G.bbox ? h("div", {}, v.cobre_bbox === false ? "o arquivo NAO cobre a area escolhida inteira" : "cobre a area escolhida") : "",
      v.celulas_estimadas != null && G.bbox ? h("div", {}, `estimativa: ${v.celulas_estimadas} celula(s), cerca de ${fmtSecs(v.segundos_estimados)} para gerar`) : "",
      v.destino ? h("div", {}, "projeto em ", h("code", {}, v.destino), v.destino_existe ? " (ja existe: troque o nome)" : "") : "",
      ...(v.avisos || []).map(a => h("div", { class: "note" }, "- " + a))));
    const go = $("#gengo");
    if (go) go.disabled = G.busy || !ok || !G.bbox || v.destino_existe;
  }

  async function openFile(p) {
    G.path = p.trim(); G.info = null; G.bbox = null; G.check = null;
    if (!G.path) return render();
    try {
      say("lendo o arquivo...");
      G.info = await api("/api/osm/validate", { path: G.path, name: G.name });
      G.check = G.info;
      if (!G.name) G.name = G.path.split(/[\\/]/).pop().replace(/\.osm(\.pbf)?$|\.pbf$/i, "").replace(/[^A-Za-z0-9 _-]/g, " ").trim() || "Lugar real";
      say("");
    } catch (e) { say(e.message, true); G.check = { ok: false, avisos: [e.message] }; }
    render();
  }

  async function generate() {
    if (G.busy) return;
    G.busy = true; renderCheck();
    try {
      await api("/api/generate", { path: G.path, bbox: G.bbox, name: G.name, footprints: G.foot });
      window.PZMS.progress.watch("generate");
      const t = setInterval(async () => {
        const s = await api("/api/state").catch(() => null);
        const j = s && s.jobs && s.jobs.generate;
        if (!j || !j.done) return;
        clearInterval(t); G.busy = false; renderCheck();
        if (j.error) return say(j.error, true);
        S.state = s; resetView(); afterState(); window.PZMS.showTab("tiles");
        say(`mapa gerado: ${j.result.path}`);
      }, 1000);
    } catch (e) { G.busy = false; renderCheck(); say(e.message, true); }
  }

  function render(tab) {
    tab = tab || $("#tab-gen");
    tab.innerHTML = "";
    const fin = h("input", { value: G.path, placeholder: "/caminho/para/area.osm.pbf", spellcheck: "false", onchange: e => openFile(e.target.value) });
    const pick = h("button", { onclick: async () => { try { const r = await api("/api/pick_file", {}); if (r.path) openFile(r.path); } catch (e) { say(e.message, true); } } }, "Escolher arquivo...");
    tab.append(h("h3", {}, "Criar mapa de um lugar real"),
      h("p", { class: "note" }, "Transforma um trecho do OpenStreetMap num mapa editavel: ruas, calcadas, predios com salas e moveis, agua, parques e arvores. 1 quadrado = 1 metro."),
      tutorial(),
      h("label", { class: "fld" }, h("span", {}, "Arquivo OSM (.osm ou .osm.pbf)"), h("div", { class: "row" }, fin, pick)));
    if (G.info && G.info.bounds) {
      const nm = h("input", { value: G.name, oninput: e => { G.name = e.target.value; revalidate(); } });
      const fp = h("input", { value: G.foot, placeholder: "opcional: contornos com altura (.gpkg/.geojson/.shp)", spellcheck: "false", onchange: e => { G.foot = e.target.value.trim(); } });
      tab.append(h("label", { class: "fld" }, h("span", {}, "Area"), areaMap(G.info), h("small", { id: "genbbox", class: "note" })),
        h("label", { class: "fld" }, h("span", {}, "Nome do mapa"), nm),
        h("label", { class: "fld" }, h("span", {}, "Fonte extra"), fp, h("small", { class: "note" }, "melhora alturas e formatos dos predios (ex.: GeoSampa)")),
        h("div", { id: "gencheck" }),
        h("div", { class: "row" }, h("button", { id: "gengo", class: "primary", onclick: generate }, "Criar mapa do lugar")));
      showBox();
    } else tab.append(h("div", { id: "gencheck" }));
    renderCheck();
  }

  (window.PZMS_TABS = window.PZMS_TABS || {}).gen = render;
})();
