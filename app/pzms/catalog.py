"""Catalogo de predios vanilla: recorta os predios dos lotheaders/lotpacks da instalacao do jogo do usuario,
classifica por tipo (nomes das salas), deduplica e guarda prefabs + miniaturas no cache (nada e redistribuido).

Prefab (json gz): {"id","type","label","w","h","zmin","zmax","rooms":[[nome,z,[[x,y,w,h]]]],
                   "tiles":[nomes], "sq":[[x,y,z,[indices]]], "count", "src"}
Orientacoes (o): 0..3 = giro de 90 graus horario; +4 = espelhado na diagonal (troca x<->y) antes do giro.
O espelho (o=4) e exato inclusive no telhado; giros trocam paredes/portas/janelas/moveis pelo sprite equivalente,
mas telhado inclinado so existe com caida para Sul/Leste: nos giros sem equivalente ele vira telhado plano.
"""
import gzip
import hashlib
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor

from . import formats as F
from . import progress as PG

CS = 256
CATALOG_VER = 1

# ---------------------------------------------------------------- classificacao
TYPES = [
    ("casa", "Casas"), ("motel", "Hoteis e moteis"), ("loja", "Lojas"), ("comida", "Restaurantes e bares"),
    ("escritorio", "Escritorios e servicos"), ("saude", "Saude"), ("seguranca", "Policia, bombeiro e militar"),
    ("educacao", "Escolas"), ("igreja", "Igrejas"), ("industria", "Industria e galpoes"),
    ("rural", "Fazenda e rural"), ("lazer", "Lazer"), ("ruina", "Abandonados"), ("outro", "Outros"),
]
TYPE_NAMES = dict(TYPES)
NEUTRAL = {"bathroom", "closet", "hall", "hallway", "empty", "emptyoutside", "storage", "stairwell", "elevator",
           "corridor", "janitor", "breakroom", "lobby", "garbage", "attic", "balcony", "basement", "foyer",
           "changeroom", "lockerroom", "showers", "porch", "patio", "room1", "room2", "room3", "room4", "Empty"}
RULES = [  # (tipo, peso, prefixos/trechos) - primeira regra que casa ganha
    ("ruina", 3, ("derelict", "vacated", "drugshack", "druglab")),
    ("seguranca", 3, ("police", "prison", "fire", "army", "security", "swat", "ranger", "interrogation",
                      "evidence", "detective", "bunker", "oldarmy", "firearm", "killbox", "decontamination")),
    ("saude", 3, ("medical", "medclinic", "clinic", "hospital", "morgue", "dentist", "optometrist", "vet",
                  "pharmacy", "laboratory", "coroner", "oldmedical")),
    ("educacao", 3, ("classroom", "school", "university", "daycare", "elementary", "secondary", "library")),
    ("igreja", 3, ("church", "cultist")),
    ("motel", 3, ("motel", "hotel")),
    ("comida", 3, ("restaurant", "dining", "cafe", "bar", "diner", "pizza", "spiffo", "burger", "icecream",
                   "donut", "sushi", "chinese", "mexican", "italian", "seafood", "western", "jayschicken", "chili",
                   "deepfry", "crepe", "taco", "fishchips", "catfish", "foodcourt", "bakerykitchen", "hotdog",
                   "kitchen_", "barkitchen", "cafeteria", "beergarden", "juicestand")),
    ("lazer", 3, ("gym", "theatre", "arena", "bowling", "lasertag", "stripclub", "lapdance", "recreation",
                  "arcade", "pool", "sport", "boxing", "rollerrink", "musicstage", "stage", "backstage", "game",
                  "ballroom", "racetrack", "golf", "baseball", "fitness", "spa", "gallery", "museum", "cinema")),
    ("rural", 3, ("barn", "farm", "stable", "horse", "chicken", "pig", "kennel", "greenhouse", "hay", "shed",
                  "agriworker", "slaughter", "cattle", "egg", "potato", "produce", "woodshed")),
    ("industria", 3, ("warehouse", "factory", "industry", "storageunit", "shipping", "workshop", "mechanic",
                      "logging", "railroad", "metal", "welding", "construction", "bottling", "brewery",
                      "distillery", "plumber", "carpenter", "machinery", "power", "electricroom", "technical",
                      "serverroom", "aircraft", "boathouse", "traincar", "garbage", "jerky", "whittler", "knapping",
                      "blacksmith", "pottery", "tailor", "sewingroom", "printing", "newspaperprint")),
    ("loja", 3, ("store", "shop", "grocery", "gas", "mart", "butcher", "bakery", "pawn", "liquor", "movierental",
                 "florist", "zippee", "cornerstore", "carsupply", "jewelry", "clothes", "clothing", "hunting",
                 "fishing", "camping", "toystore", "candystore", "kitchenwares", "antique", "hairdresser",
                 "dealership", "camerastore", "comicstore", "musicstore", "pet", "fossoil", "aesthetic",
                 "generalstore", "departmentstore", "plazastore", "armysurplus", "wedding", "glassesstore",
                 "cdstore", "lighting", "toolstore", "post")),
    ("escritorio", 3, ("bank", "broadcasting", "meeting", "newsroom", "office", "communications", "studio",
                       "archive", "controlroom", "vault", "depositboxes", "mayor", "ticketoffice", "waitingroom",
                       "baggage", "contraband", "auction")),
    ("casa", 1, ("bedroom", "livingroom", "kitchen", "diningroom", "laundry", "garage", "kidsbedroom", "ww_",
                 "guestbedroom", "nursery", "pantry", "sunroom", "homecinema", "sewing", "photoroom", "darkroom",
                 "musicroom", "smokingroom", "bandlivingroom", "bandkitchen", "storage")),
]


