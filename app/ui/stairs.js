// Ferramenta Escada (S): escada vanilla de 3 degraus que ja abre o caminho.
//  - subir: o quadrado sob o mouse e o degrau de baixo; o piso do andar de cima some em cima dos degraus
//  - descer: o quadrado sob o mouse e o patamar deste andar; a escada vai no andar de baixo e abre o piso daqui
//  - R gira (W / N); a previa ja mostra o resultado (sem os moveis e a parede que fechava a passagem)
"use strict";
(() => {
  const { S, api, h, say, applyChanged } = window.PZMS;
  const keep = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* sem storage */ } };
  const load = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };
  const E = { mode: load("pzms.stairs.mode", "up"), dir: load("pzms.stairs.dir", "W"), set: load("pzms.stairs.set", ""), sets: null, seq: 0, last: null };

  async function sets() {
    if (!E.sets) {
      try { E.sets = (await api("/api/stairs/sets")).sets; } catch (e) { E.sets = []; say(e.message, true); }
      if (!E.sets.some(s => s.id === E.set) && E.sets.length) E.set = E.sets[0].id;
      if (S.tool === "stairs") window.PZMS.setTool("stairs");
    }
    return E.sets;
  }
  const body = (sq, extra) => ({ x: sq[0], y: sq[1], z: S.z, dir: E.dir, mode: E.mode, set: E.set, ...extra });

  async function ghost(hv) {
    const n = ++E.seq;
    let r;
    try { r = await api("/api/stairs", body(hv, { preview: true })); } catch (e) { r = null; }
    if (n !== E.seq || S.tool !== "stairs") return;                 // so a ultima previa vale
    if (!r || !S.hover) { S.gl.setGhost(null); S.gl.setHide(null); S.needDraw = true; return; }
    S.gl.setHide(r.sq.map(([x, y, z]) => [x, y, z]));
    S.gl.setGhost(S.gl.build(r.sq));
    E.last = r.sq; S.needDraw = true;
  }

  function re() { window.PZMS.setTool("stairs"); }

  window.PZMS_TOOLS = window.PZMS_TOOLS || {};
  window.PZMS_TOOLS.stairs = {
    key: "s",
    opts() {
      if (!E.sets) sets();
      const mode = [["up", "subir", "o quadrado e o degrau de baixo; abre o piso do andar de cima"],
                    ["down", "descer", "o quadrado e o patamar deste andar; a escada vai no andar de baixo"]]
        .map(([k, l, t]) => h("button", { class: E.mode === k ? "on" : "", title: t, onclick: () => { E.mode = k; keep("pzms.stairs.mode", k); re(); } }, l));
      const dir = [["W", "sobe para noroeste (W)"], ["N", "sobe para nordeste (N)"]]
        .map(([k, t]) => h("button", { class: E.dir === k ? "on" : "", title: t, onclick: () => { E.dir = k; keep("pzms.stairs.dir", k); re(); } }, k));
      const sel = h("select", { onchange: () => { E.set = sel.value; keep("pzms.stairs.set", E.set); re(); } },
        ...(E.sets || []).map(s => h("option", { value: s.id, selected: s.id === E.set ? "" : null }, s.label + (s.W && s.N ? "" : s.W ? " (so W)" : " (so N)"))));
      if (E.sets) sel.value = E.set;
      return [h("label", {}, "Escada"), ...mode, h("label", {}, "Direcao"), ...dir, sel,
        h("label", { style: "color:var(--dim)" }, "R gira  -  clique poe a escada e abre o caminho (Ctrl+Z desfaz)")];
    },
    ghost(hv) { ghost(hv); },
    rotate() { E.dir = E.dir === "W" ? "N" : "W"; keep("pzms.stairs.dir", E.dir); re(); },
    down(sq) {
      S.drag = null;
      if (!E.sets || !E.sets.length) return;
      window.PZMS.serial(async () => {
        try {
          await applyChanged(await api("/api/stairs", body(sq)));
          say(E.mode === "down" ? "escada para o andar de baixo" : "escada para o andar de cima");
        } catch (e) { say(e.message, true); }
        window.PZMS.updateGhost();
      });
    },
  };
})();
