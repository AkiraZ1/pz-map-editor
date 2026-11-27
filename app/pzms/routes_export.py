"""Rotas do export direto para mod."""
import os

from .server import route, ApiError
from . import export as E
from . import workshop as W
from . import progress as PG

WS_KEYS = ("workshop", "ws_dir", "visibility", "tags", "changenote", "published_id", "steam_user")


def _opts(app, body):
    p = app.need_project()
    o = dict(p.meta.get("export") or {})
    o.update({k: v for k, v in (body or {}).items() if k in ("modid", "title", "description", "author", "mods_dir") + WS_KEYS})
    o.setdefault("modid", "".join(ch for ch in (p.meta.get("mapid") or p.meta.get("name") or "MeuMapa") if ch.isalnum()) or "MeuMapa")
    o.setdefault("title", p.meta.get("name") or o["modid"])
    o.setdefault("mods_dir", E.default_mods_dir())
    return p, o


@route("GET", "/api/export")
def _export_info(app, q, body):
    p, o = _opts(app, {})
    root = os.path.join(o["mods_dir"], o["modid"])
    ws = o.get("ws_dir") or W.ws_root(o["modid"])
    return {"opts": o, "exists": os.path.isdir(root), "ours": os.path.exists(os.path.join(root, E.MARK)),
            "path": root, "last": p.meta.get("export_last"), "cover": W.cover_info(p), "ws_path": ws,
            "ws_foreign": os.path.isdir(ws) and bool(os.listdir(ws)) and not os.path.exists(os.path.join(ws, W.MARK))}


@route("POST", "/api/export/cover")
def _export_cover(app, q, body):
    """capa do Workshop: {data: dataURL} grava (quadrada 512 px); {delete: true} tira."""
    p = app.need_project()
    if body.get("delete"):
        W.delete_cover(p)
        return {"cover": None}
    try:
        return {"cover": W.save_cover(p, body.get("data"))}
    except Exception as e:                      # noqa: BLE001 - formato que o PIL nao abre
        raise ApiError(f"capa: {e}")


@route("POST", "/api/export")
def _export_run(app, q, body):
    p, o = _opts(app, body)
    if not o["modid"] or any(not (ch.isalnum() or ch in "_-") for ch in o["modid"]):
        raise ApiError("ID do mod: so letras, numeros, _ e -")
    root = os.path.join(o["mods_dir"], o["modid"])
    if os.path.isdir(root) and not os.path.exists(os.path.join(root, E.MARK)) and not body.get("overwrite"):
        raise ApiError(f"ja existe um mod '{o['modid']}' que nao foi feito por este app em {o['mods_dir']}; troque o ID")
    j = app.jobs.get("export")
    if j and not j.done:
        return {"started": False, "running": True}
    p.meta["export"] = o
    p.meta_dirty = True

    def work(job):
        r = E.export(p, o["mods_dir"], o)
        if o.get("workshop"):
            PG.mark("workshop", 0, 1, "pasta do Workshop")
            r["workshop"] = W.stage(p, r["path"], r["modid"], o)
            if r["workshop"]["published_id"] and not o.get("published_id"):
                o["published_id"] = r["workshop"]["published_id"]
            PG.finish("workshop")
        p.meta["export_last"] = r
        p.save()
        return r
    app.start_job("export", work, ["salvar", "celulas", "worldmap", "metadados"] + (["workshop"] if o.get("workshop") else []), [root], f"Exportando mod {o['modid']}")
    return {"started": True, "path": root}
