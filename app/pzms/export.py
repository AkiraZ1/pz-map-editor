"""Exporta o projeto direto para uma pasta de mod B42 pronta (sem WorldEd/TileZed).

<mods>/<modid>/42/mod.info
<mods>/<modid>/common/media/maps/<modid>/
    map.info  spawnpoints.lua  spawnregions.lua  objects.lua  thumb.png
    <cx>_<cy>.lotheader  world_<cx>_<cy>.lotpack  chunkdata_<cx>_<cy>.bin
    worldmap.xml(.bin)  worldmap-forest.xml(.bin)
<mods>/<modid>/common/media/lua/server/Items/<modid>_Distributions.lua   (spawns do projeto, se houver)

Incremental: celula so e copiada se mudou (tamanho+mtime); worldmap de celula fica em cache
(<projeto>/.export/wm/<cx>_<cy>.json) com chave = mtime do lotpack.
"""
import json
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor

from . import catalog as C
from . import formats as F
from . import progress as PG
from . import wmbin

CS = F.CS
MARK = ".jpzmapstudio"                    # marca a pasta como gerada por este app (nunca sobrescrever mod alheio)
# chaves que o estilo vanilla do mapa (ISMapDefinitions.lua) pinta
BCAT = {"casa": "Residential", "motel": "Hospitality", "loja": "RetailAndCommercial", "comida": "RestaurantsAndEntertainment",
        "lazer": "RestaurantsAndEntertainment", "saude": "Medical", "industria": "Industrial", "rural": "Industrial",
        "escritorio": "CommunityServices", "seguranca": "CommunityServices", "educacao": "CommunityServices",
        "igreja": "CommunityServices"}
PROFS = ["unemployed", "policeofficer", "fireofficer", "doctor", "nurse", "securityguard", "parkranger", "chef",
         "constructionworker", "repairman", "burgerflipper", "carpenter", "electrician", "engineer", "farmer",
         "fisherman", "fitnessInstructor", "lumberjack", "mechanics", "metalworker", "rancher", "smither", "tailor",
         "veteran", "veterinarian"]


def _floor_class(n):
    if n.startswith(("floors_exterior_street", "blends_street")):
        return "road"
    if n.startswith("blends_natural_02"):
        return "water"
    return None


def _rects(mask):
    """mask: set de (x,y) -> retangulos (x,y,w,h) por corridas de linha fundidas na vertical."""
    rows = {}
    for x, y in mask:
        rows.setdefault(y, []).append(x)
    open_, out = {}, []
    for y in range(CS + 1):
        runs = set()
        xs = sorted(rows.get(y, []))
        i = 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and xs[j + 1] == xs[j] + 1:
                j += 1
            runs.add((xs[i], xs[j] + 1)); i = j + 1
        nxt = {}
        for r, (y0, h) in open_.items():
            if r in runs:
                nxt[r] = (y0, h + 1)
            else:
                out.append((r[0], y0, r[1] - r[0], h))
        for r in runs:
            if r not in nxt:
                nxt[r] = (y, 1)
        open_ = nxt
    return out


