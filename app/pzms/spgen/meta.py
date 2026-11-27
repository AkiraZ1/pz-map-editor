"""Metadados do mapa gerado (copia adaptada de saopaulo/scripts/zones.py + worldmap.py, sem cv2/shapely).

objects_lua(d, out)  -> gen/objects.lua   (TownZone, ParkingStall, Nav, Forest, ZombiesType)
worldmap(out, outf)  -> gen/worldmap.xml + gen/worldmap-forest.xml (mapa do jogador; o export gera o .bin)
Usa a geometria ja configurada em gen (gen.configure) e os rasters gen/raster/b_*.npz.
"""
import glob
import math
import os

import numpy as np
from PIL import Image, ImageDraw

from . import gen as GN

CS = 256
G_ASPH, G_WOOD, G_PARK, G_WATER = 1, 4, 7, 8
NAV_W = {"motorway": 20, "trunk": 18, "primary": 16, "secondary": 13, "tertiary": 10, "residential": 8,
         "unclassified": 8, "living_street": 7, "motorway_link": 8, "trunk_link": 8, "primary_link": 8,
         "secondary_link": 7, "tertiary_link": 7}
ZT_AMEN = {"police": "Police", "fire_station": "FireDept", "hospital": "Doctor", "clinic": "Doctor",
           "doctors": "Doctor", "school": "School", "kindergarten": "School", "university": "University",
           "college": "University", "restaurant": "Restaurant", "fast_food": "Dinner", "bar": "Bar",
           "pub": "Bar", "nightclub": "Bar", "cafe": "CoffeeShop", "bank": "Bank", "place_of_worship": "Church",
           "pharmacy": "Pharmacist", "fuel": "Gas2Go", "prison": "Prison", "theatre": "Theatre",
           "cinema": "Theatre"}
SERVICE = {"police": "police", "hospital": "ambulance", "clinic": "ambulance", "fire_station": "fire"}
CURB = ("residential", "tertiary", "unclassified", "living_street", "secondary")
ZT_SHOP = {"supermarket": "Gigamart", "convenience": "VariousFoodMarket", "car_repair": "CarRepair",
           "butcher": "Butcher", "bakery": "VariousFoodMarket"}
ZT_BLD = {"office": "Offices", "commercial": "Offices", "industrial": "Factory", "warehouse": "Factory",
          "construction": "ConstructionSite", "hotel": "FancyHotel", "hospital": "Doctor", "school": "School",
          "university": "University", "church": "Church", "cathedral": "Church"}
ZT_LU = {"construction": "ConstructionSite", "industrial": "Factory"}
ZT_LEIS = {"sports_centre": "StreetSports", "pitch": "StreetSports", "swimming_pool": "Swimmer",
           "stadium": "StreetSports"}
CAT = ["", "Residential", "CommunityServices", "Hospitality", "Industrial", "Medical",
       "RestaurantsAndEntertainment", "RetailAndCommercial"]
HW = {1: "primary", 2: "secondary", 3: "tertiary"}


def zt_of(t):
    return (ZT_AMEN.get(t.get("amenity")) or ZT_SHOP.get(t.get("shop")) or ZT_LEIS.get(t.get("leisure"))
            or ZT_BLD.get(t.get("building")) or ZT_LU.get(t.get("landuse")))


def load_raster():
    """mosaico dos b_*.npz -> G (chao), L (andares), R (classe de via), K (categoria de predio), mapa inteiro."""
    W, H = GN.NCX * CS, GN.NCY * CS
    out = {k: np.zeros((H, W), np.uint8) for k in "GLRK"}
    for f in glob.glob(os.path.join(GN.RAS, "b_*.npz")):
        i, j = map(int, os.path.basename(f)[2:-4].split("_"))
        z = np.load(f)
        x0, y0 = i * GN.BS * CS, j * GN.BS * CS
        for k in "GLRK":
            if k not in z.files:
                continue
            a = z[k]
            h, w = min(a.shape[0], H - y0), min(a.shape[1], W - x0)
            if h > 0 and w > 0:
                out[k][y0:y0 + h, x0:x0 + w] = a[:h, :w]
    return out


def P(pts):
    a = np.asarray(pts, np.float64)
    x, y = GN.proj(a[:, 0], a[:, 1])
    return np.stack([x, y], 1)


