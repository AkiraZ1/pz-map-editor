"""Paleta em estilo 'menu de construcao': categoria -> subcategoria -> itens (com variantes de rotacao).

Item: {"id", "label", "cat", "sub", "icon": tile, "kind": floor|wall|object|..., "parts": [[dx,dy,tile]...],
       "rot": [ids das outras orientacoes, em ordem], "wall": {"W","N","NW","SE","winW","winN","doorW","doorN"}}
Gerado uma vez por versao do jogo e guardado em <cache>/palette.json.
"""
import json
import os
import re

from .assets import sheet_of

CATS = [
    ("terreno", "Terreno"), ("rua", "Rua e calcada"), ("pisos", "Pisos"), ("paredes", "Paredes"),
    ("portas", "Portas e janelas"), ("telhados", "Telhados"), ("escadas", "Escadas"),
    ("moveis", "Moveis"), ("cozinha", "Cozinha e banheiro"), ("lojas", "Lojas e servicos"),
    ("luz", "Luz e fixos"), ("vegetacao", "Vegetacao"), ("cercas", "Cercas e muros"),
    ("carros", "Veiculos e rua"), ("placas", "Placas"), ("decoracao", "Decoracao e itens"), ("outros", "Outros"),
    ("mods", "Tiles de mods e do projeto"),
]

FACE_ORDER = ["S", "E", "N", "W"]
# fora da paleta: cache de chunks, neve, fogo/fumaca, rastros, variantes acesas (o jogo troca sozinho)
HIDE = re.compile(r"^(B42ChunkCaching|overlay_|Overlay|object_snow|e_roof_snow|Fire|Smoke|animaltracks|"
                  r"blood|d_wallcracks|.*_on_\d+$)")


def pretty(sheet):
    s = re.sub(r"_\d+$", "", sheet)
    s = s.replace("_", " ").strip()
    return s[:1].upper() + s[1:]


def cat_of(sheet, props, kind):
    s = sheet.lower()
    if kind == "floor" or kind == "overlay":
        if s.startswith(("blends_natural", "floors_exterior_natural", "blends_grassoverlays", "floors_overlay_grass")):
            return "terreno"
        if s.startswith(("blends_street", "floors_exterior_street", "street_", "floors_exterior_tilesandstone",
                         "floors_exterior_concrete")):
            return "rua"
        return "pisos"
    if s.startswith(("roofs_", "walls_exterior_roofs", "walls_burnt_roofs")) or "WestRoofT" in props or "RoofGroup" in props:
        return "telhados"
    if "stairs" in s or any(k.startswith("stairs") for k in props):
        return "escadas"
    if s.startswith(("fixtures_doors", "fixtures_windows", "fixtures_garage", "walls_garage")) \
            or any(k in props for k in ("doorW", "doorN", "windowW", "windowN", "GarageDoor")):
        return "portas"
    if kind == "wall":
        return "cercas" if s.startswith(("fencing", "walls_exterior_wooden_fence")) else "paredes"
    if s.startswith(("fencing_", "carpentry_02")):
        return "cercas"
    if s.startswith(("vegetation_", "e_", "f_", "d_", "jumbo", "trees")) or "vegitation" in props:
        return "vegetacao"
    if s.startswith(("appliances_", "fixtures_counters", "fixtures_sinks", "fixtures_bathroom")):
        return "cozinha"
    if s.startswith("location_"):
        return "lojas"
    if s.startswith(("furniture_", "carpentry_01")):
        return "moveis"
    if s.startswith(("lighting_", "fixtures_", "industry_", "construction_", "trashcontainers", "camping_")):
        return "luz"
    if s.startswith(("vehicles_", "street_decoration", "trafficlines", "advertising_")):
        return "carros"
    if s.startswith(("signs_", "constructedobjects_signs")):
        return "placas"
    if s.startswith(("walls_decoration", "walls_detailing", "walls_interior_detailing", "crafted", "books",
                     "food", "clothing", "recreational", "desks", "storage", "seating", "rooftop_furniture",
                     "farm", "trash", "constructedobjects", "carpentry", "electricity", "radio_tower")):
        return "decoracao"
    return "outros"


