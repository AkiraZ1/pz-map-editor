"""Ferramenta Zumbis: densidade de zumbis por chunk (8x8 quadrados).

O dado e Cell.density: 1024 bytes por celula, um por chunk, indice ci = lx*32 + ly (lx, ly = chunk local).
Vai no fim do lotheader, que o projeto ja salva e o export ja copia.

Escala (medida nos 4065 lotheaders vanilla do B42, Muldraugh KY): valores 0..10.
  0: 98,6% dos chunks (mato, estrada vazia)   1-2: rural/suburbio   3-4: cidade
  5-7: centro denso                           8-10: pontos quentes (raros)
O B42 nao precisa de ZombieSpawnMap nem de zpop no mapa: o zpop_X_Y.bin e do save (o jogo gera a
populacao a partir da densidade do lotheader), e o chunkdata_X_Y.bin vanilla e so '00 01' + 1024 zeros,
sem densidade. Por isso export() so confere e resume; nada extra e gravado.
"""
import base64
import os

from . import formats as F

CS, CH, NCH = F.CS, F.CH, F.NCH            # 256 quadrados, chunk 8, 32 chunks por lado
LEVELS = {"nenhuma": 0, "baixa": 1, "media": 3, "alta": 6}
VANILLA_MAX = 10
MAX_VALUE = 255


def level_value(v):
    if isinstance(v, str) and v in LEVELS:
        return LEVELS[v]
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"nivel invalido: {v!r}")
    if not 0 <= n <= MAX_VALUE:
        raise ValueError(f"densidade fora de 0..{MAX_VALUE}: {n}")
    return n


def _header_density(project, ck):
    """densidade da celula sem carregar o lotpack (le so o lotheader, com cache por mtime)."""
    c = project.cells.get(ck)
    if c is not None:
        return bytes(c.density)
    if ck not in project.cellset:
        return None
    hp = os.path.join(project.cdir, f"{ck[0]}_{ck[1]}.lotheader")
    try:
        mt = os.path.getmtime(hp)
    except OSError:
        return bytes(1024)
    cache = project.__dict__.setdefault("_zb_cache", {})
    hit = cache.get(ck)
    if hit and hit[0] == mt:
        return hit[1]
    with open(hp, "rb") as f:
        d = bytes(F.read_header(f.read()).density)
    cache[ck] = (mt, d)
    return d


def density(project, ck):
    with project.lock:
        return _header_density(project, ck)


def view(project, box=None):
    """{"cx,cy": base64(1024)} so das celulas com algum chunk > 0. box=(cx0, cy0, cx1, cy1) inclusivo."""
    out = {}
    with project.lock:
        for ck in sorted(project.cellset):
            if box and not (box[0] <= ck[0] <= box[2] and box[1] <= ck[1] <= box[3]):
                continue
            d = _header_density(project, ck)
            if d and any(d):
                out[f"{ck[0]},{ck[1]}"] = base64.b64encode(d).decode("ascii")
    return out


