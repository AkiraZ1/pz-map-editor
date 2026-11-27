"""Cache local de assets, gerado na primeira execucao a partir da instalacao do PROPRIO usuario.

Nada do jogo e redistribuido: os sprites sao lidos dos .pack do jogo e reduzidos (R = 4: tile 2x de
128x256 vira 32x64) em paginas de atlas PNG. Propriedades dos tiles vem de media/tile_definitions/*.tiles.txt.

Layout do cache (por versao do jogo):  <cache>/<versao>/
  atlas/p<N>.png        paginas 2048x2048 RGBA
  atlas.json            {"R":4,"page":2048,"pages":n,"sprites":{nome:[pagina,x,y,w,h,dx,dy]}}
                        dx,dy = posicao do recorte relativa ao canto do canvas 32x64 do quadrado
  tiles.json            {nome: {prop: valor}}
  sheets.json           {folha: {"cat": categoria, "n": [indices]}}
"""
import io
import json
import math
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor

from . import formats as F
from . import gamedir

R = 4                 # reducao em relacao aos sprites 2x
PAGE = 2048
PACKS = ("Tiles2x.floor.pack", "Tiles2x.pack", "JumboTrees2x.pack", "B42ChunkCaching2x.floor.pack",
         "B42ChunkCaching2x.pack", "Overlays2x.pack")
CACHE_FORMAT = 3      # sobe quando o layout do cache muda


def cache_root(version):
    d = os.path.join(gamedir.cache_dir(), (version or "unknown") + f"-c{CACHE_FORMAT}")
    os.makedirs(d, exist_ok=True)
    return d


def is_ready(version):
    d = cache_root(version)
    return all(os.path.exists(os.path.join(d, f)) for f in ("atlas.json", "tiles.json", "sheets.json"))


# ---------------------------------------------------------------- tiles.json
def build_tiledefs(media):
    out = {}
    tdir = os.path.join(media, "tile_definitions")
    files = sorted(f for f in os.listdir(tdir) if f.endswith(".tiles.txt")) if os.path.isdir(tdir) else []
    for fn in files:
        cur, cols, props = None, 8, None
        for raw in open(os.path.join(tdir, fn), encoding="utf-8", errors="replace"):
            s = raw.strip()
            if s.startswith("file ="):
                cur = s.split("=", 1)[1].strip()
            elif s.startswith("size =") and props is None:
                try:
                    cols = int(s.split("=", 1)[1].split(",")[0])
                except ValueError:
                    pass
            elif s == "tile":
                props = {}
            elif s.startswith("xy =") and props is not None:
                try:
                    x, y = map(int, s.split("=", 1)[1].split(","))
                    props["_i"] = y * cols + x
                except ValueError:
                    pass
            elif s == "}" and props is not None:
                i = props.pop("_i", None)
                if i is not None and cur:
                    out.setdefault(f"{cur}_{i}", props)
                props = None
            elif props is not None and "=" in s:
                k, v = s.split("=", 1)
                props[k.strip()] = v.strip()
    return out


# ---------------------------------------------------------------- categorias
CATS = [
    ("ground", "Terreno", ("blends_natural", "floors_exterior_natural", "blends_grassoverlays", "floors_overlay_grass")),
    ("street", "Rua e calcada", ("blends_street", "floors_exterior_street", "street_", "floors_exterior_tilesandstone")),
    ("floor", "Pisos", ("floors_", "blends_")),
    ("wall", "Paredes", ("walls_",)),
    ("door", "Portas e janelas", ("fixtures_doors", "fixtures_windows", "fixtures_garage", "walls_garage")),
    ("roof", "Telhados", ("roofs_",)),
    ("stairs", "Escadas", ("fixtures_stairs", "industry_02_")),
    ("furniture", "Moveis", ("furniture_",)),
    ("appliance", "Eletros e cozinha", ("appliances_", "fixtures_counters", "fixtures_sinks", "fixtures_bathroom")),
    ("location", "Lojas e locais", ("location_",)),
    ("fixture", "Fixos", ("fixtures_", "lighting_", "industry_", "construction_")),
    ("vegetation", "Vegetacao", ("vegetation_", "e_", "f_", "d_", "jumbo")),
    ("fence", "Cercas e muros", ("fencing_", "carpentry_")),
]


def category(sheet):
    s = sheet.lower()
    for key, _, pre in CATS:
        if s.startswith(pre):
            return key
    return "other"


def sheet_of(name):
    m = re.match(r"^(.*)_(\d+)$", name)
    return (m.group(1), int(m.group(2))) if m else (name, 0)


