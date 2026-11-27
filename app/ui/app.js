// PZ Map Studio - UI principal
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
};

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
  });
  const ct = r.headers.get("Content-Type") || "";
  if (ct.startsWith("application/json")) {
    const j = await r.json();
    if (!r.ok || j.error) throw new Error(j.error || r.statusText);
    return j;
  }
  if (!r.ok) throw new Error(r.statusText);
  return r.arrayBuffer();
}

function say(t, err = false) {
  const m = $("#msg"); m.textContent = t || ""; m.className = err ? "err" : "";
  if (t && !err) setTimeout(() => { if (m.textContent === t) m.textContent = ""; }, 4000);
}

// ---------------------------------------------------------------- estado
const S = {
  state: null, atlas: null, gl: null, pal: null, itemById: new Map(), itemByTile: new Map(),
  tool: "brush", item: null, brush: 1, z: 0, eraseMode: "top", eraseFloor: false, wallMode: "wall", paintMode: "add",
  cells: new Map(),        // "cx,cy" -> {loading, loaded}
  rooms: [], hover: null, drag: null, cat: "terreno", sub: null, search: "",
  stroke: null, queue: [], flushT: null, needDraw: true, lastRoom: "bedroom",
};

const CS = 256, CH = 8, NCH = 32;

// ---------------------------------------------------------------- modal
function modal(title, body, actions) {
  const box = $("#modalbox"); box.innerHTML = "";
  box.append(h("h3", {}, title), ...[].concat(body));
  if (actions) box.append(h("div", { class: "actions" }, actions));
  $("#modal").classList.remove("hidden");
  const f = box.querySelector("input,select"); if (f) setTimeout(() => f.focus(), 30);
}
function closeModal() { $("#modal").classList.add("hidden"); }
$("#modal").addEventListener("mousedown", e => { if (e.target.id === "modal" && !S.modalLocked) closeModal(); });

// ---------------------------------------------------------------- inicializacao
async function boot() {
  try { S.state = await api("/api/state"); } catch (e) { say("servidor indisponivel: " + e.message, true); return; }
  const st = S.state;
  $("#gamever").textContent = st.game.version ? `Jogo ${st.game.version}${st.game.supported ? "" : " (nao testado)"}` : "jogo nao encontrado";
  if (!st.game.media) return setupGame();
  if (!st.cache.ready) return buildCache();
  if (!S.atlas) await loadAtlas();
  if (!S.pal) await loadPalette();
  afterState();
  if (S.state.project && !S.cells.size) resetView();
  if (!S.state.project && S.state.resume) await resumeSession(S.state.resume);
  for (const f of window.PZMS_INIT || []) f();
  if (!S.viewT) S.viewT = setInterval(postView, 2000);
}

// o instalador fecha o app salvando; ao reabrir volta ao mesmo projeto e camera
async function resumeSession(r) {
  try { await api("/api/resume/done", {}); } catch (e) { /* segue */ }
  await openProject(r.path);
  const v = r.view || {};
  if (!S.state.project || v.x == null) return;
  if (v.z != null && v.z !== S.z) setZ(v.z);
  Object.assign(S.gl.cam, { x: v.x, y: v.y, zoom: v.zoom || S.gl.cam.zoom });
  S.needDraw = true; ensureCells();
  say("projeto reaberto de onde parou");
}

function postView() {
  if (!S.state || !S.state.project || !S.gl) return;
  const c = S.gl.cam, v = { x: c.x, y: c.y, zoom: c.zoom, z: S.z }, k = JSON.stringify(v);
  if (k === S.viewK) return;
  S.viewK = k; api("/api/view", v).catch(() => {});
}

function setupGame(err) {
  S.modalLocked = true;
  const inp = h("input", { type: "text", style: "flex:1", placeholder: "pasta do Project Zomboid" });
  const cands = (S.state.game.candidates || []).map(c => h("button", { onclick: () => inp.value = c }, c));
  modal("Onde esta o Project Zomboid?", [
    h("p", { class: "note" }, "Nao achei a instalacao pela Steam. Aponte a pasta do jogo (ProjectZomboid, o .app no Mac ou a pasta media). Os sprites sao lidos dela e convertidos num cache local; nada do jogo e redistribuido."),
    err ? h("p", { style: "color:var(--bad)" }, err) : null,
    h("div", { class: "row" }, inp, h("button", { onclick: async () => { try { const r = await api("/api/pick_folder", {}); if (r.path) inp.value = r.path; } catch (e) { say(e.message, true); } } }, "Escolher...")),
    cands.length ? h("div", { class: "row" }, cands) : null,
  ], [h("button", { class: "primary", onclick: async () => {
    try { S.state = await api("/api/game", { path: inp.value }); S.modalLocked = false; closeModal(); boot(); }
    catch (e) { setupGame(e.message); }
  } }, "Usar esta pasta")]);
}

async function buildCache() {
  S.modalLocked = true;
  const bar = h("div", { class: "bar" }, h("i")), txt = h("div", { class: "note" }, "iniciando...");
  modal("Preparando sprites (so na primeira vez)", [
    h("p", { class: "note" }, `Lendo os tiles do seu jogo ${S.state.game.version || ""} e gerando um atlas reduzido em cache local.`), bar, txt]);
  await api("/api/cache/build", {});
  window.PZMS.progress && window.PZMS.progress.watch("cache");
  const t = setInterval(async () => {
    const j = (await api("/api/jobs")).cache;
    if (!j) return;
    bar.firstChild.style.width = (j.frac * 100).toFixed(1) + "%"; txt.textContent = j.msg;
    if (j.done) {
      clearInterval(t); S.modalLocked = false;
      if (j.error) { txt.textContent = "Erro: " + j.error; return; }
      closeModal(); boot();
    }
  }, 400);
}

async function loadAtlas() {
  say("carregando sprites...");
  const meta = await (await fetch("/cache/atlas.json")).json();
  const pages = await Promise.all([...Array(meta.pages).keys()].map(async i => {
    const b = await (await fetch(`/cache/atlas/p${i}.png`)).blob();
    return createImageBitmap(b, { premultiplyAlpha: "none", colorSpaceConversion: "none" });
  }));
  S.atlas = new Atlas(meta, pages);
  S.gl = new IsoGL($("#gl"), S.atlas, pages);
  S.gl.resize(); resizeOv();
  say("");
  requestAnimationFrame(frame);
}

async function loadPalette() {
  S.pal = await api("/api/palette");
  for (const it of S.pal.items) {
    S.itemById.set(it.id, it);
    for (const p of it.parts) if (!S.itemByTile.has(p[2])) S.itemByTile.set(p[2], it);
    if (it.wall) for (const t of Object.values(it.wall)) if (!S.itemByTile.has(t)) S.itemByTile.set(t, it);
  }
  renderCats();
  selectItem(S.itemById.get("t:blends_natural_01_32") || S.pal.items[0]);
}

function afterState() {
  const p = S.state.project;
  $("#empty").classList.toggle("hidden", !!p);
  $("#projname").textContent = p ? `${p.meta.name}  -  ${p.cells.length} celula(s)` : "";
  $("#bUndo").disabled = !(p && p.undo); $("#bRedo").disabled = !(p && p.redo);
  $("#bUndo").title = p && p.undo ? `Desfazer: ${p.undo}` : "Desfazer";
  $("#bRedo").title = p && p.redo ? `Refazer: ${p.redo}` : "Refazer";
  const rec = $("#recent"); rec.innerHTML = "";
  for (const r of S.state.recent || []) rec.append(h("button", { onclick: () => openProject(r) }, r));
  S.needDraw = true;
}