def _wm_cell(args):
    """(cx, cy, hp, pp) -> {"main": [(k, v, rect)], "forest": [rect]} em coordenadas locais da celula."""
    cx, cy, hp, pp = args
    PG.micro("worldmap", f"celula {cx},{cy}", "lendo")
    h, sq = F.read_cell_files(hp, pp)
    cls = {"road": set(), "water": set()}
    trees = set()
    for (x, y, z), names in sq.items():
        if z != 0 or not names:
            continue
        c = _floor_class(names[0])
        if c:
            cls[c].add((x, y))
        if any(n.startswith("vegetation_trees") for n in names):
            trees.add((x, y))
    feats = []
    for k, v, m in (("water", "river", cls["water"]), ("highway", "tertiary", cls["road"])):
        feats += [(k, v, r) for r in _rects(m)]
    # predios: salas do andar 0 agrupadas por predio, categoria pelo tipo
    for b in h.buildings:
        rooms = [h.rooms[i] for i in b if i < len(h.rooms)]
        t, _ = C.classify([[r[0], r[1], r[2]] for r in rooms])
        cat = BCAT.get(t, "Residential")
        m = set()
        for r in rooms:
            if r[1] == 0:
                for (x, y, w, hh) in r[2]:
                    m.update((a, b2) for a in range(x, x + w) for b2 in range(y, y + hh))
        feats += [("building", cat, r) for r in _rects(m)]
    # floresta: blocos 8x8 com muitas arvores
    forest = set()
    for x, y in trees:
        forest.add((x // 8, y // 8))
    fr = [(x * 8, y * 8, w * 8, hh * 8) for x, y, w, hh in _rects(forest)] if len(trees) > 40 else []
    PG.micro_done()
    return cx, cy, {"main": feats, "forest": fr}


def _write_wm(path, cells):
    with open(path, "w", encoding="utf-8") as f:
        f.write("<?xml version='1.0' encoding='UTF-8'?>\n<world version=\"1.0\" cellSize=\"256\">\n")
        for (cx, cy), fl in sorted(cells.items()):
            f.write(f'<cell x="{cx}" y="{cy}">\n')
            for k, v, (x, y, w, h) in fl:
                f.write('<feature><geometry type="Polygon"><coordinates>'
                        f'<point x="{x}" y="{y}"/><point x="{x + w}" y="{y}"/><point x="{x + w}" y="{y + h}"/><point x="{x}" y="{y + h}"/>'
                        f'</coordinates></geometry><properties><property name="{k}" value="{v}"/></properties></feature>\n')
            f.write("</cell>\n")
        f.write("</world>\n")
    c = wmbin.from_xml(path)
    if c:
        wmbin.write(c, path + ".bin")
    elif os.path.exists(path + ".bin"):
        os.remove(path + ".bin")


def _lua_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def default_mods_dir():
    return os.path.join(os.path.expanduser("~"), "Zomboid", "mods")


def export(project, mods_dir=None, opts=None, jobs=None):
    """Grava o mod. opts: {modid, title, description, author}. Retorna {path, cells, secs}."""
    t0 = time.time()
    opts = opts or {}
    meta = project.meta
    modid = "".join(ch for ch in (opts.get("modid") or meta.get("mapid") or "MeuMapa") if ch.isalnum() or ch in "_-") or "MeuMapa"
    title = opts.get("title") or meta.get("name") or modid
    desc = opts.get("description") or meta.get("description") or f"Mapa feito no J' PZ MAP STUDIO: {title}"
    root = os.path.join(mods_dir or default_mods_dir(), modid)
    mdir = os.path.join(root, "common", "media", "maps", modid)
    os.makedirs(mdir, exist_ok=True)
    os.makedirs(os.path.join(root, "42"), exist_ok=True)
    with open(os.path.join(root, MARK), "w", encoding="utf-8") as f:
        f.write("gerado pelo J' PZ MAP STUDIO; o export pode reescrever esta pasta\n")

    PG.mark("salvar", 0, 1, "salvando o projeto")
    project.save()
    PG.finish("salvar")

    cells = sorted(tuple(c) for c in meta.get("cells", []))
    if not cells:
        raise ValueError("projeto sem celulas")
    n = len(cells)
    # ---- celulas (copia so o que mudou)
    keep = set()
    for i, (cx, cy) in enumerate(cells):
        for src, dst in ((f"{cx}_{cy}.lotheader", f"{cx}_{cy}.lotheader"), (f"world_{cx}_{cy}.lotpack", f"world_{cx}_{cy}.lotpack")):
            s, d = os.path.join(project.cdir, src), os.path.join(mdir, dst)
            keep.add(dst)
            if not os.path.exists(s):
                continue
            st = os.stat(s)
            if os.path.exists(d) and os.path.getsize(d) == st.st_size and int(os.path.getmtime(d)) == int(st.st_mtime):
                continue
            shutil.copy2(s, d)
        cd = os.path.join(mdir, f"chunkdata_{cx}_{cy}.bin")
        keep.add(f"chunkdata_{cx}_{cy}.bin")
        if not os.path.exists(cd):
            with open(cd, "wb") as f:
                f.write(F.chunkdata_blank())
        if i % 8 == 0 or i == n - 1:
            PG.mark("celulas", i + 1, n, f"celula {cx},{cy}")
    # remove celulas que sairam do projeto
    for fn in os.listdir(mdir):
        if fn.endswith((".lotheader", ".lotpack")) or fn.startswith("chunkdata_"):
            if fn not in keep:
                os.remove(os.path.join(mdir, fn))
    PG.finish("celulas")

    # ---- mapa do jogador (worldmap), com cache por celula
    wmc = os.path.join(project.path, ".export", "wm")
    os.makedirs(wmc, exist_ok=True)
    main, forest, todo = {}, {}, []
    for cx, cy in cells:
        pp = os.path.join(project.cdir, f"world_{cx}_{cy}.lotpack")
        hp = os.path.join(project.cdir, f"{cx}_{cy}.lotheader")
        if not os.path.exists(hp):
            continue
        key = f"{os.path.getmtime(pp):.0f}-{os.path.getmtime(hp):.0f}"
        cp = os.path.join(wmc, f"{cx}_{cy}.json")
        try:
            with open(cp, encoding="utf-8") as f:
                d = json.load(f)
            if d["key"] == key:
                main[(cx, cy)], forest[(cx, cy)] = d["main"], d["forest"]
                continue
        except (OSError, ValueError, KeyError):
            pass
        todo.append(((cx, cy, hp, pp), cp, key))
    done = len(main)
    PG.mark("worldmap", done, n, f"{done} celula(s) do cache")

    def got(cx, cy, r, cp, key):
        main[(cx, cy)], forest[(cx, cy)] = r["main"], r["forest"]
        with open(cp, "w", encoding="utf-8") as f:
            json.dump({"key": key, **r}, f)

    if len(todo) > 2:
        with ProcessPoolExecutor(max_workers=jobs or max(1, min(8, (os.cpu_count() or 2) - 1))) as ex:
            futs = {ex.submit(_wm_cell, a): (cp, key) for a, cp, key in todo}
            for fu in futs:
                cx, cy, r = fu.result()
                got(cx, cy, r, *futs[fu])
                done += 1
                PG.mark("worldmap", done, n, f"celula {cx},{cy}")
    else:
        for a, cp, key in todo:
            cx, cy, r = _wm_cell(a)
            got(cx, cy, r, cp, key)
            done += 1
            PG.mark("worldmap", done, n, f"celula {cx},{cy}")
    _write_wm(os.path.join(mdir, "worldmap.xml"), {k: [tuple(f[:2]) + (tuple(f[2]),) for f in v] for k, v in main.items()})
    _write_wm(os.path.join(mdir, "worldmap-forest.xml"),
              {k: [("natural", "forest", tuple(r)) for r in v] for k, v in forest.items() if v})
    PG.finish("worldmap")

    # ---- metadados
    PG.mark("metadados", 0, 1, "map.info, spawnpoints, objects")
    sx, sy, sz = (meta.get("spawn") or [cells[0][0] * CS + 128, cells[0][1] * CS + 128, 0])[:3]
    with open(os.path.join(mdir, "map.info"), "w", encoding="utf-8") as f:
        f.write(f"title={title}\ndescription={desc}\nfixed2x=true\nzoomX={sx}\nzoomY={sy}\nzoomS=12\n")
    spawns = meta.get("spawns") or [[sx, sy, sz]]
    with open(os.path.join(mdir, "spawnpoints.lua"), "w", encoding="utf-8") as f:
        f.write("function SpawnPoints()\n    local all = {\n")
        for x, y, z in spawns:
            f.write(f"        {{ posX = {int(x)}, posY = {int(y)}, posZ = {int(z)} }},\n")
        f.write("    }\n    return {\n" + "".join(f"        {p} = all,\n" for p in PROFS) + "    }\nend\n")
    with open(os.path.join(mdir, "spawnregions.lua"), "w", encoding="utf-8") as f:
        f.write(f"function SpawnRegions()\nreturn {{\n  {{ name = {_lua_str(title)}, file = \"media/maps/{modid}/spawnpoints.lua\" }}\n}}\nend\n")
    zones = list(meta.get("zones") or [])
    if not any(z.get("type") == "TownZone" for z in zones):
        zones += [{"name": "", "type": "TownZone", "x": cx * CS, "y": cy * CS, "z": 0, "width": CS, "height": CS} for cx, cy in cells]
    gz = os.path.join(project.path, "gen", "zones.json")         # zonas do gerador OSM, se houver
    if os.path.exists(gz):
        with open(gz, encoding="utf-8") as f:
            zones += json.load(f)
    with open(os.path.join(mdir, "objects.lua"), "w", encoding="utf-8") as f:
        f.write("objects = {\n")
        for z in zones:
            f.write(f'  {{ name = {_lua_str(z.get("name", ""))}, type = {_lua_str(z["type"])}, x = {int(z["x"])}, y = {int(z["y"])}, '
                    f'z = {int(z.get("z", 0))}, width = {int(z["width"])}, height = {int(z["height"])} }},\n')
        f.write("}\n")
    # distribuicoes do projeto (ferramenta de spawn)
    from . import spawns as SP
    SP.export_lua(project, root, modid)
    try:
        from . import zombies as ZB                # ferramenta Zumbis (zpop / spawn map), se houver
        if hasattr(ZB, "export"):
            ZB.export(project, mdir)
    except ImportError:
        pass
    from . import modtiles as MT                   # folhas PNG do projeto viram pack + tiledef do mod
    extra = MT.export(project, root, modid)
    with open(os.path.join(root, "42", "mod.info"), "w", encoding="utf-8") as f:
        f.write(f"name={title}\nid={modid}\ndescription={desc}\nversionMin=42.0.0\nposter=poster.png\n")
        if opts.get("author"):
            f.write(f"author={opts['author']}\n")
        for ln in extra:
            f.write(ln + "\n")
        need = [m for m in (meta.get("tilemods") or []) if m and m != modid]
        if need:                                     # mods cujos tiles o mapa usa (formato B42: require=IdA,IdB)
            f.write("require=" + ",".join(need) + "\n")
    th = os.path.join(mdir, "thumb.png")
    try:
        if todo or not os.path.exists(th):
            PG.log("gerando miniatura")
            _thumb(project, cells, th, os.path.join(root, "42", "poster.png"))
    except Exception as e:                       # noqa: BLE001 - miniatura nunca impede o export
        PG.log(f"miniatura nao gerada: {e}")
    from . import workshop as WS
    if os.path.exists(WS.cover_path(project)):     # capa escolhida no Exportar tambem vira o poster do mod
        shutil.copy2(WS.cover_path(project), os.path.join(root, "42", "poster.png"))
    PG.finish("metadados")
    return {"path": root, "modid": modid, "cells": n, "secs": round(time.time() - t0, 1),
            "needs": list(meta.get("tilemods") or []), "sheets": len(MT.proj_sheets(project))}


def _thumb(project, cells, out, poster):
    """miniatura do mapa (vista de cima, 1 px por 2 tiles) para a tela de escolha do mapa."""
    from PIL import Image
    x0, y0 = min(c[0] for c in cells), min(c[1] for c in cells)
    x1, y1 = max(c[0] for c in cells), max(c[1] for c in cells)
    W, H = (x1 - x0 + 1) * 128, (y1 - y0 + 1) * 128
    im = Image.new("RGB", (W, H), (58, 74, 40))
    px = im.load()
    for cx, cy in cells:
        hp = os.path.join(project.cdir, f"{cx}_{cy}.lotheader")
        if not os.path.exists(hp):
            continue
        h, sq = F.read_cell_files(hp, os.path.join(project.cdir, f"world_{cx}_{cy}.lotpack"))
        inroom = set()
        for r in h.rooms:
            if r[1] == 0:
                for (x, y, w, h) in r[2]:
                    inroom.update((a, b) for a in range(x, x + w) for b in range(y, y + h))
        for (x, y, z), names in sq.items():
            if z or not names or x % 2 or y % 2:
                continue
            k = _floor_class(names[0])
            col = (70, 70, 74) if k == "road" else (52, 88, 130) if k == "water" else \
                (150, 120, 90) if (x, y) in inroom else (128, 128, 120) if names[0].startswith("floors_exterior") else None
            if col:
                px[(cx - x0) * 128 + x // 2, (cy - y0) * 128 + y // 2] = col
    im.thumbnail((512, 512))
    im.save(out)
    im.save(poster)
