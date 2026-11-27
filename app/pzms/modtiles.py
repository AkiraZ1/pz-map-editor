"""Tiles extras: folhas de outros mods (.pack + .tiles) e folhas novas do projeto (PNG).

Fontes:
- mod instalado: <mod>/{42,common,.}/media/texturepacks/*.pack + <mod>/.../media/*.tiles (tdef binario)
  procurado em ~/Zomboid/mods, ~/Zomboid/Workshop/*/Contents/mods e steamapps/workshop/content/108600/*/mods
- folha do projeto: <projeto>/tiles/<folha>.png (tile 2x = 128x256, 8 colunas => 1024 de largura;
  1x = 64x128 tambem aceito e ampliado) + <projeto>/tiles/sheets.json {folha: {"default": tipo, "tiles": {i: tipo}}}

Cada fonte vira um cache igual ao vanilla (atlas reduzido R=4) em <dados>/modtiles/<chave>/ e e somada
ao Assets (paginas depois das vanilla). O projeto guarda as fontes em meta["tilemods"] (ids dos mods);
ao abrir, os mods que tem as folhas usadas no mapa entram sozinhos.
Export: as folhas do projeto vao para o mod (pack + tiledef + linhas no mod.info)."""
import hashlib
import io
import json
import os
import re
import struct
import threading
import zlib
from concurrent.futures import ProcessPoolExecutor

from . import assets as A
from . import formats as F
from . import gamedir

VER = 1
TYPES = {   # tipo da folha nova -> propriedades do tiledef
    "floor": {"solidfloor": ""},
    "overlay": {"FloorOverlay": ""},
    "wallW": {"WallW": "", "collideW": ""},
    "wallN": {"WallN": "", "collideN": ""},
    "wallNW": {"WallNW": "", "collideW": "", "collideN": ""},
    "attachW": {"attachedW": ""},
    "attachN": {"attachedN": ""},
    "object": {},
    "solid": {"solidtrans": ""},
}
NAME_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_]*_\d\d$")
_lock = threading.Lock()


def root():
    d = os.path.join(gamedir.data_dir(), "modtiles")
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- tdef (.tiles binario)
def read_tdef(path):
    """[(folha, colunas, linhas, [props de cada tile])]"""
    with open(path, "rb") as f:
        b = f.read()
    if b[:4] != b"tdef":
        raise ValueError("nao e tdef: " + path)
    p = 8
    n, = struct.unpack_from("<i", b, p); p += 4

    def line():
        nonlocal p
        e = b.index(b"\n", p); s = b[p:e].decode("utf-8", "replace"); p = e + 1
        return s
    out = []
    for _ in range(n):
        name = line(); line()                                  # nome e imagem
        cols, rows, _id, nt = struct.unpack_from("<4i", b, p); p += 16
        tiles = []
        for _t in range(nt):
            k, = struct.unpack_from("<i", b, p); p += 4
            pr = {}
            for _k in range(k):
                key = line(); pr[key] = line()
            tiles.append(pr)
        out.append((name, cols, rows, tiles))
    return out


def write_tdef(path, sheets):
    b = bytearray(b"tdef") + struct.pack("<ii", 1, len(sheets))
    for i, (name, cols, rows, tiles) in enumerate(sheets):
        b += f"{name}\n{name}.png\n".encode()
        b += struct.pack("<4i", cols, rows, i + 1, len(tiles))
        for pr in tiles:
            b += struct.pack("<i", len(pr))
            for k, v in pr.items():
                b += f"{k}\n{v}\n".encode()
    with open(path, "wb") as f:
        f.write(b)


def write_pack(path, pages):
    """pages: [(nome_pagina, [(sprite, x, y, w, h, ox, oy, cw, ch)], png_bytes)] -> PZPK v1."""
    def s(t):
        e = t.encode("utf-8"); return struct.pack("<i", len(e)) + e
    b = bytearray(b"PZPK") + struct.pack("<ii", 1, len(pages))
    for name, sprites, png in pages:
        b += s(name) + struct.pack("<ii", len(sprites), 1)
        for sp in sprites:
            b += s(sp[0]) + struct.pack("<8i", *sp[1:])
        b += struct.pack("<i", len(png)) + png
    with open(path, "wb") as f:
        f.write(b)


# ---------------------------------------------------------------- mods instalados
def _mod_roots():
    z = gamedir.zomboid_user_dir()
    out = []
    ws = os.path.join(z, "Workshop")
    if os.path.isdir(ws):
        for w in sorted(os.listdir(ws)):
            out.append(os.path.join(ws, w, "Contents", "mods"))
    out.append(os.path.join(z, "mods"))
    for lib in gamedir._steam_roots():
        c = os.path.join(lib, "steamapps", "workshop", "content", "108600")
        if os.path.isdir(c):
            out += [os.path.join(c, w, "mods") for w in sorted(os.listdir(c))]
    return [r for r in out if os.path.isdir(r)]