// ---------------------------------------------------------------- projeto
function resetView() {
  for (const k of S.cells.keys()) { const [cx, cy] = k.split(",").map(Number); S.gl.dropCell(cx, cy); }
  S.cells.clear(); S.rooms = [];
  const p = S.state.project; if (!p) return;
  const sp = p.meta.spawn || [(p.bounds[0] + p.bounds[2]) * 128, (p.bounds[1] + p.bounds[3]) * 128, 0];
  centerOn(sp[0], sp[1]);
}
function centerOn(x, y) {
  const g = S.gl; g.cam.zoom = g.cam.zoom || 1;
  const sx = (x - y) * ISO.D, sy = (x + y) * ISO.HH + ISO.HH - S.z * ISO.FL;
  g.cam.x = sx - g.vw / 2 / g.cam.zoom; g.cam.y = sy - g.vh / 2 / g.cam.zoom;
  S.needDraw = true;
}

async function openProject(path) {
  try { S.state = await api("/api/project/open", { path }); closeModal(); resetView(); afterState(); }
  catch (e) { say(e.message, true); }
}

function dlgNew() {
  const f = {
    name: h("input", { value: "Meu Mapa" }), w: h("input", { type: "number", value: 1, min: 1, max: 64 }),
    hh: h("input", { type: "number", value: 1, min: 1, max: 64 }),
    cx0: h("input", { type: "number", value: 2 }), cy0: h("input", { type: "number", value: 2 }),
    ground: h("input", { type: "checkbox", checked: true }),
  };
  modal("Novo mapa", [
    h("div", { class: "row" }, h("label", {}, "Nome"), f.name),
    h("div", { class: "row" }, h("label", {}, "Tamanho (celulas)"), f.w, "x", f.hh, h("span", { class: "note" }, "1 celula = 256x256 quadrados")),
    h("div", { class: "row" }, h("label", {}, "Posicao no mundo"), f.cx0, f.cy0, h("span", { class: "note" }, "celula inicial (mapa proprio)")),
    h("div", { class: "row" }, h("label", {}, "Preencher com grama"), f.ground),
    h("p", { class: "note" }, `Salvo em ${S.state.projects_dir}`),
  ], [h("button", { onclick: closeModal }, "Cancelar"), h("button", { class: "primary", onclick: async () => {
    try {
      S.state = await api("/api/project/new", { name: f.name.value, w: +f.w.value, h: +f.hh.value, cx0: +f.cx0.value, cy0: +f.cy0.value, ground: f.ground.checked });
      closeModal(); resetView(); afterState(); say("projeto criado");
    } catch (e) { say(e.message, true); }
  } }, "Criar")]);
}

function dlgOpen() {
  const inp = h("input", { style: "flex:1", placeholder: "pasta do projeto" });
  modal("Abrir projeto", [
    ...(S.state.recent || []).map(r => h("button", { style: "text-align:left", onclick: () => openProject(r) }, r)),
    h("div", { class: "row" }, inp, h("button", { onclick: async () => { try { const r = await api("/api/pick_folder", {}); if (r.path) inp.value = r.path; } catch (e) { say(e.message, true); } } }, "Escolher...")),
  ], [h("button", { onclick: closeModal }, "Cancelar"), h("button", { class: "primary", onclick: () => openProject(inp.value) }, "Abrir")]);
}

async function save() {
  if (!S.state.project) return;
  await flush();
  try { S.state = await api("/api/project/save", {}); afterState(); say("salvo"); } catch (e) { say(e.message, true); }
}

// ---------------------------------------------------------------- celulas e chunks
function projCells() { return new Set((S.state.project ? S.state.project.cells : []).map(c => c[0] + "," + c[1])); }

function visibleCells() {
  const g = S.gl, out = [];
  const pts = [[0, 0], [g.vw, 0], [0, g.vh], [g.vw, g.vh]].map(([a, b]) => g.toWorld(a, b, 0));
  const pts2 = [[0, 0], [g.vw, 0], [0, g.vh], [g.vw, g.vh]].map(([a, b]) => g.toWorld(a, b, S.z + 4));
  const all = pts.concat(pts2);
  const x0 = Math.floor(Math.min(...all.map(p => p[0])) / CS), x1 = Math.floor(Math.max(...all.map(p => p[0])) / CS);
  const y0 = Math.floor(Math.min(...all.map(p => p[1])) / CS), y1 = Math.floor(Math.max(...all.map(p => p[1])) / CS);
  const pc = projCells();
  for (let cx = x0; cx <= x1; cx++) for (let cy = y0; cy <= y1; cy++) if (pc.has(cx + "," + cy)) out.push([cx, cy]);
  return out;
}

let loadingN = 0;
function ensureCells() {
  if (!S.state.project || !S.gl) return;
  const vis = visibleCells();
  if (S.gl.cam.zoom < 0.2) return;
  for (const [cx, cy] of vis) {
    const k = cx + "," + cy;
    if (S.cells.has(k) || loadingN >= 2) continue;
    S.cells.set(k, { loading: true });
    loadingN++;
    loadCell(cx, cy).finally(() => loadingN--);
  }
  // descarrega celulas longe da vista
  if (S.cells.size > 16) {
    const keep = new Set(vis.map(c => c[0] + "," + c[1]));
    for (const k of [...S.cells.keys()]) if (!keep.has(k) && !S.cells.get(k).loading) {
      const [cx, cy] = k.split(",").map(Number); S.gl.dropCell(cx, cy); S.cells.delete(k);
    }
  }
  fetchRooms();
}

const cellChain = new Map();
function loadCell(cx, cy, chunks) {
  const k = cx + "," + cy;
  const p = (cellChain.get(k) || Promise.resolve()).then(() => loadCellNow(cx, cy, chunks));
  cellChain.set(k, p);
  p.finally(() => { if (cellChain.get(k) === p) cellChain.delete(k); });
  return p;
}
async function loadCellNow(cx, cy, chunks) {
  try {
    const q = `/api/cell?cx=${cx}&cy=${cy}` + (chunks ? `&chunks=${chunks.join(",")}` : "");
    applyBlob(await api(q));
    S.cells.set(cx + "," + cy, { loaded: true });
  } catch (e) { S.cells.delete(cx + "," + cy); say(e.message, true); }
  S.needDraw = true;
}

function applyBlob(buf) {
  const dv = new DataView(buf), hl = dv.getUint32(0, true);
  const head = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hl)));
  const data = new Int32Array(buf, 4 + hl);
  const ox = head.cx * CS, oy = head.cy * CS, names = head.names;
  const per = new Map();
  for (let i = 0; i < data.length;) {
    const x = data[i], y = data[i + 1], z = data[i + 2], n = data[i + 3];
    const ci = (x >> 3) * NCH + (y >> 3);
    let a = per.get(ci); if (!a) per.set(ci, a = []);
    const nm = new Array(n);
    for (let j = 0; j < n; j++) nm[j] = names[data[i + 4 + j]];
    a.push([ox + x, oy + y, z, nm]);
    i += 4 + n;
  }
  const cis = head.full ? [...Array(1024).keys()] : Object.keys(head.ver).map(Number);
  for (const ci of cis) {
    const sq = per.get(ci);
    const key = `${head.cx},${head.cy},${ci}`;
    if (!sq) S.gl.dropChunk(key); else S.gl.setChunk(key, S.gl.build(sq));
  }
}

async function applyChanged(r) {
  if (!r) return;
  S.state.project.undo = r.undo; S.state.project.redo = r.redo; S.state.project.nu = r.nu; S.state.project.nr = r.nr;
  S.state.project.dirty = true;
  afterState();
  let rooms = false;
  for (const [cx, cy, cis] of r.changed) {
    const k = cx + "," + cy;
    if (!projCells().has(k)) { S.state.project.cells.push([cx, cy]); }
    const cs = cis.filter(c => c >= 0);
    if (cis.includes(-1)) rooms = true;
    if (cs.length && S.cells.get(k)) await loadCell(cx, cy, cs);
  }
  if (rooms) fetchRooms(true);
  S.needDraw = true;
}

