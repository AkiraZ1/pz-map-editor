"""Spawns de container e area: grupos vanilla + itens avulsos + grupos personalizados, misturados.

Dados no projeto (project.json -> "loot"):
  {"custom": {"<nome>": {"vanilla": ["FridgeGeneric", "kitchen/fridge", ...],
                         "items": [{"item": "Base.Apple", "chance": 50, "count": 2, "cond": 80}]}},
   "rules":  [{"id": "r1", "room": "kitchen" | "all", "container": "fridge" | "all",
               "vanilla": [...], "items": [...], "custom": ["<nome>"], "rolls": 1}]}
  - vanilla: nome de lista de ProceduralDistributions.list ("FridgeGeneric") ou "sala/container" de
    Distributions.lua ("kitchen/fridge"; se for procedural, sorteia uma das listas dele a cada rolagem).
  - rolls: quantas vezes cada grupo vanilla e sorteado no container (cada sorteio usa os rolls da propria lista).
Grupos personalizados tambem ficam no perfil do usuario (<data>/loot_groups.json) para reusar entre mapas.
Area pintada = sala com nome proprio no lotheader (ferramenta Sala); a regra usa esse nome.

Export: <mod>/common/media/lua/server/Items/<modid>_Distributions.lua, SOMANDO ao vanilla (nada e trocado).
Conferido no B42 (media/lua/server/Items + projectzomboid.jar):
  - IsoWorld dispara OnPreDistributionMerge -> OnDistributionMerge (SuburbsDistributions.lua junta
    Distributions[2..] em Distributions[1] e cria os apelidos house_kitchen=kitchen etc.) -> OnPostDistributionMerge
    -> ItemPickerJava.Parse(). Por isso mexemos na tabela em OnPostDistributionMerge.
  - Enfiar uma lista no procList de um container NAO soma: o jogo escolhe UMA lista por container, entao a nossa
    tomaria o lugar da vanilla em parte dos containers. Em vez disso sorteamos por cima em OnFillContainer com
    ItemPickerJava.getItemContainer(sala, container, lista, false) + ItemPickerJava.doRollItem(...), o mesmo
    caminho do ISLootStressTestUI vanilla.
  - getItemContainer so acha lista que esteja no procList da sala/container pedido: registramos uma sala oculta
    "pzms_<modid>" com um container "g" cujo procList tem todas as listas usadas (so checadas em
    ProceduralDistributions.list, senao o Java da NullPointerException).
  - fillContainerInternal: sala cujo nome nao existe na distribuicao nao recebe loot e NAO dispara
    OnFillContainer. Area com nome proprio ganha uma sala vazia ({}) para o evento chegar.
  - OnFillContainer(roomName, containerType, container) tambem vem com roomName "Zombie", "Zombie Bag" e
    "Container" (bolsas), as vezes com uma tabela de distribuicao no 3o argumento: ignorados; e o
    doRollItem pode disparar o evento de novo (bolsas) -> trava de reentrada.
"""
import json
import os
import re

from . import gamedir

_cache = {}
PSEUDO_ROOMS = ("Zombie", "Zombie Bag", "Container")


def _media_scripts(media):
    return os.path.join(media, "scripts")


def _defs(txt):
    """(nivel, nome) de cada `nome = {` (os .lua do jogo misturam tab e 4 espacos na indentacao)."""
    for m in re.finditer(r"^([ \t]*)(\w+)\s*=\s*\{", txt, re.M):
        yield len(m.group(1).expandtabs(4)) // 4, m.group(2)


def _defs_at(txt):
    for m in re.finditer(r"^([ \t]*)(\w+)\s*=\s*\{", txt, re.M):
        yield m.start(), len(m.group(1).expandtabs(4)) // 4, m.group(2)


def _container(blk):
    """um container de Distributions.lua: procedural? listas do procList (nome, peso, so p/ certos tiles), rolls."""
    proc = bool(re.search(r"procedural\s*=\s*true", blk))
    m = re.search(r"\brolls\s*=\s*(\d+)", blk)
    lists = []
    for e in re.finditer(r'\{\s*name\s*=\s*"(\w+)"([^}]*)\}', blk):
        w = re.search(r"weightChance\s*=\s*(\d+)", e.group(2))
        lists.append([e.group(1), int(w.group(1)) if w else 100, "forceForTiles" in e.group(2) or "forceForZones" in e.group(2)
                      or "forceForRooms" in e.group(2) or "forceForItems" in e.group(2)])
    return {"proc": proc, "rolls": int(m.group(1)) if m else 0, "lists": lists}


