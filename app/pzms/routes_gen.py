"""Rotas de "Gerar de lugar real": arquivo OSM do usuario -> validacao -> projeto novo do editor."""
import os

from .server import route, ApiError
from . import gamedir
from .project import Project

EXTS = (".osm", ".osm.pbf", ".pbf", ".xml")


def _check_path(p):
    p = (p or "").strip()
    if not p:
        raise ApiError("escolha o arquivo .osm ou .osm.pbf")
    if not os.path.isfile(p):
        raise ApiError(f"arquivo nao encontrado: {p}")
    if not p.lower().endswith(EXTS):
        raise ApiError("o arquivo precisa ser .osm ou .osm.pbf")
    return p


def _bbox(b):
    if not b:
        return None
    try:
        lat0, lon0, lat1, lon1 = (float(v) for v in b)
    except (TypeError, ValueError):
        raise ApiError("area invalida")
    if not (-90 <= lat0 < lat1 <= 90 and -180 <= lon0 < lon1 <= 180):
        raise ApiError("area invalida: confira latitude/longitude (sul < norte, oeste < leste)")
    return (lat0, lon0, lat1, lon1)


def _dir_for(name, base=None):
    base = base or gamedir.projects_dir()
    return os.path.join(base, "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip() or "mapa")


@route("POST", "/api/pick_file")
def _pick_file(app, q, body):
    """dialogo nativo para escolher o .osm/.pbf (quando roda no webview)."""
    w = app.handlers.get("window")
    if not w:
        raise ApiError("dialogo nativo indisponivel; cole o caminho do arquivo")
    import webview
    r = w.create_file_dialog(webview.OPEN_DIALOG, file_types=("OpenStreetMap (*.osm;*.pbf)", "Todos (*.*)"))
    return {"path": r[0] if r else None}


@route("POST", "/api/osm/validate")
def _validate(app, q, body):
    from . import spgen
    path = _check_path(body.get("path"))
    try:
        v = spgen.validate(path, _bbox(body.get("bbox")))
    except ApiError:
        raise
    except Exception as e:                      # noqa: BLE001 - arquivo ruim vira mensagem na UI
        raise ApiError(f"arquivo OSM invalido: {type(e).__name__}: {e}")
    name = (body.get("name") or "").strip()
    if name:
        v["destino"] = _dir_for(name, body.get("dir"))
        v["destino_existe"] = os.path.exists(os.path.join(v["destino"], "project.json"))
    return v


@route("POST", "/api/generate")
def _generate(app, q, body):
    from . import spgen
    if not app.kinds:
        raise ApiError("cache de sprites ainda nao foi gerado")
    path = _check_path(body.get("path"))
    bbox = _bbox(body.get("bbox"))
    if not bbox:
        raise ApiError("escolha a area no mapa antes de gerar")
    name = (body.get("name") or "").strip() or "Lugar real"
    out = _dir_for(name, body.get("dir"))
    if os.path.exists(os.path.join(out, "project.json")):
        raise ApiError(f"ja existe um projeto em {out}; troque o nome")
    j = app.jobs.get("generate")
    if j and not j.done:
        return {"started": False, "running": True}
    extra = {}
    fp = (body.get("footprints") or "").strip()
    if fp:
        if not os.path.isfile(fp):
            raise ApiError(f"fonte extra nao encontrada: {fp}")
        extra["footprints"] = fp

    def work(job):
        from .progress import PG
        r = spgen.generate(path, bbox, out, name, progress=PG, extra=extra or None)
        with app.lock:
            if app.project and app.project.dirty():
                app.project.save()
            app.project = Project.open(out, app.kinds)
            app.remember(out)
        return {"path": out, **(r if isinstance(r, dict) else {})}

    app.start_job("generate", work, ["ler osm", "celulas", "metadados"], [out], f"Gerando {name}")
    return {"started": True, "path": out}