let roomT = 0;
async function fetchRooms(force) {
  if (!S.state.project) return;
  const g = S.gl, pts = [[0, 0], [g.vw, 0], [0, g.vh], [g.vw, g.vh]].map(([a, b]) => g.toWorld(a, b, S.z));
  const box = [Math.floor(Math.min(...pts.map(p => p[0]))), Math.floor(Math.min(...pts.map(p => p[1]))),
    Math.ceil(Math.max(...pts.map(p => p[0]))), Math.ceil(Math.max(...pts.map(p => p[1])))];
  const key = box.map(v => Math.floor(v / 64)).join(",");
  if (!force && key === S.roomKey) return;
  const now = Date.now(); if (!force && now - roomT < 400) return; roomT = now;
  S.roomKey = key;
  try { S.rooms = (await api(`/api/rooms?x0=${box[0] - 64}&y0=${box[1] - 64}&x1=${box[2] + 64}&y1=${box[3] + 64}`)).rooms; S.needDraw = true; }
  catch (e) { /* sem projeto */ }
}

// ---------------------------------------------------------------- edicao
function queueOps(ops, label) {
  if (!ops.length) return;
  S.queue.push(...ops); S.queueLabel = label;
  if (!S.flushT) S.flushT = setTimeout(flush, 70);
  // previa imediata local: o servidor confirma e o chunk e refeito
}
// edicao, desfazer e refazer passam por UMA fila: o servidor atende em paralelo e um Ctrl+Z
// chegando antes do ultimo pedaco do pincel desfazia o comando errado
S.editChain = Promise.resolve();
function serial(fn) { const p = S.editChain.then(fn, fn); S.editChain = p.catch(() => {}); return p; }
function flush() {
  clearTimeout(S.flushT); S.flushT = null;
  if (!S.queue.length) return S.editChain;
  const ops = S.queue, label = S.queueLabel || "editar", stroke = S.stroke; S.queue = [];
  return serial(async () => {
    try { await applyChanged(await api("/api/edit", { ops, label, stroke })); }
    catch (e) { say(e.message, true); }
  });
}
async function undo() { await flush(); return serial(async () => { try { await applyChanged(await api("/api/undo", {})); } catch (e) { say(e.message, true); } }); }
async function redo() { await flush(); return serial(async () => { try { await applyChanged(await api("/api/redo", {})); } catch (e) { say(e.message, true); } }); }

function itemParts(it) { return it ? it.parts : []; }

// apagar com pincel/area: tira so o tile escolhido (e as variantes de grama); sem item, apaga o topo
function rmOp(x, y, it) {
  if (!it) return { x, y, z: S.z, erase: "top" };
  const t = it.parts.map(p => p[2]);
  return { x, y, z: S.z, remove: GRASS.includes(t[0]) ? [...t, ...GRASS] : t };
}
function brushOps(x, y) {
  const it = S.item;
  if (S.paintMode === "erase") {
    const r = it && it.kind !== "floor" && it.kind !== "overlay" ? 0 : S.brush >> 1, ops = [];
    for (let dx = -r; dx <= r; dx++) for (let dy = -r; dy <= r; dy++) ops.push(rmOp(x + dx, y + dy, it));
    return ops;
  }
  if (!it) return [];
  const ops = [];
  if (it.kind === "floor" || it.kind === "overlay") {
    const r = S.brush >> 1;
    for (let dx = -r; dx <= r; dx++) for (let dy = -r; dy <= r; dy++)
      ops.push({ x: x + dx, y: y + dy, z: S.z, tile: pickVariant(it, x + dx, y + dy) });
  } else {
    for (const [dx, dy, t] of it.parts) ops.push({ x: x + dx, y: y + dy, z: S.z, tile: t });
  }
  return ops;
}
const GRASS = ["blends_natural_01_32", "blends_natural_01_37", "blends_natural_01_38", "blends_natural_01_39"];
function pickVariant(it, x, y) {       // grama: alterna variantes para nao ficar repetitivo
  const t = it.parts[0][2];
  return GRASS.includes(t) ? GRASS[((x * 73856093) ^ (y * 19349663)) >>> 0 & 3] : t;
}

function rectOf(a, b) {
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
}

function areaOps(a, b) {
  const [x0, y0, x1, y1] = rectOf(a, b), ops = [];
  if ((x1 - x0 + 1) * (y1 - y0 + 1) > 70000) { say("area grande demais (max ~256x256)", true); return []; }
  for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) {
    if (S.tool === "erase") ops.push({ x, y, z: S.z, erase: S.eraseMode, floor: S.eraseFloor });
    else if (S.paintMode === "erase") ops.push(rmOp(x, y, S.item));
    else if (S.item) for (const [dx, dy, t] of S.item.parts) if (S.item.kind === "floor" || S.item.kind === "overlay" || (dx === 0 && dy === 0)) ops.push({ x: x + dx, y: y + dy, z: S.z, tile: t });
  }
  return ops;
}

function wallFam() {
  const it = S.item;
  if (it && it.wall) return it.wall;
  return (S.itemById.get("w:walls_exterior_house_01_0") || {}).wall;
}

function wallOps(a, b) {
  const f = wallFam(); if (!f) return [];
  const [x0, y0, x1, y1] = rectOf(a, b), ops = [], z = S.z;
  const put = (x, y, t) => t && ops.push({ x, y, z, tile: t });
  if (y0 === y1 && x0 !== x1) { for (let x = x0; x <= x1; x++) put(x, y0, f.N); return ops; }
  if (x0 === x1 && y0 !== y1) { for (let y = y0; y <= y1; y++) put(x0, y, f.W); return ops; }
  for (let x = x0; x <= x1; x++) { put(x, y0, x === x0 ? (f.NW || f.N) : f.N); put(x, y1 + 1, f.N); }
  for (let y = y0; y <= y1; y++) { if (y !== y0) put(x0, y, f.W); put(x1 + 1, y, f.W); }
  if (x0 === x1 && y0 === y1) { put(x0, y0, f.NW); }
  put(x1 + 1, y1 + 1, f.SE);
  return ops;
}

// lado da parede mais perto do cursor dentro do quadrado
// borda mais perto das 4: S vira N do quadrado de baixo, E vira W do quadrado da direita
function edgeAt(fx, fy) {
  let x = Math.floor(fx), y = Math.floor(fy);
  const ax = fx - x, ay = fy - y;
  const d = [[ax, "W"], [ay, "N"], [1 - ax, "E"], [1 - ay, "S"]].sort((a, b) => a[0] - b[0])[0][1];
  if (d === "E") return [x + 1, y, "W"];
  if (d === "S") return [x, y + 1, "N"];
  return [x, y, d];
}

// portas/janelas vanilla (pares W/N) e a escolhida em cada modo
const OPEN = { list: null, sel: { door: "fixtures_doors_01_0", window: "fixtures_windows_01_0" }, q: "" };
try { Object.assign(OPEN.sel, JSON.parse(localStorage.getItem("pzms.openings") || "{}")); } catch (e) { /* sem storage */ }
async function openings() {
  if (!OPEN.list) { try { OPEN.list = await api("/api/openings"); } catch (e) { OPEN.list = { door: [], window: [] }; } }
  return OPEN.list;
}
function openingSel(kind) {
  const L = (OPEN.list || {})[kind] || [];
  return L.find(o => o.W === OPEN.sel[kind]) || L[0] ||
    (kind === "door" ? { W: "fixtures_doors_01_0", N: "fixtures_doors_01_1" } : { W: "fixtures_windows_01_0", N: "fixtures_windows_01_1" });
}

function wallClickOps(fx, fy) {
  const f = wallFam(); if (!f) return [];
  const [x, y, side] = edgeAt(fx, fy), z = S.z;
  if (S.wallMode === "window" || S.wallMode === "door") {
    const k = S.wallMode === "door" ? "door" : "win";
    const def = (S.itemById.get("w:walls_exterior_house_01_0") || {}).wall || {};
    const fr = f[k + side] || def[k + side];               // parede sem moldura: usa a da casa padrao
    const o = openingSel(S.wallMode);
    return fr ? [{ x, y, z, tile: fr }, { x, y, z, tile: o[side] }] : [];
  }
  return [{ x, y, z, tile: side === "W" ? f.W : f.N }];
}

