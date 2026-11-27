"""Ferramenta Escada: poe os 3 degraus vanilla e abre caminho para subir/descer.
Medido no vanilla (Muldraugh): degrau de baixo (B) em x, meio (M) em x-1, topo (T) em x-2 para escada W
(em y para N); o patamar fica no 4o quadrado, no andar de cima. Em cima dos 3 degraus nao ha piso.
- subir: o quadrado clicado e o degrau B no andar atual; abre o piso do andar de cima.
- descer: o quadrado clicado e o patamar no andar atual; a escada vai no andar de baixo e abre o piso deste andar.
Nos degraus fica o piso e as paredes do lado; sai mobilia e a parede que fecha a passagem (porta fica).
Em cima dos degraus sai tudo, menos as paredes do lado."""
from .server import route, changed_view, ApiError
from .catalog import _side

_sets = {}
STEP = {"W": (-1, 0), "N": (0, -1)}


def stair_sets(tiles):
    """[{id, label, W: [B, M, T], N: [B, M, T]}] das folhas que tem stairsB/M/T (par W/N mais proximo)."""
    k = id(tiles)
    if k in _sets:
        return _sets[k]
    runs = {"W": {}, "N": {}}
    for n, p in tiles.items():
        for d in ("W", "N"):
            if f"stairsB{d}" in p:
                s, _, i = n.rpartition("_")
                if not i.isdigit():
                    continue
                i = int(i)
                m, t = f"{s}_{i + 1}", f"{s}_{i + 2}"
                if f"stairsM{d}" in tiles.get(m, {}) and f"stairsT{d}" in tiles.get(t, {}):
                    runs[d].setdefault(s, []).append((i, [n, m, t]))
    out = []
    for s, ws in runs["W"].items():
        ns = list(runs["N"].get(s, []))
        for i, w in sorted(ws):
            best = min(ns, key=lambda e: abs(e[0] - i), default=None)
            if best is not None:
                ns.remove(best)
            out.append({"id": w[0], "label": f"{s} {i}", "W": w, "N": best[1] if best else None})
    for s, ns in runs["N"].items():
        used = {e["N"][0] for e in out if e["N"]}
        for i, nn in sorted(ns):
            if nn[0] not in used:
                out.append({"id": nn[0], "label": f"{s} {i}", "W": None, "N": nn})
    out.sort(key=lambda e: (not e["label"].startswith("fixtures_stairs"), e["label"].split()[0], int(e["label"].split()[1])))
    _sets[k] = out
    return out


def plan(p, tiles, x, y, z, d, mode, run):
    """[(x, y, z, nomes)] do resultado. run = [B, M, T] na direcao d."""
    dx, dy = STEP[d]
    if mode == "down":
        zs, bx, by = z - 1, x - 3 * dx, y - 3 * dy
    else:
        zs, bx, by = z, x, y
    K = p.kinds

    def blocks(n):                          # parede/anexo que fecha a passagem (borda d do quadrado)
        pr = tiles.get(n, {})
        if K.kind(n) not in ("wall", "attach"):
            return False
        if any(k in pr for k in (f"door{d}", f"DoorWall{d}")):
            return False
        s = _side(pr)
        return s == d or s == "NW"

    def open_side(n):                       # canto NW: fica so a metade do lado
        pr = tiles.get(n, {})
        if _side(pr) == "NW":
            o = pr.get("CornerNorthWall" if d == "W" else "CornerWestWall")
            return [o] if o else []
        return []

    def strip(cur):
        out = []
        for n in cur:
            if blocks(n):
                out += open_side(n)
            else:
                out.append(n)
        return out

    res = []
    for i in range(-1, 3):
        sx, sy = bx + dx * i, by + dy * i
        cur = p.get(sx, sy, zs)
        if i < 0:                           # quadrado de entrada: so abre a parede entre ele e o degrau B
            new = strip(cur)
        else:
            keep = [n for n in cur if K.kind(n) in ("floor", "overlay") or K.kind(n) in ("wall", "attach")]
            new = strip(keep) + [run[i]]
        res.append((sx, sy, zs, new))
    for i in range(0, 3):
        sx, sy = bx + dx * i, by + dy * i
        cur = p.get(sx, sy, zs + 1)
        new = [n for n in strip(cur) if K.kind(n) in ("wall", "attach")]
        res.append((sx, sy, zs + 1, new))
    return res


@route("GET", "/api/stairs/sets")
def _stairs_sets(app, q, body):
    if not app.assets:
        raise ApiError("cache nao pronto")
    return {"sets": stair_sets(app.assets.tiles)}


@route("POST", "/api/stairs")
def _stairs(app, q, body):
    """{x, y, z, dir: W|N, mode: up|down, set: id, preview?}. preview devolve so os quadrados resultantes."""
    p = app.need_project()
    tiles = app.assets.tiles
    d = body.get("dir") if body.get("dir") in STEP else "W"
    mode = "down" if body.get("mode") == "down" else "up"
    st = next((s for s in stair_sets(tiles) if s["id"] == body.get("set")), None) or (stair_sets(tiles) or [None])[0]
    if not st:
        raise ApiError("nenhuma escada no cache")
    run = st[d] or st["N" if d == "W" else "W"]
    if not st[d]:
        d = "N" if d == "W" else "W"
    x, y, z = int(body["x"]), int(body["y"]), int(body.get("z", 0))
    if mode == "down" and z <= -8:
        raise ApiError("nao ha andar abaixo")
    res = plan(p, tiles, x, y, z, d, mode, run)
    if body.get("preview"):
        return {"sq": [[a, b, c, n] for a, b, c, n in res], "dir": d}
    ops = [{"x": a, "y": b, "z": c, "set": n} for a, b, c, n in res]
    lab = "escada " + ("descer" if mode == "down" else "subir")
    return changed_view(app, p.apply(ops, lab))
