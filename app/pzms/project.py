"""Projeto de mapa: celulas no formato do jogo (lotheader/lotpack), edicao por quadrado e desfazer/refazer.

Pasta do projeto:
  project.json                {name, cells:[[cx,cy]...], spawn:[x,y,z], ...}
  cells/<cx>_<cy>.lotheader   celula em formato B42 (carregada sob demanda, gravada so quando suja)
  cells/world_<cx>_<cy>.lotpack
Coordenadas de mundo: wx = cx*256 + x.  Chunk 8x8: ci = ccx*32 + ccy (ordem do lotpack).
"""
import json
import os
import random
import struct
import threading
import time

from . import formats as F

CS, CH, NCH = F.CS, F.CH, F.NCH
GRASS = ["blends_natural_01_32", "blends_natural_01_37", "blends_natural_01_38", "blends_natural_01_39"]  # B42: floors_exterior_natural_01_0..7 nao tem sprite


# ---------------------------------------------------------------- classificacao de tiles
class Kinds:
    """camada de cada tile pelas propriedades do tiles.json: floor, overlay, wall, attach, object."""

    def __init__(self, tiles):
        self.tiles = tiles
        self._c = {}

    def props(self, n):
        return self.tiles.get(n) or {}

    def kind(self, n):
        k = self._c.get(n)
        if k is None:
            p = self.props(n)
            if "solidfloor" in p:
                k = "floor"
            elif "FloorOverlay" in p or ("attachedFloor" in p and "vegitation" not in p):
                k = "overlay"
            elif "wall" in p or any(w in p for w in ("WallW", "WallN", "WallNW", "WallSE", "DoorWallW", "DoorWallN")):
                k = "wall"
            elif "WallOverlay" in p or "attachedW" in p or "attachedN" in p or "doorW" in p or "doorN" in p \
                    or "windowW" in p or "windowN" in p:
                k = "attach"
            else:
                k = "object"
            self._c[n] = k
        return k

    def sides(self, n):
        """lados de parede ocupados: subconjunto de {'W','N'} ('SE' = pilar)."""
        p = self.props(n)
        if "WallNW" in p:
            return {"W", "N"}
        s = set()
        if any(k in p for k in ("WallW", "DoorWallW", "WindowW", "doorW", "windowW", "attachedW")):
            s.add("W")
        if any(k in p for k in ("WallN", "DoorWallN", "WindowN", "doorN", "windowN", "attachedN")):
            s.add("N")
        if "WallSE" in p:
            s.add("SE")
        return s


ORDER = {"floor": 0, "overlay": 1, "wall": 2, "attach": 3, "object": 4}