function openingOpts(kind) {
  const box = h("span", { class: "opgrid" });
  const search = h("input", { type: "search", placeholder: "buscar (en/pt/tile)", value: OPEN.q, style: "width:11em" });
  const name = o => o.pt || o.en || o.label;
  const fill = () => {
    box.innerHTML = "";
    const L = (OPEN.list || {})[kind] || [], q = fold(OPEN.q);
    const cur = openingSel(kind);
    for (const o of L) {
      if (q && ![o.label, o.en, o.pt, o.W, o.N].some(t => fold(t).includes(q))) continue;
      const c = h("canvas", { width: 30, height: 44 });
      try { S.atlas.thumb(c, [o.W], 30, 44); } catch (e) { /* atlas carregando */ }
      box.append(h("button", { class: o.W === cur.W ? "on" : "", title: `${name(o)}${o.en && o.pt ? " / " + o.en : ""}\n${o.W} | ${o.N}`,
        onclick: () => { OPEN.sel[kind] = o.W; try { localStorage.setItem("pzms.openings", JSON.stringify(OPEN.sel)); } catch (e) { /* ok */ } setTool("wall"); } }, c));
    }
    if (!box.children.length) box.append(h("span", { style: "color:var(--dim)" }, OPEN.list ? "nada encontrado" : "carregando..."));
  };
  search.addEventListener("input", () => { OPEN.q = search.value; fill(); });
  if (!OPEN.list) openings().then(() => { if (S.tool === "wall" && S.wallMode === kind) setTool("wall"); });
  fill();
  const cur = openingSel(kind);
  return [h("label", {}, kind === "door" ? "Porta" : "Janela"), h("b", { class: "opname", title: `${cur.W} | ${cur.N}` }, name(cur)), search, box,
    h("label", { style: "color:var(--dim)" }, "clique na borda (fica amarela): as 4 bordas do quadrado servem  -  a moldura vem da parede escolhida")];
}

const ROOM_NAMES = ["bedroom", "livingroom", "kitchen", "bathroom", "hall", "closet", "office", "garagestorage",
  "storage", "laundry", "diningroom", "empty", "emptyoutside", "grocery", "gasstore", "pharmacy", "pharmacystorage",
  "policeoffice", "prisoncells", "classroom", "medclinic", "hospitalroom", "church", "bank", "library", "post",
  "bar", "restaurant", "motelroom", "warehouse", "mechanic", "gunstore", "zippeestore", "clothesstore", "firestorage"];

let ROOM_TYPES = null;
async function roomTypes() {
  if (!ROOM_TYPES) { try { ROOM_TYPES = await api("/api/rooms/types"); } catch (e) { ROOM_TYPES = { types: ROOM_NAMES.map(n => ({ name: n, type: "", count: 0 })), labels: {} }; } }
  return ROOM_TYPES;
}
// escolha de tipo de sala vanilla: busca + grupos por tipo de predio
async function pickRoomType(title, initial, extra, onOk) {
  const T = await roomTypes();
  let sel = initial || S.lastRoom || "bedroom", grp = null;
  const q = h("input", { type: "search", placeholder: "Buscar tipo (ex.: kitchen, pharmacy, policestorage)..." });
  const chips = h("div", { class: "chips" }), list = h("div", { class: "rtlist" }), cur = h("b", {}, sel);
  const groups = [...new Set(T.types.map(t => t.type))];
  function draw() {
    chips.innerHTML = ""; list.innerHTML = "";
    chips.append(h("button", { class: grp == null ? "on" : "", onclick: () => { grp = null; draw(); } }, "Todos"));
    for (const g of groups) chips.append(h("button", { class: grp === g ? "on" : "", onclick: () => { grp = g; draw(); } }, T.labels[g] || g));
    const k = q.value.trim().toLowerCase();
    const rows = T.types.filter(t => (grp == null || t.type === grp) && (!k || t.name.includes(k))).slice(0, 400);
    for (const t of rows) list.append(h("button", { class: t.name === sel ? "on" : "", title: t.count ? `aparece em ${t.count} predio(s) vanilla` : "so no Distributions.lua",
      onclick: () => { sel = t.name; cur.textContent = sel; draw(); }, ondblclick: ok }, t.name, h("small", {}, t.count ? String(t.count) : "")));
    if (k && !rows.some(r => r.name === k) && /^[a-z0-9_]+$/.test(k)) list.append(h("button", { onclick: () => { sel = k; cur.textContent = sel; draw(); } }, `usar "${k}" (nome proprio: so os itens das regras de Spawn de itens)`));
  }
  q.addEventListener("input", draw);
  function ok() { S.lastRoom = sel; closeModal(); onOk(sel); }
  modal(title, [q, chips, list, h("p", { class: "note" }, "O tipo define o loot vanilla e quais zumbis aparecem. Selecionado: ", cur), ...(extra || [])],
    [h("button", { onclick: closeModal }, "Cancelar"), h("button", { class: "primary", onclick: ok }, "OK")]);
  draw(); setTimeout(() => q.focus(), 30);
}
async function dlgRoom(a, b) {
  const [x0, y0, x1, y1] = rectOf(a, b);
  // clique simples numa sala existente: trocar o tipo
  if (x0 === x1 && y0 === y1) {
    const r = await api(`/api/rooms/at?x=${x0}&y=${y0}&z=${S.z}`).catch(() => ({}));
    if (r.room) return pickRoomType(`Trocar tipo da sala "${r.room.name}"`, r.room.name, [], async name => {
      try { applyChanged(await api("/api/rooms/rename", { x: x0, y: y0, z: S.z, name })); say(`sala agora e ${name}`); } catch (e) { say(e.message, true); }
    });
  }
  const st = await api(`/api/rooms/at?x=${a[0]}&y=${a[1]}&z=${S.z}`).catch(() => ({}));
  const join = h("input", { type: "checkbox", checked: !!st.room });
  const extra = st.room ? [h("label", { class: "row" }, join, `juntar ao predio da sala "${st.room.name}" (mesmo predio: alarme, chave e loot juntos)`)] : [];
  pickRoomType(`Sala ${x1 - x0 + 1}x${y1 - y0 + 1} no andar ${S.z}`, S.lastRoom, extra, async name => {
    try {
      applyChanged(await api("/api/rooms/add", { rooms: [{ name, z: S.z, rects: [[x0, y0, x1 - x0 + 1, y1 - y0 + 1]] }], label: "sala " + name,
        join: join.checked && st.room ? [a[0], a[1], S.z] : null }));
    } catch (e) { say(e.message, true); }
  });
}