def paint(project, chunks, value, label=None, values=None):
    """chunks: iteravel de (wcx, wcy) em coordenadas de chunk do mundo, todos com `value`; values: [(wcx, wcy, v)]
    com valor proprio por chunk (pincel suave, somar/tirar). Aplica com undo (um comando).
    Chunks fora das celulas do projeto sao ignorados. Retorna o dict changed {(cx,cy): {-2}}."""
    value = level_value(value) if chunks else 0
    per = {}
    for wcx, wcy, v in [(c[0], c[1], value) for c in chunks or []] + [tuple(t) for t in values or []]:
        wcx, wcy, v = int(wcx), int(wcy), level_value(v)
        ck = (wcx // NCH, wcy // NCH)
        per.setdefault(ck, {})[(wcx - ck[0] * NCH) * NCH + (wcy - ck[1] * NCH)] = v
    diff, changed = {}, {}
    with project.lock:
        for ck, cis in per.items():
            if ck not in project.cellset:
                continue
            old = _header_density(project, ck) or bytes(1024)
            new = bytearray(old)
            for ci, v in cis.items():
                new[ci] = v
            if bytes(new) != old:
                diff[ck] = (old, bytes(new))
                changed[ck] = {-2}
        if diff:
            name = {v: k for k, v in LEVELS.items()}.get(value, str(value))
            project.push_cmd(label or f"zumbis {name}", density=diff)
    return changed


def rect_chunks(x0, y0, x1, y1):
    """chunks que um retangulo de quadrados (inclusivo) toca."""
    a0, b0, a1, b1 = min(x0, x1) // CH, min(y0, y1) // CH, max(x0, x1) // CH, max(y0, y1) // CH
    return [(a, b) for a in range(a0, a1 + 1) for b in range(b0, b1 + 1)]


def stats(project):
    hist, cells = [0] * 256, 0
    with project.lock:
        for ck in project.cellset:
            d = _header_density(project, ck) or bytes(1024)
            if any(d):
                cells += 1
            for v in d:
                hist[v] += 1
    return {"hist": {i: n for i, n in enumerate(hist) if n}, "cells_with_zombies": cells,
            "above_vanilla": sum(hist[VANILLA_MAX + 1:])}


def export(project, map_dir):
    """Chamado pelo export.py. No B42 a densidade ja vai no lotheader copiado; nao ha ZombieSpawnMap/zpop
    de mapa a gravar. Confere os lotheaders exportados e devolve um resumo."""
    st = stats(project)
    try:
        from . import progress as PG
        tot = sum(st["hist"].values()) or 1
        busy = tot - st["hist"].get(0, 0)
        msg = f"zumbis: {busy} de {tot} chunks com densidade ({100 * busy / tot:.1f}%)"
        if st["above_vanilla"]:
            msg += f"; {st['above_vanilla']} chunks acima de {VANILLA_MAX} (maximo vanilla)"
        PG.log(msg)
    except Exception:                               # noqa: BLE001 - resumo nunca impede o export
        pass
    bad = []
    for ck in sorted(project.cellset):
        hp = os.path.join(map_dir, f"{ck[0]}_{ck[1]}.lotheader")
        if os.path.exists(hp):
            with open(hp, "rb") as f:
                if bytes(F.read_header(f.read()).density) != (density(project, ck) or bytes(1024)):
                    bad.append(ck)
    st["mismatch"] = bad
    return st


# ----- estimativa relativa (ferramenta Zumbis > Estimar)
# A conta densidade -> zumbis fica na lib nativa do jogo (libPZPopMan), que nao da para ler.
# Aqui o indice e relativo: soma das densidades x multiplicadores do sandbox, comparado com o vanilla.
# Multiplicadores do B42 (media/lua/shared/defines.lua); nomes na ordem do sandbox (Zombies = 1..6).
PRESETS = [("Insano", 2.5, 4.0, 4.0), ("Muito alta", 1.6, 2.0, 2.0), ("Alta", 1.2, 1.5, 1.5),
           ("Normal", 0.65, 1.0, 1.0), ("Baixa", 0.15, 0.5, 0.5), ("Nenhum", 0.0, 0.0, 0.0)]
_ref = {}


def _defines(media):
    """le os multiplicadores do defines.lua do jogo instalado; cai nos valores acima se nao achar."""
    import re
    try:
        s = open(os.path.join(media, "lua", "shared", "defines.lua"), encoding="utf-8", errors="ignore").read()
    except (OSError, TypeError):
        return PRESETS
    keys = ["Insane", "VeryHigh", "High", "Normal", "Low", "None"]
    out = []
    for (nm, p0, s0, k0), key in zip(PRESETS, keys):
        def g(tab, dflt):
            m = re.search(rf'{tab}\.{key}\s*=\s*"([\d.]+)"', s)
            return float(m.group(1)) if m else dflt
        out.append((nm, g("ZombiePopulationMultiplier", p0), g("ZombiePopulationStartMultiplier", s0),
                    g("ZombiePopulationPeakMultiplier", k0)))
    return out


def vanilla_ref(media):
    """soma media de densidade por celula vanilla com zumbis (Muldraugh, KY), com cache em disco."""
    import json
    from . import gamedir
    if media in _ref:
        return _ref[media]
    cp = os.path.join(gamedir.cache_dir(), "zombie_ref.json")
    try:
        j = json.load(open(cp))
        if j.get("media") == media:
            _ref[media] = j
            return j
    except (OSError, ValueError):
        pass
    d = os.path.join(media or "", "maps", "Muldraugh, KY")
    sums = []
    try:
        names = [f for f in os.listdir(d) if f.endswith(".lotheader")]
    except OSError:
        names = []
    for f in names:
        try:
            with open(os.path.join(d, f), "rb") as fh:
                s = sum(F.read_header(fh.read()).density)
        except Exception:                                   # celula estranha nao derruba a estimativa
            continue
        if s:
            sums.append(s)
    sums.sort()
    j = {"media": media, "cells": len(sums), "avg": (sum(sums) / len(sums)) if sums else 0,
         "p90": sums[int(len(sums) * 0.9)] if sums else 0, "max": sums[-1] if sums else 0}
    try:
        json.dump(j, open(cp, "w"))
    except OSError:
        pass
    _ref[media] = j
    return j


def servers():
    """configuracoes de servidor salvas (~/Zomboid/Server/*_SandboxVars.lua): multiplicadores de populacao."""
    import re
    from . import gamedir
    d = os.path.join(gamedir.zomboid_user_dir(), "Server")
    out = []
    try:
        fs = sorted(f for f in os.listdir(d) if f.endswith("_SandboxVars.lua"))
    except OSError:
        return out
    for f in fs:
        try:
            s = open(os.path.join(d, f), encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        def g(k, dflt):
            m = re.search(rf"\b{k}\s*=\s*([\d.]+)", s)
            return float(m.group(1)) if m else dflt
        out.append({"name": f[:-len("_SandboxVars.lua")], "pop": g("PopulationMultiplier", 0.65),
                    "start": g("PopulationStartMultiplier", 1.0), "peak": g("PopulationPeakMultiplier", 1.5),
                    "peakday": g("PopulationPeakDay", 28), "respawn_h": g("RespawnHours", 0),
                    "respawn_m": g("RespawnMultiplier", 0)})
    return out


def sim(project, media):
    """dados para a estimativa: soma das densidades do projeto, referencia vanilla, presets e servidores."""
    s = st = n = 0
    per = []
    with project.lock:
        for ck in sorted(project.cellset):
            d = _header_density(project, ck) or bytes(1024)
            cs = sum(d)
            s += cs; n += sum(1 for v in d if v)
            if cs:
                per.append([ck[0], ck[1], cs])
    return {"sum": s, "chunks": n, "cells": len(project.cellset), "per_cell": per,
            "ref": vanilla_ref(media), "presets": [list(p) for p in _defines(media)], "servers": servers()}
