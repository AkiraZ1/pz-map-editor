// Painel de progresso MACRO / MICRO / LOG (portado do painel do Sao Paulo)
"use strict";
(() => {
  const { api, $ } = window.PZMS;
  const fmt = s => { s = Math.max(0, Math.floor(s || 0)); return s >= 3600 ? `${Math.floor(s / 3600)}h${String(Math.floor(s % 3600 / 60)).padStart(2, "0")}m` : `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`; };
  const esc = t => String(t ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
  let timer = null, op = null, hideT = null;
  const LIVE = { working: ["#7fb069", "●"], stalled: ["#e0b84a", "●"], idle: ["#8a8780", "○"] };

  function render(p) {
    const el = $("#prog");
    if (!p) { el.classList.add("hidden"); return; }
    el.classList.remove("hidden");
    $("#progtitle").textContent = p.title || p.op;
    const [c, dot] = LIVE[p.live.state] || LIVE.idle;
    $("#proglive").innerHTML = `<span style="color:${c}">${dot} ${esc(p.live.text)}</span>`;
    const m = p.macro;
    $("#progtrail").innerHTML = m.trail.map(t => `<span class="${t.state}">${t.state === "done" ? "✔" : t.state === "cur" ? "▶" : "·"} ${esc(t.step)}</span>`).join("");
    $("#progbar").style.width = (m.frac * 100).toFixed(1) + "%";
    $("#progbar").classList.toggle("err", !!p.error);
    const parts = [`${(m.frac * 100).toFixed(1)}%`];
    if (m.total) parts.push(`${m.done}/${m.total}`);
    parts.push(`decorrido ${fmt(m.elapsed)}`);
    if (!p.done) parts.push(m.eta != null ? `falta ~${fmt(m.eta)}` : "falta —");
    if (!p.done && m.since_mark != null && m.frac < 1) parts.push(`ultimo passo ha ${fmt(m.since_mark)}`);
    $("#progtxt").innerHTML = esc(parts.join("  ·  ")) + (m.msg ? `<br>${esc(m.msg)}` : "") + (p.error ? `<br><span style="color:var(--bad)">${esc(p.error)}</span>` : "");
    const mic = p.micro.map(w => `<div><b>${esc(w.chave)}</b> ${esc(w.msg)}${w.frac != null ? ` <i>${Math.round(w.frac * 100)}%</i>` : ""}` +
      `<span>${w.cpu != null ? `cpu ${w.cpu.toFixed(0)}% · ${w.mb} MB · ` : ""}ha ${fmt(w.age)}</span></div>`);
    if (p.last_file) mic.push(`<div class="lf">ultimo arquivo: ${esc(p.last_file.path.split(/[\\/]/).pop())} ha ${fmt(p.last_file.age)}</div>`);
    $("#progmicro").innerHTML = mic.join("") || `<div class="note">${p.done ? "nenhum worker ativo" : "aguardando workers..."}</div>`;
    const lg = $("#proglog"), atEnd = lg.scrollTop + lg.clientHeight >= lg.scrollHeight - 4;
    lg.textContent = p.log.join("\n"); if (atEnd) lg.scrollTop = lg.scrollHeight;
    $("#jobinfo").textContent = p.done ? "" : `${p.title || p.op}: ${(m.frac * 100).toFixed(0)}%`;
    busy(!p.done, p.title || p.op);
  }
  // janela de carregamento: enquanto ocupado cobre o editor e a barra inferior mostra o credito
  function busy(on, title) {
    const min = $("#prog").classList.contains("min");
    $("#busy").classList.toggle("hidden", !on || min);
    $("#prog").classList.toggle("center", on && !min);
    $("#busytitle").textContent = title || "";
    document.body.classList.toggle("busy", on);
  }

  async function poll() {
    try {
      const r = await api("/api/progress" + (op ? `?op=${encodeURIComponent(op)}` : ""));
      render(r.progress);
      if (r.progress && r.progress.done) {
        stop();
        if (!r.progress.error) hideT = setTimeout(() => $("#prog").classList.add("hidden"), 6000);
      }
    } catch (e) { /* servidor ocupado */ }
  }
  function stop() { clearInterval(timer); timer = null; }

  window.PZMS.progress = {
    watch(name) { op = name; clearTimeout(hideT); stop(); poll(); timer = setInterval(poll, 1000); },
    show() { clearTimeout(hideT); poll(); },
  };
  $("#progmin").addEventListener("click", () => {
    $("#prog").classList.toggle("min");
    const on = document.body.classList.contains("busy");
    busy(on, $("#busytitle").textContent);
  });
  // retoma painel se uma tarefa ja estiver rodando quando a UI abre
  api("/api/state").then(s => { for (const [k, j] of Object.entries(s.jobs || {})) if (!j.done) window.PZMS.progress.watch(k); }).catch(() => {});
})();