def _info(d):
    for p in (os.path.join(d, "42", "mod.info"), os.path.join(d, "mod.info")):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                kv = {}
                for ln in f:
                    if "=" in ln:
                        k, v = ln.split("=", 1)
                        kv.setdefault(k.strip().lower(), v.strip())
                return kv
        except OSError:
            pass
    return {}


def find_mods():
    """{id: {id, name, dir, packs, tdefs}} so de mods com tiles; o primeiro achado vence (Workshop local antes)."""
    mods = {}
    for r in _mod_roots():
        for m in sorted(os.listdir(r)):
            d = os.path.join(r, m)
            if not os.path.isdir(d) or os.path.exists(os.path.join(d, ".jpzmapstudio")):
                continue
            packs, tdefs = [], []
            for sub in ("42", "common", "."):
                media = os.path.normpath(os.path.join(d, sub, "media"))
                tp = os.path.join(media, "texturepacks")
                if os.path.isdir(tp):
                    packs += [os.path.join(tp, f) for f in sorted(os.listdir(tp)) if f.endswith(".pack")]
                if os.path.isdir(media):
                    tdefs += [os.path.join(media, f) for f in sorted(os.listdir(media)) if f.endswith(".tiles")]
            if not packs or not tdefs:
                continue
            inf = _info(d)
            mid = inf.get("id") or m
            if mid in mods:
                continue
            mods[mid] = {"id": mid, "name": inf.get("name") or m, "dir": d, "packs": packs, "tdefs": tdefs}
    return mods


def _stamp(paths):
    h = hashlib.sha1(str(VER).encode())
    for p in paths:
        st = os.stat(p)
        h.update(f"{p}|{st.st_size}|{int(st.st_mtime)}".encode())
    return h.hexdigest()[:16]