// ---------------------------------------------------------------- paleta (menu por categorias, estilo construcao)
function renderCats() {
  const el = $("#cats"); el.innerHTML = "";
  for (const c of S.pal.cats) {
    if (!c.n) continue;
    el.append(h("button", { class: c.key === S.cat ? "on" : "", onclick: () => { S.cat = c.key; S.sub = null; S.search = ""; $("#search").value = ""; renderCats(); } },
      c.label, h("small", {}, c.n + " itens")));
  }
  renderSubs(); renderItems();
}
const fold = s => String(s).toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "");   // busca sem acento
const playerName = it => [it.pt, it.en && it.en !== it.pt ? it.en : ""].filter(Boolean).join(" / ");
function catItems() {
  const q = fold(S.search.trim());
  if (q) return S.pal.items.filter(it => [it.label, it.id, it.sub, it.en, it.pt].some(v => v && fold(v).includes(q)));
  return S.pal.items.filter(it => it.cat === S.cat);
}
function renderSubs() {
  const el = $("#subs"); el.innerHTML = "";
  if (S.search) return;
  const cnt = new Map();
  for (const it of catItems()) cnt.set(it.sub, (cnt.get(it.sub) || 0) + 1);
  const subs = [...cnt.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  if (subs.length < 2) return;
  el.append(h("button", { class: S.sub === null ? "on" : "", onclick: () => { S.sub = null; renderSubs(); renderItems(); } }, "Todos"));
  for (const [s, n] of subs) el.append(h("button", { class: S.sub === s ? "on" : "", title: n + " itens", onclick: () => { S.sub = s; renderSubs(); renderItems(); } }, s));
}

const thumbIO = new IntersectionObserver(ents => {
  for (const e of ents) if (e.isIntersecting) {
    const c = e.target; thumbIO.unobserve(c);
    const it = S.itemById.get(c.dataset.id);
    if (it) S.atlas.thumb(c, it.wall ? [[0, 0, it.wall.NW || it.wall.W], [1, 0, it.wall.N], [0, 1, it.wall.W]] : it.parts, 112, 112);
  }
}, { root: null, rootMargin: "200px" });

function renderItems(limit = 360) {
  const el = $("#items"); el.innerHTML = "";
  let items = catItems();
  if (S.sub !== null && !S.search) items = items.filter(it => it.sub === S.sub);
  for (const it of items.slice(0, limit)) {
    if (S.item && it.rot && it.rot[0] !== it.id && S.sub === null && !S.search && it.rot.length > 1) continue; // so 1 orientacao por grupo
    const c = h("canvas", { "data-id": it.id });
    const card = h("div", { class: "card" + (S.item && S.item.id === it.id ? " on" : ""), title: `${playerName(it) || it.label}\n${it.label}\n${it.icon}`, onclick: () => selectItem(it) }, c, h("span", {}, it.pt || it.en || it.label));
    el.append(card); thumbIO.observe(c);
  }
  if (items.length > limit) el.append(h("button", { style: "grid-column:1/-1", onclick: () => renderItems(limit * 3) }, `mostrar mais (${items.length - limit})`));
}

function selectItem(it) {
  if (!it) return;
  S.item = it;
  if (it.wall && !["wall", "erase", "inspect"].includes(S.tool)) setTool("wall");
  else if (!it.wall && S.tool === "wall") setTool("brush");
  else if (["pick", "inspect", "erase", "room", "place"].includes(S.tool)) setTool("brush");
  $$("#items .card").forEach(c => c.classList.toggle("on", c.firstChild.dataset.id === it.id));
  const sb = $("#selbox"); sb.innerHTML = "";
  const c = h("canvas"); S.atlas.thumb(c, it.wall ? [[0, 0, it.wall.NW || it.wall.W], [1, 0, it.wall.N], [0, 1, it.wall.W]] : it.parts, 96, 96);
  sb.append(c, h("div", { class: "t" }, it.label, h("small", {}, it.icon + (it.rot ? "  -  R gira" : "") + (it.wall ? "  -  arraste para paredes" : ""))));
  ctxPanel(it);
  updateGhost();
}

// ---------------------------------------------------------------- painel contextual do item/ferramenta
const PIECE = { W: "lado oeste", N: "lado norte", NW: "canto", SE: "pilar", winW: "janela O", winN: "janela N", doorW: "porta O", doorN: "porta N" };
const KEYPROPS = ["CustomName", "GroupName", "container", "ContainerCapacity", "Facing", "Material", "IsMoveAble", "PickUpWeight", "solid", "solidtrans", "BlocksPlacement", "WallW", "WallN", "WindowW", "WindowN", "doorW", "doorN", "IsFridge", "Freezer", "LightRadius"];
async function ctxPanel(it) {
  const box = h("div", { class: "ctx" });
  $("#selbox").append(box);
  // pecas e orientacoes do grupo de parede
  if (it.wall) {
    const row = h("div", { class: "pieces" });
    for (const [k, t] of Object.entries(it.wall)) {
      const c = h("canvas"); S.atlas.thumb(c, [[0, 0, t]], 44, 44);
      row.append(h("button", { title: `${PIECE[k] || k}: ${t}\nclique = pintar so esta peca com o Pincel`, onclick: () => {
        const one = { id: "t:" + t, label: `${it.label} (${PIECE[k] || k})`, icon: t, kind: "attach", parts: [[0, 0, t]] };
        S.itemById.set(one.id, one); selectItem(one); setTool("brush");
      } }, c, h("small", {}, PIECE[k] || k)));
    }
    box.append(h("div", { class: "sec" }, "Pecas do grupo"), row);
  } else if (it.rot && it.rot.length > 1) {
    const row = h("div", { class: "pieces" });
    for (const id of it.rot) {
      const o = S.itemById.get(id); if (!o) continue;
      const c = h("canvas"); S.atlas.thumb(c, o.parts, 44, 44);
      row.append(h("button", { class: o.id === it.id ? "on" : "", title: o.icon, onclick: () => selectItem(o) }, c));
    }
    box.append(h("div", { class: "sec" }, "Orientacoes (R gira)"), row);
  }
  // propriedades do tile e grupos de spawn se for container
  const tile = it.wall ? (it.wall.W || it.icon) : (it.parts[0] && it.parts[0][2]) || it.icon;
  let r; try { r = await api("/api/tile?name=" + encodeURIComponent(tile)); } catch (e) { return; }
  if (S.item !== it) return;
  const pr = r.props || {};
  const keys = KEYPROPS.filter(k => k in pr);
  if (keys.length) box.append(h("div", { class: "sec" }, "Propriedades"),
    h("div", { class: "props" }, ...keys.map(k => h("span", {}, h("b", {}, k), pr[k] ? " " + pr[k] : ""))));
  if (pr.container) {
    box.append(h("div", { class: "sec" }, "Spawn de itens"),
      h("div", { class: "row" }, h("span", { class: "note" }, `container "${pr.container}": loot vanilla pelo tipo da sala.`),
        window.PZMS_TOOLS && window.PZMS_TOOLS.loot ? h("button", { onclick: () => { window.PZMS_lootTarget = { container: pr.container }; setTool("loot"); } }, "Regras de spawn...") : ""));
  }
}

function rotate() {
  if (S.tool === "place" && window.PZMS_rotatePrefab) return window.PZMS_rotatePrefab();
  const it = S.item; if (!it || !it.rot) return;
  const i = it.rot.indexOf(it.id);
  selectItem(S.itemById.get(it.rot[(i + 1) % it.rot.length]));
}

// ---------------------------------------------------------------- ferramentas
function paintModeOpts(t) {
  return [h("label", {}, "Acao"), ...[["add", "adicionar"], ["erase", "apagar"]].map(([k, l]) => h("button", {
    class: S.paintMode === k ? "on" : "", title: k === "erase" ? "tira o item escolhido (X alterna)" : "coloca o item escolhido (X alterna)",
    onclick: () => { S.paintMode = k; setTool(t); } }, l))];
}
const TOOL_OPTS = {
  brush: () => [...paintModeOpts("brush"), h("label", {}, "Tamanho"), ...[1, 3, 5, 9].map(n => h("button", { class: S.brush === n ? "on" : "", onclick: () => { S.brush = n; setTool("brush"); } }, n)), h("label", {}, "[ ] muda  -  R gira")],
  erase: () => [h("label", {}, "Apagar"), ...[["top", "topo"], ["objects", "objetos"], ["walls", "paredes"], ["all", "tudo"]].map(([k, l]) => h("button", { class: S.eraseMode === k ? "on" : "", onclick: () => { S.eraseMode = k; setTool("erase"); } }, l)), h("label", { class: "chk", title: "Desligado: piso e misturas do chao ficam; so o que esta em cima e apagado" }, h("input", { type: "checkbox", checked: S.eraseFloor, onchange: e => { S.eraseFloor = e.target.checked; } }), "apagar chao"), h("label", {}, "Shift+arrastar = area")],
  wall: () => [h("label", {}, "Modo"), ...[["wall", "Parede (arraste: retangulo/linha)"], ["window", "Janela (clique)"], ["door", "Porta (clique)"]].map(([k, l]) => h("button", { class: S.wallMode === k ? "on" : "", onclick: () => { S.wallMode = k; setTool("wall"); } }, l)),
    ...(S.wallMode === "wall" ? [] : openingOpts(S.wallMode))],
  area: () => [...paintModeOpts("area"), h("label", {}, S.paintMode === "erase" ? "Arraste: tira o item escolhido do retangulo (sem item: apaga o topo)" : "Arraste para preencher um retangulo com o item escolhido")],
  room: () => [h("label", {}, "Arraste para criar sala  -  clique numa sala troca o tipo  -  comece o arraste dentro de uma sala para juntar ao predio  -  Alt+clique apaga o predio")],
  pick: () => [h("label", {}, "Clique para copiar o tile do topo (vira o item do pincel)")],
  inspect: () => [h("label", {}, "Clique: tiles do quadrado  -  Arraste: tiles da area (remover um tipo ou todos de uma vez)")],
  place: () => (window.PZMS_placeOpts ? window.PZMS_placeOpts() : [h("label", {}, "Escolha um predio na aba Predios")]),
};
function setTool(t) {
  const X = (window.PZMS_TOOLS || {})[t];
  if (S.pal && t !== S.tool) {
    if (t === "wall" && S.cat !== "paredes") { S.cat = "paredes"; S.sub = null; renderCats(); }
    else if ((t === "brush" || t === "area") && S.cat === "paredes" && !(S.item && S.item.id.startsWith("t:"))) { S.cat = "pisos"; S.sub = null; renderCats(); }
    if (t === "place") showTab("build");
    else if (["wall", "brush", "area"].includes(t) && S.tab && S.tab !== "tiles") showTab("tiles");
  }
  S.tool = t;
  $$("#tools button").forEach(b => b.classList.toggle("on", b.dataset.tool === t));
  const o = $("#toolopts");
  const fk = document.activeElement && o.contains(document.activeElement) ? document.activeElement.dataset.k : null;
  o.innerHTML = ""; o.append(...(X && X.opts ? X.opts() : TOOL_OPTS[t] ? TOOL_OPTS[t]() : []));
  if (fk) { const f = o.querySelector(`[data-k="${fk}"]`); if (f) f.focus(); }   // setas do teclado seguem no mesmo campo
  updateGhost(); S.needDraw = true;
}

function updateGhost() {
  if (!S.gl) return;
  const hv = S.hover;
  if (!hv || !S.state.project) { S.gl.setGhost(null); S.needDraw = true; return; }
  let sq = [];
  if (S.tool === "brush" && S.item && !S.drag && S.paintMode !== "erase") sq = brushOps(hv[0], hv[1]).map(o => [o.x, o.y, o.z, [o.tile]]);
  else if (S.tool === "place" && window.PZMS_ghost) sq = window.PZMS_ghost(hv[0], hv[1], S.z) || [];
  else if (S.tool === "wall" && S.drag && S.wallMode === "wall") sq = wallOps(S.drag.a, hv).map(o => [o.x, o.y, o.z, [o.tile]]);
  else if (S.tool === "wall" && S.wallMode !== "wall" && S.hoverF) sq = wallClickOps(...S.hoverF).map(o => [o.x, o.y, o.z, [o.tile]]);
  S.gl.setGhost(sq.length && sq.length < 20000 ? S.gl.build(sq) : null);
  S.needDraw = true;
}

// Ver arrastando: lista os tiles do retangulo; remove um tipo (ou tudo) na area num desfazer so
async function inspectArea(a, b) {
  const [x0, y0, x1, y1] = rectOf(a, b), z = S.z;
  let r;
  try { r = await api(`/api/area_tiles?x0=${x0}&y0=${y0}&x1=${x1}&y1=${y1}&z=${z}`); } catch (e) { return say(e.message, true); }
  const sqs = () => { const o = []; for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) o.push([x, y]); return o; };
  const run = async (names, label) => {
    await flush();
    await serial(async () => {
      try { await applyChanged(await api("/api/edit", { ops: sqs().map(([x, y]) => ({ x, y, z, remove: names })), label })); }
      catch (e) { say(e.message, true); }
    });
    closeModal(); inspectArea(a, b);
  };
  const KIND = { floor: "piso", overlay: "camada", wall: "parede", object: "objeto" };
  const kinds = [...new Set(r.tiles.map(t => t.kind))];
  const filt = h("span", { class: "row" });
  const list = h("div", { class: "inspect" });
  let only = null;
  const fill = () => {
    list.innerHTML = "";
    for (const t of r.tiles) {
      if (only && t.kind !== only) continue;
      const c = h("canvas"); S.atlas.thumb(c, [t.name], 40, 40);
      list.append(h("div", {}, c, h("code", {}, `${t.name}  ${t.label ? "(" + t.label + ")" : ""}  [${KIND[t.kind] || t.kind}]  x${t.count}`),
        h("button", { onclick: () => { selectItem(S.itemByTile.get(t.name)); closeModal(); } }, "usar"),
        h("button", { onclick: () => run([t.name], `remover ${t.label || t.name} da area`) }, "remover na area")));
    }
    if (!list.children.length) list.append(h("p", { class: "note" }, "nenhum tile aqui"));
  };
  const btn = (k, l) => h("button", { class: only === k ? "on" : "", onclick: () => { only = k; filt.querySelectorAll("button").forEach(x => x.classList.toggle("on", x.textContent === l)); fill(); } }, l);
  filt.append(btn(null, "todos"), ...kinds.map(k => btn(k, KIND[k] || k)));
  fill();
  const visible = () => r.tiles.filter(t => !only || t.kind === only).map(t => t.name);
  modal(`Area ${x1 - x0 + 1} x ${y1 - y0 + 1} (${x0},${y0} a ${x1},${y1}), andar ${z}`,
    [h("p", { class: "note" }, `${r.tiles.length} tipo(s) de tile em ${r.squares} quadrado(s). Cada remocao e um passo do Ctrl+Z.`), filt, list],
    [h("button", { onclick: () => { const v = visible(); if (v.length) run(v, only ? `remover ${KIND[only] || only} da area` : "remover tudo da area"); } }, "remover todos (filtro atual)"),
     h("button", { onclick: closeModal }, "Fechar")]);
}