def room_type(name):
    n = name.lower()
    if n in NEUTRAL:
        return None, 0
    for t, w, keys in RULES:
        if any(k in n for k in keys):
            return t, w
    return "outro", 1


def classify(rooms):
    """rooms: [[nome, z, rects]] -> (tipo, nome principal)."""
    score, top = {}, {}
    for name, _z, rects in rooms:
        t, w = room_type(name)
        if not t:
            continue
        a = sum(r[2] * r[3] for r in rects) * w
        score[t] = score.get(t, 0) + a
        if a > top.get(t, (0, ""))[0]:
            top[t] = (a, name)
    if not score:
        return "outro", rooms[0][0] if rooms else "?"
    t = max(score, key=score.get)
    return t, top[t][1]


def label_for(t, main, rooms, zmin, zmax):
    floors = len({z for _n, z, _r in rooms if z >= 0})
    base = len({z for _n, z, _r in rooms if z < 0})
    if t == "casa":
        beds = sum(1 for n, _z, _r in rooms if "bedroom" in n.lower())
        s = f"Casa {beds} quarto{'s' if beds != 1 else ''}" if beds else "Casa"
    else:
        s = main.replace("_", " ").capitalize()
    s += f" · {floors} andar{'es' if floors != 1 else ''}"
    if base:
        s += " + porao"
    return s


# ---------------------------------------------------------------- recorte (worker)
STRUCT = ("walls_", "roofs_", "fixtures_doors", "fixtures_windows", "fixtures_stairs", "fixtures_garage",
          "walls_garage", "fixtures_railings", "fixtures_roof", "location_")
_W = {"WallW", "DoorWallW", "WindowW", "doorW", "windowW", "attachedW", "WallWTrans", "HoppableW", "TallHoppableW"}
_N = {"WallN", "DoorWallN", "WindowN", "doorN", "windowN", "attachedN", "WallNTrans", "HoppableN", "TallHoppableN"}
_tiles = None


def _tiledefs(path):
    global _tiles
    if _tiles is None:
        with open(path, encoding="utf-8") as f:
            _tiles = json.load(f)
    return _tiles


def _side(props):
    if "WallNW" in props:
        return "NW"
    if any(k in props for k in _W):
        return "W"
    if any(k in props for k in _N):
        return "N"
    return ""