# ---------------------------------------------------------------- reducao de sprites (processo filho)
def _shrink_page(args):
    from PIL import Image
    from . import progress as PG
    png, sprites, pi, pn = args
    page = Image.open(io.BytesIO(png)).convert("RGBA")
    out = []
    for k, (name, x, y, w, h, ox, oy, cw, ch) in enumerate(sprites):
        if k % 64 == 0:
            PG.micro("sprites", f"pagina {pi + 1}/{pn}", f"{name}", k / max(1, len(sprites)))
        if w <= 0 or h <= 0:
            continue
        sx, sy = ox, oy
        if (cw, ch) == (384, 512):          # arvores Jumbo: canvas maior, centrado no quadrado
            sx, sy = ox - 128, oy - 256
        im = page.crop((x, y, x + w, y + h))
        a0, b0 = math.floor(sx / R) * R, math.floor(sy / R) * R
        a1, b1 = math.ceil((sx + w) / R) * R, math.ceil((sy + h) / R) * R
        c = Image.new("RGBA", (a1 - a0, b1 - b0), (0, 0, 0, 0))
        c.paste(im, (sx - a0, sy - b0))
        c = c.resize((c.width // R, c.height // R), Image.BOX)
        al = c.getchannel("A")
        bb = al.getbbox()
        if not bb:
            continue
        c.putalpha(al.point(lambda v: min(255, v * 2)))     # borda meio transparente vira linha: reforca
        c = c.crop(bb)
        out.append((name, c.width, c.height, a0 // R + bb[0], b0 // R + bb[1], c.tobytes()))
    return out


class Shelf:
    def __init__(self):
        self.pages = []
        self._new()

    def _new(self):
        from PIL import Image
        self.cur = Image.new("RGBA", (PAGE, PAGE), (0, 0, 0, 0))
        self.pages.append(self.cur)
        self.x = self.y = self.rowh = 0

    def put(self, w, h, data):
        from PIL import Image
        if self.x + w > PAGE:
            self.x, self.y, self.rowh = 0, self.y + self.rowh + 1, 0
        if self.y + h > PAGE:
            self._new()
        im = Image.frombytes("RGBA", (w, h), data)
        self.cur.paste(im, (self.x, self.y))
        r = (len(self.pages) - 1, self.x, self.y)
        self.x += w + 1
        self.rowh = max(self.rowh, h)
        return r


def build(media, version, progress=None, jobs=None):
    """gera o cache completo; progress(frac, msg)."""
    from . import progress as PG
    t0 = time.time()
    root = cache_root(version)
    say = progress or (lambda f, m: None)
    say(0.01, "lendo definicoes de tiles")
    tdefs = build_tiledefs(media)
    tasks = []
    seen = set()
    for pk in PACKS:
        p = os.path.join(media, "texturepacks", pk)
        if not os.path.exists(p):
            continue
        for page, alpha, sprites, png in F.parse_pack(p):
            sp = [s for s in sprites if s[0] not in seen]
            seen.update(s[0] for s in sp)
            if sp:
                tasks.append((png, sp))
    tasks = [(png, sp, i, len(tasks)) for i, (png, sp) in enumerate(tasks)]
    say(0.03, f"{len(tasks)} paginas de sprites")
    small = []
    jobs = jobs or max(1, min(8, (os.cpu_count() or 2) - 1))
    with ProcessPoolExecutor(jobs) as ex:
        for i, res in enumerate(ex.map(_shrink_page, tasks, chunksize=2)):
            small += res
            PG.mark("sprites", i + 1, len(tasks), f"reduzindo sprites {i + 1}/{len(tasks)}")
            if i % 8 == 0:
                say(0.03 + 0.8 * i / max(1, len(tasks)), f"reduzindo sprites {i}/{len(tasks)}")
    PG.finish("sprites")
    PG.mark("atlas", 0, 1, "montando atlas")
    say(0.85, "montando atlas")
    small.sort(key=lambda s: (sheet_of(s[0])[0], s[2], sheet_of(s[0])[1]))
    sh = Shelf()
    idx = {}
    for name, w, h, dx, dy, data in small:
        pg, x, y = sh.put(w, h, data)
        idx[name] = [pg, x, y, w, h, dx, dy]
    ad = os.path.join(root, "atlas")
    os.makedirs(ad, exist_ok=True)
    for i, im in enumerate(sh.pages):
        say(0.88 + 0.1 * i / len(sh.pages), f"gravando pagina {i + 1}/{len(sh.pages)}")
        PG.mark("atlas", i, len(sh.pages), f"gravando pagina {i + 1}/{len(sh.pages)}")
        im.save(os.path.join(ad, f"p{i}.png"), compress_level=3)
    sheets = {}
    for name in idx:
        s, i = sheet_of(name)
        sheets.setdefault(s, {"cat": category(s), "n": []})["n"].append(i)
    for v in sheets.values():
        v["n"].sort()
    _dump(os.path.join(root, "tiles.json"), tdefs)
    _dump(os.path.join(root, "sheets.json"), sheets)
    _dump(os.path.join(root, "atlas.json"), {"R": R, "page": PAGE, "pages": len(sh.pages), "sprites": idx,
                                             "version": version, "built": time.time()})
    say(1.0, f"pronto: {len(idx)} sprites em {len(sh.pages)} paginas ({time.time() - t0:.0f} s)")
    return root


def _dump(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


JUMBO = ["e_americanlindenJUMBO_1_0", "e_redmapleJUMBO_1_0", "e_yellowwoodJUMBO_1_0", "e_riverbirchJUMBO_1_0",
         "e_americanlindenJUMBO_1_1", "e_redmapleJUMBO_1_1", "e_dogwoodJUMBO_1_0", "e_yellowwoodJUMBO_1_1"]


class Assets:
    """acesso ao cache pronto (atlas + propriedades)."""

    def __init__(self, version):
        self.root = cache_root(version)
        self.version = version
        self.atlas = json.load(open(os.path.join(self.root, "atlas.json")))
        self.sprites = self.atlas["sprites"]
        self.tiles = json.load(open(os.path.join(self.root, "tiles.json")))
        self.sheets = json.load(open(os.path.join(self.root, "sheets.json")))
        self._pages = {}
        self.nbase = self.atlas["pages"]
        self.base = (dict(self.sprites), dict(self.tiles), dict(self.sheets))
        self.base_sheets = self.base[2]
        self.files = [os.path.join(self.root, "atlas", f"p{i}.png") for i in range(self.nbase)]
        self.urls = [f"/cache/atlas/p{i}.png" for i in range(self.nbase)]
        self.extras = []
        self.sig = ""

    def set_extras(self, roots):
        """soma caches de tiles extras (modtiles) depois das paginas vanilla; dicts mudam no lugar
        (Kinds e catalogo guardam a referencia). Vanilla vence em nome repetido."""
        sp, ti, sh = (dict(d) for d in self.base)
        files, urls = self.files[:self.nbase], self.urls[:self.nbase]
        for r in roots:
            a = json.load(open(os.path.join(r, "atlas.json")))
            off = len(files)
            for n, e in a["sprites"].items():
                if n not in sp:
                    sp[n] = [e[0] + off] + e[1:]
            for n, p in json.load(open(os.path.join(r, "tiles.json"))).items():
                ti.setdefault(n, p)
            for s, v in json.load(open(os.path.join(r, "sheets.json"))).items():
                sh.setdefault(s, dict(v, extra=a.get("label", "")))
            key = os.path.basename(r)
            files += [os.path.join(r, f"p{i}.png") for i in range(a["pages"])]
            urls += [f"/data/modtiles/{key}/p{i}.png" for i in range(a["pages"])]
        for d, new in ((self.sprites, sp), (self.tiles, ti), (self.sheets, sh)):
            d.clear(); d.update(new)
        self.files, self.urls, self.extras = files, urls, list(roots)
        self._pages = {k: v for k, v in self._pages.items() if k < self.nbase}
        self.sig = "|".join(os.path.basename(r) for r in roots)
        self.atlas["pages"] = len(files)

    @property
    def palette_path(self):
        if not self.extras:
            return os.path.join(self.root, "palette.json")
        import hashlib
        return os.path.join(os.path.dirname(self.extras[0]), "pal-" + hashlib.sha1(
            (self.root + self.sig).encode()).hexdigest()[:16] + ".json")

    def meta(self):
        """atlas.json para a UI, com as paginas extras."""
        return dict(self.atlas, urls=self.urls, sig=self.sig)

    def page(self, i):
        from PIL import Image
        im = self._pages.get(i)
        if im is None:
            im = Image.open(self.files[i]).convert("RGBA")
            im.load()
            self._pages[i] = im
        return im

    def resolve(self, name):
        """nome de sprite que o jogo realmente desenha (arvores 'vegetation_trees_01_N' viram Jumbo)."""
        if name in self.sprites:
            return name
        if name.startswith("vegetation_trees_01_"):
            if not hasattr(self, "_leafy"):
                self._leafy = [n for n in JUMBO if n in self.sprites] or [None]
            try:
                return self._leafy[int(name.rsplit("_", 1)[1]) % len(self._leafy)]
            except ValueError:
                return None
        return None

    def sprite(self, name):
        """(imagem, dx, dy) reduzida, ou None."""
        e = self.sprites.get(self.resolve(name) or "")
        if not e:
            return None
        pg, x, y, w, h, dx, dy = e
        return self.page(pg).crop((x, y, x + w, y + h)), dx, dy

    def props(self, name):
        return self.tiles.get(name) or {}