async function inspectAt(x, y) {
  try {
    const r = await api(`/api/square?x=${x}&y=${y}&z=${S.z}`);
    const list = h("div", { class: "inspect" });
    for (const t of r.tiles) {
      const c = h("canvas"); S.atlas.thumb(c, [t.name], 40, 40);
      list.append(h("div", {}, c, h("code", {}, `${t.name}  ${t.label ? "(" + t.label + ")" : ""}  [${t.kind}]`),
        h("button", { onclick: () => { selectItem(S.itemByTile.get(t.name)); closeModal(); } }, "usar"),
        h("button", { onclick: async () => { await applyChanged(await api("/api/edit", { ops: [{ x, y, z: S.z, set: r.tiles.map(q => q.name).filter(n => n !== t.name) }], label: "remover tile" })); closeModal(); inspectAt(x, y); } }, "remover")));
    }
    modal(`Quadrado ${x}, ${y}, andar ${S.z}`, [r.rooms.length ? h("p", { class: "note" }, "Sala: " + r.rooms.join(", ")) : h("p", { class: "note" }, "Fora de sala (externo)"), list],
      [h("button", { onclick: closeModal }, "Fechar")]);
  } catch (e) { say(e.message, true); }
}

// ---------------------------------------------------------------- entrada
const cv = $("#gl");
function mouseSq(e) {
  const r = cv.getBoundingClientRect();
  const [fx, fy] = S.gl.toWorld(e.clientX - r.left, e.clientY - r.top, S.z);
  return [[Math.floor(fx), Math.floor(fy)], [fx, fy]];
}