def _cut_cell(args):
    """recorta os predios de uma celula. Devolve lista de prefabs (sem dedupe)."""
    mapdir, cx, cy, tiles_path, pi, pn = args
    tdef = _tiledefs(tiles_path)
    hp = os.path.join(mapdir, f"{cx}_{cy}.lotheader")
    pp = os.path.join(mapdir, f"world_{cx}_{cy}.lotpack")
    PG.micro("predios", f"celula {cx},{cy}", f"{pi + 1}/{pn}", 0.0, worker=f"w{os.getpid()}")
    with open(hp, "rb") as f:
        h = F.read_header(f.read())
    blds = []
    for b in h.buildings:
        rooms = [h.rooms[i] for i in b if i < len(h.rooms)]
        rects = [r for rm in rooms for r in rm[2]]
        if not rects:
            continue
        x0 = min(r[0] for r in rects); y0 = min(r[1] for r in rects)
        x1 = max(r[0] + r[2] for r in rects); y1 = max(r[1] + r[3] for r in rects)
        if x0 <= 2 or y0 <= 2 or x1 >= CS - 2 or y1 >= CS - 2:
            continue                                  # cruza a borda da celula: fica fora (metade em outra celula)
        if (x1 - x0) * (y1 - y0) > 120 * 120:
            continue
        blds.append((rooms, x0, y0, x1, y1))
    if not blds:
        return []
    chunks = set()
    for _r, x0, y0, x1, y1 in blds:
        for x in range((x0 - 1) >> 3, ((x1 + 1) >> 3) + 1):
            for y in range((y0 - 1) >> 3, ((y1 + 1) >> 3) + 1):
                if 0 <= x < 32 and 0 <= y < 32:
                    chunks.add(x * 32 + y)
    with open(pp, "rb") as f:
        sq = F.read_pack(f.read(), h.zmin, h.zmax, h.tiles, chunks)
    out = []
    for k, (rooms, x0, y0, x1, y1) in enumerate(blds):
        inside = {}
        for name, z, rects, _o in rooms:
            for rx, ry, rw, rh in rects:
                for x in range(rx, rx + rw):
                    for y in range(ry, ry + rh):
                        inside[(x, y, z)] = True
        zs = [z for _n, z, _r, _o in rooms]
        zlo, zhi = min(zs), min(h.zmax, max(zs) + 2)
        keep = {}
        for z in range(zlo, zhi + 1):
            for x in range(x0 - 1, x1 + 2):
                for y in range(y0 - 1, y1 + 2):
                    t = sq.get((x, y, z))
                    if not t:
                        continue
                    ring = x < x0 or y < y0 or x >= x1 or y >= y1
                    if (x, y, z) in inside:
                        sel = t
                    else:
                        sel = []
                        for n in t:
                            if not n.startswith(STRUCT) and not (z > 0 and n.startswith("floors_")):
                                continue
                            if ring:
                                if n.startswith("roofs_"):
                                    pass
                                elif x == x1 and y < y1 and y >= y0 and _side(tdef.get(n, {})) == "W":
                                    pass
                                elif y == y1 and x < x1 and x >= x0 and _side(tdef.get(n, {})) == "N":
                                    pass
                                else:
                                    continue
                            sel.append(n)
                    if sel:
                        keep[(x, y, z)] = sel
        if not keep:
            continue
        mx = min(p[0] for p in keep); my = min(p[1] for p in keep)
        names = sorted({n for v in keep.values() for n in v})
        ix = {n: i for i, n in enumerate(names)}
        sqs = sorted([x - mx, y - my, z, [ix[n] for n in v]] for (x, y, z), v in keep.items())
        rl = sorted([n, z, sorted([rx - mx, ry - my, rw, rh] for rx, ry, rw, rh in rects)] for n, z, rects, _o in rooms)
        key = hashlib.sha1(json.dumps([names, sqs, rl], separators=(",", ":")).encode()).hexdigest()[:16]
        t, main = classify(rl)
        out.append({"id": key, "type": t, "main": main, "rooms": rl, "tiles": names, "sq": sqs,
                    "w": max(p[0] for p in sqs) + 1, "h": max(p[1] for p in sqs) + 1,
                    "zmin": min(p[2] for p in sqs), "zmax": max(p[2] for p in sqs),
                    "src": [cx * CS + x0, cy * CS + y0]})
        PG.micro("predios", f"celula {cx},{cy}", f"{pi + 1}/{pn} predio {k + 1}/{len(blds)}",
                 (k + 1) / len(blds), worker=f"w{os.getpid()}")
    return out


# ---------------------------------------------------------------- build / indice
def root(cache_root):
    return os.path.join(cache_root, "catalog")


def is_ready(cache_root):
    try:
        with open(os.path.join(root(cache_root), "index.json"), encoding="utf-8") as f:
            return json.load(f).get("ver") == CATALOG_VER
    except (OSError, ValueError):
        return False


def map_dirs(media):
    md = os.path.join(media, "maps")
    out = []
    for d in sorted(os.listdir(md)) if os.path.isdir(md) else []:
        p = os.path.join(md, d)
        try:
            if any(f.endswith(".lotheader") for f in os.listdir(p)):
                out.append(p)
        except OSError:
            pass
    return out