def vanilla_lists(media):
    """{"procedural": [nomes], "rooms": {sala: [containers]}, "containers": [todos], "items": ["Base.X"...]}
    lido do jogo instalado (cache)."""
    if not media:
        return {"procedural": [], "rooms": {}, "containers": [], "items": [], "dist": {}}
    if media in _cache:
        return _cache[media]
    out = {"procedural": [], "rooms": {}, "containers": [], "items": []}
    pd = os.path.join(media, "lua", "server", "Items", "ProceduralDistributions.lua")
    try:
        txt = open(pd, encoding="utf-8", errors="replace").read()
        out["procedural"] = sorted({n for lv, n in _defs(txt) if lv == 1})
    except OSError:
        pass
    dd = os.path.join(media, "lua", "server", "Items", "Distributions.lua")
    out["dist"] = {}
    try:
        txt = open(dd, encoding="utf-8", errors="replace").read()
        room, defs = None, list(_defs_at(txt))
        for i, (pos, lv, n) in enumerate(defs):
            if lv == 1:
                room = n; out["rooms"].setdefault(room, [])
            elif lv == 2 and room and n not in ("procList", "items", "junk") and n not in out["rooms"][room]:
                out["rooms"][room].append(n)
                end = next((p for p, l2, _n in defs[i + 1:] if l2 <= 2), len(txt))
                out["dist"].setdefault(room, {})[n] = _container(txt[pos:end])
    except OSError:
        pass
    out["containers"] = sorted({c for cs in out["rooms"].values() for c in cs})
    items = set()
    for root, _ds, fs in os.walk(_media_scripts(media)):
        for fn in fs:
            if not fn.endswith(".txt"):
                continue
            try:
                txt = open(os.path.join(root, fn), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            mod = "Base"
            for m in re.finditer(r"^\s*(module|item)\s+([\w.]+)", txt, re.M):
                if m.group(1) == "module":
                    mod = m.group(2)
                else:
                    items.add(f"{mod}.{m.group(2)}")
    out["items"] = sorted(items)
    _cache[media] = out
    return out


# ---------------------------------------------------------------- grupos do usuario (entre mapas)
def _ugpath():
    return os.path.join(gamedir.data_dir(), "loot_groups.json")


def user_groups():
    try:
        with open(_ugpath(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_user_group(name, g):
    d = user_groups()
    if g is None:
        d.pop(name, None)
    else:
        d[name] = norm_group(g)
    os.makedirs(os.path.dirname(_ugpath()), exist_ok=True)
    with open(_ugpath(), "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    return d


# ---------------------------------------------------------------- validacao
_NAME = re.compile(r"^[\w .\-/]{1,80}$")


def _num(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def norm_item(it):
    if isinstance(it, str):
        it = {"item": it}
    name = str(it.get("item") or "").strip()
    if not name or not re.match(r"^[\w.\-]+$", name):
        return None
    if "." not in name:
        name = "Base." + name
    cond = it.get("cond")
    return {"item": name, "chance": _num(it.get("chance", 100), 0, 100, 100),
            "count": int(_num(it.get("count", 1), 1, 100, 1)),
            "cond": None if cond in (None, "") else int(_num(cond, 1, 100, 100))}


def norm_group(g):
    g = g or {}
    van = []
    for v in g.get("vanilla") or []:
        v = str(v).strip()
        if v and re.match(r"^\w+(/\w+)?$", v) and v not in van:
            van.append(v)
    items = [x for x in (norm_item(i) for i in g.get("items") or []) if x]
    return {"vanilla": van, "items": items}


def norm_loot(loot):
    """valida o que vem da UI (nomes, faixas) antes de ir para o projeto."""
    loot = loot or {}
    custom = {}
    for k, g in (loot.get("custom") or {}).items():
        k = str(k).strip()
        if _NAME.match(k):
            custom[k] = norm_group(g)
    rules, ids = [], set()
    for i, r in enumerate(loot.get("rules") or []):
        g = norm_group(r)
        rid = str(r.get("id") or f"r{i + 1}")
        while rid in ids:
            rid += "_"
        ids.add(rid)
        room = str(r.get("room") or "all").strip() or "all"
        cont = str(r.get("container") or "all").strip() or "all"
        if not re.match(r"^[\w\-]+$", room) or not re.match(r"^[\w\-]+$", cont):
            continue
        rules.append({"id": rid, "room": room, "container": cont, "vanilla": g["vanilla"], "items": g["items"],
                      "custom": [str(c) for c in r.get("custom") or [] if str(c) in custom or str(c) in user_groups()],
                      "rolls": int(_num(r.get("rolls", 1), 1, 20, 1)),
                      **({"replace": True} if r.get("replace") else {}),
                      **({"pick": "one", "weights": {k: int(_num(w, 1, 1000, 100)) for k, w in (r.get("weights") or {}).items()
                                                     if k in g["vanilla"]}} if r.get("pick") == "one" else {}),
                      **({"note": str(r["note"])[:200]} if r.get("note") else {})})
    return {"custom": custom, "rules": rules}


# ---------------------------------------------------------------- export
def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def _num_lua(v):
    v = float(v)
    return str(int(v)) if v == int(v) else repr(v)


def _expand(rule, custom, ug=None):
    ug = user_groups() if ug is None else ug
    van, items = list(rule.get("vanilla") or []), list(rule.get("items") or [])
    for name in rule.get("custom") or []:
        g = custom.get(name) or ug.get(name) or {}
        van += g.get("vanilla") or []
        items += g.get("items") or []
    return van, items


def build_lua(project, modid):
    """texto do Lua (ou None sem regras)."""
    loot = project.meta.get("loot") or {}
    rules = loot.get("rules") or []
    custom = loot.get("custom") or {}
    ug = user_groups()
    proc, fill, areas, repl, picks = [], [], [], [], []
    for r in rules:
        van, items = _expand(r, custom, ug)
        room, cont = r.get("room") or "all", r.get("container") or "all"
        if not van and not items:
            continue
        if room != "all" and room not in areas:
            areas.append(room)
        if r.get("replace") and (room, cont) not in repl:
            repl.append((room, cont))
        if r.get("pick") == "one" and van:       # como o vanilla: UMA lista sorteada (por peso) a cada rolagem
            w = r.get("weights") or {}
            picks.append((room, cont, [(v, w.get(v, 100)) for v in van], int(r.get("rolls") or 1)))
            van = []
        for v in van:
            proc.append((room, cont, v, int(r.get("rolls") or 1)))
        for it in items:
            it = norm_item(it)
            if it:
                fill.append((room, cont, it["item"], it["chance"], it["count"], it["cond"]))
    if not proc and not fill and not picks:
        return None
    L = [f"-- gerado pelo J' PZ MAP STUDIO para o mapa {modid}: soma aos spawns vanilla; regra com"
         " 'substituir' esvazia o container (removeAllItems) antes de sortear o loot dela.",
         "-- grupos vanilla: sorteio extra no OnFillContainer (ItemPickerJava.getItemContainer + doRollItem).",
         "-- itens avulsos: chance exata, quantidade e condicao.",
         'require "Items/Distributions"', 'require "Items/ProceduralDistributions"', 'require "Items/SuburbsDistributions"', "",
         f"local MOD = {_q(modid)}", 'local HID = "pzms_" .. MOD', "local AREAS = {"]
    L += [f"  {_q(a)}," for a in areas]
    L += ["}", "local PROC = {"]
    for a, b, v, n in proc:
        if "/" in v:
            dr, dc = v.split("/", 1)
            L.append(f"  {{ room = {_q(a)}, cont = {_q(b)}, droom = {_q(dr)}, dcont = {_q(dc)}, rolls = {n} }},")
        else:
            L.append(f"  {{ room = {_q(a)}, cont = {_q(b)}, list = {_q(v)}, rolls = {n} }},")
    for a, b, vs, n in picks:
        L.append(f"  {{ room = {_q(a)}, cont = {_q(b)}, rolls = {n}, pick = {{ "
                 + ", ".join(f"{{ {_q(v)}, {int(w)} }}" for v, w in vs) + " } },")
    L += ["}", "local REPL = {"]
    L += [f"  {{ room = {_q(a)}, cont = {_q(b)} }}," for a, b in repl]
    L += ["}", "local FILL = {"]
    L += [f"  {{ room = {_q(a)}, cont = {_q(b)}, item = {_q(c)}, chance = {_num_lua(e)}, count = {f}, cond = {g if g is not None else 'nil'} }},"
          for a, b, c, e, f, g in fill]
    L += ["}", "local SKIP = { " + ", ".join(f"[{_q(p)}] = true" for p in PSEUDO_ROOMS) + " }", r"""
local function post()
  local D = SuburbsDistributions or Distributions[1]
  if type(D) ~= "table" then return end
  -- area com nome proprio: sem sala na distribuicao o jogo nem dispara OnFillContainer
  for _, rn in ipairs(AREAS) do
    if D[rn] == nil then D[rn] = {} end
  end
  local PL = ProceduralDistributions and ProceduralDistributions.list or {}
  local names, seen = {}, {}
  local function need(n)
    if type(n) == "string" and PL[n] and not seen[n] then
      seen[n] = true
      table.insert(names, { name = n, min = 0, max = 1 })
    end
    return seen[n]
  end
  local function procOf(droom, dcont)
    local R = D[droom]
    local C = type(R) == "table" and R[dcont] or nil
    return type(C) == "table" and C.procedural and type(C.procList) == "table" and C.procList or nil
  end
  for _, p in ipairs(PROC) do
    if p.pick then
      -- uma lista por rolagem, sorteada por peso; "sala/container" entra com as listas dele (pesos do jogo)
      p.choices, p.weights, p.total = {}, {}, 0
      local function add(n, w)
        if need(n) and w > 0 then table.insert(p.choices, n); table.insert(p.weights, w); p.total = p.total + w end
      end
      for _, e in ipairs(p.pick) do
        local dr, dc = string.match(e[1], "^([%w_%-]+)/([%w_%-]+)$")
        if dr then
          for _, x in ipairs(procOf(dr, dc) or {}) do
            if type(x) == "table" then add(x.name, tonumber(x.weightChance) or 100) end
          end
        else
          add(e[1], e[2])
        end
      end
      p.ok = #p.choices > 0
    elseif p.list then
      p.ok = need(p.list)
    else
      local R = D[p.droom]
      local C = type(R) == "table" and R[p.dcont] or nil
      if type(C) == "table" then
        if C.procedural and type(C.procList) == "table" then
          p.choices = {}
          for _, e in ipairs(C.procList) do
            if type(e) == "table" and need(e.name) then table.insert(p.choices, e.name) end
          end
          p.ok = #p.choices > 0
        elseif C.items then
          p.ok = true
        end
      end
    end
    if not p.ok then print("[" .. MOD .. "] spawn: grupo vanilla nao encontrado: " .. tostring(p.list or p.droom and (p.droom .. "/" .. p.dcont) or "(sorteio)")) end
  end
  if #names > 0 then D[HID] = { g = { procedural = true, procList = names } } end
end
Events.OnPostDistributionMerge.Add(post)

local function match(r, roomName, containerType)
  return (r.room == "all" or r.room == roomName) and (r.cont == "all" or r.cont == containerType)
end

local function rollVanilla(p, container)
  local dist
  if p.list then
    dist = ItemPickerJava.getItemContainer(HID, "g", p.list, false)
  elseif p.total then
    local r, k = ZombRand(p.total), 1
    while k < #p.choices and r >= p.weights[k] do r = r - p.weights[k]; k = k + 1 end
    dist = ItemPickerJava.getItemContainer(HID, "g", p.choices[k], false)
  elseif p.choices then
    dist = ItemPickerJava.getItemContainer(HID, "g", p.choices[ZombRand(#p.choices) + 1], false)
  else
    dist = ItemPickerJava.getItemContainer(p.droom, p.dcont, "", false)
  end
  if dist then ItemPickerJava.doRollItem(dist, container, 0, nil, true, nil) end
end

local function addItems(f, container)
  if ZombRandFloat(0, 100) >= f.chance then return end
  for i = 1, f.count do
    local it = container:AddItem(f.item)
    if it and f.cond then
      local mx = it:getConditionMax()
      if mx and mx > 0 then it:setConditionNoSound(math.max(1, math.floor(mx * f.cond / 100))) end
    end
  end
end

local busy = false
local function onFill(roomName, containerType, container)
  if busy or SKIP[roomName] or not container or not instanceof(container, "ItemContainer") then return end
  busy = true
  local ok, err = pcall(function()
    for _, q in ipairs(REPL) do
      if match(q, roomName, containerType) then container:removeAllItems(); break end
    end
    for _, p in ipairs(PROC) do
      if p.ok and match(p, roomName, containerType) then
        for i = 1, p.rolls do rollVanilla(p, container) end
      end
    end
    for _, f in ipairs(FILL) do
      if match(f, roomName, containerType) then addItems(f, container) end
    end
  end)
  busy = false
  if not ok then print("[" .. MOD .. "] spawn: " .. tostring(err)) end
end
Events.OnFillContainer.Add(onFill)
"""]
    return "\n".join(L)


def export_lua(project, mod_root, modid):
    path = os.path.join(mod_root, "common", "media", "lua", "server", "Items", f"{modid}_Distributions.lua")
    txt = build_lua(project, modid)
    if txt is None:
        if os.path.exists(path):
            os.remove(path)
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)
    return path