def poly_mask(outer, inner, x0, y0, w, h):
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    d.polygon([tuple(p) for p in (outer - (x0, y0)).tolist()], fill=1)
    for r in inner:
        d.polygon([tuple(p) for p in (r - (x0, y0)).tolist()], fill=0)
    return np.array(m, np.uint8)


def stalls(ok):
    """vagas 3x4 / 4x3 que cabem inteiras na mascara, com corredor; escolhe a orientacao com mais vagas."""
    best = []
    for sw, sh in ((3, 4), (4, 3)):
        H, W = ok.shape
        if H < sh or W < sw:
            continue
        I = np.pad(ok.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        full = (I[sh:, sw:] - I[:-sh, sw:] - I[sh:, :-sw] + I[:-sh, :-sw]) == sw * sh
        taken = np.zeros_like(ok, bool)
        got = []
        ys, xs = np.nonzero(full)
        for y, x in zip(ys.tolist(), xs.tolist()):
            if not taken[y:y + sh, x:x + sw].any():
                got.append((x, y, sw, sh))
                taken[y:y + sh, x:x + sw] = True
                if sw == 3:
                    taken[y + sh:y + sh + 5, x:x + sw] = True
                else:
                    taken[y:y + sh, x + sw:x + sw + 5] = True
        if len(got) > len(best):
            best = got
    return best


def _clip_poly(pts, x0, y0, x1, y1):
    """Sutherland-Hodgman: poligono recortado no retangulo."""
    def clip(ps, inside, inter):
        out = []
        for k in range(len(ps)):
            a, b = ps[k - 1], ps[k]
            ia, ib = inside(a), inside(b)
            if ib:
                if not ia:
                    out.append(inter(a, b))
                out.append(b)
            elif ia:
                out.append(inter(a, b))
        return out

    def ix(xc):
        return lambda a, b: (xc, a[1] + (b[1] - a[1]) * (xc - a[0]) / ((b[0] - a[0]) or 1e-9))

    def iy(yc):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (yc - a[1]) / ((b[1] - a[1]) or 1e-9), yc)

    ps = list(pts)
    for ins, it in ((lambda p: p[0] >= x0, ix(x0)), (lambda p: p[0] <= x1, ix(x1)),
                    (lambda p: p[1] >= y0, iy(y0)), (lambda p: p[1] <= y1, iy(y1))):
        if not ps:
            break
        ps = clip(ps, ins, it)
    return ps


def _seg_quads(pts, half):
    """faixa de largura 2*half sobre a polilinha: um quadrilatero por trecho (no lugar do buffer do shapely)."""
    out = []
    for (ax, ay), (bx, by) in zip(pts[:-1], pts[1:]):
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        if L < 4:
            continue
        nx, ny = -dy / L * half, dx / L * half
        out.append([(ax + nx, ay + ny), (bx + nx, by + ny), (bx - nx, by - ny), (ax - nx, ay - ny)])
    return out