def build(media, cache_root, progress=None, jobs=None):
    say = progress or (lambda f, m: None)
    t0 = time.time()
    croot = root(cache_root)
    pdir = os.path.join(croot, "p")
    os.makedirs(pdir, exist_ok=True)
    tiles_path = os.path.join(cache_root, "tiles.json")
    tasks = []
    for d in map_dirs(media):
        for fn in os.listdir(d):
            if fn.endswith(".lotheader"):
                cx, cy = map(int, fn[:-10].split("_"))
                tasks.append((d, cx, cy))
    tasks.sort()
    n = len(tasks)
    tasks = [(d, cx, cy, tiles_path, i, n) for i, (d, cx, cy) in enumerate(tasks)]
    say(0.02, f"{n} celulas vanilla")
    PG.mark("predios", 0, n, f"recortando predios de {n} celulas")
    found = {}
    total = 0
    jobs = jobs or max(1, min(8, (os.cpu_count() or 2) - 1))
    with ProcessPoolExecutor(jobs) as ex:
        for i, res in enumerate(ex.map(_cut_cell, tasks, chunksize=8)):
            for b in res:
                total += 1
                e = found.get(b["id"])
                if e:
                    e["count"] += 1
                    continue
                b["count"] = 1
                found[b["id"]] = b
            if i % 16 == 0 or i == n - 1:
                PG.mark("predios", i + 1, n, f"{i + 1}/{n} celulas · {len(found)} predios unicos ({total} no mapa)")
                say(0.02 + 0.8 * (i + 1) / n, f"recortando predios {i + 1}/{n}")
    PG.finish("predios", f"{len(found)} predios unicos de {total}")
    items = []
    k = 0
    for b in found.values():
        b["label"] = label_for(b["type"], b.pop("main"), b["rooms"], b["zmin"], b["zmax"])
        with gzip.open(os.path.join(pdir, b["id"] + ".json.gz"), "wt", encoding="utf-8", compresslevel=5) as f:
            json.dump(b, f, separators=(",", ":"))
        items.append({k2: b[k2] for k2 in ("id", "type", "label", "w", "h", "zmin", "zmax", "count", "src")}
                     | {"rooms": sorted({r[0] for r in b["rooms"]})})
        k += 1
        if k % 200 == 0:
            PG.mark("gravar", k, len(found), f"gravando prefabs {k}/{len(found)}")
            say(0.82 + 0.16 * k / len(found), f"gravando prefabs {k}/{len(found)}")
    PG.finish("gravar")
    items.sort(key=lambda it: (it["type"], -it["count"], it["label"]))
    idx = {"ver": CATALOG_VER, "types": [{"key": t, "name": nm, "count": sum(1 for it in items if it["type"] == t)}
                                         for t, nm in TYPES], "items": items, "secs": round(time.time() - t0, 1)}
    tmp = os.path.join(croot, "index.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, separators=(",", ":"))
    os.replace(tmp, os.path.join(croot, "index.json"))
    PG.log(f"catalogo: {len(items)} predios unicos de {total} em {idx['secs']} s")
    return idx


class Catalog:
    def __init__(self, cache_root, assets):
        self.root = root(cache_root)
        self.assets = assets
        with open(os.path.join(self.root, "index.json"), encoding="utf-8") as f:
            self.index = json.load(f)
        self.byid = {it["id"]: it for it in self.index["items"]}
        self._pref = {}
        self.rot = Rotator(assets.tiles)

    def prefab(self, pid):
        if pid not in self.byid:
            raise KeyError(pid)
        p = self._pref.get(pid)
        if p is None:
            with gzip.open(os.path.join(self.root, "p", pid + ".json.gz"), "rt", encoding="utf-8") as f:
                p = json.load(f)
            if len(self._pref) > 64:
                self._pref.clear()
            self._pref[pid] = p
        return p

    def oriented(self, pid, o=0):
        """prefab na orientacao o: {"w","h","sq":[[x,y,z,[nomes]]],"rooms":[[nome,z,[[x,y,w,h]]]],"approx":n}."""
        p = self.prefab(pid)
        sq = [[x, y, z, [p["tiles"][i] for i in t]] for x, y, z, t in p["sq"]]
        return self.rot.transform(sq, p["rooms"], p["w"], p["h"], int(o) % 8)

    def thumb(self, pid, size=(176, 132)):
        path = os.path.join(self.root, "t", pid + ".png")
        if not os.path.exists(path):
            from . import render
            p = self.prefab(pid)
            sq = {(x, y, z): [p["tiles"][i] for i in t] for x, y, z, t in p["sq"] if z >= 0}
            im = render.render(self.assets, sq, fit=size)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f"{path}.{os.getpid()}.tmp"
            im.save(tmp, "PNG", optimize=True)
            os.replace(tmp, path)
        with open(path, "rb") as f:
            return f.read()


# ---------------------------------------------------------------- orientacao
FACE = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}
FACE_INV = {v: k for k, v in FACE.items()}


