"""Servidor HTTP local (so 127.0.0.1): API JSON/binaria para a UI WebGL e tarefas longas com progresso."""
import json
import mimetypes
import os
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, SUPPORTED_GAME, APP_NAME
from . import assets as A
from . import gamedir
from . import progress as PG
from .project import Kinds, Project

UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")


class Job:
    def __init__(self, kind):
        self.kind, self.frac, self.msg, self.done, self.error, self.result = kind, 0.0, "", False, None, None

    def view(self):
        return {"kind": self.kind, "frac": round(self.frac, 3), "msg": self.msg, "done": self.done,
                "error": self.error, "result": self.result}


class App:
    """estado do aplicativo (um projeto aberto por vez)."""

    def __init__(self):
        self.cfg = gamedir.load_config()
        self.media = gamedir.find_media()
        self.version = gamedir.game_version(self.media) if self.media else None
        self.assets = None
        self.kinds = None
        self.project = None
        self.jobs = {}
        self.lock = threading.RLock()
        self._catalog = None
        self.handlers = {}                 # extensoes registradas por modulos (catalogo, osm, export)
        self.resume = None                 # {"path", "view"} para reabrir depois de atualizar (routes_session)
        if self.media and A.is_ready(self.version):
            self._load_assets()

    def _load_assets(self):
        self.assets = A.Assets(self.version)
        self.kinds = Kinds(self.assets.tiles)

    def catalog(self):
        from . import catalog as C
        if self._catalog is None and self.assets and C.is_ready(self.assets.root):
            self._catalog = C.Catalog(self.assets.root, self.assets)
        return self._catalog

    def start_job(self, kind, fn, steps=None, outputs=(), title=""):
        job = Job(kind)
        self.jobs[kind] = job
        PG.begin(kind, steps or [kind], outputs, title)

        def run():
            try:
                job.result = fn(job)
            except Exception as e:                      # noqa: BLE001 - erro vai para a UI
                traceback.print_exc()
                job.error = f"{type(e).__name__}: {e}"
            PG.end(kind, job.error)
            job.done = True
        threading.Thread(target=run, daemon=True).start()
        return job

    def state(self):
        p = self.project
        return {
            "app": __version__, "name": APP_NAME, "supported": SUPPORTED_GAME,
            "game": {"media": self.media, "version": self.version, "candidates": gamedir.candidates(),
                     "supported": bool(self.version and self.version in SUPPORTED_GAME)},
            "cache": {"ready": self.assets is not None, "root": self.assets.root if self.assets else None},
            "project": None if p is None else {
                "path": p.path, "meta": p.meta, "bounds": p.bounds(), "cells": sorted(p.cellset),
                "undo": p.undo[-1]["label"] if p.undo else None, "redo": p.redo[-1]["label"] if p.redo else None,
                "nu": len(p.undo), "nr": len(p.redo), "dirty": p.dirty()},
            "recent": self.cfg.get("recent", [])[:10],
            "resume": self.resume if p is None else None,
            "projects_dir": gamedir.projects_dir(),
            "jobs": {k: j.view() for k, j in self.jobs.items()},
        }

    def remember(self, path):
        r = [path] + [x for x in self.cfg.get("recent", []) if x != path]
        self.cfg["recent"] = r[:10]
        gamedir.save_config(self.cfg)

    def need_project(self):
        if not self.project:
            raise ApiError("nenhum projeto aberto")
        return self.project


OPEN_HOOKS = []                         # f(app) depois de abrir/criar projeto (modtiles)


class ApiError(Exception):
    pass


def changed_view(app, changed):
    p = app.project
    return {"changed": [[ck[0], ck[1], sorted(v)] for ck, v in changed.items()],
            "undo": p.undo[-1]["label"] if p.undo else None, "redo": p.redo[-1]["label"] if p.redo else None,
            "nu": len(p.undo), "nr": len(p.redo)}       # profundidade: rotulos iguais nao enganam quem observa a pilha


# ---------------------------------------------------------------- rotas
ROUTES = {}


def route(method, path):
    def deco(fn):
        ROUTES[(method, path)] = fn
        return fn
    return deco


@route("GET", "/api/state")
def _state(app, q, body):
    return app.state()