def objects_lua(d, path):
    R = load_raster()
    Gm, Lm = R["G"], R["L"]
    NY, NX = Gm.shape
    OX, OY = GN.CX0 * CS, GN.CY0 * CS

    def rect(name, typ, x, y, w, h):
        return (f'  {{ name = "{name}", type = "{typ}", x = {x + OX}, y = {y + OY}, z = 0, '
                f'width = {w}, height = {h} }}')

    out = []
    for cx in range(GN.NCX):
        for cy in range(GN.NCY):
            out.append(rect("", "TownZone", cx * CS, cy * CS, CS, CS))
    n = {"TownZone": len(out), "ParkingStall": 0, "Nav": 0, "Forest": 0, "ZombiesType": 0}
    zts, serv = [], []
    for a in d["areas"]:
        t = a["tags"]
        park = (t.get("amenity") == "parking" and t.get("parking") not in ("multi-storey", "underground", "rooftop")
                and t.get("building") is None)
        zt = zt_of(t)
        if not park and not zt:
            continue
        for r in a["rings"]:
            if len(r["outer"]) < 3:
                continue
            o = P(r["outer"])
            x0, y0 = np.floor(o.min(0)).astype(int)
            x1, y1 = np.ceil(o.max(0)).astype(int)
            x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, NX - 1), min(y1, NY - 1)
            if x1 - x0 < 3 or y1 - y0 < 3:
                continue
            if zt:
                zts.append((zt, x0, y0, x1 - x0 + 1, y1 - y0 + 1))
            if park:
                m = poly_mask(o, [P(i) for i in r["inner"] if len(i) >= 3], x0, y0, x1 - x0 + 1, y1 - y0 + 1)
                ok = (m > 0) & (Gm[y0:y1 + 1, x0:x1 + 1] == G_ASPH) & (Lm[y0:y1 + 1, x0:x1 + 1] == 0)
                for x, y, w, h in stalls(ok)[:80]:
                    out.append(rect("good", "ParkingStall", x0 + x, y0 + y, w, h)); n["ParkingStall"] += 1
            sv = SERVICE.get(t.get("amenity"))
            if sv:
                serv.append((sv, x0, y0, x1, y1))
    for p in d.get("pois", []):
        x, y = GN.proj(p["lat"], p["lon"])
        sv = SERVICE.get(p["tags"].get("amenity"))
        if sv:
            serv.append((sv, int(x) - 10, int(y) - 10, int(x) + 10, int(y) + 10))
        zt = zt_of(p["tags"])
        if zt:
            x, y = int(x) - 8, int(y) - 8
            if 0 <= x < NX - 16 and 0 <= y < NY - 16:
                zts.append((zt, x, y, 16, 16))
    seen = set()
    for zt, x, y, w, h in zts:
        k = (zt, x // 4, y // 4)
        if k in seen or w * h > 400 * 400:
            continue
        seen.add(k)
        out.append(rect(zt, "ZombiesType", x, y, w, h)); n["ZombiesType"] += 1
    seen_sv = set()
    for sv, a0, b0, a1, b1 in serv:
        a0, b0, a1, b1 = max(a0 - 12, 0), max(b0 - 12, 0), min(a1 + 12, NX - 1), min(b1 + 12, NY - 1)
        if (sv, a0 // 64, b0 // 64) in seen_sv or a1 - a0 < 4 or b1 - b0 < 4:
            continue
        seen_sv.add((sv, a0 // 64, b0 // 64))
        ok = (Gm[b0:b1 + 1, a0:a1 + 1] == G_ASPH) & (Lm[b0:b1 + 1, a0:a1 + 1] == 0)
        for x, y, w, h in stalls(ok)[:3]:
            out.append(rect(sv, "ParkingStall", a0 + x, b0 + y, w, h)); n["ParkingStall"] += 1
    # carro estacionado no meio-fio das vias locais, a cada ~30 m, alternando o lado
    for w in d["ways"]:
        t = w["tags"]
        if t.get("highway") not in CURB or t.get("tunnel") or t.get("bridge") or len(w["pts"]) < 2:
            continue
        pts = P(w["pts"])
        seg = np.hypot(*np.diff(pts, axis=0).T)
        cum = np.concatenate([[0], np.cumsum(seg)])
        total = float(cum[-1])
        off = NAV_W[t["highway"]] / 2 - 1.5
        for k, dpos in enumerate(np.arange(10, total - 10, 30)):
            i = min(int(np.searchsorted(cum, dpos, "right")) - 1, len(seg) - 1)
            if seg[i] <= 0:
                continue
            f = (dpos - cum[i]) / seg[i]
            (ax, ay), (bx, by) = pts[i], pts[i + 1]
            px, py = ax + (bx - ax) * f, ay + (by - ay) * f
            dx, dy = (bx - ax) / seg[i], (by - ay) / seg[i]
            sgn = 1 if k % 2 else -1
            x, y = int(round(px - dy * off * sgn)) - 1, int(round(py + dx * off * sgn)) - 1
            if not (0 <= x < NX - 3 and 0 <= y < NY - 3):
                continue
            if (Gm[y:y + 3, x:x + 3] == G_ASPH).all() and not Lm[y:y + 3, x:x + 3].any():
                out.append(rect("", "ParkingStall", x, y, 3, 3)); n["ParkingStall"] += 1
    # Nav: faixa sobre cada via publica, recortada no mapa
    for w in d["ways"]:
        t = w["tags"]
        hw = t.get("highway")
        if hw not in NAV_W or t.get("tunnel") or t.get("area") == "yes" or len(w["pts"]) < 2:
            continue
        for q in _seg_quads(P(w["pts"]).tolist(), NAV_W[hw] / 2):
            q = _clip_poly(q, 0, 0, NX - 1, NY - 1)
            pts = []
            for x, y in q:
                p = (int(round(x)) + OX, int(round(y)) + OY)
                if not pts or pts[-1] != p:
                    pts.append(p)
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts.pop()
            if len(pts) < 3:
                continue
            ar = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))) / 2
            if ar < 30:
                continue
            flat = ", ".join(f"{x}, {y}" for x, y in pts)
            out.append(f'  {{ name = "", type = "Nav", z = 0, geometry = "polygon", points = {{ {flat} }} }}')
            n["Nav"] += 1
    # Forest: mata em retangulos de 8 m
    S = 8
    gy, gx = NY // S * S, NX // S * S
    wood = (Gm[:gy, :gx] == G_WOOD).reshape(gy // S, S, gx // S, S).mean((1, 3)) > 0.6
    for x, y, w_, h_ in rects(wood):
        out.append(rect("", "Forest", x * S, y * S, w_ * S, h_ * S)); n["Forest"] += 1
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("objects = {\n" + ",\n".join(out) + "\n}\n")
    os.replace(tmp, path)
    return n


# ---------------------------------------------------------------- worldmap
def rects(m):
    """mascara booleana -> retangulos (x, y, w, h) juntando faixas iguais de linhas consecutivas."""
    out, open_ = [], {}
    for y in range(m.shape[0]):
        d = np.diff(np.concatenate([[0], m[y].astype(np.int8), [0]]))
        cur = {}
        for r in zip(np.nonzero(d == 1)[0].tolist(), np.nonzero(d == -1)[0].tolist()):
            cur[r] = (open_[r][0], open_[r][1] + 1) if r in open_ else (y, 1)
        for r, (y0, h) in open_.items():
            if r not in cur:
                out.append((r[0], y0, r[1] - r[0], h))
        open_ = cur
    for r, (y0, h) in open_.items():
        out.append((r[0], y0, r[1] - r[0], h))
    return out


def _shift_or(m, r=1):
    o = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx or dy:
                o |= np.roll(np.roll(m, dy, 0), dx, 1)
    return o


def _shift_and(m, r=1):
    o = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx or dy:
                o &= np.roll(np.roll(m, dy, 0), dx, 1)
    return o


def close3(m):
    return _shift_and(_shift_or(np.pad(m, 1)))[1:-1, 1:-1]


def open3(m):
    return _shift_or(_shift_and(np.pad(m, 1)))[1:-1, 1:-1]


def feats(mask, k, v, x0, y0):
    """retangulos em coordenada de mundo (o vanilla usa coordenada relativa a celula: x0/y0 = 0)."""
    return [(f'<feature><geometry type="Polygon"><coordinates><point x="{x}" y="{y}"/><point x="{x + w}" y="{y}"/>'
             f'<point x="{x + w}" y="{y + h}"/><point x="{x}" y="{y + h}"/></coordinates></geometry>'
             f'<properties><property name="{k}" value="{v}"/></properties></feature>\n')
            for x, y, w, h in rects(mask)]


def worldmap(path, path_forest):
    R = load_raster()
    G, L, Rr, K = R["G"], R["L"], R["R"], R["K"]
    head = "<?xml version='1.0' encoding='UTF-8'?>\n<world version=\"1.0\" cellSize=\"256\">\n"
    n = 0
    with open(path + ".tmp", "w", encoding="utf-8") as f, open(path_forest + ".tmp", "w", encoding="utf-8") as ff:
        f.write(head); ff.write(head)
        for i in range(GN.NCX):
            for j in range(GN.NCY):
                sl = (slice(j * CS, (j + 1) * CS), slice(i * CS, (i + 1) * CS))
                g, l_, r_, k_ = G[sl], L[sl], Rr[sl], K[sl]
                o = feats(g == G_WATER, "water", "river", 0, 0)
                for c in (3, 2, 1):
                    o += feats(r_ == c, "highway", HW[c], 0, 0)
                kb = np.where(l_ > 0, k_, 0)
                for c in range(1, len(CAT)):
                    m = kb == c
                    if m.any():
                        o += feats(close3(m), "building", CAT[c], 0, 0)
                cx, cy = GN.CX0 + i, GN.CY0 + j
                if o:
                    f.write(f'<cell x="{cx}" y="{cy}">\n' + "".join(o) + "</cell>\n")
                    n += 1
                fo = feats(open3((g == G_WOOD) | (g == G_PARK)), "natural", "forest", 0, 0)
                if fo:
                    ff.write(f'<cell x="{cx}" y="{cy}">\n' + "".join(fo) + "</cell>\n")
        f.write("</world>\n"); ff.write("</world>\n")
    os.replace(path + ".tmp", path)
    os.replace(path_forest + ".tmp", path_forest)
    return n