def _lin(o):
    """parte linear (matriz 2x2 como funcao) da orientacao o: espelho diagonal (bit 4) e depois giro horario."""
    def f(u, v):
        if o & 4:
            u, v = v, u
        for _ in range(o & 3):
            u, v = -v, u
        return u, v
    return f


class Rotator:
    """troca cada sprite pelo equivalente na nova orientacao, usando as propriedades dos tiledefs."""

    def __init__(self, tiles):
        self.t = tiles
        self.flip = {}          # W <-> N (paredes, portas, janelas, anexos)
        self.corner = {}        # NW -> (W, N)
        self.join = {}          # (W, N) -> NW
        self.face = {}          # (sheet, nome, grupo) -> {facing: {(gx,gy): sprite}}
        self.faceof = {}        # sprite -> (chave, facing, (gx,gy))
        side = {}
        for n, p in tiles.items():
            sheet, _, i = n.rpartition("_")
            if not i.isdigit():
                continue
            i = int(i)
            s = _side(p)
            if s in ("W", "N"):
                side[(sheet, i)] = (s, p.get("CustomName", ""))
            if "WallNW" in p and "CornerWestWall" in p and "CornerNorthWall" in p:
                self.corner[n] = (p["CornerWestWall"], p["CornerNorthWall"])
                self.join[(p["CornerWestWall"], p["CornerNorthWall"])] = n
            f = p.get("Facing")
            if f in FACE and "CustomName" in p:
                gp = tuple(int(c) for c in p.get("SpriteGridPos", "0,0").split(","))
                key = (sheet, p["CustomName"], p.get("GroupName", ""))
                self.face.setdefault(key, {}).setdefault(f, {})[gp] = n
                self.faceof[n] = (key, f, gp)
        # par W<->N: vizinho imediato (W em i, N em i+1 e o padrao das folhas), senao o mais proximo com o mesmo nome
        for (sheet, i), (s, cn) in side.items():
            o = "N" if s == "W" else "W"
            step = 1 if s == "W" else -1
            j = None
            base, k = divmod(i, 32)
            r, c = divmod(k, 8)
            if sheet.startswith(("walls_exterior_roofs", "roofs_")) and r in (0, 1, 3) and c <= 5 \
                    and side.get((sheet, base * 32 + r * 8 + 5 - c), ("", ""))[0] == o:
                j = base * 32 + r * 8 + 5 - c          # oitao: W1 W2 W3 N3 N2 N1 (mesmo padrao do telhado)
            elif side.get((sheet, i + step), ("", ""))[0] == o:
                j = i + step
            else:
                for d in range(1, 17):
                    for k in (i + step * d, i - step * d):
                        e = side.get((sheet, k))
                        if e and e[0] == o and e[1] == cn:
                            j = k
                            break
                    if j is not None:
                        break
            if j is not None:
                self.flip[f"{sheet}_{i}"] = f"{sheet}_{j}"

    # telhado: so ha caida S/E; espelho diagonal troca colunas 0..5 (S1..S3 <-> E3..E1), 6<->7, 20<->21, 22<->23
    @staticmethod
    def roof_mirror(n):
        sheet, _, i = n.rpartition("_")
        i = int(i)
        base, k = divmod(i, 32)
        r, c = divmod(k, 8)
        if r in (0, 1, 3) and c <= 5:
            c = 5 - c
        elif r in (0,) and c in (6, 7):
            c = 13 - c
        elif r == 2 and c in (4, 5, 6, 7):
            c = {4: 5, 5: 4, 6: 7, 7: 6}[c]
        elif r == 3 and c in (6, 7):
            c = 13 - c
        return f"{sheet}_{base * 32 + r * 8 + c}"

    def roof_flat(self, n):
        sheet, _, i = n.rpartition("_")
        base = int(i) // 32 * 32
        cand = f"{sheet}_{base + 22}"
        return cand if cand in self.t else None

    def transform(self, sq, rooms, w, h, o):
        if o == 0:
            return {"w": w, "h": h, "sq": sq, "rooms": rooms, "approx": 0}
        L = _lin(o)
        # caixa transformada: cantos de [0,w]x[0,h]
        cs = [L(u, v) for u, v in ((0, 0), (w, 0), (0, h), (w, h))]
        ox, oy = -min(c[0] for c in cs), -min(c[1] for c in cs)
        nw, nh = max(c[0] for c in cs) + ox, max(c[1] for c in cs) + oy

        def pt(u, v):
            a, b = L(u, v)
            return a + ox, b + oy

        lin = L(1, 0), L(0, 1)
        exact_roof = (o == 4)                      # so o espelho preserva caida S/E
        out = {}
        approx = 0

        def put(x, y, z, n):
            out.setdefault((x, y, z), []).append(n)

        for x, y, z, names in sq:
            for n in names:
                p = self.t.get(n, {})
                s = _side(p)
                if s == "NW" and n in self.corner:
                    parts = [(self.corner[n][0], "W"), (self.corner[n][1], "N")]
                elif s in ("W", "N"):
                    parts = [(n, s)]
                elif "WallSE" in p:
                    # pilar no ponto do canto NW do quadrado
                    a, b = pt(x, y)
                    put(round(a), round(b), z, n)
                    continue
                else:
                    parts = None
                if parts:
                    for m, side in parts:
                        mx, my = (x, y + 0.5) if side == "W" else (x + 0.5, y)
                        a, b = pt(mx, my)
                        if abs(a - round(a)) < 1e-6:           # cai numa linha vertical -> parede W
                            ns, nx, ny = "W", round(a), int(b - 0.5)
                        else:
                            ns, nx, ny = "N", int(a - 0.5), round(b)
                        if ns != side:
                            m2 = self.flip.get(m)
                            if not m2:
                                approx += 1
                                m2 = m
                            m = m2
                        put(nx, ny, z, m)
                    continue
                a, b = pt(x + 0.5, y + 0.5)
                nx, ny = int(a - 0.5), int(b - 0.5)
                if n.startswith("roofs_") and "RoofGroup" in p:
                    if exact_roof:
                        m = self.roof_mirror(n)
                        put(nx, ny, z, m if m in self.t else n)
                    else:
                        f = self.roof_flat(n) if ("BlockRain" in p or "solidfloor" in p) else None
                        approx += 1
                        if f:
                            put(nx, ny, z, f)
                    continue
                fo = self.faceof.get(n)
                if fo:
                    key, f, gp = fo
                    nf = FACE_INV[L(*FACE[f])]
                    grp = self.face[key]
                    gw = max(g[0] for g in grp[f]) + 1
                    gh = max(g[1] for g in grp[f]) + 1
                    ga, gb = L(gp[0] + 0.5, gp[1] + 0.5)
                    gc = [L(u, v) for u, v in ((0, 0), (gw, 0), (0, gh), (gw, gh))]
                    ngp = (int(ga - min(c[0] for c in gc)), int(gb - min(c[1] for c in gc)))
                    m = grp.get(nf, {}).get(ngp) or (grp.get(nf, {}).get((0, 0)) if len(grp.get(nf, {})) == 1 else None)
                    if m:
                        put(nx, ny, z, m)
                        continue
                    approx += 1
                put(nx, ny, z, n)
        # junta W+N do mesmo quadrado num canto NW quando existir
        for k, names in out.items():
            ws = [n for n in names if _side(self.t.get(n, {})) == "W" and "wall" in self.t.get(n, {})]
            ns = [n for n in names if _side(self.t.get(n, {})) == "N" and "wall" in self.t.get(n, {})]
            for a in ws:
                for b in ns:
                    j = self.join.get((a, b))
                    if j and a in names and b in names:
                        i = names.index(a)
                        names[i] = j
                        names.remove(b)
        # andar: quadrados ordenados, pisos primeiro (mesma ordem relativa do original)
        nsq = [[x, y, z, v] for (x, y, z), v in sorted(out.items())]
        nrooms = []
        for name, z, rects in rooms:
            nr = []
            for rx, ry, rw, rh in rects:
                c = [pt(u, v) for u, v in ((rx, ry), (rx + rw, ry + rh))]
                ax, bx = sorted((c[0][0], c[1][0]))
                ay, by = sorted((c[0][1], c[1][1]))
                nr.append([round(ax), round(ay), round(bx - ax), round(by - ay)])
            nrooms.append([name, z, nr])
        return {"w": round(nw), "h": round(nh), "sq": nsq, "rooms": nrooms, "approx": approx}