def build(assets, kinds, force=False):
    path = getattr(assets, "palette_path", None) or os.path.join(assets.root, "palette.json")
    if not force and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    T = assets.tiles
    names = [n for n in assets.sprites if not HIDE.match(n)]
    items = []
    used = set()
    by_sheet = {}
    for n in names:
        s, i = sheet_of(n)
        by_sheet.setdefault(s, {})[i] = n

    # paredes: um item por base (W) com as variantes vizinhas da mesma folha
    for s, tiles in by_sheet.items():
        for i, n in sorted(tiles.items()):
            p = T.get(n, {})
            if "WallW" not in p or kinds.kind(n) != "wall":
                continue
            fam = {"W": n}
            for off, key, need in ((1, "N", "WallN"), (2, "NW", "WallNW"), (3, "SE", "WallSE"),
                                   (8, "winW", "WindowW"), (9, "winN", "WindowN"),
                                   (10, "doorW", "DoorWallW"), (11, "doorN", "DoorWallN")):
                m = tiles.get(i + off)
                if m and need in T.get(m, {}):
                    fam[key] = m
            if "N" not in fam:
                continue
            used.update(fam.values())
            items.append({"id": f"w:{n}", "label": p.get("CustomName") or pretty(s), "cat": cat_of(s, p, "wall"),
                          "sub": pretty(s), "icon": fam.get("NW", n), "kind": "wall", "wall": fam,
                          "parts": [[0, 0, n]]})

    # moveis e objetos com GroupName/CustomName: junta partes (SpriteGridPos) e orientacoes (Facing)
    groups = {}
    for n in names:
        if n in used:
            continue
        p = T.get(n, {})
        k = kinds.kind(n)
        if k in ("floor", "overlay", "wall"):
            continue
        g, c = p.get("GroupName"), p.get("CustomName")
        if not (g or c):
            continue
        s, i = sheet_of(n)
        key = (s.rsplit("_", 1)[0] if re.search(r"_\d+$", s) else s, g or "", c or "")
        groups.setdefault(key, {}).setdefault(p.get("Facing", ""), []).append(n)
    for (base, g, c), faces in groups.items():
        ids, gitems = [], []
        for f in sorted(faces, key=lambda f: FACE_ORDER.index(f) if f in FACE_ORDER else 9):
            parts = []
            for n in faces[f]:
                gp = T[n].get("SpriteGridPos", "0,0").split(",")
                try:
                    dx, dy = int(gp[0]), int(gp[1])
                except (ValueError, IndexError):
                    dx = dy = 0
                parts.append([dx, dy, n])
            # pecas repetidas na mesma posicao sao variantes (cores): separa em itens
            seen, variants = {}, []
            for prt in sorted(parts, key=lambda q: (sheet_of(q[2])[1])):
                pos = (prt[0], prt[1])
                vi = seen.get(pos, 0)
                seen[pos] = vi + 1
                while len(variants) <= vi:
                    variants.append([])
                variants[vi].append(prt)
            for vi, v in enumerate(variants[:6]):
                if not v:
                    continue
                s0 = sheet_of(v[0][2])[0]
                lab = " ".join(x for x in (g, c) if x) or pretty(s0)
                iid = f"o:{v[0][2]}"
                icon = min(v, key=lambda q: (q[0] + q[1], q[0]))[2]
                kd = kinds.kind(v[0][2])
                it = {"id": iid, "label": lab + (f" ({f})" if f else ""), "cat": cat_of(s0, T.get(v[0][2], {}), kd),
                      "sub": c or pretty(s0), "icon": icon, "kind": kd,
                      "parts": [[a - min(q[0] for q in v), b - min(q[1] for q in v), t] for a, b, t in v], "face": f}
                items.append(it)
                gitems.append(it)
                used.update(q[2] for q in v)
                if vi == 0:
                    ids.append(iid)
        if len(ids) > 1:
            for it in gitems:
                if it["id"] in ids:
                    it["rot"] = ids

    # o resto: um item por tile (pisos, terreno, rua, telhados, vegetacao...)
    for s, tiles in sorted(by_sheet.items()):
        for i, n in sorted(tiles.items()):
            if n in used:
                continue
            p = T.get(n, {})
            k = kinds.kind(n)
            if k == "wall" and not ("WallW" in p or "WallN" in p or "WallNW" in p):
                continue
            items.append({"id": f"t:{n}", "label": p.get("CustomName") or pretty(s) + f" {i}",
                          "cat": cat_of(s, p, k), "sub": pretty(s), "icon": n, "kind": k, "parts": [[0, 0, n]]})
    for it in items:                                  # folhas extras (modtiles): categoria propria, sub = fonte
        x = (assets.sheets.get(sheet_of(it["icon"])[0]) or {}).get("extra")
        if x is not None:
            it["cat"], it["sub"] = "mods", f"{x}: {pretty(sheet_of(it['icon'])[0])}"
    out = {"cats": [{"key": k, "label": l, "n": sum(1 for it in items if it["cat"] == k)} for k, l in CATS],
           "items": items}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    os.replace(tmp, path)
    return out
