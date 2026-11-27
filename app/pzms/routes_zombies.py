"""Rotas da ferramenta Zumbis (densidade por chunk)."""
from .server import route, changed_view, ApiError
from . import zombies as ZB


@route("GET", "/api/zombies")
def _zombies(app, q, body):
    """densidade das celulas (base64 de 1024 bytes, so as que tem algo). ?cx0&cy0&cx1&cy1 filtra."""
    p = app.need_project()
    box = None
    if all(k in q for k in ("cx0", "cy0", "cx1", "cy1")):
        box = tuple(int(q[k]) for k in ("cx0", "cy0", "cx1", "cy1"))
    return {"cells": ZB.view(p, box), "levels": ZB.LEVELS, "vanilla_max": ZB.VANILLA_MAX}


@route("POST", "/api/zombies/paint")
def _zombies_paint(app, q, body):
    """{value: nivel|numero, chunks: [[wcx, wcy], ...]} e/ou {rect: [x0, y0, x1, y1]} em quadrados e/ou {all: true};
    values: [[wcx, wcy, v], ...] com valor por chunk."""
    p = app.need_project()
    chunks = [tuple(c) for c in body.get("chunks") or []]
    if body.get("rect"):
        chunks += ZB.rect_chunks(*[int(v) for v in body["rect"]])
    if body.get("all"):                        # preencher/limpar o mapa inteiro
        chunks += [(cx * ZB.NCH + i, cy * ZB.NCH + j) for cx, cy in p.cellset for i in range(ZB.NCH) for j in range(ZB.NCH)]
    values = [tuple(t) for t in body.get("values") or [] if len(t) == 3]
    if not chunks and not values:
        raise ApiError("nenhum chunk")
    if len(chunks) + len(values) > 2000000:
        raise ApiError("area grande demais")
    try:
        ch = ZB.paint(p, chunks, body.get("value", "media"), body.get("label"), values)
    except ValueError as e:
        raise ApiError(str(e))
    r = changed_view(app, ch)
    r["cells"] = {f"{cx},{cy}": ZB.view(p, (cx, cy, cx, cy)).get(f"{cx},{cy}", "") for cx, cy in ch}
    return r


@route("GET", "/api/zombies/stats")
def _zombies_stats(app, q, body):
    return ZB.stats(app.need_project())