# ---------------------------------------------------------------- celula
class Cell:
    def __init__(self, cx, cy):
        self.cx, self.cy = cx, cy
        self.sq = {}              # (x, y, z) local -> [nomes]
        self.rooms = []           # [nome, z, [(x,y,w,h)], [(tipo,x,y)]]
        self.buildings = []       # [[indices de room]]
        self.density = bytes(1024)
        self.dirty = False
        self.ver = {}             # ci -> versao (sobe a cada mudanca no chunk)

    @staticmethod
    def blank(cx, cy, ground=True, seed=0):
        c = Cell(cx, cy)
        if ground:
            r = random.Random(seed ^ (cx * 7919 + cy))
            for x in range(CS):
                for y in range(CS):
                    c.sq[(x, y, 0)] = [GRASS[r.randrange(len(GRASS)) if r.random() < 0.35 else 0]]
        c.dirty = True
        return c

    def touch(self, x, y):
        ci = (x // CH) * NCH + (y // CH)
        self.ver[ci] = self.ver.get(ci, 0) + 1
        self.dirty = True

    def zrange(self):
        zs = [k[2] for k in self.sq]
        for r in self.rooms:
            zs.append(r[1])
        return (min(zs), max(zs)) if zs else (0, 0)

    def to_bytes(self):
        h = F.Header()
        idx = {}
        sq = {}
        for k, v in self.sq.items():
            if v:
                sq[k] = [idx.setdefault(n, len(idx)) for n in v]
        h.tiles = list(idx)
        h.zmin, h.zmax = self.zrange()
        h.rooms = [[r[0], r[1], [tuple(t) for t in r[2]], [tuple(t) for t in r[3]]] for r in self.rooms]
        h.buildings = [list(b) for b in self.buildings]
        h.density = self.density
        return F.write_header(h), F.write_pack(sq, h.zmin, h.zmax)

    @staticmethod
    def from_files(cx, cy, hp, pp):
        h, sq = F.read_cell_files(hp, pp)
        c = Cell(cx, cy)
        c.sq = {k: list(v) for k, v in sq.items() if v}
        c.rooms = [[r[0], r[1], [list(t) for t in r[2]], [list(t) for t in r[3]]] for r in h.rooms]
        c.buildings = [list(b) for b in h.buildings]
        c.density = h.density
        return c


# ---------------------------------------------------------------- projeto
class Project:
    MAX_UNDO = 300

    def __init__(self, path, kinds):
        self.path = path
        self.kinds = kinds
        self.meta = {}
        self.cells = {}           # (cx, cy) -> Cell carregada
        self.cellset = set()
        self.undo, self.redo = [], []
        self.lock = threading.RLock()
        self.saved_at = 0
        self.meta_dirty = False

    # ----- arquivo
    @property
    def cdir(self):
        return os.path.join(self.path, "cells")

    @staticmethod
    def create(path, name, cx0, cy0, w, h, kinds, ground=True):
        os.makedirs(os.path.join(path, "cells"), exist_ok=True)
        p = Project(path, kinds)
        p.meta = {"name": name, "format": 1, "created": time.time(), "cells": [],
                  "spawn": [cx0 * CS + w * CS // 2, cy0 * CS + h * CS // 2, 0],
                  "mapid": "".join(ch for ch in name if ch.isalnum()) or "MeuMapa"}
        for cx in range(cx0, cx0 + w):
            for cy in range(cy0, cy0 + h):
                p.cells[(cx, cy)] = Cell.blank(cx, cy, ground)
                p.cellset.add((cx, cy))
        p.save()
        return p

    @staticmethod
    def open(path, kinds):
        p = Project(path, kinds)
        with open(os.path.join(path, "project.json"), encoding="utf-8") as f:
            p.meta = json.load(f)
        p.cellset = {tuple(c) for c in p.meta.get("cells", [])}
        return p

    def save(self):
        with self.lock:
            os.makedirs(self.cdir, exist_ok=True)
            for (cx, cy), c in self.cells.items():
                if c.dirty:
                    hb, pb = c.to_bytes()
                    for fn, data in ((f"{cx}_{cy}.lotheader", hb), (f"world_{cx}_{cy}.lotpack", pb)):
                        tmp = os.path.join(self.cdir, fn + ".tmp")
                        with open(tmp, "wb") as f:
                            f.write(data)
                        os.replace(tmp, os.path.join(self.cdir, fn))
                    c.dirty = False
            self.meta["cells"] = sorted([list(c) for c in self.cellset])
            tmp = os.path.join(self.path, "project.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.meta, f, indent=1)
            os.replace(tmp, os.path.join(self.path, "project.json"))
            self.saved_at = time.time()
            self.meta_dirty = False
            # descarrega celulas limpas se houver muitas na memoria
            if len(self.cells) > 24:
                for k in [k for k, c in self.cells.items() if not c.dirty][:len(self.cells) - 24]:
                    del self.cells[k]

    def dirty(self):
        return self.meta_dirty or any(c.dirty for c in self.cells.values())

    def cell(self, cx, cy, create=False):
        k = (cx, cy)
        c = self.cells.get(k)
        if c is None:
            if k in self.cellset:
                hp = os.path.join(self.cdir, f"{cx}_{cy}.lotheader")
                pp = os.path.join(self.cdir, f"world_{cx}_{cy}.lotpack")
                c = Cell.from_files(cx, cy, hp, pp) if os.path.exists(hp) else Cell.blank(cx, cy)
            elif create:
                c = Cell.blank(cx, cy)
                self.cellset.add(k)
            else:
                return None
            self.cells[k] = c
        return c

    def bounds(self):
        if not self.cellset:
            return 0, 0, 1, 1
        xs = [c[0] for c in self.cellset]; ys = [c[1] for c in self.cellset]
        return min(xs), min(ys), max(xs) + 1, max(ys) + 1

    # ----- leitura
    def get(self, wx, wy, z):
        c = self.cell(wx // CS, wy // CS)
        return list(c.sq.get((wx % CS, wy % CS, z), [])) if c else []

    def chunk_blob(self, cx, cy, chunks=None):
        """binario de chunks para o cliente: JSON (nomes, versoes) + Int32 [x,y,z,n,idx...]."""
        c = self.cell(cx, cy)
        if c is None:
            return None
        names, idx, data, vers = [], {}, [], {}
        want = set(chunks) if chunks is not None else None
        for ci in (sorted(want) if want is not None else range(NCH * NCH)):
            vers[ci] = c.ver.get(ci, 0)
        keys = c.sq.keys() if want is None else [k for k in c.sq if (k[0] // CH) * NCH + k[1] // CH in want]
        for k in keys:
            v = c.sq[k]
            if not v:
                continue
            data += [k[0], k[1], k[2], len(v)]
            for n in v:
                i = idx.get(n)
                if i is None:
                    i = idx[n] = len(names); names.append(n)
                data.append(i)
        rooms = [{"name": r[0], "z": r[1], "rects": r[2]} for r in c.rooms]
        head = json.dumps({"cx": cx, "cy": cy, "names": names, "ver": vers, "rooms": rooms,
                           "full": want is None}).encode()
        pad = (-(4 + len(head))) % 4
        head += b" " * pad
        return struct.pack("<I", len(head)) + head + struct.pack(f"<{len(data)}i", *data)

    # ----- edicao
    def _set(self, wx, wy, z, tiles, changed):
        cx, cy = wx // CS, wy // CS
        c = self.cell(cx, cy, create=True)
        k = (wx % CS, wy % CS, z)
        if tiles:
            c.sq[k] = list(tiles)
        else:
            c.sq.pop(k, None)
        c.touch(k[0], k[1])
        changed.setdefault((cx, cy), set()).add((k[0] // CH) * NCH + k[1] // CH)

    def layered(self, cur, tile, mode="paint"):
        """nova lista de tiles do quadrado ao aplicar 'tile' (pintar) respeitando as camadas."""
        K = self.kinds
        kd = K.kind(tile)
        out = list(cur)
        if kd == "floor":
            out = [t for t in out if K.kind(t) not in ("floor", "overlay")]
            out.insert(0, tile)
            return out
        if tile in out:
            return out
        if kd == "overlay":
            pass
        elif kd == "wall":
            sd = K.sides(tile)
            nw = []
            for t in out:
                if K.kind(t) != "wall":
                    nw.append(t); continue
                ts = K.sides(t)
                if not (ts & sd):
                    nw.append(t)
                elif ts == {"W", "N"} and len(sd) == 1:   # canto: mantem o lado que sobra
                    p = K.props(t)
                    keep = p.get("CornerNorthWall") if sd == {"W"} else p.get("CornerWestWall")
                    if keep:
                        nw.append(keep)
            out = nw
        elif kd == "object":
            # objeto do mesmo grupo e lado (moveis de varias partes) substitui
            p = K.props(tile)
            g = p.get("GroupName"), p.get("CustomName")
            if g != (None, None):
                out = [t for t in out if not (K.kind(t) == "object" and
                                              (K.props(t).get("GroupName"), K.props(t).get("CustomName")) == g
                                              and K.props(t).get("SpriteGridPos") == p.get("SpriteGridPos"))]
        out.append(tile)
        out.sort(key=lambda t: ORDER[K.kind(t)])           # sort estavel
        return out

    def erase(self, cur, what="top", floor=True):
        K = self.kinds
        if not cur:
            return cur
        if not floor:                                       # preserva o chao (piso + camadas de mistura)
            base = [t for t in cur if K.kind(t) in ("floor", "overlay")]
            rest = [t for t in cur if K.kind(t) not in ("floor", "overlay")]
            return base + (self.erase(rest, what) if rest else [])
        if what == "all":
            return []
        if what == "objects":
            return [t for t in cur if K.kind(t) in ("floor", "overlay")]
        if what == "walls":
            return [t for t in cur if K.kind(t) not in ("wall", "attach")]
        out = list(cur)
        out.pop()                                           # topo
        return out

    def apply(self, ops, label="edit", stroke=None):
        """ops: [{"x","y","z", "tile"} | {"x","y","z","erase": modo} | {"x","y","z","remove":[tiles]} | {"x","y","z","set":[...]}].
        Devolve {(cx,cy): {ci}} das mudancas; empilha no desfazer."""
        with self.lock:
            rec = {}
            changed = {}
            for op in ops:
                wx, wy, z = int(op["x"]), int(op["y"]), int(op.get("z", 0))
                if (wx // CS, wy // CS) not in self.cellset and not op.get("grow"):
                    continue
                cur = self.get(wx, wy, z)
                if "set" in op:
                    new = list(op["set"])
                elif "erase" in op:
                    new = self.erase(cur, op["erase"], op.get("floor", True))
                elif "remove" in op:                       # pincel/area no modo apagar: tira so esses tiles
                    rm = set(op["remove"])
                    new = [t for t in cur if t not in rm]
                else:
                    new = self.layered(cur, op["tile"])
                if new == cur:
                    continue
                key = (wx, wy, z)
                if key not in rec:
                    rec[key] = cur
                self._set(wx, wy, z, new, changed)
            if not rec:
                return {}
            last = self.undo[-1] if self.undo else None
            if stroke and last and last.get("stroke") == stroke and not self.redo:
                # mesmo arraste do pincel: junta no comando anterior (um desfazer so)
                idx = {k: i for i, (k, _o, _n) in enumerate(last["sq"])}
                for k, old in rec.items():
                    if k in idx:
                        i = idx[k]
                        last["sq"][i] = (k, last["sq"][i][1], self.get(*k))
                    else:
                        last["sq"].append((k, old, self.get(*k)))
                return changed
            cmd = {"label": label, "sq": [(k, old, self.get(*k)) for k, old in rec.items()], "rooms": {}, "stroke": stroke}
            self._push(cmd)
            return changed

    def _push(self, cmd):
        self.undo.append(cmd)
        del self.undo[:-self.MAX_UNDO]
        self.redo.clear()

    def _replay(self, cmd, forward):
        changed = {}
        for k, old, new in cmd["sq"]:
            self._set(*k, new if forward else old, changed)
        for ck, (old, new) in cmd["rooms"].items():
            c = self.cell(*ck, create=True)
            c.rooms, c.buildings = [json.loads(json.dumps(x)) for x in (new if forward else old)]
            c.dirty = True
            changed.setdefault(ck, set()).add(-1)
        for ck, (old, new) in cmd.get("density", {}).items():       # zumbis: 1024 bytes por celula
            c = self.cell(*ck, create=True)
            c.density = bytearray(new if forward else old); c.dirty = True
            changed.setdefault(ck, set()).add(-2)
        for key, (old, new) in cmd.get("meta", {}).items():         # loot, zonas, spawns... (json)
            v = json.loads(new if forward else old)
            if v is None:
                self.meta.pop(key, None)
            else:
                self.meta[key] = v
            self.meta_dirty = True
        return changed

    def push_cmd(self, label, density=None, meta=None):
        """registra comando de undo generico. density={(cx,cy): (old_bytes, new_bytes)} ja aplicado;
        meta={chave: novo_valor} -> aplica e guarda o antigo."""
        with self.lock:
            cmd = {"label": label, "sq": [], "rooms": {}}
            if density:
                cmd["density"] = {ck: (bytes(o), bytes(n)) for ck, (o, n) in density.items()}
                for ck, (_o, n) in density.items():
                    c = self.cell(*ck, create=True); c.density = bytearray(n); c.dirty = True
            if meta:
                cmd["meta"] = {k: (json.dumps(self.meta.get(k)), json.dumps(v)) for k, v in meta.items()}
                for k, v in meta.items():
                    self.meta[k] = v
                self.meta_dirty = True
            self._push(cmd)

    def do_undo(self):
        with self.lock:
            if not self.undo:
                return None
            cmd = self.undo.pop(); self.redo.append(cmd)
            return self._replay(cmd, False), cmd["label"]

    def do_redo(self):
        with self.lock:
            if not self.redo:
                return None
            cmd = self.redo.pop(); self.undo.append(cmd)
            return self._replay(cmd, True), cmd["label"]

    # ----- salas e predios
    def _room_snapshot(self, ck):
        c = self.cell(*ck, create=True)
        return json.loads(json.dumps([c.rooms, c.buildings]))

    def add_building(self, rooms, label="predio", sq_ops=None, join=None):
        """rooms: [{"name","z","rects":[(wx,wy,w,h) mundo]}] -> um predio (dividido por celula).
        sq_ops opcionais entram no mesmo passo de desfazer."""
        with self.lock:
            before = {}
            changed = {}
            per = {}
            for r in rooms:
                for (x, y, w, h) in r["rects"]:
                    for cx in range(x // CS, (x + w - 1) // CS + 1):
                        for cy in range(y // CS, (y + h - 1) // CS + 1):
                            if (cx, cy) not in self.cellset:
                                continue
                            ax0, ay0 = max(x, cx * CS), max(y, cy * CS)
                            ax1, ay1 = min(x + w, (cx + 1) * CS), min(y + h, (cy + 1) * CS)
                            if ax1 > ax0 and ay1 > ay0:
                                per.setdefault((cx, cy), {}).setdefault((r["name"], r["z"]), []).append(
                                    [ax0 - cx * CS, ay0 - cy * CS, ax1 - ax0, ay1 - ay0])
            for ck, rs in per.items():
                before[ck] = self._room_snapshot(ck)
                c = self.cell(*ck)
                b = []
                for (name, z), rects in rs.items():
                    b.append(len(c.rooms))
                    c.rooms.append([name, z, rects, []])
                if join and join[0] == ck and join[1] is not None and join[1] < len(c.buildings):
                    c.buildings[join[1]].extend(b)
                else:
                    c.buildings.append(b)
                c.dirty = True
                changed.setdefault(ck, set()).add(-1)
            sqrec = {}
            for op in sq_ops or []:
                wx, wy, z = op["x"], op["y"], op.get("z", 0)
                if (wx // CS, wy // CS) not in self.cellset:
                    continue
                cur = self.get(wx, wy, z)
                new = list(op["set"]) if "set" in op else self.layered(cur, op["tile"])
                if new != cur:
                    sqrec.setdefault((wx, wy, z), cur)
                    self._set(wx, wy, z, new, changed)
            cmd = {"label": label, "sq": [(k, old, self.get(*k)) for k, old in sqrec.items()],
                   "rooms": {ck: (before[ck], self._room_snapshot(ck)) for ck in before}}
            self._push(cmd)
            return changed

    def remove_rooms_at(self, wx, wy, z):
        """apaga o predio que tem uma sala neste quadrado."""
        with self.lock:
            ck = (wx // CS, wy // CS)
            c = self.cell(*ck)
            if not c:
                return {}
            lx, ly = wx % CS, wy % CS
            hit = None
            for i, r in enumerate(c.rooms):
                if r[1] == z and any(a <= lx < a + w and b <= ly < b + h for a, b, w, h in r[2]):
                    hit = i; break
            if hit is None:
                return {}
            before = self._room_snapshot(ck)
            bi = next((j for j, b in enumerate(c.buildings) if hit in b), None)
            drop = set(c.buildings[bi]) if bi is not None else {hit}
            remap, rooms = {}, []
            for i, r in enumerate(c.rooms):
                if i not in drop:
                    remap[i] = len(rooms); rooms.append(r)
            c.buildings = [[remap[i] for i in b if i in remap] for j, b in enumerate(c.buildings) if j != bi]
            c.buildings = [b for b in c.buildings if b]
            c.rooms = rooms
            c.dirty = True
            self._push({"label": "apagar salas", "sq": [], "rooms": {ck: (before, self._room_snapshot(ck))}})
            return {ck: {-1}}

    def _room_at(self, wx, wy, z):
        ck = (wx // CS, wy // CS)
        c = self.cell(*ck)
        if not c:
            return ck, None, None
        lx, ly = wx % CS, wy % CS
        for i, r in enumerate(c.rooms):
            if r[1] == z and any(a <= lx < a + w and b <= ly < b + h for a, b, w, h in r[2]):
                return ck, c, i
        return ck, c, None

    def rename_room_at(self, wx, wy, z, name):
        """troca o tipo (nome vanilla) da sala neste quadrado; pedacos da mesma sala nas celulas vizinhas tambem."""
        with self.lock:
            ck, c, i = self._room_at(wx, wy, z)
            if i is None:
                return {}
            old = c.rooms[i][0]
            # sala que cruza a borda da celula: renomeia pedacos encostados com o mesmo nome
            todo, seen, changed, before = [(ck, i)], set(), {}, {}
            while todo:
                k, j = todo.pop()
                if (k, j) in seen:
                    continue
                seen.add((k, j))
                cc = self.cell(*k)
                before.setdefault(k, self._room_snapshot(k))
                cc.rooms[j][0] = name; cc.dirty = True
                changed.setdefault(k, set()).add(-1)
                for a, b, w, h in cc.rooms[j][2]:
                    for (ex, ey) in ((a - 1, b), (a + w, b), (a, b - 1), (a, b + h)):
                        if 0 <= ex < CS and 0 <= ey < CS:
                            continue
                        gx, gy = k[0] * CS + ex, k[1] * CS + ey
                        # varre a borda inteira encostada
                        span = range(h) if ex in (a - 1, a + w) else range(w)
                        for t in span:
                            px, py = (gx, gy + t) if ex in (a - 1, a + w) else (gx + t, gy)
                            nk, nc, ni = self._room_at(px, py, z)
                            if ni is not None and nk != k and nc.rooms[ni][0] == old:
                                todo.append((nk, ni)); break
            self._push({"label": f"sala {old} -> {name}", "sq": [],
                        "rooms": {k: (v, self._room_snapshot(k)) for k, v in before.items()}})
            return changed

    def building_at(self, wx, wy, z):
        ck, c, i = self._room_at(wx, wy, z)
        if i is None:
            return None
        return ck, next((j for j, b in enumerate(c.buildings) if i in b), None)

    def rooms_world(self):
        """todas as salas em coordenadas de mundo (para spawn/objetos/exportar)."""
        out = []
        for ck in sorted(self.cellset):
            c = self.cell(*ck)
            for bi, b in enumerate(c.buildings):
                for ri in b:
                    r = c.rooms[ri]
                    out.append({"cell": ck, "b": bi, "name": r[0], "z": r[1],
                                "rects": [(ck[0] * CS + a, ck[1] * CS + bb, w, h) for a, bb, w, h in r[2]]})
        return out