def sheet_index(mods):
    """{folha: id do mod} lendo so os tdefs (cache em modtiles/index.json)."""
    ip = os.path.join(root(), "index.json")
    try:
        with open(ip, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    new, out = {}, {}
    for m in mods.values():
        for t in m["tdefs"]:
            k = _stamp([t])
            names = old.get(t, {}).get("k") == k and old[t]["sheets"]
            if names is False or names is None:
                try:
                    names = [s[0] for s in read_tdef(t)]
                except (OSError, ValueError, struct.error):
                    names = []
            new[t] = {"k": k, "sheets": names}
            for s in names:
                out.setdefault(s, m["id"])
    if new != old:
        A._dump(ip, new)
    return out


# ---------------------------------------------------------------- cache de uma fonte
def _shrink_any(args):
    """como assets._shrink_page, mas aceita pagina 1x (canvas 64x128): amplia 2x antes."""
    png, sprites, pi, pn = args
    if any(s[7] == 64 for s in sprites):
        from PIL import Image
        im = Image.open(io.BytesIO(png)).convert("RGBA")
        im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
        bio = io.BytesIO(); im.save(bio, "PNG"); png = bio.getvalue()
        sprites = [(n, x * 2, y * 2, w * 2, h * 2, ox * 2, oy * 2, cw * 2, ch * 2) if cw == 64 else (n, x, y, w, h, ox, oy, cw, ch)
                   for n, x, y, w, h, ox, oy, cw, ch in sprites]
    return A._shrink_page((png, sprites, pi, pn))


def _build(key, label, tasks, tiles, say=None):
    d = os.path.join(root(), key)
    if os.path.exists(os.path.join(d, "atlas.json")):
        return d
    tasks = [(png, sp, i, len(tasks)) for i, (png, sp) in enumerate(tasks)]
    small = []
    if len(tasks) > 2:
        with ProcessPoolExecutor(max(1, min(6, (os.cpu_count() or 2) - 1))) as ex:
            for i, res in enumerate(ex.map(_shrink_any, tasks)):
                small += res
                if say:
                    say(f"{label}: pagina {i + 1}/{len(tasks)}")
    else:
        for t in tasks:
            small += _shrink_any(t)
    small.sort(key=lambda s: (A.sheet_of(s[0])[0], s[2], A.sheet_of(s[0])[1]))
    sh = A.Shelf()
    idx = {}
    for name, w, h, dx, dy, data in small:
        pg, x, y = sh.put(w, h, data)
        idx[name] = [pg, x, y, w, h, dx, dy]
    tmp = d + ".tmp"
    os.makedirs(tmp, exist_ok=True)
    for i, im in enumerate(sh.pages):
        im.save(os.path.join(tmp, f"p{i}.png"), compress_level=3)
    sheets = {}
    for name in idx:
        s, i = A.sheet_of(name)
        sheets.setdefault(s, {"cat": A.category(s), "n": []})["n"].append(i)
    for v in sheets.values():
        v["n"].sort()
    A._dump(os.path.join(tmp, "tiles.json"), tiles)
    A._dump(os.path.join(tmp, "sheets.json"), sheets)
    A._dump(os.path.join(tmp, "atlas.json"), {"pages": len(sh.pages), "sprites": idx, "label": label})
    if os.path.exists(d):
        import shutil
        shutil.rmtree(d)
    os.replace(tmp, d)
    return d


def mod_key(m):
    return "m-" + re.sub(r"[^A-Za-z0-9_-]", "_", m["id"])[:40] + "-" + _stamp(m["packs"] + m["tdefs"])


def build_mod(m, say=None):
    tiles = {}
    for t in m["tdefs"]:
        try:
            for name, cols, rows, tl in read_tdef(t):
                for i, pr in enumerate(tl):
                    if pr:
                        tiles.setdefault(f"{name}_{i}", pr)
        except (OSError, ValueError, struct.error):
            pass
    want = {s for s in (A.sheet_of(n)[0] for n in tiles)}
    for t in m["tdefs"]:
        try:
            want.update(s[0] for s in read_tdef(t))
        except (OSError, ValueError, struct.error):
            pass
    tasks = []
    for p in m["packs"]:
        for _page, _al, sprites, png in F.parse_pack(p):
            sp = [s for s in sprites if A.sheet_of(s[0])[0] in want]
            if sp:
                tasks.append((png, sp))
    return _build(mod_key(m), m["name"], tasks, tiles, say)


# ---------------------------------------------------------------- folhas do projeto (PNG)
def proj_dir(project):
    return os.path.join(project.path, "tiles")


def proj_sheets(project):
    """{folha: {"default", "tiles", "cols", "rows", "png"}} das folhas PNG do projeto."""
    d = proj_dir(project)
    try:
        with open(os.path.join(d, "sheets.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        meta = {}
    out = {}
    for s, v in meta.items():
        png = os.path.join(d, s + ".png")
        if os.path.exists(png):
            out[s] = dict(v, png=png)
    return out


def save_proj_sheets(project, sheets):
    d = proj_dir(project)
    os.makedirs(d, exist_ok=True)
    A._dump(os.path.join(d, "sheets.json"), {k: {kk: vv for kk, vv in v.items() if kk != "png"} for k, v in sheets.items()})


def check_png(data):
    """valida a folha: devolve (imagem 2x RGBA, colunas, linhas, aviso)."""
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    W, H = im.size
    note = ""
    if W % 128 == 0 and H % 256 == 0:
        pass
    elif W % 64 == 0 and H % 128 == 0:
        im = im.convert("RGBA").resize((W * 2, H * 2), Image.LANCZOS)
        note = "folha 1x (64x128) ampliada para 2x"
    else:
        raise ValueError(f"{W}x{H}: a folha precisa ter largura multipla de 128 e altura multipla de 256 (tile 2x = 128x256)")
    im = im.convert("RGBA")
    return im, im.width // 128, im.height // 256, note


def tile_props(v, i):
    t = (v.get("tiles") or {}).get(str(i)) or v.get("default") or "object"
    return dict(TYPES.get(t, {}))


def _cells(im, sheet, cols, rows):
    """sprites (recorte do alfa) de cada quadrado 128x256 da folha."""
    out = []
    for i in range(cols * rows):
        x0, y0 = (i % cols) * 128, (i // cols) * 256
        bb = im.crop((x0, y0, x0 + 128, y0 + 256)).getchannel("A").getbbox()
        if bb:
            out.append((f"{sheet}_{i}", x0 + bb[0], y0 + bb[1], bb[2] - bb[0], bb[3] - bb[1], bb[0], bb[1], 128, 256))
    return out


def sheet_pages(sheets):
    """[(nome, [sprites], png 2x)] e {tile: props} das folhas PNG do projeto."""
    from PIL import Image
    pages, tiles = [], {}
    for s, v in sorted(sheets.items()):
        im = Image.open(v["png"]).convert("RGBA")
        cols, rows = im.width // 128, im.height // 256
        sp = _cells(im, s, cols, rows)
        bio = io.BytesIO(); im.save(bio, "PNG")
        pages.append((s, sp, bio.getvalue()))
        for t in sp:                                   # celulas vazias (sem alfa) nao viram tile
            tiles[t[0]] = tile_props(v, int(t[0].rsplit("_", 1)[1]))
    return pages, tiles


def build_proj(project):
    sh = proj_sheets(project)
    if not sh:
        return None
    h = hashlib.sha1(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "png"} for k, v in sh.items()}, sort_keys=True).encode())
    for v in sh.values():
        with open(v["png"], "rb") as f:
            h.update(f.read())
    key = "p-" + h.hexdigest()[:16]
    if os.path.exists(os.path.join(root(), key, "atlas.json")):
        return os.path.join(root(), key)
    pages, tiles = sheet_pages(sh)
    return _build(key, "folhas do projeto", [(png, sp) for _n, sp, png in pages], tiles)


# ---------------------------------------------------------------- nomes usados no mapa
def used_sheets(project):
    out = set()
    for cx, cy in project.cellset:
        hp = os.path.join(project.cdir, f"{cx}_{cy}.lotheader")
        try:
            with open(hp, "rb") as f:
                b = f.read()
            n, = struct.unpack_from("<i", b, 8)
            p = 12
            for _ in range(n):
                e = b.index(b"\n", p); out.add(A.sheet_of(b[p:e].decode("latin1"))[0]); p = e + 1
        except (OSError, ValueError, struct.error):
            pass
    return out


# ---------------------------------------------------------------- ativar no app
STATUS = {"busy": False, "msg": "", "sig": "", "error": None}


def wanted(app, project):
    """(mods escolhidos/detectados, mods que faltam no cache vanilla)."""
    mods = find_mods()
    ids = list(project.meta.get("tilemods") or [])
    base = app.assets.base_sheets if hasattr(app.assets, "base_sheets") else app.assets.sheets
    miss = {s for s in used_sheets(project) if s not in base}
    mine = set(proj_sheets(project))
    idx = sheet_index(mods) if miss - mine else {}
    if miss - mine:
        for s in sorted(miss - mine):
            m = idx.get(s)
            if m and m not in ids:
                ids.append(m)
        if ids != list(project.meta.get("tilemods") or []):
            project.meta["tilemods"] = ids
            project.meta_dirty = True
    return mods, [mods[i] for i in ids if i in mods], sorted(miss - mine - set(idx))


def activate(app, project=None):
    """monta (em segundo plano) e soma as fontes do projeto aberto ao atlas."""
    project = project or app.project
    if project is None or app.assets is None:
        return

    def run():
        with _lock:
            STATUS.update(busy=True, error=None, msg="procurando tiles de mods")
            try:
                _mods, use, _miss = wanted(app, project)
                roots = []
                for m in use:
                    STATUS["msg"] = f"lendo tiles de {m['name']}"
                    roots.append(build_mod(m, lambda t: STATUS.update(msg=t)))
                STATUS["msg"] = "folhas do projeto"
                pr = build_proj(project)
                if pr:
                    roots.append(pr)
                if app.project is project:
                    app.assets.set_extras(roots)
                    app.kinds._c.clear()
                    STATUS["sig"] = app.assets.sig
            except Exception as e:                      # noqa: BLE001 - vai para a UI
                import traceback
                traceback.print_exc()
                STATUS["error"] = f"{type(e).__name__}: {e}"
            STATUS.update(busy=False, msg="")
    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- export das folhas do projeto
def export(project, root_dir, modid):
    """grava pack + tiledef das folhas do projeto no mod; devolve linhas extras do mod.info."""
    sh = proj_sheets(project)
    tp = os.path.join(root_dir, "common", "media", "texturepacks")
    name = f"{modid}_tiles"
    old = [os.path.join(tp, name + ".pack"), os.path.join(root_dir, "common", "media", name + ".tiles")]
    if not sh:
        for p in old:
            if os.path.exists(p):
                os.remove(p)
        return []
    os.makedirs(tp, exist_ok=True)
    pages, _t = sheet_pages(sh)
    write_pack(old[0], [(f"{name}{i}", sp, png) for i, (_s, sp, png) in enumerate(pages)])
    defs = []
    for s, v in sorted(sh.items()):
        from PIL import Image
        with Image.open(v["png"]) as im:
            cols, rows = im.width // 128, im.height // 256
        defs.append((s, cols, rows, [tile_props(v, i) for i in range(cols * rows)]))
    write_tdef(old[1], defs)
    num = 2000 + zlib.crc32(modid.encode()) % 7000
    return [f"pack={name}", f"tiledef={name} {num}"]
