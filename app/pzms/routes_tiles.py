"""Tiles extras: mods instalados com tiles e folhas PNG novas do projeto (ver modtiles.py)."""
import base64
import os
import re

from . import modtiles as MT
from .server import route, ApiError, OPEN_HOOKS

OPEN_HOOKS.append(lambda app: MT.activate(app))


@route("GET", "/api/atlas")
def _atlas(app, q, body):
    if not app.assets:
        raise ApiError("cache nao pronto")
    return app.assets.meta()


@route("GET", "/api/tilesets/status")
def _status(app, q, body):
    return dict(MT.STATUS, sig=app.assets.sig if app.assets else "")


def _view(app):
    p = app.need_project()
    mods, use, miss = MT.wanted(app, p)
    on = {m["id"] for m in use}
    return {"mods": [{"id": m["id"], "name": m["name"], "dir": m["dir"], "on": m["id"] in on}
                     for m in sorted(mods.values(), key=lambda m: (m["id"] not in on, m["name"].lower()))],
            "sheets": [{"name": s, "default": v.get("default", "object"), "tiles": v.get("tiles", {}),
                        "cols": v.get("cols"), "rows": v.get("rows")} for s, v in sorted(MT.proj_sheets(p).items())],
            "missing": miss, "types": list(MT.TYPES), "status": dict(MT.STATUS, sig=app.assets.sig)}


@route("GET", "/api/tilesets")
def _tilesets(app, q, body):
    return _view(app)


@route("POST", "/api/tilesets/use")
def _use(app, q, body):
    p = app.need_project()
    p.meta["tilemods"] = [str(i) for i in body.get("ids", [])]
    p.save()
    MT.activate(app)
    return _view(app)


@route("POST", "/api/tilesets/sheet")
def _sheet(app, q, body):
    """{name, png: base64?, default?, tiles?}: cria/troca a folha PNG do projeto ou so muda os tipos."""
    p = app.need_project()
    name = (body.get("name") or "").strip()
    if not MT.NAME_OK.match(name):
        raise ApiError("nome da folha: letras/numeros/_ terminando em _01 (ex.: meumapa_placas_01)")
    if name in app.assets.base_sheets:
        raise ApiError("ja existe uma folha vanilla com esse nome")
    sh = MT.proj_sheets(p)
    v = sh.get(name, {})
    note = ""
    if body.get("png"):
        try:
            im, cols, rows, note = MT.check_png(base64.b64decode(re.sub(r"^data:[^,]*,", "", body["png"])))
        except ValueError as e:
            raise ApiError(str(e))
        os.makedirs(MT.proj_dir(p), exist_ok=True)
        im.save(os.path.join(MT.proj_dir(p), name + ".png"))
        v.update(cols=cols, rows=rows)
    elif name not in sh:
        raise ApiError("escolha o PNG da folha")
    if body.get("default") in MT.TYPES:
        v["default"] = body["default"]
    if isinstance(body.get("tiles"), dict):
        v["tiles"] = {str(k): t for k, t in body["tiles"].items() if t in MT.TYPES}
    v.pop("png", None)
    sh[name] = v
    MT.save_proj_sheets(p, sh)
    MT.activate(app)
    r = _view(app)
    r["note"] = note
    return r


@route("POST", "/api/tilesets/sheet_rm")
def _sheet_rm(app, q, body):
    p = app.need_project()
    sh = MT.proj_sheets(p)
    name = body.get("name")
    if name in sh:
        os.remove(sh[name]["png"])
        del sh[name]
        MT.save_proj_sheets(p, sh)
        MT.activate(app)
    return _view(app)


@route("GET", "/api/tilesets/png")
def _png(app, q, body):
    p = app.need_project()
    v = MT.proj_sheets(p).get(q.get("name", ""))
    if not v:
        raise ApiError("folha nao encontrada")
    with open(v["png"], "rb") as f:
        return ("image/png", f.read())