@route("GET", "/api/progress")
def _progress(app, q, body):
    """painel MACRO/MICRO/LOG da operacao longa (a atual ou ?op=)."""
    return {"progress": PG.snapshot(q.get("op") or PG.current())}


@route("POST", "/api/game")
def _game(app, q, body):
    m = gamedir.media_of(body.get("path"))
    if not m:
        raise ApiError("nao achei a pasta media do Project Zomboid nesse caminho")
    app.cfg["game_path"] = body["path"]
    gamedir.save_config(app.cfg)
    app.media, app.version = m, gamedir.game_version(m)
    app.assets = None
    if A.is_ready(app.version):
        app._load_assets()
    return app.state()


@route("POST", "/api/cache/build")
def _cache_build(app, q, body):
    if not app.media:
        raise ApiError("jogo nao encontrado")

    def work(job):
        def prog(f, m):
            job.frac, job.msg = f, m
            if m != getattr(prog, "last", None):
                prog.last = m
                PG.log(m)
        A.build(app.media, app.version, prog)
        PG.finish("atlas")
        app._load_assets()
        PG.mark("paleta", 0, 1, "montando categorias")
        from . import palette
        palette.build(app.assets, app.kinds)
        PG.finish("paleta")
        return {"ok": True}
    app.start_job("cache", work, ["sprites", "atlas", "paleta"], [A.cache_root(app.version)],
                  "Preparando sprites do jogo")
    return {"started": True}


@route("GET", "/api/jobs")
def _jobs(app, q, body):
    return {k: j.view() for k, j in app.jobs.items()}