cv.addEventListener("contextmenu", e => e.preventDefault());
cv.addEventListener("mousedown", async e => {
  if (!S.gl || !S.state.project) return;
  if (e.button === 1 || e.button === 2 || S.space) {
    S.pan = { x: e.clientX, y: e.clientY, cx: S.gl.cam.x, cy: S.gl.cam.y }; return;
  }
  const [sq, f] = mouseSq(e);
  S.drag = { a: sq, last: sq, shift: e.shiftKey }; S.hover = sq; S.hoverF = f;
  S.stroke = Math.random().toString(36).slice(2);
  const t = S.tool, X = (window.PZMS_TOOLS || {})[t];
  if (X) { if (X.down) X.down(sq, e); S.needDraw = true; return; }
  if (t === "brush") queueOps(brushOps(...sq), (S.paintMode === "erase" ? "apagar pincel " : "pincel ") + (S.item ? S.item.label : ""));
  else if (t === "erase" && !e.shiftKey) queueOps([{ x: sq[0], y: sq[1], z: S.z, erase: S.eraseMode, floor: S.eraseFloor }], "apagar");
  else if (t === "pick") {
    S.drag = null;
    const r = await api(`/api/square?x=${sq[0]}&y=${sq[1]}&z=${S.z}`);
    const top = r.tiles[r.tiles.length - 1]; if (top) { selectItem(S.itemByTile.get(top.name)); say("copiou " + top.name); }
  } else if (t === "inspect") { /* clique: no up; arrasto: area */ }
  else if (t === "wall" && S.wallMode !== "wall") { S.drag = null; queueOps(wallClickOps(...f), S.wallMode === "door" ? "porta" : "janela"); }
  else if (t === "room" && e.altKey) { S.drag = null; applyChanged(await api("/api/rooms/remove", { x: sq[0], y: sq[1], z: S.z })); }
  else if (t === "place" && window.PZMS_place) { S.drag = null; window.PZMS_place(sq[0], sq[1], S.z); }
  S.needDraw = true;
});
window.addEventListener("mousemove", e => {
  if (!S.gl) return;
  if (S.pan) {
    const z = S.gl.cam.zoom;
    S.gl.cam.x = S.pan.cx - (e.clientX - S.pan.x) / z; S.gl.cam.y = S.pan.cy - (e.clientY - S.pan.y) / z;
    S.needDraw = true; return;
  }
  if (e.target !== cv && !S.drag) return;
  const [sq, f] = mouseSq(e);
  S.hoverF = f;
  const moved = !S.hover || sq[0] !== S.hover[0] || sq[1] !== S.hover[1];
  S.hover = sq;
  $("#pos").textContent = `${sq[0]}, ${sq[1]}  andar ${S.z}  -  celula ${Math.floor(sq[0] / CS)},${Math.floor(sq[1] / CS)}`;
  if (S.drag && moved) {
    const t = S.tool, X = (window.PZMS_TOOLS || {})[t];
    if (X && X.move) X.move(sq, e);
    if (t === "brush") { for (const p of lineSq(S.drag.last, sq)) queueOps(brushOps(...p), "pincel"); }
    else if (t === "erase" && !S.drag.shift) { for (const p of lineSq(S.drag.last, sq)) queueOps([{ x: p[0], y: p[1], z: S.z, erase: S.eraseMode, floor: S.eraseFloor }], "apagar"); }
    S.drag.last = sq;
  }
  if (moved || S.tool === "wall") updateGhost();
  S.needDraw = true;
});
window.addEventListener("mouseup", async e => {
  if (S.pan) { S.pan = null; ensureCells(); return; }
  const d = S.drag; S.drag = null;
  if (!d || !S.hover) return;
  const t = S.tool, b = S.hover, X = (window.PZMS_TOOLS || {})[t];
  if (X) { if (X.up) await X.up(d.a, b, e); S.stroke = null; S.needDraw = true; return; }
  if (t === "area") queueOps(areaOps(d.a, b), (S.paintMode === "erase" ? "apagar area " : "area ") + (S.item ? S.item.label : ""));
  else if (t === "erase" && d.shift) queueOps(areaOps(d.a, b), "apagar area");
  else if (t === "wall" && S.wallMode === "wall") queueOps(wallOps(d.a, b), "paredes");
  else if (t === "room") dlgRoom(d.a, b);
  else if (t === "inspect") { if (d.a[0] === b[0] && d.a[1] === b[1]) inspectAt(...b); else inspectArea(d.a, b); }
  await flush(); S.stroke = null; updateGhost();
});
function lineSq(a, b) {
  const out = [], n = Math.max(Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]), 1);
  for (let i = 1; i <= n; i++) out.push([Math.round(a[0] + (b[0] - a[0]) * i / n), Math.round(a[1] + (b[1] - a[1]) * i / n)]);
  return out;
}
cv.addEventListener("wheel", e => {
  e.preventDefault();
  const g = S.gl; if (!g) return;
  const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
  const wx = mx / g.cam.zoom + g.cam.x, wy = my / g.cam.zoom + g.cam.y;
  const f = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0018));
  g.cam.zoom = Math.min(6, Math.max(0.2, g.cam.zoom * f));
  g.cam.x = wx - mx / g.cam.zoom; g.cam.y = wy - my / g.cam.zoom;
  S.needDraw = true; clearTimeout(S.wheelT); S.wheelT = setTimeout(ensureCells, 120);
}, { passive: false });

function setZ(z) {
  z = Math.max(-8, Math.min(31, z));
  const d = z - S.z; S.z = z; $("#zlabel").textContent = "Andar " + z;
  if (S.gl) { S.gl.zmax = z; S.gl.cam.y -= d * ISO.FL; }
  fetchRooms(true); updateGhost(); S.needDraw = true;
}

window.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") { if (e.key === "Enter" && !$("#modal").classList.contains("hidden")) { const p = $("#modalbox .primary"); if (p) p.click(); } return; }
  const mod = e.metaKey || e.ctrlKey, k = e.key.toLowerCase();
  if (mod && k === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
  if (mod && k === "y") { e.preventDefault(); redo(); return; }
  if (mod && k === "s") { e.preventDefault(); save(); return; }
  if (mod) return;
  if (e.key === " ") { S.space = true; e.preventDefault(); return; }
  if (e.key === "Escape") { closeModal(); S.drag = null; updateGhost(); return; }
  if (e.key === "PageUp") return setZ(S.z + 1);
  if (e.key === "PageDown") return setZ(S.z - 1);
  if (e.key === "[") { S.brush = Math.max(1, S.brush - 2); setTool(S.tool); return; }
  if (e.key === "]") { S.brush = Math.min(15, S.brush + 2); setTool(S.tool); return; }
  const tk = { v: "inspect", b: "brush", g: "area", w: "wall", e: "erase", i: "pick", m: "room", p: "place" }[k]
    || Object.keys(window.PZMS_TOOLS || {}).find(n => window.PZMS_TOOLS[n].key === k);
  if (tk) return setTool(tk);
  if (k === "r") return rotate();
  if (k === "x" && (S.tool === "brush" || S.tool === "area")) { S.paintMode = S.paintMode === "erase" ? "add" : "erase"; return setTool(S.tool); }
  const step = 64 / S.gl.cam.zoom;
  if (e.key === "ArrowLeft") S.gl.cam.x -= step; else if (e.key === "ArrowRight") S.gl.cam.x += step;
  else if (e.key === "ArrowUp") S.gl.cam.y -= step; else if (e.key === "ArrowDown") S.gl.cam.y += step; else return;
  S.needDraw = true; ensureCells();
});
window.addEventListener("keyup", e => { if (e.key === " ") S.space = false; });

// ---------------------------------------------------------------- desenho
const ov = $("#ov");
function resizeOv() {
  const r = ov.getBoundingClientRect(), d = window.devicePixelRatio || 1;
  ov.width = Math.round(r.width * d); ov.height = Math.round(r.height * d);
}
window.addEventListener("resize", () => { if (S.gl) { S.gl.resize(); resizeOv(); S.needDraw = true; ensureCells(); } });

function diamond(ctx, x, y, w = 1, hgt = 1) {
  const g = S.gl, z = S.z;
  const P = [[x, y], [x + w, y], [x + w, y + hgt], [x, y + hgt]].map(([a, b]) => g.toScreen(a - 0.5, b - 0.5, z));
  ctx.beginPath(); ctx.moveTo(...P[0]); for (const p of P.slice(1)) ctx.lineTo(...p); ctx.closePath();
}

