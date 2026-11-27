"""Sessao: o instalador pede para salvar e fechar, e o app reabre de onde parou.
- running.json (data_dir) diz a porta/pid da instancia aberta; some ao sair.
- POST /api/shutdown salva o projeto, guarda cfg["resume"] (projeto + camera) e encerra o processo.
- No boot, App.state manda "resume" uma vez e a UI reabre o projeto e a camera."""
import atexit
import json
import os
import threading

from . import gamedir, __version__
from .server import route

_view = {}


def _running_path():
    return os.path.join(gamedir.data_dir(), "running.json")


def mark_running(port):
    p = _running_path()
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"port": port, "pid": os.getpid(), "version": __version__}, f)

    def clear():
        try:
            with open(p, encoding="utf-8") as f:
                if json.load(f).get("pid") == os.getpid():
                    os.remove(p)
        except (OSError, ValueError):
            pass
    atexit.register(clear)
    return clear


def take_resume(app, recent_fallback=False):
    """le e consome cfg["resume"]; com recent_fallback usa o ultimo recente (instancia antiga fechada)."""
    r = app.cfg.pop("resume", None)
    if r is not None:
        gamedir.save_config(app.cfg)
    if not r and recent_fallback and app.cfg.get("recent"):
        r = {"path": app.cfg["recent"][0]}
    if r and r.get("path") and os.path.exists(r["path"]):
        app.resume = r


@route("POST", "/api/view")
def _set_view(app, q, body):
    _view.clear()
    _view.update({k: body[k] for k in ("x", "y", "zoom", "z") if isinstance(body.get(k), (int, float))})
    return {"ok": True}


@route("POST", "/api/resume/done")
def _resume_done(app, q, body):
    app.resume = None
    return {"ok": True}


@route("POST", "/api/shutdown")
def _shutdown(app, q, body):
    with app.lock:
        p = app.project
        if p is not None:
            if p.dirty():
                p.save()
            app.cfg["resume"] = {"path": p.path, "view": dict(_view)}
            gamedir.save_config(app.cfg)
        elif app.resume:                   # fechou antes da UI reabrir: guarda o pendente de novo
            app.cfg["resume"] = app.resume
            gamedir.save_config(app.cfg)
    clear = app.handlers.get("running_clear")

    def bye():
        if clear:
            clear()
        os._exit(0)
    threading.Timer(0.3, bye).start()
    return {"ok": True, "saved": p is not None}
