"""Portas e janelas vanilla para a ferramenta Parede (pares W/N, nome EN/PT)."""
from .server import route, ApiError

_cache = {}


def openings(assets, media):
    """{"door": [...], "window": [...]}; cada um {W, N, label, en, pt, sheet}.
    Vanilla: porta fechada em i (doorW) e i+1 (doorN); i+2/i+3 sao as abertas (sem props).
    Janela fechada tem IsClosedState; as abertas/quebradas nao."""
    k = id(assets)
    if k in _cache:
        return _cache[k]
    from . import names
    T = assets.tiles
    out = {"door": [], "window": []}
    for n, p in T.items():
        kind = "door" if "doorW" in p else "window" if "windowW" in p and "IsClosedState" in p else None
        if not kind:
            continue
        s, _, i = n.rpartition("_")
        if not i.isdigit():
            continue
        m = f"{s}_{int(i) + 1}"
        q = T.get(m) or {}
        if ("doorN" if kind == "door" else "windowN") not in q:
            continue
        g, c = p.get("GroupName"), p.get("CustomName")
        en, pt = names.moveable(media, g, c)
        label = " ".join(x for x in (g, c) if x) or s
        out[kind].append({"W": n, "N": m, "label": label, "en": en, "pt": pt, "sheet": s, "i": int(i)})
    for v in out.values():
        v.sort(key=lambda o: (not o["sheet"].startswith(("fixtures_doors_0", "fixtures_windows")), o["sheet"], o["i"]))
    _cache[k] = out
    return out


@route("GET", "/api/openings")
def _openings(app, q, body):
    if not app.assets:
        raise ApiError("cache nao pronto")
    return openings(app.assets, app.media)
