"""Rotas da ferramenta Ruas (polilinhas editaveis)."""
import uuid

from .server import route, changed_view, ApiError
from . import streets as ST


@route("GET", "/api/streets")
def _streets(app, q, body):
    p = app.need_project()
    items = ST.get(p)["items"]
    return {"items": items, "info": ST.summary(items), "fams": ST.FAMS, "def": ST.DEF}


@route("POST", "/api/streets/set")
def _streets_set(app, q, body):
    """{item: {...}} cria/atualiza (pelo id); {delete: id} apaga. label opcional."""
    p = app.need_project()
    items = ST.get(p)["items"]
    try:
        if body.get("delete"):
            it = next((x for x in items if x["id"] == body["delete"]), None)
            if not it:
                raise ApiError("rua nao existe")
            items = [x for x in items if x["id"] != body["delete"]]
            label = body.get("label") or f"apagar {it['name']}"
        else:
            src = body.get("item") or {}
            old = next((x for x in items if x["id"] == src.get("id")), None)
            it = ST.norm(src, old)
            if not old:
                it["id"] = uuid.uuid4().hex[:10]
                items = items + [it]
                label = body.get("label") or f"nova {it['name']}"
            else:
                items = [it if x["id"] == it["id"] else x for x in items]
                label = body.get("label") or f"editar {it['name']}"
        ch = ST.apply(p, items, label)
    except ValueError as e:
        raise ApiError(str(e))
    r = changed_view(app, ch)
    r["items"] = items
    r["info"] = ST.summary(items)
    r["id"] = it["id"]
    return r
