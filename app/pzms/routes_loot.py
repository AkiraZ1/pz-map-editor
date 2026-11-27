"""Rotas da ferramenta Spawn (loot de container/sala/area). Dados em project.meta["loot"] (ver spawns.py)."""
from .server import route, changed_view, ApiError
from . import spawns as SP


def _modid(p):
    m = p.meta.get("mapid") or "MeuMapa"
    return "".join(ch for ch in m if ch.isalnum() or ch in "_-") or "MeuMapa"


@route("GET", "/api/loot")
def _loot(app, q, body):
    p = app.need_project()
    return {"loot": SP.norm_loot(p.meta.get("loot")), "user": SP.user_groups(),
            "undo": p.undo[-1]["label"] if p.undo else None, "redo": p.redo[-1]["label"] if p.redo else None}


@route("GET", "/api/loot/vanilla")
def _vanilla(app, q, body):
    """listas do jogo: procedurais, salas -> containers, todos os containers (sem os itens: ver /items)."""
    v = SP.vanilla_lists(app.media)
    return {"procedural": v["procedural"], "rooms": v["rooms"], "containers": v["containers"],
            "dist": v.get("dist") or {}, "nitems": len(v["items"]), "media": bool(app.media)}


@route("GET", "/api/loot/items")
def _items(app, q, body):
    """?q=texto -> ate 200 itens (Base.X) que contem o texto."""
    s = (q.get("q") or "").strip().lower()
    lim = max(1, min(500, int(q.get("limit") or 200)))
    items = SP.vanilla_lists(app.media)["items"]
    if s:
        a = [i for i in items if i.lower().split(".", 1)[-1].startswith(s)]
        sa = set(a)
        b = [i for i in items if s in i.lower() and i not in sa]
        items = a + b
    return {"items": items[:lim], "total": len(items)}


@route("POST", "/api/loot/set")
def _set(app, q, body):
    """{loot: {...}, label} -> um passo de desfazer."""
    p = app.need_project()
    if "loot" not in body:
        raise ApiError("faltou loot")
    new = SP.norm_loot(body["loot"])
    if new == SP.norm_loot(p.meta.get("loot")):
        r = changed_view(app, {}); r["loot"] = new; r["same"] = True
        return r
    p.push_cmd(str(body.get("label") or "spawn")[:80], meta={"loot": new if (new["rules"] or new["custom"]) else None})
    r = changed_view(app, {})
    r["loot"] = new
    return r


@route("POST", "/api/loot/usergroup")
def _usergroup(app, q, body):
    """{name, group | null} -> grupo no perfil do usuario (vale para todos os mapas, sem desfazer)."""
    name = str(body.get("name") or "").strip()
    if not SP._NAME.match(name):
        raise ApiError("nome invalido (letras, numeros, espaco . - _ /, ate 80)")
    return {"user": SP.save_user_group(name, body.get("group"))}


@route("GET", "/api/loot/lua")
def _lua(app, q, body):
    """previa do Lua que o export grava."""
    p = app.need_project()
    modid = _modid(p)
    return {"modid": modid, "path": f"common/media/lua/server/Items/{modid}_Distributions.lua",
            "lua": SP.build_lua(p, modid) or ""}