@route("POST", "/api/project/new")
def _new(app, q, body):
    if not app.kinds:
        raise ApiError("cache de sprites ainda nao foi gerado")
    name = (body.get("name") or "Meu Mapa").strip()
    base = body.get("dir") or gamedir.projects_dir()
    path = os.path.join(base, "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip() or "mapa")
    if os.path.exists(os.path.join(path, "project.json")):
        raise ApiError(f"ja existe um projeto em {path}")
    w, h = int(body.get("w", 1)), int(body.get("h", 1))
    if not (1 <= w <= 64 and 1 <= h <= 64):
        raise ApiError("tamanho invalido (1 a 64 celulas por lado)")
    with app.lock:
        app.project = Project.create(path, name, int(body.get("cx0", 2)), int(body.get("cy0", 2)), w, h,
                                     app.kinds, ground=body.get("ground", True))
        app.remember(path)
    for f in OPEN_HOOKS:
        f(app)
    return app.state()


@route("POST", "/api/project/open")
def _open(app, q, body):
    if not app.kinds:
        raise ApiError("cache de sprites ainda nao foi gerado")
    path = body.get("path", "")
    if os.path.isfile(path):
        path = os.path.dirname(path)
    if not os.path.exists(os.path.join(path, "project.json")):
        raise ApiError("pasta sem project.json")
    with app.lock:
        if app.project and app.project.dirty():
            app.project.save()
        app.project = Project.open(path, app.kinds)
        app.remember(path)
    for f in OPEN_HOOKS:
        f(app)
    return app.state()


@route("POST", "/api/project/save")
def _save(app, q, body):
    app.need_project().save()
    return app.state()


@route("POST", "/api/project/meta")
def _meta(app, q, body):
    p = app.need_project()
    for k in ("name", "title", "description", "spawn", "mapid", "author", "poster"):
        if k in body:
            p.meta[k] = body[k]
    p.save()
    return app.state()


@route("POST", "/api/project/cells")
def _cells(app, q, body):
    """adiciona ou remove celulas inteiras."""
    p = app.need_project()
    with p.lock:
        for cx, cy in body.get("add", []):
            p.cell(int(cx), int(cy), create=True)
        for cx, cy in body.get("remove", []):
            p.cellset.discard((cx, cy)); p.cells.pop((cx, cy), None)
            for fn in (f"{cx}_{cy}.lotheader", f"world_{cx}_{cy}.lotpack"):
                fp = os.path.join(p.cdir, fn)
                if os.path.exists(fp):
                    os.remove(fp)
        p.save()
    return app.state()


@route("GET", "/api/cell")
def _cell(app, q, body):
    p = app.need_project()
    ch = q.get("chunks")
    chunks = [int(x) for x in ch.split(",") if x != ""] if ch else None
    with p.lock:
        blob = p.chunk_blob(int(q["cx"]), int(q["cy"]), chunks)
    if blob is None:
        raise ApiError("celula fora do projeto")
    # no-store: a mesma URL muda a cada edicao; com cache o pincel arrastado mostrava o chunk velho
    return ("application/octet-stream", blob, {"Cache-Control": "no-store"})


@route("GET", "/api/square")
def _square(app, q, body):
    p = app.need_project()
    x, y, z = int(q["x"]), int(q["y"]), int(q.get("z", 0))
    tiles = p.get(x, y, z)
    rooms = [r["name"] for r in p.rooms_world() if r["z"] == z and
             any(a <= x < a + w and b <= y < b + h for a, b, w, h in r["rects"])] \
        if (x // 256, y // 256) in p.cells else []
    return {"x": x, "y": y, "z": z, "rooms": rooms,
            "tiles": [{"name": t, "kind": p.kinds.kind(t), "label": app.assets.props(t).get("CustomName", "")}
                      for t in tiles]}


@route("GET", "/api/area_tiles")
def _area_tiles(app, q, body):
    """tiles de um retangulo (ferramenta Ver arrastando): nome, tipo, rotulo e em quantos quadrados aparece."""
    p = app.need_project()
    x0, y0, x1, y1, z = (int(q[k]) for k in ("x0", "y0", "x1", "y1", "z"))
    if (x1 - x0 + 1) * (y1 - y0 + 1) > 70000:
        raise ApiError("area grande demais (max ~256x256)")
    cnt, n = {}, 0
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            ts = p.get(x, y, z)
            n += bool(ts)
            for t in set(ts):
                cnt[t] = cnt.get(t, 0) + 1
    tiles = [{"name": t, "kind": p.kinds.kind(t), "label": app.assets.props(t).get("CustomName", ""), "count": c}
             for t, c in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {"squares": n, "tiles": tiles}


@route("POST", "/api/edit")
def _edit(app, q, body):
    p = app.need_project()
    return changed_view(app, p.apply(body.get("ops", []), body.get("label", "editar"), body.get("stroke")))


@route("POST", "/api/undo")
def _undo(app, q, body):
    p = app.need_project()
    r = p.do_undo()
    return changed_view(app, r[0] if r else {})


@route("POST", "/api/redo")
def _redo(app, q, body):
    p = app.need_project()
    r = p.do_redo()
    return changed_view(app, r[0] if r else {})


@route("POST", "/api/rooms/add")
def _room_add(app, q, body):
    p = app.need_project()
    join = None
    if body.get("join"):
        jx, jy, jz = body["join"]
        join = p.building_at(int(jx), int(jy), int(jz))
    return changed_view(app, p.add_building(body["rooms"], body.get("label", "sala"), join=join))


@route("POST", "/api/rooms/rename")
def _room_rename(app, q, body):
    p = app.need_project()
    name = (body.get("name") or "").strip()
    if not name or not all(ch.isalnum() or ch == "_" for ch in name):
        raise ApiError("tipo de sala invalido (use o nome vanilla, ex.: kitchen)")
    return changed_view(app, p.rename_room_at(int(body["x"]), int(body["y"]), int(body.get("z", 0)), name))


@route("GET", "/api/rooms/at")
def _room_at(app, q, body):
    p = app.need_project()
    ck, c, i = p._room_at(int(q["x"]), int(q["y"]), int(q.get("z", 0)))
    return {"room": None if i is None else {"name": c.rooms[i][0], "cell": ck}}


@route("GET", "/api/rooms/types")
def _room_types(app, q, body):
    """tipos de sala vanilla: nomes usados nos predios do mapa vanilla (catalogo) + salas do Distributions.lua."""
    from . import catalog as C
    cnt = {}
    cat = app.catalog()
    if cat:
        for it in cat.index["items"]:
            for r in it.get("rooms") or []:
                cnt[r] = cnt.get(r, 0) + it.get("count", 1)
    if app.media:
        from . import spawns as SP
        for r in SP.vanilla_lists(app.media)["rooms"]:
            cnt.setdefault(r, 0)
    out = []
    for n, c in cnt.items():
        t, _w = C.room_type(n)
        out.append({"name": n, "type": t or "neutro", "count": c})
    out.sort(key=lambda r: (-r["count"], r["name"]))
    return {"types": out, "labels": {k: v for k, v in getattr(C, "TYPE_NAMES", {}).items()}}


@route("POST", "/api/rooms/remove")
def _room_rm(app, q, body):
    p = app.need_project()
    return changed_view(app, p.remove_rooms_at(int(body["x"]), int(body["y"]), int(body.get("z", 0))))


@route("GET", "/api/rooms")
def _rooms(app, q, body):
    p = app.need_project()
    x0, y0, x1, y1 = (int(q[k]) for k in ("x0", "y0", "x1", "y1"))
    out = []
    for r in p.rooms_world():
        if any(a < x1 and a + w > x0 and b < y1 and b + h > y0 for a, b, w, h in r["rects"]):
            out.append(r)
    return {"rooms": out}


@route("GET", "/api/tile")
def _tile(app, q, body):
    n = q["name"]
    return {"name": n, "props": app.assets.props(n), "kind": app.kinds.kind(n)}


@route("GET", "/api/palette")
def _palette(app, q, body):
    """folhas por categoria (como o menu de construcao) com rotulos e nomes."""
    if not app.assets:
        raise ApiError("cache nao pronto")
    from . import palette, names
    pal = palette.build(app.assets, app.kinds)
    if not pal.get("named"):                         # nome do jogador (EN/PT, traducao vanilla) em cada item
        T = app.assets.tiles
        for it in pal["items"]:
            p = T.get((it.get("parts") or [[0, 0, it.get("icon")]])[0][2], {}) or {}
            en, pt = names.moveable(app.media, p.get("GroupName"), p.get("CustomName"))
            if en:
                it["en"] = en
            if pt:
                it["pt"] = pt
        pal["named"] = True
    return pal


@route("POST", "/api/pick_folder")
def _pick(app, q, body):
    """dialogo nativo de pasta (quando roda no webview)."""
    w = app.handlers.get("window")
    if not w:
        raise ApiError("dialogo nativo indisponivel; digite o caminho")
    import webview
    r = w.create_file_dialog(webview.FOLDER_DIALOG)
    return {"path": r[0] if r else None}


# ---------------------------------------------------------------- catalogo de predios vanilla
@route("GET", "/api/catalog")
def _catalog(app, q, body):
    c = app.catalog() if app.assets else None
    if not c:
        return {"ready": False}
    return {"ready": True, "types": c.index["types"], "items": c.index["items"]}


@route("POST", "/api/catalog/build")
def _catalog_build(app, q, body):
    if not app.assets:
        raise ApiError("prepare os sprites do jogo primeiro")
    j = app.jobs.get("catalog")
    if j and not j.done:
        return {"started": False, "running": True}
    from . import catalog as C

    def work(job):
        def prog(f, m):
            job.frac, job.msg = f, m
            if m != getattr(prog, "last", None):
                prog.last = m
                PG.log(m)
        C.build(app.media, app.assets.root, prog)
        app._catalog = None
        app.catalog()
        return {"ok": True}
    app.start_job("catalog", work, ["predios", "gravar"], [os.path.join(app.assets.root, "catalog")],
                  "Montando catalogo de predios vanilla")
    return {"started": True}


@route("GET", "/api/catalog/thumb")
def _catalog_thumb(app, q, body):
    c = app.catalog()
    if not c:
        raise ApiError("catalogo nao pronto")
    try:
        return "image/png", c.thumb(q["id"]), {"Cache-Control": "max-age=86400"}
    except KeyError:
        raise ApiError("predio desconhecido")


@route("GET", "/api/catalog/prefab")
def _catalog_prefab(app, q, body):
    c = app.catalog()
    if not c:
        raise ApiError("catalogo nao pronto")
    r = c.oriented(q["id"], int(q.get("o", 0)))
    return {"id": q["id"], "o": int(q.get("o", 0)), **r, "item": c.byid[q["id"]]}


@route("POST", "/api/catalog/place")
def _catalog_place(app, q, body):
    """coloca o predio com o canto (x, y) no andar z; salas e quadrados num passo so de desfazer."""
    p = app.need_project()
    c = app.catalog()
    if not c:
        raise ApiError("catalogo nao pronto")
    pid, o = body["id"], int(body.get("o", 0))
    x0, y0, dz = int(body["x"]), int(body["y"]), int(body.get("z", 0))
    r = c.oriented(pid, o)
    inroom = set()
    for _n, z, rects in r["rooms"]:
        for rx, ry, rw, rh in rects:
            for x in range(rx, rx + rw):
                for y in range(ry, ry + rh):
                    inroom.add((x, y, z))
    ops = []
    for x, y, z, names in r["sq"]:
        wx, wy, wz = x0 + x, y0 + y, z + dz
        if (x, y, z) in inroom or wz != 0:
            new = list(names)
        else:                                          # fora das salas no chao: mantem o piso/terreno
            cur = p.get(wx, wy, wz)
            new = [t for t in cur if app.kinds.kind(t) == "floor"][:1] + list(names)
        ops.append({"x": wx, "y": wy, "z": wz, "set": new})
    rooms = [{"name": n, "z": z + dz, "rects": [(x0 + rx, y0 + ry, rw, rh) for rx, ry, rw, rh in rects]}
             for n, z, rects in r["rooms"]]
    item = c.byid[pid]
    return changed_view(app, p.add_building(rooms, f"predio {item['label']}", ops))


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    app = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        if os.environ.get("PZMS_DEBUG"):
            super().log_message(fmt, *a)

    def _send(self, code, ctype, data, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if "Cache-Control" not in (extra or {}):
            self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json") else "max-age=60")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8", json.dumps(obj, separators=(",", ":")).encode())

    def _file(self, path, cache=False):
        if not os.path.isfile(path):
            return self._json({"error": "nao encontrado"}, 404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if path.endswith(".js"):
            ctype = "text/javascript"
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _route(self, method):
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        path = urllib.parse.unquote(u.path)
        app = self.app
        if method == "GET" and not path.startswith("/api/"):
            if path.startswith("/cache/"):
                if not app.assets:
                    return self._json({"error": "cache nao pronto"}, 404)
                rel = os.path.normpath(path[len("/cache/"):]).lstrip(os.sep)
                if rel.startswith(".."):
                    return self._json({"error": "caminho"}, 403)
                return self._file(os.path.join(app.assets.root, rel), cache=True)
            if path.startswith("/data/"):            # miniaturas do catalogo etc.
                rel = os.path.normpath(path[len("/data/"):]).lstrip(os.sep)
                if rel.startswith(".."):
                    return self._json({"error": "caminho"}, 403)
                return self._file(os.path.join(gamedir.data_dir(), rel), cache=True)
            rel = os.path.normpath(path.lstrip("/") or "index.html")
            if rel.startswith(".."):
                return self._json({"error": "caminho"}, 403)
            return self._file(os.path.join(UI, rel))
        fn = ROUTES.get((method, path))
        if not fn:
            return self._json({"error": f"rota desconhecida {path}"}, 404)
        body = {}
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                try:
                    body = json.loads(self.rfile.read(n))
                except ValueError:
                    return self._json({"error": "json invalido"}, 400)
        try:
            r = fn(app, q, body)
        except ApiError as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:                           # noqa: BLE001
            traceback.print_exc()
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        if isinstance(r, tuple):
            return self._send(200, r[0], r[1], r[2] if len(r) > 2 else None)
        return self._json(r)

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        # protege contra outras paginas do navegador chamando a API local
        origin = self.headers.get("Origin")
        if origin and not origin.startswith(("http://127.0.0.1", "http://localhost")):
            return self._json({"error": "origem"}, 403)
        self._route("POST")


def serve(port=0):
    app = App()
    # modulos opcionais registram rotas
    here = os.path.dirname(os.path.abspath(__file__))
    plug = sorted(f[:-3] for f in os.listdir(here) if f.startswith("routes_") and f.endswith(".py"))
    for mod in ["catalog", "osmgen", "export"] + plug:
        try:
            __import__(f"pzms.{mod}")
        except ImportError as e:
            if f"pzms.{mod}" not in str(e):
                traceback.print_exc()
    Handler.app = app
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return app, srv, f"http://127.0.0.1:{srv.server_address[1]}/"