function drawOverlay() {
  const ctx = ov.getContext("2d"), d = window.devicePixelRatio || 1;
  ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, ov.width, ov.height);
  const p = S.state.project; if (!p || !S.gl) return;
  // celulas
  ctx.lineWidth = 1; ctx.strokeStyle = "rgba(217,164,65,.35)";
  for (const [cx, cy] of p.cells) { diamond(ctx, cx * CS, cy * CS, CS, CS); ctx.stroke(); }
  // salas do andar
  ctx.strokeStyle = "rgba(127,176,105,.85)"; ctx.fillStyle = "rgba(127,176,105,.10)"; ctx.font = "11px system-ui";
  const showRooms = S.tool === "room" || S.tool === "inspect" || S.showRooms;
  if (showRooms) for (const r of S.rooms) {
    if (r.z !== S.z) continue;
    for (const [x, y, w, hh] of r.rects) { diamond(ctx, x, y, w, hh); ctx.fill(); ctx.stroke(); }
    const [x, y, w, hh] = r.rects[0]; const [sx, sy] = S.gl.toScreen(x + w / 2 - .5, y + hh / 2 - .5, S.z);
    ctx.fillStyle = "#cfe6c0"; ctx.textAlign = "center"; ctx.fillText(r.name, sx, sy); ctx.fillStyle = "rgba(127,176,105,.10)";
  }
  // spawn
  if (p.meta.spawn) { const [sx, sy] = S.gl.toScreen(p.meta.spawn[0], p.meta.spawn[1], p.meta.spawn[2] || 0); ctx.fillStyle = "#e05a47"; ctx.beginPath(); ctx.arc(sx, sy, 5, 0, 7); ctx.fill(); }
  for (const fn of window.PZMS_OVERLAYS || []) { try { fn(ctx, { diamond, toScreen: (a, b, c) => S.gl.toScreen(a, b, c), z: S.z, CS, project: p }); } catch (e) { console.error(e); } }
  // cursor e retangulos
  if (S.hover) {
    let [x, y] = S.hover, w = 1, hh = 1;
    if (S.drag && (["area", "room", "wall", "inspect"].includes(S.tool) || (window.PZMS_TOOLS || {})[S.tool]?.rect) || (S.drag && S.tool === "erase" && S.drag.shift)) {
      const [x0, y0, x1, y1] = rectOf(S.drag.a, S.hover); x = x0; y = y0; w = x1 - x0 + 1; hh = y1 - y0 + 1;
      ctx.fillStyle = "rgba(217,164,65,.12)"; diamond(ctx, x, y, w, hh); ctx.fill();
      const [sx, sy] = S.gl.toScreen(x + w, y + hh, S.z); ctx.fillStyle = "#f3d79a"; ctx.textAlign = "left"; ctx.fillText(`${w} x ${hh}`, sx + 8, sy);
    } else if (S.tool === "brush" && S.item && (S.item.kind === "floor" || S.item.kind === "overlay") && S.brush > 1) {
      const r = S.brush >> 1; x -= r; y -= r; w = hh = S.brush;
    }
    ctx.strokeStyle = S.tool === "erase" ? "#e05a47" : "#f3d79a"; ctx.lineWidth = 1.5;
    diamond(ctx, x, y, w, hh); ctx.stroke();
    if (S.tool === "wall" && S.wallMode !== "wall" && S.hoverF) {
      const [a, b, side] = edgeAt(...S.hoverF);
      const P = side === "W" ? [[a, b], [a, b + 1]] : [[a, b], [a + 1, b]];
      const q = P.map(([u, v]) => S.gl.toScreen(u - .5, v - .5, S.z));
      ctx.strokeStyle = "#ffcf5a"; ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(...q[0]); ctx.lineTo(...q[1]); ctx.stroke();
    }
  }
}

function frame() {
  if (S.needDraw && S.gl) {
    S.needDraw = false;
    S.gl.draw(); drawOverlay();
    clearTimeout(S.ensT); S.ensT = setTimeout(ensureCells, 60);
  }
  requestAnimationFrame(frame);
}

function about() {
  const st = S.state || {};
  modal(st.name || "J' PZ MAP STUDIO", [
    h("p", {}, `Versao ${st.app || ""}  -  editor de mapas para Project Zomboid B42 (${(st.supported || []).join(", ")}).`),
    h("p", { class: "note" }, `Jogo detectado: ${(st.game && st.game.version) || "?"}  -  ${(st.game && st.game.media) || ""}`),
    h("p", { class: "note" }, "Sprites e predios sao lidos da sua propria instalacao e guardados em cache local; nada do jogo e redistribuido."),
    h("p", {}, h("b", {}, "J' PZ MAP STUDIO — criado por Jemerson Barros")),
  ], [h("button", { onclick: closeModal }, "Fechar")]);
}

// ---------------------------------------------------------------- botoes e abas
document.addEventListener("click", e => {
  const b = e.target.closest("[data-act]"); if (!b) return;
  ({ new: dlgNew, open: dlgOpen, save, undo, redo, zup: () => setZ(S.z + 1), zdown: () => setZ(S.z - 1),
     gen: () => showTab("gen"), about })[b.dataset.act]?.();
});
$$("#tools button").forEach(b => b.addEventListener("click", () => setTool(b.dataset.tool)));
function showTab(t) {
  S.tab = t;
  $$(".tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  $$(".tab").forEach(s => s.classList.toggle("on", s.id === "tab-" + t));
  (window.PZMS_TABS || {})[t]?.($("#tab-" + t));
}
$$(".tabs button").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));
$("#search").addEventListener("input", e => { S.search = e.target.value; clearTimeout(S.searchT); S.searchT = setTimeout(() => { renderSubs(); renderItems(); }, 160); });

setInterval(async () => {          // salvamento automatico
  if (S.state && S.state.project && S.state.project.dirty && !S.drag) {
    try { S.state = await api("/api/project/save", {}); afterState(); say("salvo automaticamente"); } catch (e) { /* */ }
  }
}, 120000);

window.PZMS = { S, api, rectOf, fetchRooms, CS, h, $, $$, say, modal, closeModal, applyChanged, setTool, selectItem, showTab, boot, afterState, resetView, centerOn, flush };
setTool("brush");
boot();


// ---- campos de numero: setinhas visiveis (sobe/desce) e teclas seta cima/baixo aplicam na hora
(() => {
  function step(i, d) {
    if (i.disabled) return;
    d > 0 ? i.stepUp() : i.stepDown();
    i.dispatchEvent(new Event("input", { bubbles: true }));
    i.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function wrap(i) {
    if (i.dataset.nb || !i.parentNode) return;
    i.dataset.nb = "1";
    const box = document.createElement("span"); box.className = "numbox";
    const up = document.createElement("button"), dn = document.createElement("button");
    up.type = dn.type = "button"; up.tabIndex = dn.tabIndex = -1;
    up.className = "nb-up"; dn.className = "nb-dn"; up.textContent = "\u25B2"; dn.textContent = "\u25BC";
    up.title = "aumentar (seta para cima)"; dn.title = "diminuir (seta para baixo)";
    up.addEventListener("mousedown", e => { e.preventDefault(); i.focus(); step(i, 1); });
    dn.addEventListener("mousedown", e => { e.preventDefault(); i.focus(); step(i, -1); });
    i.replaceWith(box);
    const arrows = document.createElement("span"); arrows.className = "nb-arrows"; arrows.append(up, dn);
    box.append(i, arrows);
  }
  document.addEventListener("keydown", e => {
    const i = e.target;
    if (!(i instanceof HTMLInputElement) || i.type !== "number" || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault(); step(i, e.key === "ArrowUp" ? (e.shiftKey ? 10 : 1) : (e.shiftKey ? -10 : -1));
  }, true);
  const scan = root => root.querySelectorAll && root.querySelectorAll('input[type="number"]').forEach(wrap);
  new MutationObserver(ms => { for (const m of ms) m.addedNodes.forEach(n => { if (n.nodeType === 1) { if (n.matches('input[type="number"]')) wrap(n); scan(n); } }); })
    .observe(document.body, { childList: true, subtree: true });
  scan(document);
})();
