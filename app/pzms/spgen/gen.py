#!/usr/bin/env python3
"""Gerador de celulas B42 a partir de OSM (copia adaptada de saopaulo/scripts/gen.py + area.py).

Generico: nada fixo de Sao Paulo. A geometria (centro, giro, tamanho, origem no mundo) vem de configure();
as fontes ja projetadas vem de load_sources(dados_osm, extra). Escala 1 tile = 1 m.
Gera por blocos de BS x BS celulas (com margem MG) para caber na RAM; cada bloco roda num processo
(spawn: funcoes de nivel de modulo, estado em G por processo).
Removido do original: MASP, metro/masmorra/portal, galerias de rio, heliponto, aeroporto, camping do
Ibirapuera, regra de altura da Paulista, letreiros/fachadas/postos com folhas proprias (saopaulo_*),
cache incremental. GeoSampa virou fonte opcional (extra["footprints"]).
"""
import collections
import json
import math
import os
import shutil
import struct

import numpy as np
from PIL import Image, ImageDraw

# ---------------------------------------------------------------- geometria (antes area.py), via configure()
CS = 256
LAT0 = LON0 = 0.0
PHI = 0.0
NCX = NCY = NC = 1
CX0 = CY0 = 0
SIZEX = SIZEY = SIZE = CS
MXm = MYm = MX = MY = 0
_c, _s, _k = 1.0, 0.0, 1.0
OUT = RAS = GENDIR = ""
BS, MG = 6, 512                # bloco de BS x BS celulas + MG m de margem (predio cortado na borda)
W = H = BS * CS + 2 * MG       # raster de cada bloco
CFG = {}


def configure(cfg):
    """cfg: lat0, lon0 (centro), phi (graus), ncx, ncy, cx0, cy0, out (pasta cells), gen (pasta gen), bs, mg."""
    global LAT0, LON0, PHI, NCX, NCY, NC, CX0, CY0, SIZEX, SIZEY, SIZE, MXm, MYm, MX, MY, _c, _s, _k
    global OUT, RAS, GENDIR, BS, MG, W, H, CFG
    CFG = dict(cfg)
    LAT0, LON0 = float(cfg["lat0"]), float(cfg["lon0"])
    PHI = math.radians(float(cfg.get("phi", 0.0)))
    NCX, NCY = int(cfg["ncx"]), int(cfg["ncy"])
    NC = max(NCX, NCY)
    CX0, CY0 = int(cfg["cx0"]), int(cfg["cy0"])
    SIZEX, SIZEY = NCX * CS, NCY * CS
    SIZE = max(SIZEX, SIZEY)
    MXm, MYm = int(cfg.get("mxm", SIZEX // 2)), int(cfg.get("mym", SIZEY // 2))
    MX, MY = CX0 * CS + MXm, CY0 * CS + MYm
    _c, _s, _k = math.cos(PHI), math.sin(PHI), math.cos(math.radians(LAT0))
    OUT, GENDIR = cfg["out"], cfg["gen"]
    RAS = os.path.join(GENDIR, "raster")
    BS, MG = int(cfg.get("bs", 6)), int(cfg.get("mg", 512))
    W = H = BS * CS + 2 * MG


def proj(lat, lon):
    """lat/lon -> coordenada local do mapa (0..SIZEX, 0..SIZEY). Aceita numpy."""
    e = (lon - LON0) * 111320.0 * _k
    n = (lat - LAT0) * 110574.0
    return MXm + e * _c - n * _s, MYm - (e * _s + n * _c)


def unproj(x, y):
    xr, yr = x - MXm, -(y - MYm)
    e = xr * _c + yr * _s
    n = -xr * _s + yr * _c
    return LAT0 + n / 110574.0, LON0 + e / (111320.0 * _k)


def _load_tiles():
    """propriedades dos tiles (tiles.json do cache de assets do usuario): env PZMS_SPGEN_TILES."""
    p = os.environ.get("PZMS_SPGEN_TILES")
    if p and os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {}


MAXL = int(os.environ.get("MAXL", "8"))    # teto de andares: torres reais viram 5-8 andares (comp())
FULL = int(os.environ.get("FULL", str(MAXL)))  # todo andar existente e completo: sem andares ocos


def comp(v):
    """andares reais -> andares no jogo: ate 4 igual, acima comprimido (10->6, 16->7, 20+->8)."""
    v = int(round(v))
    return max(1, v if v <= 4 else min(MAXL, 4 + -(-(v - 4) // 4)))
MINFREE = int(os.environ.get("MINFREE_MB", "600")) << 20            # para de escrever celulas com menos de 600 MB livres

# ---------------------------------------------------------------- tiles vanilla
# rua = concreto cinza; calcada = o bloco de asfalto claro (o usuario viu trocado: 2026-11-24)
# rua = asfalto cinza (familia 80 do blends_street_01, igual Dirkerdam); variacoes sutis, base na maioria (sem xadrez)
ASPHALT = ["blends_street_01_80"] * 5 + ["blends_street_01_85", "blends_street_01_86", "blends_street_01_87"]
ASPH_FAM, SIDE_FAM = 80, 48     # familias do blends_street_01: base f, canto f+1..4, borda f+8..11
SIDEWALK = ["blends_street_01_48"] * 6 + ["blends_street_01_53", "blends_street_01_54"]
YARD = ["floors_exterior_street_01_17", "floors_exterior_street_01_19"]
PAVING = ["floors_exterior_tilesandstone_01_4", "floors_exterior_tilesandstone_01_4"]
GRASS = ["blends_natural_01_32", "blends_natural_01_37", "blends_natural_01_38", "blends_natural_01_39"]
GRASS2 = ["blends_natural_01_16", "blends_natural_01_21", "blends_natural_01_22", "blends_natural_01_23"]
DIRT = ["blends_natural_01_64", "blends_natural_01_69", "blends_natural_01_70", "blends_natural_01_71"]  # 02_* e AGUA
TREES = ["vegetation_trees_01_8", "vegetation_trees_01_9", "vegetation_trees_01_10", "vegetation_trees_01_11",
         "vegetation_trees_01_13", "vegetation_trees_01_14", "vegetation_trees_01_15"]
# meio-fio fica no tile de ASFALTO da borda; chave = lado onde esta a calcada (igual Dirkerdam)
CURB = {"N": "street_curbs_01_8", "W": "street_curbs_01_9", "S": "street_curbs_01_10", "E": "street_curbs_01_11"}
STAIRS_X = ["fixtures_stairs_01_2", "fixtures_stairs_01_1", "fixtures_stairs_01_0"]  # oeste -> leste
LINE_X, LINE_Y = "street_trafficlines_01_2", "street_trafficlines_01_0"
LAMP = "lighting_outdoor_01_16"
ROOF = "floors_exterior_street_01_16"
STAIRS = ["fixtures_stairs_01_13", "fixtures_stairs_01_12", "fixtures_stairs_01_11"]
WIN_W, WIN_N = "fixtures_windows_01_0", "fixtures_windows_01_1"
DOOR_EXT = ("fixtures_doors_01_20", "fixtures_doors_01_21")
DOOR_INT = ("fixtures_doors_01_0", "fixtures_doors_01_1")
FRAME_INT = ("fixtures_doors_frames_01_0", "fixtures_doors_frames_01_1")

# grupos de parede: base b -> b W, b+1 N, b+2 NW, b+3 pilar, b+8/9 janela, b+10/11 porta
RES_WALLS = [("walls_exterior_house_01", b) for b in (0, 16, 32, 48)] + \
            [("walls_exterior_house_02", b) for b in (0, 16, 32, 48, 64, 80)]
# (walls_commercial_02_16+ NAO e parede: e faixa de acabamento transparente, virava "muro baixo" no contorno)
COM_WALLS = [("walls_commercial_01", 48), ("walls_commercial_03", 48),
             ("walls_commercial_03", 0), ("walls_commercial_03", 16), ("walls_commercial_03", 32)]
INT_WALLS = [("walls_interior_house_01", b) for b in (0, 16, 32, 48)] + \
            [("walls_interior_house_02", b) for b in (0, 16, 32, 48)]
FLOORS_RES = ["floors_interior_tilesandwood_01_41", "floors_interior_tilesandwood_01_44",
              "floors_interior_tilesandwood_01_45", "floors_interior_carpet_01_0",
              "floors_interior_carpet_01_4"]
FLOORS_COM = ["floors_interior_tilesandwood_01_46", "floors_interior_tilesandwood_01_8",
              "floors_interior_tilesandwood_01_16", "floors_interior_tilesandwood_01_40"]
# varanda: piso + mureta pulavel so no contorno da varanda (padrao Louisville); porta no meio
LOW_W, LOW_N, LOW_NW = "walls_commercial_01_28", "walls_commercial_01_29", "walls_commercial_01_30"
BAL_FLOOR = "floors_exterior_tilesandstone_01_4"
LADDER = {"W": "location_sewer_01_32", "N": "location_sewer_01_33"}   # escada de servico (igual RC)
ROOF_BIG = ["rooftop_furniture_0", "rooftop_furniture_1", "industry_02_148", "industry_02_149",
            "industry_02_150"]                                        # condensadora / exaustor / caixas
DISH = ("appliances_com_01_20", "appliances_com_01_21")
AC_WALL = {"N": "rooftop_furniture_2", "W": "rooftop_furniture_3"}   # ar-condicionado de janela (fachada S / E)
# curva/mistura natural (medido no RC): overlay da familia f no quadrado conforme os lados que sao da familia
BLEND_IDX = {("N", "W"): 1, ("S", "E"): 2, ("S", "W"): 3, ("N", "E"): 4}
BLEND_EDGE = {"N": (8, 12), "W": (9, 13), "E": (10, 14), "S": (11, 15)}
MASP_PILLAR = "industry_01_3"            # pilares vermelhos (perfil industrial) do vao livre
MASP_LV = 4                                # z0-z1 vao livre (8 m), caixa de vidro z2-z3, vigas no teto z4
MASP_Z0 = 2
MASP_GLASS = ("location_shop_mall_01_24", "location_shop_mall_01_25", "location_shop_mall_01_26")
MASP_BEAM = ("industry_01_0", "industry_01_1")
# tiles proprios (arte/folhas, empacotados por scripts/pz_tiles.py)
M1, M2, MA = "saopaulo_masp_01_", "saopaulo_masp_02_", "saopaulo_masp_arte_01_"
MASP_GLASS = (M1 + "8", M1 + "9", M1 + "10")


def masp_pillar(z):
    """pilar vermelho em 4 segmentos: base, meios alternados, topo com encaixe da viga."""
    return M1 + str(0 if z == 0 else 3 if z >= MASP_LV else 1 if z % 2 else 2)


def masp_art(wx, wy):
    """acervo: cavaletes de cristal (Lina Bo Bardi) em grade, esculturas, vitrines, bancos e cordas."""
    a, b_ = wx % 4, wy % 6
    if a == 2 and b_ in (1, 4):
        return MA + str(2 * ((wx // 4 + wy // 6) % 4))          # cavalete S, 4 quadros
    if a == 0 and b_ == 2 and (wx // 4) % 3 == 0:
        return MA + str(8 + (wy // 6) % 2)                       # escultura
    if a == 0 and b_ == 5 and (wx // 4) % 3 == 1:
        return MA + "10"                                         # vitrine
    if a == 0 and b_ == 2 and (wx // 4) % 3 == 2:
        return MA + "12"                                         # banco
    return None
IND_WALLS = ("industry_01", 0)
IND_B = {"industrial", "warehouse", "manufacture", "factory", "hangar", "storage", "depot", "workshop",
         "service", "transformer_tower"}
# cela da delegacia (igual Raccoon City): grade + batente sem porta (cela aberta), beliche, vaso e pia
JAIL_BAR = ("location_community_police_01_0", "location_community_police_01_1")      # W, N
JAIL_FRAME = ("location_community_police_01_10", "location_community_police_01_11")  # batente W, N
JAIL_BUNK = ("furniture_bedding_01_85", "furniture_bedding_01_84")                   # (0,0) + (0,1) ao sul
JAIL_TOILET, JAIL_SINK = "fixtures_bathroom_01_2", "fixtures_sinks_01_29"            # Facing W (parede E)

# ---------------------------------------------------------------- mobilia (conteineres vanilla B42 = loot)
# Facing do tile = lado para onde o movel olha = oposto da parede (conferido no Raccoon City: parede N -> Facing S)
def _f(pre, S=None, E=None, N=None, W=None):
    return {k: f"{pre}_{v}" for k, v in (("S", S), ("E", E), ("N", N), ("W", W)) if v is not None}
FURN = {
    "counter": _f("fixtures_counters_01", N=1, E=3, S=5, W=7),
    "fridge": _f("appliances_refrigeration_01", S=0, E=1, N=2, W=3),
    "stove": _f("appliances_cooking_01", E=0, S=1, W=2, N=3),
    "dresser": _f("furniture_storage_01", E=8, S=9, W=10, N=11),
    "sidetable": _f("furniture_storage_01", S=48, E=49, W=50, N=51),
    "shelf": _f("furniture_shelving_01", S=40, E=41, W=42, N=43),
    "mshelf": _f("furniture_shelving_01", S=28, E=29),              # de parede: so paredes N/W
    "desk": _f("location_community_medical_01", E=106, S=107),       # 1 tile: so paredes N/W
    "bench": _f("location_community_school_01", E=4, S=5, N=6, W=7),
    "filing": _f("location_business_office_generic_01", S=16, E=17, N=24, W=25),
    "locker": _f("furniture_storage_02", S=5, E=4, N=7, W=6),
    "toolcab": _f("location_business_machinery_01", S=32, E=33, N=34, W=35),
    "display": _f("location_shop_generic_01", S=96, W=98, N=100, E=102),
    "grocer": _f("location_shop_generic_01", S=88, E=89, W=90, N=91),
    "mags": _f("location_shop_generic_01", S=24, E=26, W=104, N=106),
    "rack": _f("location_shop_generic_01", E=53, S=54),             # de parede
    "medicine": _f("fixtures_bathroom_01", S=28, E=29),             # de parede
    "toilet": _f("fixtures_bathroom_01", S=0, E=1, W=2, N=3),
    "sink": _f("fixtures_sinks_01", N=0, E=1, S=2, W=3),
    "bakery": _f("location_restaurant_pie_01", S=52, E=53, N=54, W=55),
    "mcrate": {k: "location_military_generic_01_0" for k in "SENW"},  # caixa militar (militarycrate)
    "mlocker": _f("location_military_generic_01", S=22, E=23, N=30, W=31),
    "glocker": _f("furniture_storage_02", S=9, E=8, N=11, W=10),    # armario de ARMAS (PoliceStorageGuns forceForTiles 02_8..11)
    "bookshelf": _f("furniture_shelving_01", S=9, E=10, N=11, W=12),   # estante grande (Big Wall)
    "armchair": _f("furniture_seating_indoor_01", E=8, S=9, W=10, N=11),
    "tvstand": _f("furniture_storage_01", S=48, E=49, W=50, N=51),    # mesinha + TV em cima (TV abaixo)
    "shower": _f("fixtures_bathroom_01", S=32, E=33),                 # box Deluxe
}
FURN["sshelf"] = _f("location_shop_generic_01", S=62, E=63, N=118, W=119)   # prateleira de loja (shelves)
FURN["cooler"] = _f("location_shop_generic_01", S=64, E=67)                   # geladeira de loja (fridge)
FURN["chair"] = _f("furniture_seating_outdoor_01", E=16, S=17, N=18, W=19)    # cadeira plastica
# gondola dupla no meio da loja ("Large Shop", 2 quadrados, container shelves): face -> (0,0), 2o, dx, dy
GONDOLA = {"S": ("location_shop_generic_01_72", "location_shop_generic_01_73", 1, 0),
           "N": ("location_shop_generic_01_76", "location_shop_generic_01_77", 1, 0),
           "E": ("location_shop_generic_01_75", "location_shop_generic_01_74", 0, 1),
           "W": ("location_shop_generic_01_79", "location_shop_generic_01_78", 0, 1)}
ROUND_TABLES = ["furniture_tables_high_01_14", "furniture_tables_high_01_6", "furniture_tables_high_01_7",
                "furniture_tables_high_01_23"]
# miolo do comodo: gondolas (loja), mesas redondas com cadeiras (comer), ou as duas (conveniencia de posto)
ISLAND = {k: "aisle" for k in ("pharmacy", "grocery", "generalstore", "cornerstore", "liquorstore", "departmentstore",
                               "bookstore", "toolstore", "housewarestore", "candystore", "toystore", "petstore",
                               "carsupply", "gardenstore", "paintershop", "artstore", "mall", "giftstore",
                               "electronicstore", "comicstore", "musicstore", "outdoorsupply", "tobaccostore")}
ISLAND.update({k: "tables" for k in ("cafe", "restaurantdining", "bar", "bakery", "icecream")})
ISLAND["gasstore"] = "mix"
TV = _f("appliances_television_01", E=0, S=1, W=2, N=3)
# moveis de 2 quadrados: face -> (tile na origem, tile no 2o quadrado, dx, dy) (SpriteGridPos da tiledef)
TWO = {
    "bed": {"S": ("furniture_bedding_01_1", "furniture_bedding_01_0", 0, 1),
            "E": ("furniture_bedding_01_2", "furniture_bedding_01_3", 1, 0)},
    "couch": {"S": ("furniture_seating_indoor_01_0", "furniture_seating_indoor_01_1", 1, 0),
              "E": ("furniture_seating_indoor_01_3", "furniture_seating_indoor_01_2", 0, 1),
              "N": ("furniture_seating_indoor_01_6", "furniture_seating_indoor_01_7", 1, 0),
              "W": ("furniture_seating_indoor_01_5", "furniture_seating_indoor_01_4", 0, 1)},
    "couch2": {"S": ("furniture_seating_indoor_01_17", "furniture_seating_indoor_01_16", 1, 0),
               "E": ("furniture_seating_indoor_01_19", "furniture_seating_indoor_01_18", 0, 1),
               "N": ("furniture_seating_indoor_01_20", "furniture_seating_indoor_01_21", 1, 0),
               "W": ("furniture_seating_indoor_01_23", "furniture_seating_indoor_01_22", 0, 1)},
    "bath": {"S": ("fixtures_bathroom_01_25", "fixtures_bathroom_01_24", 0, 1),
             "E": ("fixtures_bathroom_01_26", "fixtures_bathroom_01_27", 1, 0)},
}
FRONT = {"S": (0, 1), "E": (1, 0), "N": (0, -1), "W": (-1, 0)}

# ---- variacoes de movel (lidas do tiledef vanilla): cada comodo sorteia um estilo por tipo
def _vpool(pre, cname, groups=None, skip=()):
    """[(grupo, {Facing: tile})] de moveis de 1 quadrado com as 4 faces."""
    g = collections.defaultdict(dict)
    for n, p_ in _TD.items():
        if n.startswith(pre) and p_.get("CustomName") == cname and "SpriteGridPos" not in p_:
            gn = p_.get("GroupName", "")
            if (groups is None or gn in groups) and gn not in skip and p_.get("Facing"):
                g[gn][p_["Facing"]] = n
    return [(k, v) for k, v in sorted(g.items()) if len(v) == 4]


def _vpool2(pre, cname, groups=None, skip=()):
    """[(grupo, {Facing: (tile 0,0, tile 2o, dx, dy)})] de moveis de 2 quadrados."""
    g = collections.defaultdict(lambda: collections.defaultdict(dict))
    for n, p_ in _TD.items():
        if n.startswith(pre) and p_.get("CustomName") == cname and p_.get("Facing"):
            gn = p_.get("GroupName", "")
            if (groups is None or gn in groups) and gn not in skip:
                g[gn][p_["Facing"]][p_.get("SpriteGridPos", "")] = n
    out = []
    for gn, fs in sorted(g.items()):
        d = {}
        for f, pos in fs.items():
            if len(pos) == 2 and "0,0" in pos and ("1,0" in pos or "0,1" in pos):
                k2 = "1,0" if "1,0" in pos else "0,1"
                d[f] = (pos["0,0"], pos[k2], int(k2[0]), int(k2[2]))
        if d:
            out.append((gn, d))
    return out


_TD = _load_tiles()
_COMFY = None
VAR = {
    "counter": _vpool("fixtures_counters_01", "Counter",
                      {"Modern", "Wooden", "Birchwood", "Dark", "Green", "Oak", "White"}),
    "fridge": _vpool("appliances_refrigeration_01", "Fridge",
                     {"White", "Blue", "Green", "Steel", "Plain", "Red"}),
    "stove": _vpool("appliances_cooking_01", "Oven", {"Green", "Grey", "Modern", "Red"}),
    "dresser": _vpool("furniture_storage_01", "Drawers", skip={"Bedroom"}),
    "sidetable": _vpool("furniture_storage_01", "Drawers", {"Bedroom"}) +
                 _vpool("furniture_storage_01", "Table", {"Small"}),
    "shelf": _vpool("furniture_shelving_01", "Shelves", {"Oakwood", "White Fancy", "Big Wall", "Hardwood Wall",
                                                          "Dark Wall", "Lightwood Wall", "White Wall"}),
    "armchair": _vpool("furniture_seating_indoor", "Chair",
                       skip={"Black Office", "Blue Plastic", "Grey Plastic", "Folding", "Grey", "Black Fancy",
                             "Fancy White", "Fancy Wooden", "Wooden", "Dark Wooden", "Red Wooden", "White Wooden",
                             "Green Dinner", "White Simple", "Modern White"}),
    "tv": _vpool("appliances_television_01", "Television"),
    "toilet": _vpool("fixtures_bathroom", "Toilet", {"Fancy", "Hanging", "Low"}),
    "sink": _vpool("fixtures_sinks", "Sink", {"White", "Beige", "Chrome", "White Standing"}),
}
VAR["bookshelf"] = VAR["shelf"]
VAR2 = {
    "couch": _vpool2("furniture_seating_indoor", "Couch"),
    "bed": _vpool2("furniture_bedding_01", "Bed", skip={"Hospital", "Stretcher"}) +
           _vpool2("furniture_bedding_01", "Beds", {"Twin"}),
    "wardrobe": _vpool2("furniture_storage", "Wardrobe"),
}
VAR2["couch2"] = VAR2["couch"]
TWO["wardrobe"] = VAR2["wardrobe"][0][1] if VAR2["wardrobe"] else {}
FURN["wardrobe"] = {}


def room_style(seed):
    """estilo do comodo: {tipo: dict de faces}; sofa e poltrona do mesmo grupo quando existe."""
    st = {}
    for i, (k, pool) in enumerate(sorted(VAR.items()) + sorted(VAR2.items())):
        if pool:
            st[k] = pool[h32(seed, 7001 + i) % len(pool)]
    if "couch" in st:
        same_ = [v for gn, v in VAR["armchair"] if gn == st["couch"][0]]
        if same_:
            st["armchair"] = (st["couch"][0], same_[0])
    return {k: v[1] for k, v in st.items()}
# piso proprio por comodo (azulejo no banheiro, ladrilho na cozinha)
ROOM_FLOOR = {"bathroom": ["floors_interior_tilesandwood_01_5", "floors_interior_tilesandwood_01_11",
                           "floors_interior_tilesandwood_01_2"],
              "kitchen": ["floors_interior_tilesandwood_01_4", "floors_interior_tilesandwood_01_10",
                          "floors_interior_tilesandwood_01_3"]}
REGISTER = _f("location_shop_accessories_01", E=0, S=1, N=2, W=3)   # em cima do 1o balcao da loja
BED = {"S": ("furniture_bedding_01_1", "furniture_bedding_01_0"),   # parede N: cabeceira (0,0) + pe (0,1) ao sul
       "E": ("furniture_bedding_01_2", "furniture_bedding_01_3")}   # parede W: (0,0) + (1,0) a leste
FACE = {"N": "S", "W": "E", "S": "N", "E": "W"}                      # parede -> Facing
# por comodo: (itens fixos, itens que repetem para encher a loja, caixa registradora)
FURNISH = {
    "kitchen": (["counter", "stove", "counter", "fridge", "counter", "counter", "counter", "counter"], [], False),
    "bathroom": (["toilet", "sink", "bath", "medicine", "shower", "counter"], ["counter", "mshelf"], 6),
    "bedroom": (["bed", "dresser", "sidetable", "wardrobe", "shelf"], [], False),
    "livingroom": (["couch", "tvstand", "bookshelf", "armchair", "sidetable", "couch2", "bookshelf"], [], False),
    "office": (["desk", "filing", "desk", "shelf"], ["filing", "desk"], False),
    "medicaloffice": (["desk", "filing", "counter"], [], False),
    "classroom": (["desk", "shelf"], ["bench"], 4),
    "hospitalroom": (["counter"], ["bed", "sidetable", "mshelf"], False),
    "medical": (["counter", "desk"], ["shelf", "mshelf", "counter"], False),
    "library": (["counter"], ["shelf"], False),
    "storage": ([], ["mshelf", "shelf"], False),
    "policestorage": (["filing"], ["locker", "mshelf"], False),
    "firestorage": (["toolcab"], ["locker", "mshelf"], False),
    "post": (["counter", "desk"], ["mshelf", "locker"], False),
    "lobby": (["counter"], [], False),
    "theatre": (["counter"], ["shelf", "counter"], 15),
    "church": (["counter"], ["shelf", "sidetable"], 15),
    "hall": (["sidetable"], [], False),
    "glassesstore": (["counter"], ["display", "shelf"], True),
    "grocery": (["counter", "cooler", "cooler"], ["sshelf", "grocer", "cooler"], True),
    "generalstore": (["counter", "cooler"], ["sshelf", "sshelf", "mshelf"], True),
    "pharmacy": (["counter", "cooler", "mags"], ["sshelf"], True),
    "bookstore": (["counter"], ["shelf", "sshelf"], True),
    "giftstore": (["counter"], ["shelf", "display"], True),
    "gasstore": (["counter", "cooler", "cooler", "mags"], ["cooler", "sshelf", "cooler", "sshelf"], True),
    "liquorstore": (["counter", "cooler"], ["sshelf", "cooler"], True),
    "toolstore": (["counter"], ["shelf", "toolcab"], True),
    "shoestore": (["counter"], ["shelf"], True),
    "artstore": (["counter"], ["shelf", "mshelf"], True),
    "electronicstore": (["counter"], ["shelf", "display"], True),
    "sportstore": (["counter"], ["rack", "counter"], True),
    "jewelrystore": (["counter"], ["display"], True),
    "clothingstore": (["counter"], ["rack", "shelf"], True),
    "furniturestore": (["counter"], ["dresser", "sidetable", "shelf"], True),
    "bakery": (["counter", "cooler", "bakery"], ["bakery", "sshelf"], True),
    "butcher": (["counter"], ["fridge", "mshelf"], True),
    "cafe": (["counter", "stove", "cooler"], ["counter", "sshelf"], True),
    "restaurantdining": (["counter", "cooler"], ["counter"], True),
    "bar": (["counter", "cooler", "cooler"], ["counter", "sshelf"], True),
    "burgerkitchen": (["counter", "stove", "fridge"], ["counter", "mshelf"], False),
    # industrial (progressao: ferramentas, metal, solda, madeira, pecas de carro)
    "warehouse": ([], ["mshelf", "shelf", "mshelf"], 8),
    "factory": (["toolcab", "counter"], ["mshelf", "toolcab", "counter"], 8),
    "factorystorage": ([], ["mshelf", "shelf"], 6),
    "metalfabrication": (["toolcab", "counter"], ["toolcab", "mshelf"], 8),
    "metalshop": (["toolcab", "counter"], ["toolcab", "mshelf"], 8),
    "weldingworkshop": (["toolcab", "counter"], ["toolcab", "mshelf"], 8),
    "carpentryworkshop": (["toolcab", "counter"], ["mshelf", "counter"], 8),
    "mechanic": (["toolcab", "counter"], ["toolcab", "mshelf"], 8),
    "garagestorage": (["toolcab"], ["mshelf", "toolcab"], 8),
    "storageunit": ([], ["mshelf", "shelf"], 8),
    # delegacia
    "policeoffice": (["desk", "filing", "desk"], ["filing", "desk"], False),
    "policelocker": (["locker"], ["locker"], 4),
    "policegunstorage": (["glocker", "mshelf"], ["glocker", "locker"], 4),
    "armystorage": (["mlocker", "mcrate"], ["mcrate", "mshelf", "mlocker"], 5),
    "camping": ([], [], False),
    "evidenceroom": (["filing"], ["mshelf", "filing"], 5),
    "prisoncells": ([], [], False),
    # comercio extra
    "carsupply": (["counter"], ["mshelf", "shelf"], True),
    "gardenstore": (["counter"], ["shelf", "mshelf"], True),
    "petstore": (["counter"], ["shelf"], True),
    "toystore": (["counter"], ["shelf", "display"], True),
    "musicstore": (["counter"], ["shelf", "display"], True),
    "gunstore": (["counter"], ["rack", "display", "locker"], True),
    "departmentstore": (["counter"], ["rack", "shelf", "display"], True),
    "cornerstore": (["counter", "cooler", "cooler"], ["sshelf", "cooler"], True),
    "laundry": (["counter"], ["mshelf", "shelf"], True),
    "tailoringstore": (["counter"], ["rack", "shelf"], True),
    "pawnshop": (["counter"], ["display", "shelf"], True),
    "tobaccostore": (["counter"], ["shelf"], True),
    "candystore": (["counter"], ["shelf", "grocer"], True),
    "outdoorsupply": (["counter"], ["rack", "shelf"], True),
    "paintershop": (["counter"], ["mshelf", "shelf"], True),
    "camerastore": (["counter"], ["display"], True),
    "housewarestore": (["counter"], ["shelf", "display"], True),
    "knifestore": (["counter"], ["display"], True),
    "comicstore": (["counter"], ["shelf", "mags"], True),
    "icecream": (["counter", "cooler"], ["cooler"], True),
    "dentist": (["desk", "counter"], ["medicine", "counter"], False),
    "daycare": (["shelf"], ["bench", "shelf"], 6),
    "gym": (["locker"], ["locker", "shelf"], 8),
    # quarto de hotel grande (66 m2): repete cama/criado/comoda ~1 a cada 5 m2 (RC ~18/100 m2)
    "motelroom": (["bed", "dresser", "sidetable", "counter"], ["bed", "sidetable", "dresser"], 5),
    "greenhouse": ([], ["shelf"], 10),
    "barn": (["toolcab"], ["mshelf"], 12),
    "artstore": (["counter"], ["shelf", "mshelf"], True),
    "hall": (["sidetable"], [], False),
    "mall": (["counter"], ["shelf"], True),
}
STOREISH = ("store", "shop", "supply")


def furnish(add, rname, cells_, same, z, dsq, stz, seed):
    """Poe conteineres encostados nas paredes do comodo, sem bloquear porta, escada nem passagem."""
    dflt = (["counter"], ["sshelf", "mshelf"], True) if any(s in rname for s in STOREISH) else \
        ([], ["mshelf", "shelf"], 8)      # todo comodo tem loot
    fx, rep, reg = FURNISH.get(rname, dflt)
    per = reg if isinstance(reg, int) and not isinstance(reg, bool) else 5   # m2 por item (RC: ~10-27/100m2)
    reg = reg is True
    if not fx and not rep:
        return 0
    C = set(cells_)
    near = lambda x, y, S_: any((x + a, y + b) in S_ for a in (-1, 0, 1) for b in (-1, 0, 1))
    used, keep = set(), set()
    cand = []
    for x, y in sorted(C, key=lambda c: (h32(seed, c[0], c[1]), c)):
        if near(x, y, stz) or any((x + a, y + b, z) in dsq for a in (-1, 0, 1) for b in (-1, 0, 1)):
            continue
        walls = [d for d, (a, b) in (("N", (0, -1)), ("W", (-1, 0)), ("S", (0, 1)), ("E", (1, 0)))
                 if not same(x + a, y + b)]
        if not walls or ({"N", "S"} <= set(walls) and {"W", "E"} <= set(walls)):
            continue
        if {"N", "S"} <= set(walls) or {"W", "E"} <= set(walls):
            continue    # corredor de 1 tile: nao bloqueia
        cand.append((x, y, walls))
    if not cand:
        return 0
    cap = max(len(fx), min(len(C) // per, 24))
    items = list(fx) + [rep[i % len(rep)] for i in range(cap - len(fx))] if rep else list(fx)
    n = 0
    first_counter = reg
    sty = room_style(seed)
    for kind in items:
        for x, y, walls in cand:
            if (x, y) in used or (x, y) in keep:
                continue
            if kind in TWO:
                two = sty.get(kind) or TWO[kind]
                ok = None
                for w in walls:
                    f = FACE[w]
                    if f not in two:
                        continue
                    t1, t2, dx, dy = two[f]
                    x2, y2 = x + dx, y + dy
                    if (x2, y2) not in C or (x2, y2) in used or (x2, y2) in keep or near(x2, y2, stz) or \
                            any((x2 + a, y2 + b, z) in dsq for a in (-1, 0, 1) for b in (-1, 0, 1)):
                        continue
                    ok = (f, t1, t2, x2, y2); break
                if not ok:
                    continue
                f, t1, t2, x2, y2 = ok
                add(x, y, z, t1); add(x2, y2, z, t2)
                used |= {(x, y), (x2, y2)}
                a, b = FRONT[f]
                keep |= {(x + a, y + b), (x2 + a, y2 + b)}
                n += 1
                break
            opts = sty.get(kind) or FURN[kind]
            w = next((d for d in walls if FACE[d] in opts), None)
            if not w:
                continue
            f = FACE[w]
            add(x, y, z, opts[f])
            if kind == "tvstand":
                add(x, y, z, (sty.get("tv") or TV)[f])
            if kind == "counter" and first_counter:
                add(x, y, z, REGISTER[f]); first_counter = False
            used.add((x, y))
            a, b = {"N": (0, 1), "S": (0, -1), "W": (1, 0), "E": (-1, 0)}[w]
            keep.add((x + a, y + b))          # passagem na frente do movel
            n += 1
            break
    if rname in ISLAND:
        n += islands(add, ISLAND[rname], C, used | keep, z, dsq, stz, seed)
    return n


def islands(add, mode, C, busy, z, dsq, stz, seed):
    """miolo do comodo (>= 2 tiles de qualquer parede, porta ou escada): gondolas duplas em fileiras com
    corredor de 2, e/ou mesas redondas com 2 cadeiras plasticas."""
    def far(x, y, r):
        return all((x + a, y + b) in C for a in range(-r, r + 1) for b in range(-r, r + 1))
    I = {c for c in C if far(c[0], c[1], 2) and c not in busy and
         not any((c[0] + a, c[1] + b) in stz for a in range(-2, 3) for b in range(-2, 3)) and
         not any((c[0] + a, c[1] + b, z) in dsq for a in range(-2, 3) for b in range(-2, 3))}
    if len(I) < 4:
        return 0
    xs, ys = [c[0] for c in I], [c[1] for c in I]
    x0, y0 = min(xs), min(ys)
    occ, n = set(), 0
    if mode in ("tables", "mix"):
        lim = 2 if mode == "mix" else 99
        tb = ROUND_TABLES[h32(seed, 91) % len(ROUND_TABLES)]
        for y in range(y0, max(ys) + 1, 3):
            for x in range(x0 + 1, max(xs) + 1, 4):
                if lim <= 0:
                    break
                cs = [(x - 1, y), (x, y), (x + 1, y)]
                if all(c in C and c not in busy and c not in occ for c in cs) and (x, y) in I:
                    add(x, y, z, tb)
                    add(x - 1, y, z, FURN["chair"]["E"]); add(x + 1, y, z, FURN["chair"]["W"])
                    occ |= {(x + a, y + b) for a in range(-2, 3) for b in (-1, 0, 1)}
                    n += 1; lim -= 1
        if mode == "tables":
            return n
    # gondolas ao longo do eixo mais comprido; pares costas com costas, corredor de 2 e travessa a cada 6
    horiz = (max(xs) - x0) >= (max(ys) - y0)
    for (x, y) in sorted(I):
        u, v = (x - x0, y - y0) if horiz else (y - y0, x - x0)
        if v % 4 not in (0, 1) or u % 7 not in (0, 2, 4):
            continue
        if horiz:
            f = "N" if v % 4 == 0 else "S"
        else:
            f = "W" if v % 4 == 0 else "E"
        t1, t2, dx, dy = GONDOLA[f]
        x2, y2 = x + dx, y + dy
        if (x2, y2) not in I or {(x, y), (x2, y2)} & occ:
            continue
        add(x, y, z, t1); add(x2, y2, z, t2)
        occ |= {(x, y), (x2, y2)}
        n += 1
    return n

ROAD_W = {"motorway": 20, "trunk": 18, "primary": 16, "secondary": 13, "tertiary": 10,
          "motorway_link": 8, "trunk_link": 8, "primary_link": 8, "secondary_link": 7,
          "tertiary_link": 7, "residential": 8, "unclassified": 8, "living_street": 7,
          "service": 5, "busway": 7, "road": 7}
FOOT_W = {"pedestrian": 6, "footway": 2, "path": 2, "steps": 2, "cycleway": 2}
LINED = {"motorway", "trunk", "primary", "secondary", "tertiary"}

# codigos de chao (G)
G_DEF, G_ASPH, G_SIDE, G_GRASS, G_WOOD, G_PAVE, G_YARD, G_PARK, G_WATER = range(9)
WATER = ["blends_natural_02_0", "blends_natural_02_5", "blends_natural_02_6", "blends_natural_02_7"]  # tem prop water
WAY_W = {"river": 10, "canal": 8, "stream": 4, "drain": 3, "ditch": 2}   # largura dos cursos abertos (m)
UG_W = {"river": (10, 6), "canal": (8, 4), "stream": (6, 2)}   # galeria subterranea: (largura total, agua)
UG_GAP = 110                   # 1 escada de acesso a galeria a cada ~110 m


def h32(*a):
    """hash deterministico pequeno para variacoes."""
    x = 2166136261
    for v in a:
        x = ((x ^ (int(v) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    return x



# ---------------------------------------------------------------- fontes compactas (ja projetadas)
class Store:
    """Feicoes projetadas no mapa: lista de aneis float32 (0 = externo) + bbox + tags."""

    def __init__(self):
        self.rings, self.tags, self.ids, self.bbl = [], [], [], []

    def add(self, rings, tags, fid=0):
        rings = [r for r in rings if len(r) >= 2]
        if not rings:
            return
        a = rings[0]
        bb = (float(a[:, 0].min()), float(a[:, 1].min()), float(a[:, 0].max()), float(a[:, 1].max()))
        if bb[2] < -MG or bb[0] > SIZEX + MG or bb[3] < -MG or bb[1] > SIZEY + MG:
            return
        self.rings.append(rings); self.tags.append(tags); self.ids.append(fid); self.bbl.append(bb)

    def freeze(self):
        self.bb = np.array(self.bbl, np.float32).reshape(-1, 4)
        del self.bbl
        return self

    def sel(self, x0, y0, x1, y1):
        b = self.bb
        return np.nonzero((b[:, 2] >= x0) & (b[:, 0] <= x1) & (b[:, 3] >= y0) & (b[:, 1] <= y1))[0]


def pj(latlon):
    a = np.asarray(latlon, np.float64)
    x, y = proj(a[:, 0], a[:, 1])
    return np.stack([x, y], 1).astype(np.float32)


def load_sources(d, extra=None):
    """d = {"areas":[{id,tags,rings:[{outer:[(lat,lon)],inner:[...]}]}], "ways":[{id,tags,pts}],
    "pois":[{id,lat,lon,tags}], "trees":[(lat,lon)]}  (osmread). extra["footprints"] = GeoJSON(.gz) opcional
    de contornos de predio (altura em height / qt_altura_edificacao / building:levels)."""
    import gzip
    extra = extra or {}
    OB, OA, OL = Store(), Store(), Store()
    for a in d["areas"]:
        t = a["tags"]
        for r in a["rings"]:
            if len(r["outer"]) < 3:
                continue
            rings = [pj(r["outer"])] + [pj(i) for i in r["inner"] if len(i) >= 3]
            (OB if t.get("building") else OA).add(rings, t, a["id"])
    for w in d["ways"]:
        if len(w["pts"]) >= 2:
            OL.add([pj(w["pts"])], w["tags"], w["id"])
    pois = [p for p in d.get("pois", []) if p["tags"].get("shop") or p["tags"].get("amenity")]
    PXY = pj([(p["lat"], p["lon"]) for p in pois]) if pois else np.zeros((0, 2), np.float32)
    PT = [p["tags"] for p in pois]
    GB = Store()
    fp = extra.get("footprints")
    if fp:
        op = gzip.open if str(fp).endswith(".gz") else open
        with op(fp, "rt", encoding="utf-8") as f:
            fs = json.load(f)["features"]
        for k, f in enumerate(fs):
            g = f.get("geometry") or {}
            if g.get("type") not in ("Polygon", "MultiPolygon"):
                continue
            polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
            pr = f.get("properties") or {}
            hgt = 0.0
            for hk in ("qt_altura_edificacao", "height", "altura"):
                try:
                    hgt = float(str(pr.get(hk) or 0).replace("m", "").replace(",", "."))
                    if hgt > 0:
                        break
                except ValueError:
                    pass
            if hgt <= 0:
                try:
                    hgt = 3.0 * float(pr.get("building:levels") or 0)
                except ValueError:
                    hgt = 0.0
            for poly in polys:
                rings = [pj([(p[1], p[0]) for p in ring]) for ring in poly if len(ring) >= 3]
                if rings:
                    GB.add(rings, {"h": hgt}, int(pr.get("cd_identificador") or k + 1))
        del fs
    tr = d.get("trees") or []
    TXY = pj(tr) if len(tr) else np.zeros((0, 2), np.float32)
    return {"OB": OB.freeze(), "OA": OA.freeze(), "OL": OL.freeze(), "GB": GB.freeze(),
            "PXY": PXY, "PT": PT, "TXY": TXY}


# ---------------------------------------------------------------- raster global
def levels_of(t, area_m2):
    for k in ("building:levels", "levels"):
        try:
            v = float(str(t.get(k, "")).split(";")[0].replace(",", "."))
            if v > 0:
                return comp(v)
        except ValueError:
            pass
    try:
        hgt = float(str(t.get("height", "")).replace("m", "").replace(",", ".").strip())
        if hgt > 0:
            return comp(hgt / 3.0)
    except ValueError:
        pass
    b = t.get("building", "yes")
    if b in ("house", "detached", "terrace", "semidetached_house", "garage", "shed", "kiosk"):
        return 1 if b in ("garage", "shed", "kiosk") else 2
    if b in ("apartments", "residential", "hotel", "office"):
        return comp(6 if area_m2 < 400 else 10)
    if area_m2 < 120:
        return 2
    if area_m2 < 400:
        return 3
    if area_m2 < 1200:
        return 5
    return 8


def snap_poly(pts):
    """Gira o poligono em torno do centroide para alinhar ao grid se estiver a <20 graus."""
    if len(pts) < 4:
        return pts
    num = den = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy)
        if L < 1e-6:
            continue
        a = math.atan2(dy, dx) * 4.0        # mod 90 graus
        num += L * math.sin(a); den += L * math.cos(a)
    alpha = math.atan2(num, den) / 4.0
    if abs(math.degrees(alpha)) > 20 or abs(alpha) < 1e-3:
        return pts
    cx = sum(p[0] for p in pts) / len(pts); cy = sum(p[1] for p in pts) / len(pts)
    c, s = math.cos(-alpha), math.sin(-alpha)
    return [(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c) for x, y in pts]


def poly_area(pts):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))) / 2


def build_rasters(rx0, ry0):
    """Rasteriza o bloco cuja origem (canto NW do raster, com margem) e (rx0, ry0) no mapa."""
    S = G["src"]
    box = (rx0, ry0, rx0 + W, ry0 + H)
    off = np.array([rx0, ry0], np.float32)

    def P(a):
        return [tuple(p) for p in (a - off).tolist()]

    G_ = Image.new("L", (W, H), G_DEF)
    dG = ImageDraw.Draw(G_)
    # 1) usos do solo
    order = []
    LU = Image.new("L", (W, H), 0)   # 1 residencial, 2 comercial (classifica building=yes)
    dU = ImageDraw.Draw(LU)
    OA = S["OA"]
    ZN = Image.new("L", (W, H), 0)   # 1 quartel (exercito), 2 hospital, 3 governo, 4 Parque Ibirapuera
    dZ = ImageDraw.Draw(ZN)
    for i in OA.sel(*box):
        t = OA.tags[i]
        rings = OA.rings[i]
        lu = t.get("landuse")
        zc = 1 if lu == "military" and t.get("amenity") not in ("police", "fire_station") and \
            "pol" not in (t.get("name") or "").lower() else \
            2 if t.get("amenity") == "hospital" else \
            3 if t.get("amenity") in ("townhall", "courthouse") or t.get("office") == "government" else \
            0
        if zc and len(rings[0]) >= 3:
            dZ.polygon(P(rings[0]), fill=zc)
        v = 1 if lu == "residential" else 2 if lu in ("commercial", "retail") else 3 if lu == "industrial" else 0
        if v:
            dU.polygon(P(rings[0]), fill=v)
        code = None
        if lu in ("residential", "commercial", "retail", "industrial", "construction", "religious", "railway"):
            code = G_YARD
        if t.get("amenity") in ("school", "university", "hospital", "college"):
            code = G_YARD
        if t.get("leisure") in ("park", "garden", "pitch", "playground", "recreation_ground") or \
                lu in ("grass", "recreation_ground", "village_green", "meadow", "cemetery"):
            code = G_PARK if t.get("leisure") in ("park", "garden") else G_GRASS
        if t.get("natural") in ("wood", "scrub") or lu == "forest":
            code = G_WOOD
        if t.get("natural") == "water" or t.get("water") or t.get("waterway") == "riverbank" or \
                lu in ("reservoir", "basin"):
            code = G_WATER
        if t.get("amenity") == "parking" or t.get("parking") == "surface":
            if t.get("parking") in ("multi-storey", "underground", "rooftop"):
                continue
            code = G_ASPH
        if t.get("highway") == "pedestrian" or t.get("place") == "square":
            code = G_PAVE
        if code is None:
            continue
        o = P(rings[0])
        order.append((poly_area(o), code, o, [P(r) for r in rings[1:]]))
    order.sort(key=lambda z: -z[0])            # grandes primeiro, pequenos por cima
    for _, code, o, inner in order:
        if len(o) >= 3:
            dG.polygon(o, fill=code)
            for i in inner:
                if len(i) >= 3:
                    dG.polygon(i, fill=G_DEF)
    LUa = np.array(LU, dtype=np.uint8)

    # 2) vias
    roads = []
    OL = S["OL"]
    for i in OL.sel(*box):
        t = OL.tags[i]
        hw = t.get("highway")
        if not hw or t.get("tunnel") in ("yes", "building_passage") or str(t.get("layer", "0")).startswith("-"):
            continue
        if t.get("area") == "yes" or t.get("covered") == "yes" or t.get("indoor") == "yes":
            continue
        pts = P(OL.rings[i][0])
        if hw in ROAD_W:
            wd = ROAD_W[hw]
            try:
                wd = max(wd, int(float(t["lanes"]) * 3.3 + 1))
            except (KeyError, ValueError):
                pass
            if t.get("service") in ("driveway", "parking_aisle"):
                wd = 4
            roads.append((wd, G_ASPH, pts, hw, t))
        elif hw in FOOT_W:
            roads.append((FOOT_W[hw], G_PAVE if hw == "pedestrian" else G_SIDE, pts, hw, t))
    # cursos d'agua abertos (canalizados/tunel ficam de fora); vias desenhadas depois = pontes
    for i in OL.sel(*box):
        t = OL.tags[i]
        k = t.get("waterway")
        if k in WAY_W and not t.get("tunnel") and t.get("covered") != "yes" and t.get("layer", "0")[:1] != "-":
            pts = P(OL.rings[i][0])
            if len(pts) >= 2:
                dG.line(pts, fill=G_WATER, width=WAY_W[k], joint="curve")
    # cursos canalizados/tunel: galeria no subsolo (z-1) = calcada de concreto + canal d'agua no meio
    UG = Image.new("L", (W, H), 0)
    dU = ImageDraw.Draw(UG)
    under = []
    for i in OL.sel(*box):
        t = OL.tags[i]
        k = t.get("waterway")
        if k in UG_W and (t.get("tunnel") or t.get("covered") == "yes" or t.get("layer", "0")[:1] == "-"):
            pts = P(OL.rings[i][0])
            if len(pts) >= 2:
                under.append((UG_W[k], pts))
    for (gw, ww), pts in under:
        dU.line(pts, fill=1, width=gw, joint="curve")
    for (gw, ww), pts in under:
        dU.line(pts, fill=2, width=ww, joint="curve")
    G["ug"] = np.array(UG, dtype=np.uint8)
    roads.sort(key=lambda r: (r[1] == G_ASPH, r[0]))
    PUB = Image.new("L", (W, H), 0)     # vias publicas: so elas cortam predio
    dP = ImageDraw.Draw(PUB)
    for wd, code, pts, hw, t in roads:
        if len(pts) >= 2:
            dG.line(pts, fill=code, width=wd, joint="curve")
            if code == G_ASPH and hw != "service":
                dP.line(pts, fill=1, width=max(3, wd - 2), joint="curve")
    Ga = np.array(G_, dtype=np.uint8)
    pub = np.array(PUB, dtype=np.uint8) > 0
    MAIN = Image.new("L", (W, H), 0)    # faixa de ~40 m de cada lado das avenidas (comercio)
    dM = ImageDraw.Draw(MAIN)
    for wd, code, pts, hw, t in roads:
        if hw in ("motorway", "trunk", "primary", "secondary") and len(pts) >= 2:
            dM.line(pts, fill=1, width=wd + 80, joint="curve")
    MAINa = np.array(MAIN, dtype=np.uint8)

    # linhas: central (mao dupla, 1 continua) e divisoria de faixas (mao unica, 3 tracejada)
    LN = Image.new("L", (W, H), 0)
    dL = ImageDraw.Draw(LN)
    for wd, code, pts, hw, t in roads:
        if code != G_ASPH or len(pts) < 2:
            continue
        oneway = t.get("oneway") in ("yes", "-1") or hw.endswith("_link")
        try:
            lanes = int(float(t.get("lanes", "0")))
        except ValueError:
            lanes = 0
        if not oneway and hw in LINED:
            offs, dash = [0.0], 0
        elif lanes >= 2 and hw in LINED | {"residential", "unclassified"}:
            offs, dash = [(k - lanes / 2) * wd / lanes for k in range(1, lanes)], 2
        else:
            continue
        for p, q in zip(pts, pts[1:]):
            dx, dy = q[0] - p[0], q[1] - p[1]
            L = math.hypot(dx, dy)
            if L < 1e-6:
                continue
            nx, ny = -dy / L, dx / L
            v = (1 if abs(dx) >= abs(dy) else 2) + dash
            for o in offs:
                dL.line([(p[0] + nx * o, p[1] + ny * o), (q[0] + nx * o, q[1] + ny * o)], fill=v, width=1)
    LNa = np.array(LN, dtype=np.uint8)
    LNa[Ga != G_ASPH] = 0

    # 3) calcadas: anel de 3 m em volta do asfalto
    asph = Ga == G_ASPH
    near = np.zeros_like(asph)
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            if dx * dx + dy * dy <= 10:
                near |= np.roll(np.roll(asph, dy, 0), dx, 1)
    side = near & ~asph & (Ga != G_PAVE) & (Ga != G_WATER)
    Ga[side] = G_SIDE

    # 4) predios: contorno e altura do GeoSampa; tipo/nome do OSM; OSM completa onde o GeoSampa nao tem
    OB, GB = S["OB"], S["GB"]
    osm = [None]
    canop = []                                  # coberturas de posto: (contorno, tags, area)
    for i in OB.sel(*box):
        t = OB.tags[i]
        b = t.get("building")
        if b == "roof" and t.get("amenity") == "fuel":
            o = P(OB.rings[i][0])
            if len(o) >= 3 and poly_area(o) >= 12:
                canop.append((o, t, poly_area(o)))
        if not b or b in ("roof", "no", "ruins", "collapsed", "bridge") or "building:part" in t:
            continue
        name = (t.get("name") or "").lower()
        ismasp = False                         # (MASP do original: removido)
        try:
            if float(t.get("building:min_level", "0") or 0) > 0 and not ismasp:
                continue
        except ValueError:
            pass
        o = P(OB.rings[i][0])
        ar = poly_area(o)
        if len(o) < 3 or ar < 12:
            continue
        osm.append((ar, o, t, ismasp, [P(r) for r in OB.rings[i][1:]], (2, OB.ids[i])))
    osm[1:] = sorted(osm[1:], key=lambda z: -z[0])
    OBr = Image.new("I", (W, H), 0)
    dOB = ImageDraw.Draw(OBr)
    for j in range(1, len(osm)):
        dOB.polygon(osm[j][1], fill=j)
    OBa = np.array(OBr, dtype=np.int32)
    CNr = Image.new("I", (W, H), 0)
    dCN = ImageDraw.Draw(CNr)
    for j, c in enumerate(canop):
        dCN.polygon(c[0], fill=j + 1)
    CNa = np.array(CNr, dtype=np.int32)
    GSr = Image.new("L", (W, H), 0)
    dGS = ImageDraw.Draw(GSr)
    items = []
    for i in GB.sel(*box):
        o = P(GB.rings[i][0])
        ar = poly_area(o)
        if len(o) < 3 or ar < 12:
            continue
        cx_ = int(sum(p[0] for p in o) / len(o)); cy_ = int(sum(p[1] for p in o) / len(o))
        cj = int(CNa[min(H - 1, max(0, cy_)), min(W - 1, max(0, cx_))])
        if cj and ar <= 1.5 * canop[cj - 1][2]:
            continue                            # GeoSampa fecha a cobertura do posto como predio: fica aberta
        j = int(OBa[min(H - 1, max(0, cy_)), min(W - 1, max(0, cx_))])
        t = dict(osm[j][2]) if j else {"building": "yes"}
        hgt = GB.tags[i]["h"]
        if hgt > 0:
            t.pop("building:levels", None); t.pop("levels", None)
            t["height"] = "%.1f" % hgt
        t["src"] = "footprints"
        items.append((ar, o, t, osm[j][3] if j else False, [P(r) for r in GB.rings[i][1:]], (1, GB.ids[i])))
        dGS.polygon(o, fill=1)
    GSa = np.array(GSr, dtype=np.uint8) > 0
    if len(osm) > 1:
        tot = np.bincount(OBa.ravel(), minlength=len(osm))
        cov = np.bincount(OBa[GSa], minlength=len(osm))
        for j in range(1, len(osm)):
            # entra se >=30% do contorno OSM (e >=400 m2) esta fora do GeoSampa: predio novo/ampliado
            # (Sao Paulo Expo, Congonhas). Como e maior, e desenhado antes e o GeoSampa sobrescreve o que tem.
            if tot[j] and (cov[j] < 0.3 * tot[j] or tot[j] - cov[j] >= max(400, 0.3 * tot[j])):
                ar, o, t, ismasp, inner, fid = osm[j]
                t = dict(t); t["src"] = "osm"
                items.append((ar, o, t, ismasp, inner, fid))
    del OBa, GSa
    B = Image.new("I", (W, H), 0)
    dB = ImageDraw.Draw(B)
    blds = [None]
    masp = None
    masp_rect = None
    items.sort(key=lambda z: -z[0])
    for ar, o, t, ismasp, inner, fid in items:
        if ismasp and masp is not None:
            continue                            # MASP: um volume so
        idx = len(blds)
        closed = o + [o[0]] if o[0] != o[-1] else o
        o2 = snap_poly(closed)
        if ismasp:
            # caixa suspensa real: 74 x 30 m retangular, vao livre embaixo (o contorno OSM pega a praca)
            xs_ = [q[0] for q in closed]; ys_ = [q[1] for q in closed]
            mx, my = (min(xs_) + max(xs_)) / 2, (min(ys_) + max(ys_)) / 2
            hw, hh = (37, 15) if max(xs_) - min(xs_) >= max(ys_) - min(ys_) else (15, 37)
            o2 = [(mx - hw, my - hh), (mx + hw, my - hh), (mx + hw, my + hh), (mx - hw, my + hh)]
            inner = []
            ar = 74 * 30
            masp_rect = o2
        dB.polygon(o2, fill=idx)
        # patio interno (inner ring) volta a ser vazio, com o mesmo giro do contorno
        if inner and o2 is not closed:
            cxo = sum(p[0] for p in closed) / len(closed); cyo = sum(p[1] for p in closed) / len(closed)
            cxn = sum(p[0] for p in o2) / len(o2); cyn = sum(p[1] for p in o2) / len(o2)
            ang = math.atan2(o2[1][1] - cyn, o2[1][0] - cxn) - math.atan2(closed[1][1] - cyo, closed[1][0] - cxo)
            c_, s_ = math.cos(ang), math.sin(ang)
            inner = [[(cxo + (x - cxo) * c_ - (y - cyo) * s_, cyo + (x - cxo) * s_ + (y - cyo) * c_)
                      for x, y in i] for i in inner]
        for i in inner:
            if len(i) >= 3:
                dB.polygon(i, fill=0)
        lv = levels_of(t, ar)
        b = t.get("building", "yes")
        cxp = min(W - 1, max(0, int(sum(p[0] for p in o) / len(o))))
        cyp = min(H - 1, max(0, int(sum(p[1] for p in o) / len(o))))
        # predio muito alto so na Paulista e no centro perto do MASP; fora, 1 em 12 passa de 8 andares
        mxl, myl = rx0 + cxp, ry0 + cyp
        lv = min(lv, MAXL)
        per_ = sum(math.hypot(q1[0] - q0[0], q1[1] - q0[1]) for q0, q1 in zip(closed, closed[1:]))
        circ = 4 * math.pi * poly_area(closed[:-1]) / max(per_ * per_, 1e-6)
        keep = ismasp or (circ > 0.8 and len(closed) >= 9) or b in ("roof", "dome", "stadium", "grandstand") or \
            "leisure" in t
        lu = int(LUa[cyp, cxp])
        if b in ("house", "detached", "terrace", "semidetached_house", "bungalow"):
            kind, rk = "res", "res"
        elif b in IND_B or (b in ("yes", "roof") and lu == 3 and ar >= 150 and "shop" not in t):
            kind, rk = "com", "ind"            # galpao/fabrica: progressao (ferramentas, metal, solda)
        elif b in ("apartments", "residential", "dormitory"):
            kind, rk = ("res", "res") if lv <= 2 else ("com", "apt")
        elif b == "yes" and lu == 1:            # em quadra residencial
            kind, rk = ("res", "res") if lv <= 3 and ar < 400 else ("com", "apt")
        elif b == "yes" and lv <= 2 and ar < 250 and lu < 2:
            kind, rk = "res", "res"
        elif b == "yes" and lu < 2 and lv >= 3 and ar < 2500 and "office" not in t and not MAINa[cyp, cxp]:
            kind, rk = "com", "apt"            # torre fora de avenida: residencial (padrao paulistano)
        else:
            kind, rk = "com", "com"
        obel = t.get("man_made") == "obelisk"
        if obel:
            kind, rk = "com", "com"
        if ismasp:
            lv = MASP_LV
            masp = idx
            kind = rk = "masp"
        blds.append({"lv": lv, "kind": kind, "rooms": rk, "tags": t, "h": h32(fid[0], fid[1] & 0x7FFFFFFF, 77),
                     "poi": None, "fid": fid, "keep": keep, "obel": obel})
    if masp_rect:
        dB.polygon(masp_rect, fill=masp)    # por cima dos anexos menores da praca
    Ba = np.array(B, dtype=np.int32)
    del B, dB
    Ba[pub & (Ba > 0)] = 0  # via publica vence; estacionamento/servico ficam sob o predio
    # remove lascas de 1 tile: fica so quem pertence a algum bloco 2x2 do mesmo predio
    keep = np.zeros(Ba.shape, bool)
    for dy in (0, -1):
        for dx in (0, -1):
            a0 = np.roll(np.roll(Ba, dy, 0), dx, 1)
            blk = (a0 > 0) & (a0 == np.roll(a0, -1, 1)) & (a0 == np.roll(a0, -1, 0)) & \
                  (a0 == np.roll(np.roll(a0, -1, 0), -1, 1))
            keep |= np.roll(np.roll(blk, -dy, 0), -dx, 1)
    Ba[~keep] = 0
    rectify(Ba, blds)
    # remove predios minusculos (<16 tiles) ou finos (bbox com lado < 3)
    nb = len(blds)
    cnt = np.bincount(Ba.ravel(), minlength=nb)
    bbx = bld_bbox(Ba, nb)
    bw_ = bbx[:, 2] - bbx[:, 0] + 1; bh_ = bbx[:, 3] - bbx[:, 1] + 1
    drop = (cnt < 16) | (np.minimum(bw_, bh_) < 3)
    drop[0] = False
    if masp:
        drop[masp] = False
    Ba[drop[Ba]] = 0
    # POIs (lojas/servicos) dentro do predio nomeiam os comodos do terreo
    PXY = S["PXY"]
    if len(PXY):
        sel = np.nonzero((PXY[:, 0] >= rx0) & (PXY[:, 0] < rx0 + W) & (PXY[:, 1] >= ry0) & (PXY[:, 1] < ry0 + H))[0]
        # POI fora do poligono (ponto na calcada/na frente): vai para o predio mais perto ate POI_SNAP tiles
        for k in sel:
            xi, yi = int(PXY[k, 0] - rx0), int(PXY[k, 1] - ry0)
            pt = S["PT"][k]
            am_ = pt.get("amenity")
            if not pt.get("shop") and am_ not in AMEN_ROOMS and am_ not in AMEN_CAT and am_ not in PUB_A:
                continue            # banco de praca, estacionamento, lixeira... nao nomeia predio
            bi = int(Ba[yi, xi])
            if not bi:
                r_ = POI_SNAP
                win = Ba[max(0, yi - r_):yi + r_ + 1, max(0, xi - r_):xi + r_ + 1]
                ys_, xs_ = np.nonzero(win)
                if not len(xs_):
                    continue
                d_ = (ys_ + max(0, yi - r_) - yi) ** 2 + (xs_ + max(0, xi - r_) - xi) ** 2
                j_ = int(d_.argmin())
                if d_[j_] > r_ * r_:
                    continue
                bi = int(win[ys_[j_], xs_[j_]])
            b_ = blds[bi]
            b_.setdefault("pois", []).append((xi, yi, pt))
            # o POI "principal" do predio: o 1o com loja/servico (nao sobrescreve um que ja nomeia o predio)
            if b_["poi"] is None or (not (b_["poi"].get("shop") or b_["poi"].get("amenity")) and
                                     (pt.get("shop") or pt.get("amenity"))):
                b_["poi"] = pt
    ZNa = np.array(ZN, dtype=np.uint8)
    nb = len(blds)
    tot = np.bincount(Ba.ravel(), minlength=nb)
    for zc, key_ in ((1, "mil"), (2, "hosp"), (3, "gov")):
        inz = np.bincount(Ba[ZNa == zc].ravel(), minlength=nb)
        for i in np.nonzero(inz * 2 > tot)[0].tolist():
            if i:
                blds[i][key_] = True
    for i in range(1, nb):
        t = blds[i]["tags"]
        if t.get("amenity") == "hospital" or t.get("building") == "hospital":
            blds[i]["hosp"] = True
        if t.get("amenity") in ("townhall", "courthouse") or t.get("office") == "government" or \
                t.get("building") in ("government", "civic", "public"):
            blds[i]["gov"] = True
        if t.get("amenity") == "police":
            blds[i].pop("mil", None)
    G["ZN"] = ZNa
    lvl_of = np.array([0] + [b["lv"] for b in blds[1:]], np.uint8)
    Lv = lvl_of[Ba]
    plan_heli(Ba, Lv, blds)
    plan_extras(Ba, Lv, Ga, blds)
    plan_specials(Ba, Lv, Ga, blds)
    PST = plan_postos(Ba, Ga, blds, canop, CNa, fuel_sources(S, box, off))
    Ga[Ba > 0] = 255   # chao sob predio (o piso vem do predio)
    # arvores reais (GeoSampa) fora de predio e de asfalto
    TR = np.zeros((H, W), bool)
    TXY = S["TXY"]
    if len(TXY):
        sel = (TXY[:, 0] >= rx0) & (TXY[:, 0] < rx0 + W) & (TXY[:, 1] >= ry0) & (TXY[:, 1] < ry0 + H)
        tx = (TXY[sel, 0] - rx0).astype(np.int32); ty = (TXY[sel, 1] - ry0).astype(np.int32)
        TR[ty, tx] = True
        TR &= (Ba == 0) & (Ga != G_ASPH) & ~PST
    return Ga, LNa, Ba, Lv, blds, masp, roads, TR


POI_SNAP = 6        # tiles: POI na calcada ainda nomeia o predio da frente
PSH = "saopaulo_postos_01_"
# bandeira -> indice na folha saopaulo_postos_01 (ordem de arte/tools/gera_postos.py BRANDS); 4 = sem bandeira
FUEL_WD = {"Q4836468": 0, "Q154950": 1, "Q2081136": 2, "Q9600717": 3}
PUMPS = {"S": ("location_shop_fossoil_01_14", "location_shop_fossoil_01_15"),
         "E": ("location_shop_fossoil_01_12", "location_shop_fossoil_01_13")}


def fuel_brand(t):
    """bandeira do posto pelas tags (brand/name/operator/wikidata) ou None."""
    for k in ("brand:wikidata", "operator:wikidata"):
        if t.get(k) in FUEL_WD:
            return FUEL_WD[t[k]]
    for k in ("brand", "name", "operator"):
        v = _norm(t.get(k))
        if not v:
            continue
        w = v.replace("-", " ").split()
        if "petrobras" in v or "vibra" in w or "br" in w or v.startswith("posto br"):
            return 0
        if "shell" in w or "raizen" in v:
            return 1
        if "ipiranga" in v:
            return 2
        if "ale" in w or v.startswith("ale "):
            return 3
    return None


def fuel_sources(S, box, off):
    """postos (areas, predios e pontos do OSM) com bandeira, em coordenada de raster: [(x, y, bandeira)]."""
    out = []
    for st in (S["OB"], S["OA"]):
        for i in st.sel(*box):
            t = st.tags[i]
            if t.get("amenity") == "fuel":
                b = fuel_brand(t)
                if b is not None:
                    r = st.rings[i][0] - off
                    out.append((float(r[:, 0].mean()), float(r[:, 1].mean()), b))
    PXY = S["PXY"]
    if len(PXY):
        x0, y0, x1, y1 = box
        sel = np.nonzero((PXY[:, 0] >= x0 - 64) & (PXY[:, 0] < x1 + 64) & (PXY[:, 1] >= y0 - 64) & (PXY[:, 1] < y1 + 64))[0]
        for k in sel:
            t = S["PT"][k]
            if t.get("amenity") == "fuel":
                b = fuel_brand(t)
                if b is not None:
                    out.append((float(PXY[k, 0] - off[0]), float(PXY[k, 1] - off[1]), b))
    return out


def plan_postos(Ba, Ga, blds, canop, CNa, srcs):
    """posto aberto sob cada cobertura do OSM: piso de pedra, bombas vanilla, pilares, cobertura z1 na cor da
    bandeira (borda) e branca (miolo), totem na calcada e letreiro na loja mais perto. Devolve mascara (sem arvore)."""
    H_, W_ = Ba.shape
    xsq = G["xsq"]
    used = np.zeros((H_, W_), bool)
    nb = len(blds)
    stat = [0] * 5

    def put(x, y, z, *ts):
        if 0 <= x < W_ and 0 <= y < H_:
            xsq.setdefault((x, y, z), []).extend(ts)

    for j, (o, t, ar) in enumerate(canop):
        m = (CNa == j + 1) & (Ba == 0)
        ys, xs = np.nonzero(m)
        if len(xs) < 6:
            continue
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        br = fuel_brand(t)
        if br is None:
            best = None
            for sx, sy, sb in srcs:
                d2 = (sx - cx) ** 2 + (sy - cy) ** 2
                if d2 <= 60 * 60 and (best is None or d2 < best[0]):
                    best = (d2, sb)
            br = best[1] if best else 4
        stat[br] += 1
        Ga[m] = G_PAVE
        used |= m
        # cobertura z1: borda na cor da bandeira, miolo branco
        for y, x in zip(ys.tolist(), xs.tolist()):
            edge = any(not (0 <= x + dx < W_ and 0 <= y + dy < H_ and m[y + dy, x + dx])
                       for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
            put(x, y, 1, ROOF)            # cobertura (original: cor da bandeira)
        # pilares nos cantos recuados (+ meio quando comprido)
        pil = set()
        ix0, ix1, iy0, iy1 = x0 + 1, x1 - 1, y0 + 1, y1 - 1
        if ix1 - ix0 >= 2 and iy1 - iy0 >= 2:
            xs_p = [ix0, ix1] + ([(ix0 + ix1) // 2] if ix1 - ix0 >= 14 else [])
            ys_p = [iy0, iy1] + ([(iy0 + iy1) // 2] if iy1 - iy0 >= 14 else [])
            for px in xs_p:
                for py in ys_p:
                    if m[py, px]:
                        pil.add((px, py))
        # bombas vanilla (com combustivel) em ilhas ao longo do eixo comprido
        ew = (x1 - x0) >= (y1 - y0)
        L0, L1, S0, S1 = (x0, x1, y0, y1) if ew else (y0, y1, x0, x1)
        span = S1 - S0 + 1
        rows = [(S0 + S1) // 2] if span < 7 else [S0 + span // 3, S1 - span // 3]
        a, b2 = PUMPS["S" if ew else "E"]
        for r in rows:
            for k in range(L0 + 2, L1 - 2, 5):
                c1 = (k, r) if ew else (r, k)
                c2 = (k + 1, r) if ew else (r, k + 1)
                if all(m[c[1], c[0]] and c not in pil for c in (c1, c2)):
                    put(c1[0], c1[1], 0, a)
                    put(c2[0], c2[1], 0, b2)
        # totem: quadrado livre fora da cobertura, encostado no asfalto, perto do canto
        tot = None
        for rr in range(1, 5):
            for yy in range(y0 - rr, y1 + rr + 1):
                for xx in range(x0 - rr, x1 + rr + 1):
                    if not (1 <= xx < W_ - 1 and 1 <= yy < H_ - 1) or m[yy, xx] or Ba[yy, xx] or CNa[yy, xx]:
                        continue
                    if Ga[yy, xx] in (G_ASPH, G_WATER):
                        continue
                    if not (Ga[yy - 1:yy + 2, xx - 1:xx + 2] == G_ASPH).any():
                        continue
                    sc = (rr, abs(xx - cx) + abs(yy - cy))
                    if tot is None or sc < tot[0]:
                        tot = (sc, xx, yy)
            if tot:
                break
        if tot:
            used[tot[2], tot[1]] = True
        # letreiro: predio mais perto (ate 8 quadrados da cobertura), se nao for publico/rede
        ya, yb, xa, xb = max(0, y0 - 8), min(H_, y1 + 9), max(0, x0 - 8), min(W_, x1 + 9)
        sub = Ba[ya:yb, xa:xb]
        if sub.any():
            yy, xx = np.nonzero(sub)
            d = np.maximum(np.maximum(x0 - (xx + xa), (xx + xa) - x1), np.maximum(y0 - (yy + ya), (yy + ya) - y1))
            bi = int(sub[yy[d.argmin()], xx[d.argmin()]])
            if 0 < bi < nb and blds[bi].get("posto") is None and blds[bi]["lv"] <= 2:
                blds[bi]["posto"] = br
    if os.environ.get("ONLY") and canop:
        print("postos:", len(canop), "coberturas, bandeiras BR/Shell/Ipiranga/ALE/sem:", stat)
    return used


def max_rect(m):
    """maior retangulo de True na mascara (histograma por linha) -> (y0, x0, y1, x1) ou None."""
    hist = np.zeros(m.shape[1], np.int32)
    best, bb = 0, None
    for y in range(m.shape[0]):
        hist = np.where(m[y], hist + 1, 0)
        st = []
        for x, hh in enumerate(hist.tolist() + [0]):
            start = x
            while st and st[-1][1] >= hh:
                s0, sh = st.pop()
                a = sh * (x - s0)
                if a > best:
                    best, bb = a, (y - sh + 1, s0, y + 1, x)
                start = s0
            st.append((start, hh))
    return bb


def rectify(Ba, blds):
    """Paredes retas: predio nao circular vira uniao de ate 4 retangulos dentro do contorno real
    (o contorno rasterizado torto/diagonal virava escadinha). Circulares e estruturas do Ibirapuera ficam."""
    bbx = bld_bbox(Ba, len(blds))          # (scipy.ndimage.find_objects no original)
    for i in range(1, len(blds)):
        if bbx[i, 2] < 0 or blds[i]["keep"]:
            continue
        sl = (slice(int(bbx[i, 1]), int(bbx[i, 3]) + 1), slice(int(bbx[i, 0]), int(bbx[i, 2]) + 1))
        sub = Ba[sl]
        m = sub == i
        n0 = int(m.sum())
        if n0 < 16:
            continue
        rem = m.copy()
        cov = np.zeros_like(m)
        for k in range(4):
            r = max_rect(rem)
            if r is None:
                break
            y0, x0, y1, x1 = r
            if min(y1 - y0, x1 - x0) < 3 or (k and (y1 - y0) * (x1 - x0) < max(16, 0.12 * n0)):
                break
            cov[y0:y1, x0:x1] = True
            rem[y0:y1, x0:x1] = False
            if rem.sum() < 0.08 * n0:
                break
        sub[m & ~cov] = 0


def plan_extras(Ba, Lv, Ga, blds):
    """Varandas (predio residencial alto: trechos de 3 quadrados nas fachadas retas, mureta so nelas)
    e escada de servico ate o telhado (1 por predio comercial/industrial baixo, ~metade deles)."""
    H_, W_ = Ba.shape
    yy, xx = np.mgrid[0:H_, 0:W_]
    apt = np.array([False] + [b["rooms"] == "apt" and b["lv"] >= 3 for b in blds[1:]])
    BAL = np.zeros(Ba.shape, np.uint8)
    BC = np.zeros(Ba.shape, bool)
    free = (Ba == 0) & (Ga != G_WATER)
    for ax, sh in ((0, 1), (0, -1), (1, 1), (1, -1)):        # fachada S, N, E, W
        own = np.roll(Ba, sh, ax)
        cand = free & (own > 0) & apt[own]
        along = 1 - ax                                       # varanda corre ao longo da fachada
        pos = xx if along == 1 else yy
        c0 = cand & (pos % 7 == 2)
        for k in (1, 2):
            c0 &= np.roll(cand, -k, along) & (np.roll(own, -k, along) == own)
        for k in (0, 1, 2):
            m_ = np.roll(c0, k, along)
            lvv = np.roll(np.where(c0, np.roll(Lv, sh, ax), 0), k, along)
            BAL[m_] = np.maximum(BAL[m_], lvv[m_])
        BC |= np.roll(c0, 1, along)
    BC &= BAL > 0
    lad = {}
    key = ((xx * 73856093) ^ (yy * 19349663)) & 0xFFFFFF
    okb = np.array([False] + [(b["kind"] == "com" and 2 <= b["lv"] <= 6 and b["h"] % 2 == 0) or "heli" in b
                             for b in blds[1:]])
    walk = (Ba == 0) & (BAL == 0) & np.isin(Ga, (G_SIDE, G_PAVE, G_YARD, G_GRASS, G_PARK, G_DEF))
    for side, ax in (("W", 1), ("N", 0)):                    # escada na face E (parede W do quadrado) ou S
        own = np.roll(Ba, 1, ax)
        along = 1 - ax
        c = walk & (own > 0) & okb[own] & (np.roll(own, 1, along) == own) & (np.roll(own, -1, along) == own)
        ys, xs = np.nonzero(c)
        for y, x, b_, k_ in zip(ys.tolist(), xs.tolist(), own[ys, xs].tolist(), key[ys, xs].tolist()):
            if b_ not in lad or k_ < lad[b_][0]:
                lad[b_] = (k_, x, y, side)
    G["BAL"], G["BC"] = BAL, BC
    G["ladb"] = set(lad)
    G["ladders"] = {(x, y): (side, int(Lv[y, x - 1] if side == "W" else Lv[y - 1, x]))
                    for _, x, y, side in lad.values()}


# ---------------------------------------------------------------- pontos especiais (heliponto, camping, metro, aeroporto)
METRO_STATIONS = []
RAIL_N, RAIL_W = "fixtures_railings_01_0", "fixtures_railings_01_4"
BASE_W = ("walls_commercial_03", 0)   # concreto do subsolo
CRATE = "location_military_generic_01_0"
CANDLE = "constructedobjects_01_0"
ALTAR = "location_community_church_small_01_40"
BLOOD = ["overlay_blood_floor_01_%d" % k for k in range(5)]
GRIME = ["overlay_grime_floor_01_%d" % k for k in range(8)]


def plan_heli(Ba, Lv, blds):
    """heliponto: desligado no generico (o piso pintado era a folha propria saopaulo_heli_01)."""
    return
    nb = len(blds)
    cnt = np.bincount(Ba.ravel(), minlength=nb)
    bb = bld_bbox(Ba, nb)
    for i in range(1, nb):
        b = blds[i]
        if bb[i, 2] < 0 or b["kind"] == "masp":
            continue
        x0, y0, x1, y1 = (int(v) for v in bb[i])
        mx, my = G["rx0"] + (x0 + x1) // 2, G["ry0"] + (y0 + y1) // 2
        hosp = b.get("hosp") and cnt[i] >= 1500 and b["lv"] >= 3
        paul = b["lv"] >= MAXL and abs(my - MYm) < 450 and 400 < mx < 3700 and b["h"] % 8 == 0
        if not (hosp or paul):
            continue
        m = (Ba[y0:y1 + 1, x0:x1 + 1] == i).astype(np.int32)
        if m.shape[0] < 11 or m.shape[1] < 11:
            continue
        ii = np.pad(m, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        s = ii[11:, 11:] - ii[:-11, 11:] - ii[11:, :-11] + ii[:-11, :-11]   # janela 11x11 (9x9 + borda)
        ys, xs = np.nonzero(s == 121)
        if not len(ys):
            continue
        cy_, cx_ = (m.shape[0] - 11) / 2, (m.shape[1] - 11) / 2
        k = int(np.argmin((ys - cy_) ** 2 + (xs - cx_) ** 2))
        b["heli"] = (x0 + int(xs[k]) + 1, y0 + int(ys[k]) + 1)   # canto NW do 9x9


def plan_specials(Ba, Lv, Ga, blds):
    """tiles/comodos extras em coordenada de raster: G['xsq'] {(x,y,z): [tiles]}, G['xclr'] (limpa antes),
    G['xrooms'] [(nome, z, {(x,y)})], G['heli'] (sem enfeite no telhado), G['pts'] pontos p/ Lua (mundo)."""
    rx0, ry0 = G["rx0"], G["ry0"]
    H_, W_ = Ba.shape
    GX, GY = rx0 + CX0 * CS, ry0 + CY0 * CS
    xsq, xclr, xrooms, heli = {}, set(), [], set()
    pts = {"heli": [], "camp": [], "portal": [], "cars": [], "dungeon": []}

    def core(x, y):
        return MG <= x < MG + BS * CS and MG <= y < MG + BS * CS

    def put(x, y, z, *ts):
        if 0 <= x < W_ and 0 <= y < H_:
            xsq.setdefault((x, y, z), []).extend(ts)

    # (original: heliponto, camping, metro/masmorra, galerias de rio, patio do aeroporto: especificos de SP)
    G.update(xsq=xsq, xclr=xclr, xrooms=xrooms, heli=heli, pts=pts)


# ---------------------------------------------------------------- por predio
def bld_bbox(Ba, nb):
    ys, xs = np.nonzero(Ba)
    ids = Ba[ys, xs]
    bb = np.zeros((nb, 4), np.int32)
    bb[:, 0] = bb[:, 1] = 1 << 30
    bb[:, 2] = bb[:, 3] = -1
    np.minimum.at(bb[:, 0], ids, xs); np.minimum.at(bb[:, 1], ids, ys)
    np.maximum.at(bb[:, 2], ids, xs); np.maximum.at(bb[:, 3], ids, ys)
    return bb


def grid_of(b):
    return {"res": 8, "apt": 10}.get(b.get("rooms"), 14)


def plan_stairs(Ba, Lv, blds, bb, masp):
    """Escada de 3 tiles em cada predio com 2+ andares: (x, y..y+2), sobe para o norte."""
    st = {}
    GX, GY = G["rx0"] + CX0 * CS, G["ry0"] + CY0 * CS   # raster -> mundo (grade de comodos global)
    for i in range(1, len(blds)):
        if blds[i]["lv"] < 2 or bb[i, 2] < 0:
            continue
        x0, y0, x1, y1 = (int(v) for v in bb[i])
        sub = Ba[y0:y1 + 1, x0:x1 + 1] == i
        hh, ww = sub.shape
        S = grid_of(blds[i])
        found = None
        for yy in range(1, hh - 4):
            wy = y0 + yy
            if any((wy + GY + k) % S == 0 for k in range(0, 4)):
                continue
            for xx in range(1, ww - 1):
                wx = x0 + xx
                if (wx + GX) % S in (0, 1):
                    continue
                if sub[yy - 1:yy + 4, xx - 1:xx + 2].all():
                    found = (wx, wy)
                    break
            if found:
                break
        if found is None:
            for yy in range(1, hh - 4):
                for xx in range(1, ww - 1):
                    if sub[yy - 1:yy + 4, xx - 1:xx + 2].all():
                        found = (x0 + xx, y0 + yy); break
                if found:
                    break
        d = "N"
        if found is None:   # coluna de 1 tile (3 degraus + patamar em cima e embaixo)
            for yy in range(1, hh - 3):
                for xx in range(0, ww):
                    if sub[yy - 1:yy + 4, xx].all() and sub[yy:yy + 3, xx].sum() == 3:
                        found = (x0 + xx, y0 + yy); break
                if found:
                    break
        if found is None:   # escada horizontal (sobe para oeste), linha de 5 tiles
            for yy in range(0, hh):
                for xx in range(1, ww - 3):
                    if sub[yy, xx - 1:xx + 4].all():
                        found = (x0 + xx, y0 + yy); d = "W"; break
                if found:
                    break
        if found:
            st[i] = (found[0], found[1], d)
        elif i != masp:
            blds[i]["acc"] = 1   # sem espaco para escada: mantem a altura real, so o terreo e acessivel
    return st


def st_set(st):
    return {(a, b) for a, b, _ in stair_cells(st)}


def st_zone(st):
    """escada + patamares (sem parede interna)."""
    x, y, d = st
    if d == "N":
        return {(x + i, y + k) for i in (-1, 0, 1) for k in range(-1, 4)}
    return {(x + k, y) for k in range(-1, 4)}


def stair_cells(st):
    """3 tiles da escada (x, y, d) com o sprite de cada um."""
    x, y, d = st
    if d == "N":
        return [(x, y + k, STAIRS[k]) for k in range(3)]
    return [(x + k, y, STAIRS_X[k]) for k in range(3)]


# ---------------------------------------------------------------- delegacia: celas
def jail_layout(S, n=3):
    """celas de 5 tiles de fundo no norte do bloco, grade na linha v=5, corredor ao sul."""
    cells_ = [(0, 4), (5, 9)] + ([(10, S - 1)] if S >= 14 and n >= 3 else [])
    return cells_


def put_jail(add, rooms, bld_rooms, bi, k, S, WX, WY, dsq):
    """desenha as celas do bloco k (grade do mundo) na celula atual. WX/WY = local -> mundo."""
    bx, by = k[0] * S - WX + k[3], k[1] * S - WY + k[4]

    def put(u, v, n):
        lx, ly = bx + u, by + v
        if 0 <= lx < CS and 0 <= ly < CS:
            add(lx, ly, 0, n)

    cl = jail_layout(S, k[2])
    doors = {c0 + 2 for c0, _ in cl}
    for u in range(cl[-1][1] + 1):
        put(u, 5, JAIL_FRAME[1] if u in doors else JAIL_BAR[1])
        if u in doors:
            dsq |= {(bx + u, by + 5, 0), (bx + u, by + 4, 0), (bx + u, by + 6, 0)}
    for c0, c1 in cl:
        if c0 or k[3]:
            for v in range(5):
                put(c0, v, JAIL_BAR[0])
    if k[3] + cl[-1][1] + 1 < S:
        for v in range(5):
            put(cl[-1][1] + 1, v, JAIL_BAR[0])
    if k[4]:
        for u in range(cl[-1][1] + 1):
            put(u, 0, JAIL_BAR[1])
    for c0, c1 in cl:
        put(c0, 0, JAIL_BUNK[0]); put(c0, 1, JAIL_BUNK[1])
        put(c1, 0, JAIL_TOILET); put(c1, 1, JAIL_SINK)
    regs = [("prisoncells", bx + c0, by, c1 - c0 + 1, 5) for c0, c1 in cl]
    for name, x, y, w, h in regs:
        xa, ya, xb, yb = max(x, 0), max(y, 0), min(x + w, CS), min(y + h, CS)
        if xa < xb and ya < yb:
            bld_rooms.setdefault(bi, []).append(len(rooms))
            rooms.append((name, 0, [(xa, ya, xb - xa, yb - ya)]))


def btags(b):
    t = dict(b["tags"])
    if b.get("poi"):
        for kk in ("shop", "amenity", "leisure", "tourism"):
            if b["poi"].get(kk):
                t.setdefault(kk, b["poi"][kk])
    return t


F1, F2, F3 = "saopaulo_fachadas_01_", "saopaulo_fachadas_02_", "saopaulo_fachadas_03_"
# (texto normalizado no inicio do brand/name, folha, 1o indice W, pecas); N vem logo depois das W
SIGN_BRANDS = [("carrefour express", F2, 6, 3), ("carrefour bairro", F2, 6, 3), ("drogasil", F1, 0, 3),
               ("droga raia", F1, 6, 3), ("raia", F1, 6, 3), ("drogaria sao paulo", F1, 12, 3),
               ("pague menos", F1, 18, 3), ("ultrafarma", F1, 24, 3), ("farmacia popular", F3, 20, 3),
               ("oxxo", F2, 0, 3), ("am/pm", F2, 12, 3), ("ampm", F2, 12, 3), ("dia", F2, 24, 3),
               ("pao de acucar", F2, 30, 3), ("minuto pao de acucar", F2, 30, 3), ("extra", F2, 36, 3),
               ("mini extra", F2, 36, 3), ("atacadao", F3, 0, 5), ("assai", F3, 10, 5), ("carrefour", F2, 42, 3)]
SIGN_GEN = {"pharmacy": [(F1, 30, 3), (F3, 20, 3)], "chemist": [(F1, 30, 3), (F3, 20, 3)],
            "convenience": [(F2, 18, 3), (F3, 26, 3)], "supermarket": [(F2, 48, 3), (F3, 32, 3)],
            "wholesale": [(F3, 32, 3)]}


def _norm(v):
    import unicodedata
    v = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode().lower().strip()
    return " ".join(v.split())


F4 = "saopaulo_fachadas_04_"
# predios publicos (placas simplificadas, sem logo oficial): W = indice, N = indice + 3
PUB_A = {"hospital": 0, "clinic": 6, "doctors": 6, "townhall": 12, "police": 18, "fire_station": 24,
         "school": 30, "college": 30, "kindergarten": 30, "university": 30, "post_office": 36,
         "courthouse": 42, "public_building": 48, "community_centre": 48, "library": 48, "social_facility": 6}
PUB_B = {"hospital": 0, "clinic": 6, "school": 30, "college": 30, "university": 30, "kindergarten": 30,
         "fire_station": 24, "government": 48, "public": 48, "civic": 48}


def sign_of(b, i):
    """letreiro da fachada: orgao publico/hospital pelo tipo, rede pelo brand/name do OSM, senao generico pela loja."""
    t = btags(b)
    am, bt = t.get("amenity"), t.get("building")
    if b.get("hosp") and am not in PUB_A:
        return F4, 0, 3
    if am in PUB_A:
        return F4, PUB_A[am], 3
    if t.get("office") == "government" or t.get("government"):
        return F4, 48, 3
    if bt in PUB_B:
        return F4, PUB_B[bt], 3
    if am == "fuel" or b.get("posto") is not None:
        pb = b.get("posto")
        if pb is None:
            pb = fuel_brand(t)
        return PSH, 6 * (4 if pb is None else pb), 3
    for k in ("brand", "name"):
        v = _norm((b.get("poi") or {}).get(k) or t.get(k))
        if not v:
            continue
        for key, sh, w0, n in SIGN_BRANDS:
            if v == key or v.startswith(key + " ") or (k == "brand" and len(key) >= 6 and key in v):
                return sh, w0, n
    kind = t.get("shop") if t.get("shop") in SIGN_GEN else t.get("amenity")
    if kind in SIGN_GEN:
        opts = SIGN_GEN[kind]
        return opts[h32(i, 5) % len(opts)]
    cat = shop_cat(t)
    if cat:
        return LSH, LOJA_IDX[cat], 3
    return None


LSH = "saopaulo_lojas_01_"
# categoria -> 1o indice na folha saopaulo_lojas_01 (ordem de arte/tools/gera_lojas.py CATS)
LOJA_IDX = {k: 6 * i for i, k in enumerate(
    ("padaria", "restaurante", "lanchonete", "bar", "cafe", "mercado", "acougue", "moda", "otica", "construcao",
     "autopecas", "celular", "pet", "beleza", "papelaria", "banco", "adega", "loja"))}
SHOP_CAT = {"bakery": "padaria", "pastry": "padaria", "confectionery": "padaria",
            "supermarket": "mercado", "convenience": "mercado", "greengrocer": "mercado", "kiosk": "mercado",
            "deli": "mercado", "butcher": "acougue", "seafood": "acougue",
            "clothes": "moda", "shoes": "moda", "fashion": "moda", "boutique": "moda", "tailor": "moda",
            "fabric": "moda", "bag": "moda", "fashion_accessories": "moda",
            "optician": "otica", "jewelry": "otica", "watches": "otica",
            "hardware": "construcao", "doityourself": "construcao", "paint": "construcao", "trade": "construcao",
            "building_materials": "construcao", "glaziery": "construcao", "electrical": "construcao",
            "car_parts": "autopecas", "car_repair": "autopecas", "tyres": "autopecas", "car": "autopecas",
            "motorcycle": "autopecas",
            "mobile_phone": "celular", "electronics": "celular", "computer": "celular", "video_games": "celular",
            "pet": "pet", "hairdresser": "beleza", "beauty": "beleza", "cosmetics": "beleza", "perfumery": "beleza",
            "books": "papelaria", "stationery": "papelaria", "copyshop": "papelaria", "books;stationery": "papelaria",
            "alcohol": "adega", "beverages": "adega", "wine": "adega"}
AMEN_CAT = {"restaurant": "restaurante", "food_court": "restaurante", "fast_food": "lanchonete",
            "cafe": "cafe", "bar": "bar", "pub": "bar", "nightclub": "bar", "biergarten": "bar",
            "bank": "banco", "bureau_de_change": "banco", "veterinary": "pet", "ice_cream": "lanchonete",
            "marketplace": "mercado"}


def shop_cat(t):
    """categoria de letreiro generico de uma loja/servico (None = sem letreiro)."""
    s, a = t.get("shop"), t.get("amenity")
    if s in SHOP_CAT:
        return SHOP_CAT[s]
    if a in AMEN_CAT:
        return AMEN_CAT[a]
    if s and s not in ("vacant", "no", "yes;vacant"):
        return "loja"
    if t.get("building") in ("retail", "supermarket", "kiosk") and t.get("name"):
        return "loja"
    return None


def plan_signs(Ga, Ba, blds, bb, masp):
    """letreiros na fachada N ou W do terreo (overlays so prendem em parede N/W), de frente para a rua.
    Um por loja do predio (b["pois"]): cada um no trecho de fachada mais perto do ponto do POI, sem sobrepor.
    Generico: desligado (as placas eram folhas proprias saopaulo_fachadas_* / saopaulo_lojas_01)."""
    return {}
    out = {}
    H_, W_ = Ba.shape
    for i in range(1, len(blds)):
        b = blds[i]
        if bb[i, 2] < 0 or i == masp or b.get("obel") or b["kind"] == "masp":
            continue
        reqs = []
        sg = sign_of(b, i)
        if sg:
            p0 = (b.get("pois") or [None])[0]
            reqs.append((sg, p0[:2] if p0 else None))
        for k_, (px, py, pt) in enumerate((b.get("pois") or [])[1:6], 1):
            sg2 = sign_of(dict(b, poi=pt, tags={kk: vv for kk, vv in b["tags"].items()
                                                 if kk not in ("shop", "amenity", "name", "brand")}), i + 977 * k_)
            if sg2 and sg2[0] != F4 and all(sg2[:2] != q[0][:2] for q in reqs):
                reqs.append((sg2, (px, py)))
        if not reqs:
            continue
        x0, y0, x1, y1 = (int(v) for v in bb[i])
        runs = []
        for y in range(max(y0, 1), y1 + 1):
            row = [x for x in range(x0, x1 + 1) if Ba[y, x] == i and Ba[y - 1, x] != i]
            runs += [("N", y, r) for r in _runs(row)]
        for x in range(max(x0, 1), x1 + 1):
            col = [y for y in range(y0, y1 + 1) if Ba[y, x] == i and Ba[y, x - 1] != i]
            runs += [("W", x, r) for r in _runs(col)]
        used = set()
        for (sh, w0, n), tgt in reqs:
            best = None
            for side, c, r in runs:
                for j in range(0, len(r) - n + 1):
                    seg = r[j:j + n]
                    cells = [(v, c) if side == "N" else (c, v) for v in seg]
                    if any(q in used for q in cells):
                        continue
                    mid = seg[n // 2]
                    ox_ = (mid, c - 1) if side == "N" else (c - 1, mid)
                    street = 0 <= ox_[1] < H_ and 0 <= ox_[0] < W_ and Ga[ox_[1], ox_[0]] in (G_ASPH, G_SIDE, G_PAVE)
                    mx, my = (mid, c) if side == "N" else (c, mid)
                    if tgt is not None:
                        sc = (street, -abs(mx - tgt[0]) - abs(my - tgt[1]))
                    else:
                        sc = (street, len(r), -abs(j - (len(r) - n) // 2))
                    if best is None or sc > best[0]:
                        best = (sc, side, c, seg)
            if not best:
                continue
            _, side, c, seg = best
            for k in range(n):
                cell = (seg[k], c) if side == "N" else (c, seg[n - 1 - k])
                used.add(cell)
                # vizinhos tambem ficam ocupados: placas encostadas viram uma faixa so
            used |= {((seg[0] - 1, c) if side == "N" else (c, seg[0] - 1)),
                     ((seg[-1] + 1, c) if side == "N" else (c, seg[-1] + 1))}
            for k in range(n):
                if side == "N":
                    out[(seg[k], c)] = sh + str(w0 + n + k)          # N: esquerda = menor x
                else:
                    out[(c, seg[n - 1 - k])] = sh + str(w0 + k)      # W: esquerda = maior y
    return out


def _runs(v):
    out, cur = [], []
    for a in v:
        if cur and a != cur[-1] + 1:
            out.append(cur); cur = []
        cur.append(a)
    if cur:
        out.append(cur)
    return out


def plan_jails(Ba, blds, bb, stairs):
    """um bloco de comodo inteiro (com anel de 1 tile do mesmo predio) por delegacia vira cela."""
    GX, GY = G["rx0"] + CX0 * CS, G["ry0"] + CY0 * CS
    H_, W_ = Ba.shape
    out = {}
    for i in range(1, len(blds)):
        if bb[i, 2] < 0 or btags(blds[i]).get("amenity") != "police":
            continue
        S = grid_of(blds[i])
        if S < 10:
            continue
        x0, y0, x1, y1 = (int(v) for v in bb[i])
        zone = st_zone(stairs[i]) if i in stairs else set()
        # 1) bloco inteiro com anel; 2) bloco inteiro; 3) so a faixa das celas + 2 linhas de corredor
        # alinhado ao bloco (com anel / sem anel), depois deslocado dentro do bloco, 3 ou 2 celas
        tries = [(-1, S + 1, -1, S + 1, 0, 0), (0, S, 0, S, 0, 0), (0, S, 0, 7, 0, 0)]
        tries += [(0, w, 0, 7, ox_, oy_) for w in (S, 10) for oy_ in range(0, S - 6) for ox_ in range(0, S - w + 1)]
        for k1 in range((y0 + GY) // S, (y1 + GY) // S + 1):
            for k0 in range((x0 + GX) // S, (x1 + GX) // S + 1):
                bx, by = k0 * S - GX, k1 * S - GY
                if bx < MG or by < MG or bx + S > MG + BS * CS or by + S > MG + BS * CS:
                    continue
                for a0, a1, b0, b1, ox_, oy_ in tries:
                    X, Y = bx + ox_, by + oy_
                    if not (Ba[Y + b0:Y + b1, X + a0:X + a1] == i).all():
                        continue
                    if any(X - 1 <= a <= X + a1 and Y - 1 <= c <= Y + 7 for a, c in zone):
                        continue
                    out[i] = (k0, k1, 3 if a1 >= S else 2, ox_, oy_)
                    break
                if i in out:
                    break
            if i in out:
                break
    return out


CAT = ["", "Residential", "CommunityServices", "Hospitality", "Industrial", "Medical",
       "RestaurantsAndEntertainment", "RetailAndCommercial"]
MED_A = {"hospital", "clinic", "doctors", "dentist", "pharmacy", "veterinary"}
COMM_A = {"police", "fire_station", "school", "university", "college", "kindergarten", "library",
          "place_of_worship", "townhall", "post_office", "community_centre", "courthouse", "prison",
          "social_facility", "bus_station"}
COMM_B = {"school", "church", "chapel", "cathedral", "civic", "public", "government", "university", "college",
          "kindergarten", "train_station", "transportation", "fire_station", "religious"}
FUN_A = {"restaurant", "fast_food", "cafe", "bar", "pub", "cinema", "theatre", "nightclub", "ice_cream",
         "food_court", "arts_centre", "biergarten"}


def bcat(b):
    """categoria do predio no mapa do jogo (cores vanilla do ISMapDefinitions)."""
    t = btags(b)
    am, bt = t.get("amenity"), t.get("building")
    if b["kind"] == "masp":
        return 2
    if b.get("hosp") or am in MED_A or bt in ("hospital", "clinic"):
        return 5
    if am in COMM_A or bt in COMM_B:
        return 2
    if am in FUN_A or t.get("leisure") in ("fitness_centre", "sports_centre", "stadium"):
        return 6
    if bt in ("hotel", "motel") or t.get("tourism") in ("hotel", "motel", "hostel"):
        return 3
    if b["rooms"] == "ind":
        return 4
    if b["rooms"] in ("res", "apt") and not t.get("shop"):
        return 1
    return 7


# ---------------------------------------------------------------- escrita de celula
G = {}


def write_cell(args):
    cx, cy = args
    Ga, LNa, Ba, Lv, blds, stairs, masp = G["Ga"], G["LNa"], G["Ba"], G["Lv"], G["blds"], G["stairs"], G["masp"]
    ox, oy = (cx - CX0) * CS - G["rx0"], (cy - CY0) * CS - G["ry0"]   # celula no raster do bloco
    GX, GY = G["rx0"] + CX0 * CS, G["ry0"] + CY0 * CS                 # raster -> mundo
    TRw, ntree = G["TR"], G["ntree"]
    # janela com margem 1 para olhar vizinhos
    pad = lambda A: np.pad(A, 1, mode="edge")
    sl = (slice(oy, oy + CS), slice(ox, ox + CS))
    y0p, x0p = max(oy - 1, 0), max(ox - 1, 0)
    b_ = Ba[y0p:oy + CS + 1, x0p:ox + CS + 1]
    l_ = Lv[y0p:oy + CS + 1, x0p:ox + CS + 1]
    # normaliza para (CS+2)^2 com borda
    Bw = np.zeros((CS + 2, CS + 2), np.int32); Lw = np.zeros((CS + 2, CS + 2), np.uint8)
    Bw[(y0p - (oy - 1)):(y0p - (oy - 1)) + b_.shape[0], (x0p - (ox - 1)):(x0p - (ox - 1)) + b_.shape[1]] = b_
    Lw[(y0p - (oy - 1)):(y0p - (oy - 1)) + l_.shape[0], (x0p - (ox - 1)):(x0p - (ox - 1)) + l_.shape[1]] = l_
    g = Ga[sl]; ln = LNa[sl]
    gw = np.full((CS + 2, CS + 2), G_DEF, np.uint8)
    gg = Ga[y0p:oy + CS + 1, x0p:ox + CS + 1]
    gw[(y0p - (oy - 1)):(y0p - (oy - 1)) + gg.shape[0], (x0p - (ox - 1)):(x0p - (ox - 1)) + gg.shape[1]] = gg

    def win(A, dt):
        w_ = np.zeros((CS + 2, CS + 2), dt)
        a_ = A[y0p:oy + CS + 1, x0p:ox + CS + 1]
        w_[(y0p - (oy - 1)):(y0p - (oy - 1)) + a_.shape[0], (x0p - (ox - 1)):(x0p - (ox - 1)) + a_.shape[1]] = a_
        return w_
    BALw, BCw = win(G["BAL"], np.uint8), win(G["BC"], bool)
    lads = {(lx - ox, ly - oy): v for (lx, ly), v in G["ladders"].items()
            if 0 <= lx - ox < CS and 0 <= ly - oy < CS}
    maxz = int(Lw[1:-1, 1:-1].max()) if Lw.size else 0
    maxz = max(maxz, int(BALw.max()), max((v[1] for v in lads.values()), default=0))
    sq = {}           # (x,y,z) -> [tiles]
    names, nidx = [], {}

    def T(n):
        i = nidx.get(n)
        if i is None:
            i = nidx[n] = len(names); names.append(n)
        return i

    def add(x, y, z, n):
        if n.startswith("saopaulo_"):          # folha propria do projeto SP: nao existe no jogo vanilla
            return
        sq.setdefault((x, y, z), []).append(T(n))

    heli_ = G["heli"]
    jails = G.get("jails", {})
    mst = stairs.get(masp) if masp is not None else None
    mzone = st_zone(mst) if mst else set()

    def nofl(bi_, z, wx, wy):   # MASP: vao livre de pe-direito duplo (so o patamar da escada tem piso)
        return bi_ == masp and 0 < z < MASP_Z0 and (wx, wy) not in mzone

    # ---- chao z0
    for y in range(CS):
        wy = oy + y
        for x in range(CS):
            wx = ox + x
            bi = Bw[y + 1, x + 1]
            hh = h32(wx + GX, wy + GY)
            if bi:
                b = blds[bi]
                if b["kind"] == "masp":
                    add(x, y, 0, PAVING[hh & 1])
                else:
                    fl = FLOORS_RES if b["kind"] == "res" else FLOORS_COM
                    add(x, y, 0, fl[b["h"] % len(fl)])
                continue
            c = g[y, x]
            if c == G_ASPH:
                add(x, y, 0, ASPHALT[hh & 7])
                nb = {"N": gw[y, x + 1], "S": gw[y + 2, x + 1], "W": gw[y + 1, x], "E": gw[y + 1, x + 2]}
                curb = next((d for d in ("N", "S", "W", "E") if nb[d] in (G_SIDE, G_PAVE)), None)
                if curb:
                    add(x, y, 0, CURB[curb])
                else:
                    v = int(ln[y, x])
                    dashed = v >= 3
                    if dashed:
                        v -= 2
                    if v and (not dashed or ((wx if v == 1 else wy) // 3) % 2 == 0):
                        add(x, y, 0, LINE_X if v == 1 else LINE_Y)
            elif c == G_SIDE:
                add(x, y, 0, SIDEWALK[(hh >> 3) & 7])
                touches = G_ASPH in (gw[y, x + 1], gw[y + 2, x + 1], gw[y + 1, x], gw[y + 1, x + 2])
                if touches:
                    if ((wx + GX) * 3 + (wy + GY) * 5) % 23 == 0:
                        add(x, y, 0, LAMP)
                elif TRw[wy, wx] or (ntree == 0 and (hh % 13) == 0):   # arvore real do GeoSampa
                    add(x, y, 0, TREES[(hh >> 5) % len(TREES)])
            elif c == G_PAVE:
                add(x, y, 0, PAVING[(hh >> 2) & 1])
            elif c == G_YARD:
                add(x, y, 0, YARD[(hh >> 2) & 1])
            elif c in (G_PARK, G_GRASS):
                add(x, y, 0, GRASS[hh & 3])
                if c == G_PARK and hh % 9 == 0:
                    add(x, y, 0, TREES[(hh >> 5) % len(TREES)])
            elif c == G_WATER:
                add(x, y, 0, WATER[hh & 3])
            elif c == G_WOOD:
                add(x, y, 0, GRASS2[hh & 3])
                if hh % 3 == 0:
                    add(x, y, 0, TREES[(hh >> 5) % len(TREES)])
            else:
                add(x, y, 0, GRASS[hh & 3])   # terra sorteada no meio da grama virava quadrado escuro (xadrez)

    # ---- curvas: grama/agua invadem o vizinho com overlay de canto (meio a meio) ou de borda
    NAT = {G_PARK: 32, G_GRASS: 32, G_WOOD: 16}
    for y in range(CS):
        for x in range(CS):
            if Bw[y + 1, x + 1]:
                continue
            c = g[y, x]
            nb = {"N": gw[y, x + 1], "S": gw[y + 2, x + 1], "W": gw[y + 1, x], "E": gw[y + 1, x + 2]}
            if c in (G_SIDE, G_PAVE, G_YARD) and sum(v == G_ASPH for v in nb.values()) == 2:
                ds_ = {d for d, v in nb.items() if v == G_ASPH}
                k_ = next((v for pr, v in BLEND_IDX.items() if set(pr) == ds_), None)
                if k_ is not None:      # degrau da via na diagonal vira meio a meio (curva)
                    sq.setdefault((x, y, 0), []).insert(1, T(f"blends_street_01_{ASPH_FAM + k_}"))
            if c in (G_SIDE, G_PAVE, G_YARD, G_ASPH):
                fams = [(d, NAT[v]) for d, v in nb.items() if v in NAT]
                ts = "blends_natural_01"
            elif c in (G_PARK, G_GRASS, G_WOOD, G_DEF):
                fams = [(d, 0) for d, v in nb.items() if v == G_WATER]
                ts = "blends_natural_02"
            else:
                continue
            if not fams:
                continue
            ds = {d for d, _ in fams}
            f = max(f_ for _, f_ in fams)
            hh = h32(ox + x + GX, oy + y + GY, 3)
            k = next((v for pr, v in BLEND_IDX.items() if set(pr) <= ds), None)
            if k is None:
                k = BLEND_EDGE[next(iter(sorted(ds)))][hh & 1]
            sq.setdefault((x, y, 0), []).insert(1, T(f"{ts}_{f + k}"))

    # ---- predios, andar a andar
    rooms = []                       # (name, z, rects)
    bld_rooms = {}                   # bi -> [room idx]
    doors_done = set()
    dsq = set()                      # quadrados de porta (dos dois lados), por z: mobilia nao encosta
    nfurn = 0
    for z in range(0, maxz + 1):
        In = (Bw > 0) & (Lw > z)
        Id = np.where(In, Bw, 0)
        if z == 0:
            opening = plan_openings(Id, gw, blds, ox, oy, GX, GY)
            for jb, jk in jails.items():
                S_ = grid_of(blds[jb])
                jx, jy = jk[0] * S_ - GX - ox + jk[3], jk[1] * S_ - GY - oy + jk[4]
                for key in [q for q in opening if jx - 1 <= q[0] <= jx + S_ and jy - 1 <= q[1] <= jy + 6]:
                    del opening[key]
            for (lx, ly), (lsd, _) in lads.items():      # escada de servico: parede lisa, sem porta
                opening.pop((lx, ly, lsd), None)
        # bordas: wallW[y,x] entre (x-1,y) e (x,y); wallN entre (x,y-1) e (x,y)  (coords com borda)
        eW = Id[:, 1:] != Id[:, :-1]           # shape (CS+2, CS+1): coluna j = borda entre j e j+1
        eN = Id[1:, :] != Id[:-1, :]
        cand = Id[1:-1, 1:-1] > 0
        cand = cand | eW[1:-1, 0:CS] | eN[0:CS, 1:-1] | eW[0:CS, 0:CS] | eN[0:CS, 0:CS]
        for y, x in zip(*np.nonzero(cand)):
            y = int(y); x = int(x)
            if True:
                X, Y = x + 1, y + 1
                hasW = eW[Y, X - 1]
                hasN = eN[Y - 1, X]
                inside = Id[Y, X]
                if not (hasW or hasN):
                    # piso dos andares de cima + pilar
                    if inside and 0 < z <= min(FULL, blds[inside].get("acc", FULL)) and \
                            not nofl(inside, z, ox + x, oy + y):  # <= : forro no 1o nivel sem acesso
                        b = blds[inside]
                        st = stairs.get(inside)
                        wx, wy = ox + x, oy + y
                        if st and (wx, wy) in st_set(st) and z <= min(b["lv"], FULL) - 1:
                            pass  # vao da escada que chega neste andar
                        else:
                            fl = FLOORS_RES if b["kind"] == "res" else FLOORS_COM
                            add(x, y, z, fl[b["h"] % len(fl)])
                    if (eN[Y - 1, X - 1] or eW[Y - 1, X - 1]) and not inside:
                        owner = Id[Y - 1, X - 1] or Id[Y, X - 1] or Id[Y - 1, X]
                        if owner and blds[owner]["kind"] == "masp":
                            if z >= MASP_Z0:
                                add(x, y, z, M1 + "11")       # quina da caixa
                        elif owner:
                            sh, bs = wall_style(blds[owner])
                            add(x, y, z, f"{sh}_{bs + 3}")
                    continue
                a = Id[Y, X - 1] if hasW else 0
                n_ = Id[Y - 1, X] if hasN else 0
                owner = inside or a or n_
                b = blds[owner]
                if inside and 0 < z <= min(FULL, blds[inside].get("acc", FULL)) and \
                        not nofl(inside, z, ox + x, oy + y):  # <= : forro no 1o nivel sem acesso
                    fl = FLOORS_RES if b["kind"] == "res" else FLOORS_COM
                    add(x, y, z, fl[b["h"] % len(fl)])
                if b["kind"] == "masp":   # vao livre embaixo, caixa toda de vidro em cima
                    if z >= MASP_Z0:
                        add(x, y, z, MASP_GLASS[2] if hasW and hasN else MASP_GLASS[0] if hasW else MASP_GLASS[1])
                        if z in (MASP_Z0, MASP_LV - 1):          # vigas laterais na base e no topo da caixa
                            o_ = 0 if z == MASP_Z0 else 2
                            if hasW:
                                add(x, y, z, M2 + str(o_))
                            if hasN:
                                add(x, y, z, M2 + str(o_ + 1))
                    continue
                sh, bs = wall_style(b)
                wx, wy = ox + x, oy + y
                exterior_w = hasW and (a == 0 or inside == 0)
                exterior_n = hasN and (n_ == 0 or inside == 0)
                if hasW and hasN:
                    add(x, y, z, f"{sh}_{bs + 2}")
                    continue
                if hasW:
                    op = opening.get((x, y, "W")) if z == 0 and exterior_w else None
                    if op and op != "door":   # portao de garagem (o sprite ja e a parede)
                        add(x, y, z, op); dsq |= {(x, y, z), (x - 1, y, z)}
                        continue
                    door = op == "door"
                    out_ = (Y, X) if inside == 0 else (Y, X - 1)
                    if exterior_w and 0 < z < min(FULL, b.get("acc", FULL)) and BCw[out_] and BALw[out_] > z:
                        door = True                        # porta da varanda
                    win = exterior_w and not door and not b.get("obel") and ((wy + GY) % 3 == 1 or b["kind"] == "masp")
                    add(x, y, z, f"{sh}_{bs + (10 if door else 8 if win else 0)}")
                    if exterior_w and inside == 0 and z > 0 and not door and not win and not BALw[Y, X] and \
                            b["rooms"] != "ind" and not b.get("obel") and (x, y) not in lads and h32(wx + GX, wy + GY, z, 11) % 9 == 0:
                        add(x, y, z, AC_WALL["W"])
                    if door:
                        add(x, y, z, DOOR_EXT[0]); dsq |= {(x, y, z), (x - 1, y, z)}
                    elif win:
                        add(x, y, z, WIN_W)
                else:
                    op = opening.get((x, y, "N")) if z == 0 and exterior_n else None
                    if op and op != "door":
                        add(x, y, z, op); dsq |= {(x, y, z), (x, y - 1, z)}
                        continue
                    door = op == "door"
                    out_ = (Y, X) if inside == 0 else (Y - 1, X)
                    if exterior_n and 0 < z < min(FULL, b.get("acc", FULL)) and BCw[out_] and BALw[out_] > z:
                        door = True
                    win = exterior_n and not door and not b.get("obel") and ((wx + GX) % 3 == 1 or b["kind"] == "masp")
                    add(x, y, z, f"{sh}_{bs + 1 + (10 if door else 8 if win else 0)}")
                    if exterior_n and inside == 0 and z > 0 and not door and not win and not BALw[Y, X] and \
                            b["rooms"] != "ind" and not b.get("obel") and (x, y) not in lads and h32(wx + GX, wy + GY, z, 11) % 9 == 0:
                        add(x, y, z, AC_WALL["N"])
                    if door:
                        add(x, y, z, DOOR_EXT[1]); dsq |= {(x, y, z), (x, y - 1, z)}
                    elif win:
                        add(x, y, z, WIN_N)
        # paredes internas (grade de comodos) + comodos
        for bi in (np.unique(Id[1:-1, 1:-1]) if z < FULL else ()):
            if bi == 0:
                continue
            b = blds[bi]
            if z >= b.get("acc", FULL):
                continue
            S = grid_of(b)
            if b["kind"] == "masp" or b.get("obel"):
                S = 1000                          # MASP e obelisco: um salao por andar
            m = Id[1:-1, 1:-1] == bi
            ys, xs = np.nonzero(m)
            gx = (xs + ox + GX) // S; gy = (ys + oy + GY) // S
            sh, bs = INT_WALLS[b["h"] % len(INT_WALLS)]
            st = stairs.get(bi)
            # bordas internas entre blocos
            for (x, y, wgx, wgy) in zip(xs, ys, gx, gy):
                wx, wy = x + ox, y + oy
                if st and (wx, wy) in st_zone(st):
                    continue
                wW = bool(((wx + GX) % S == 0) and m[y, x - 1]) if x > 0 else False
                wN = bool(((wy + GY) % S == 0) and m[y - 1, x]) if y > 0 else False
                if b["kind"] == "masp" or b.get("obel"):
                    wW = wN = False
                if not (wW or wN):
                    continue
                # nao sobrepor parede externa
                if eW[y + 1, x] or eN[y, x + 1]:
                    continue
                dW = wW and ((wy + GY) % S) == S // 2
                dN = wN and ((wx + GX) % S) == S // 2 and not (z == 0 and jails.get(bi, ())[:2] == (wgx, wgy))
                if wW and wN:
                    add(x, y, z, f"{sh}_{bs + 2}")
                elif wW:
                    if dW:
                        add(x, y, z, FRAME_INT[0]); add(x, y, z, DOOR_INT[0]); dsq |= {(x, y, z), (x - 1, y, z)}
                    else:
                        add(x, y, z, f"{sh}_{bs}")
                else:
                    if dN:
                        add(x, y, z, FRAME_INT[1]); add(x, y, z, DOOR_INT[1]); dsq |= {(x, y, z), (x, y - 1, z)}
                    else:
                        add(x, y, z, f"{sh}_{bs + 1}")
            if z == 0 and bi in jails:
                put_jail(add, rooms, bld_rooms, bi, jails[bi], S, ox + GX, oy + GY, dsq)
            # comodos = blocos
            keys = {}
            for (x, y, k1, k2) in zip(xs, ys, gx, gy):
                keys.setdefault((k1, k2), []).append((x, y))
            for k, cells_ in keys.items():
                if b["kind"] == "masp" and z < MASP_Z0:
                    continue
                if z == 0 and jails.get(bi, ())[:2] == k:
                    jk = jails[bi]; jw = jail_layout(S, jk[2])[-1][1]
                    cells_ = [(x_, y_) for x_, y_ in cells_
                              if not (0 <= (x_ + ox + GX) % S - jk[3] <= jw and 0 <= (y_ + oy + GY) % S - jk[4] < 5)]
                    if not cells_:
                        continue
                rects = to_rects(cells_)
                rname = room_name(b, z, k)
                stz = {(a_ - ox, b_ - oy) for a_, b_ in st_zone(st)} if st else set()
                same = lambda xx, yy, bi=bi, k=k, S=S: Id[yy + 1, xx + 1] == bi and \
                    ((xx + ox + GX) // S, (yy + oy + GY) // S) == k
                if b["kind"] == "masp":            # pinacoteca: acervo em grade, sem mobilia comum
                    for x_, y_ in cells_:
                        spr = masp_art(x_ + ox + GX, y_ + oy + GY)
                        if spr and (x_, y_) not in stz and (x_, y_, z) not in dsq and \
                                same(x_ + 1, y_) and same(x_, y_ + 1) and same(x_ - 1, y_) and same(x_, y_ - 1):
                            add(x_, y_, z, spr); nfurn += 1
                elif not b.get("obel"):            # obelisco: so a escada por dentro
                    if rname in ROOM_FLOOR:
                        rf = T(ROOM_FLOOR[rname][h32(bi, k[0], k[1]) % len(ROOM_FLOOR[rname])])
                        for x_, y_ in cells_:
                            lst = sq.get((x_, y_, z))
                            if lst:
                                sq[(x_, y_, z)] = [rf if names[i].startswith("floors_interior") else i for i in lst]
                    nfurn += furnish(add, rname, cells_, same, z, dsq, stz, h32(bi, z, k[0], k[1]))
                bld_rooms.setdefault(bi, []).append(len(rooms))
                rooms.append((rname, z, rects))
        # escadas neste nivel
        for bi, st in stairs.items():
            b = blds[bi]
            if z > min(b["lv"], FULL) - (1 if "heli" in b else 2):   # heliponto: escada sobe ao telhado
                continue
            for sx, sy, spr in stair_cells(st):
                lx, ly = sx - ox, sy - oy
                if 0 <= lx < CS and 0 <= ly < CS and Bw[ly + 1, lx + 1] == bi:
                    add(lx, ly, z, spr)
        # varandas: piso + mureta so nas bordas livres da varanda
        if z > 0:
            bz = BALw > z
            cz = (bz[1:-1, 1:-1] | bz[1:-1, :-2] | bz[:-2, 1:-1]) & (Bw[1:-1, 1:-1] == 0)
            for y, x in zip(*np.nonzero(cz)):
                y = int(y); x = int(x); Y, X = y + 1, x + 1
                me = bz[Y, X]
                if me:
                    add(x, y, z, BAL_FLOOR)
                lw_ = me != bz[Y, X - 1] and not Bw[Y, X - 1]
                ln_ = me != bz[Y - 1, X] and not Bw[Y - 1, X]
                if lw_ and ln_:
                    add(x, y, z, LOW_NW)
                elif lw_:
                    add(x, y, z, LOW_W)
                elif ln_:
                    add(x, y, z, LOW_N)
        # telhado plano no topo, com condensadoras/exaustores (comercio) ou antena (casa)
        topm = (Bw[1:-1, 1:-1] > 0) & (Lw[1:-1, 1:-1] == z) if z > 0 else None
        if topm is not None:
            for y, x in zip(*np.nonzero(topm)):
                y = int(y); x = int(x)
                bi = Bw[y + 1, x + 1]
                st_ = stairs.get(bi)
                if st_ and "heli" in blds[bi] and (ox + x, oy + y) in st_set(st_):
                    continue                      # vao da escada que chega ao heliponto
                add(x, y, z, ROOF)
                if (ox + x, oy + y) in heli_:
                    continue
                if bi == masp or not (Bw[y, x + 1] == Bw[y + 2, x + 1] == Bw[y + 1, x] == Bw[y + 1, x + 2] == bi):
                    continue
                hh = h32(ox + x + GX, oy + y + GY, 5)
                if blds[bi]["kind"] == "res":
                    if hh % 23 == 0:
                        add(x, y, z, DISH[hh >> 8 & 1])
                elif hh % 19 == 0:
                    add(x, y, z, ROOF_BIG[(hh >> 8) % len(ROOF_BIG)])
                elif hh % 151 == 0:
                    add(x, y, z, DISH[hh >> 8 & 1])
    # escada de servico na fachada, do chao ate o andar de baixo do telhado
    for (lx, ly), (lsd, llv) in lads.items():
        for z in range(llv):
            add(lx, ly, z, LADDER[lsd])
    # letreiros das redes (farmacia, mercado, atacarejo) no terreo
    for (px, py), spr in G.get("signs", {}).items():
        lx, ly = px - ox, py - oy
        if 0 <= lx < CS and 0 <= ly < CS:
            add(lx, ly, 0, spr)
    # MASP: 4 pilares (2 em cada ponta) do chao ao teto + 2 vigas no teto ao longo do lado comprido
    if masp is not None and masp in G["bb"]:
        x0, y0, x1, y1 = G["bb"][masp]
        for (px, py) in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            lx, ly = px - ox, py - oy
            if 0 <= lx < CS and 0 <= ly < CS:
                for z in range(0, MASP_LV + 1):
                    add(lx, ly, z, masp_pillar(z))
        # vigas de cobertura (faixa vermelha sobre a laje), cruzamento sobre os pilares
        if x1 - x0 >= y1 - y0:
            beam = [(x, y, M2 + ("6" if x in (x0, x1) else "4")) for x in range(x0, x1 + 1) for y in (y0, y1)]
        else:
            beam = [(x, y, M2 + ("6" if y in (y0, y1) else "5")) for y in range(y0, y1 + 1) for x in (x0, x1)]
        for px, py, spr in beam:
            lx, ly = px - ox, py - oy
            if 0 <= lx < CS and 0 <= ly < CS:
                add(lx, ly, MASP_LV, spr)
    # extras (heliponto, camping, metro/masmorra): tiles e comodos em coordenada de raster
    for (px, py, pz), ts in G["xsq"].items():
        lx, ly = px - ox, py - oy
        if 0 <= lx < CS and 0 <= ly < CS:
            if (px, py, pz) in G["xclr"]:
                sq.pop((lx, ly, pz), None)
            for n in ts:
                add(lx, ly, pz, n)
    for rname, rz, cells_ in G["xrooms"]:
        loc = [(px - ox, py - oy) for px, py in cells_ if 0 <= px - ox < CS and 0 <= py - oy < CS]
        if loc:
            if rz < 0:   # subsolo precisa de predio proprio: comodo orfao nunca e "visto" e fica preto
                bld_rooms.setdefault(("x", rname, len(rooms)), []).append(len(rooms))
            rooms.append((rname, rz, to_rects(loc)))
    return finish_cell(cx, cy, sq, names, rooms, bld_rooms, maxz)


def wall_style(b):
    if b["rooms"] == "ind":
        return IND_WALLS
    if b["kind"] == "res":
        return RES_WALLS[b["h"] % len(RES_WALLS)]
    return COM_WALLS[b["h"] % len(COM_WALLS)]


GARAGE_W = ("walls_garage_01_2", "walls_garage_01_1", "walls_garage_01_0")   # norte -> sul (igual RC)
GARAGE_N = ("walls_garage_01_3", "walls_garage_01_4", "walls_garage_01_5")   # oeste -> leste
OUT_SCORE = {G_SIDE: 3, G_PAVE: 3, G_ASPH: 3, G_YARD: 2, G_PARK: 1, G_GRASS: 1, G_DEF: 1}


def plan_openings(Id, gw, blds, ox, oy, GX, GY):
    """Portas externas e portao de garagem no terreo, por predio na celula (padrao Raccoon City:
    todo predio com entrada, ~2-3 portas por casa, portao de garagem em parte das casas).
    Devolve {(x, y, lado): "door" | sprite do portao}. Lado W = parede oeste do quadrado, N = norte."""
    C = Id.shape[0] - 2
    eW = Id[:, 1:] != Id[:, :-1]
    eN = Id[1:, :] != Id[:-1, :]
    cand = collections.defaultdict(list)   # bi -> [(score, x, y, lado)]
    per = collections.Counter()

    def edge(x, y, side):
        X, Y = x + 1, y + 1
        if not (0 <= x < C and 0 <= y < C):
            return None
        if side == "W":
            if not eW[Y, X - 1] or eN[Y - 1, X]:
                return None
            a, b = Id[Y, X - 1], Id[Y, X]
            o = (Y, X) if b == 0 else (Y, X - 1)
        else:
            if not eN[Y - 1, X] or eW[Y, X - 1]:
                return None
            a, b = Id[Y - 1, X], Id[Y, X]
            o = (Y, X) if b == 0 else (Y - 1, X)
        if (a == 0) == (b == 0):
            return None
        return int(a or b), OUT_SCORE.get(int(gw[o]), 0)

    ys, xs = np.nonzero(eW[1:-1, 0:C] | eN[0:C, 1:-1])
    for y, x in zip(ys.tolist(), xs.tolist()):
        for side in ("W", "N"):
            e = edge(x, y, side)
            if not e:
                continue
            bi, sc = e
            if blds[bi]["kind"] == "masp":
                continue
            per[bi] += 1
            if sc == 0:
                continue
            # nao na quina: a parede continua dos dois lados
            nb = ((x, y - 1), (x, y + 1)) if side == "W" else ((x - 1, y), (x + 1, y))
            if all((edge(a, b, side) or (0,))[0] == bi for a, b in nb):
                cand[bi].append((sc, x, y, side))
    area = np.bincount(Id[1:-1, 1:-1].ravel(), minlength=len(blds) + 1)
    plan = {}
    for bi, cs in cand.items():
        cs.sort(key=lambda c: (-c[0], h32(bi, c[1] + ox + GX, c[2] + oy + GY)))
        picked = []
        b = blds[bi]
        # portao de garagem: casa (res) pequena/media, ~1 em 3, 3 quadrados voltados para rua/calcada/piso
        if (b["kind"] == "res" and 40 <= area[bi] <= 600 and h32(bi, 7) % 3 != 0) or \
                (b["kind"] not in ("res", "masp") and b.get("lv", 9) <= 2 and 30 <= area[bi] <= 400 and h32(bi, 7) % 2 == 0):
            cs_set = {(c[1], c[2], c[3]) for c in cs if c[0] >= 2}
            for sc, x, y, side in cs:
                if sc < 2:
                    break
                run = [(x, y + k) if side == "W" else (x + k, y) for k in range(3)]
                if all((a, c, side) in cs_set for a, c in run):
                    spr = GARAGE_W if side == "W" else GARAGE_N
                    for (a, c), sp in zip(run, spr):
                        plan[(a, c, side)] = sp
                    picked.append((x + 1, y + 1))
                    break
        nd = min(3, 1 + per[bi] // 40)
        nd_ = 0
        for sc, x, y, side in cs:
            if nd_ >= nd:
                break
            if (x, y, side) in plan or any(abs(x - a) + abs(y - c) < 8 for a, c in picked):
                continue
            plan[(x, y, side)] = "door"
            picked.append((x, y))
            nd_ += 1
    return plan


RES_ROOMS = ["livingroom", "bedroom", "kitchen", "bathroom", "bedroom", "livingroom"]
IND_ROOMS = ["warehouse", "factory", "metalfabrication", "factorystorage", "weldingworkshop",
             "carpentryworkshop", "warehouse", "metalshop", "mechanic", "storageunit"]
POLICE_ROOMS = ["policeoffice", "policelocker", "policeoffice", "evidenceroom", "policegunstorage",
                "policestorage"]
BLD_ROOMS = {"hotel": "motelroom", "motel": "motelroom", "garage": "garagestorage", "garages": "garagestorage",
             "greenhouse": "greenhouse", "barn": "barn", "farm_auxiliary": "barn", "church": "church",
             "chapel": "church", "school": "classroom", "kindergarten": "daycare", "hospital": "hospitalroom",
             "supermarket": "grocery", "kiosk": "cornerstore", "fire_station": "firestorage",
             "train_station": "lobby", "transportation": "lobby", "university": "classroom"}
SHOP_ROOMS = {"supermarket": "grocery", "convenience": "grocery", "bakery": "bakery",
              "pharmacy": "pharmacy", "chemist": "pharmacy", "clothes": "clothingstore",
              "shoes": "shoestore", "books": "bookstore", "electronics": "electronicstore",
              "hardware": "toolstore", "doityourself": "toolstore", "jewelry": "jewelrystore",
              "butcher": "butcher", "alcohol": "liquorstore", "beverages": "liquorstore",
              "sports": "sportstore", "furniture": "furniturestore", "mobile_phone": "electronicstore",
              "gift": "giftstore", "optician": "glassesstore", "florist": "florist",
              "car_parts": "carsupply", "car": "carsupply", "car_repair": "mechanic", "tyres": "carsupply",
              "garden_centre": "gardenstore", "pet": "petstore", "toys": "toystore", "music": "musicstore",
              "musical_instrument": "musicstore", "weapons": "gunstore", "department_store": "departmentstore",
              "mall": "departmentstore", "kiosk": "cornerstore", "laundry": "laundry", "dry_cleaning": "laundry",
              "tailor": "tailoringstore", "fabric": "tailoringstore", "pawnbroker": "pawnshop",
              "second_hand": "pawnshop", "tobacco": "tobaccostore", "confectionery": "candystore",
              "outdoor": "outdoorsupply", "paint": "paintershop", "photo": "camerastore", "camera": "camerastore",
              "houseware": "housewarestore", "kitchen": "housewarestore", "books;stationery": "bookstore",
              "stationery": "bookstore", "comic": "comicstore", "video_games": "electronicstore",
              "computer": "electronicstore", "greengrocer": "grocery", "deli": "butcher", "seafood": "butcher",
              "art": "artstore", "craft": "artstore", "bicycle": "sportstore", "variety_store": "generalstore",
              "general": "generalstore", "trade": "toolstore", "agrarian": "gardenstore", "bag": "clothingstore",
              "boutique": "clothingstore", "cosmetics": "pharmacy", "beauty": "pharmacy", "medical_supply": "pharmacy",
              "ice_cream": "icecream", "pastry": "bakery", "wine": "liquorstore", "storage_rental": "storageunit"}
_SHOP_EXTRA = {"greengrocer": "grocery", "deli": "grocery", "pastry": "bakery", "variety_store": "generalstore",
               "wine": "liquorstore", "seafood": "butcher", "cosmetics": "pharmacy", "perfumery": "giftstore",
               "medical_supply": "pharmacy", "frozen_food": "grocery", "copyshop": "bookstore",
               "building_materials": "toolstore", "trade": "toolstore", "electrical": "toolstore",
               "computer": "electronicstore", "bag": "clothingstore", "boutique": "clothingstore",
               "fashion": "clothingstore", "watches": "jewelrystore", "motorcycle": "carsupply"}
AMEN_ROOMS = {"restaurant": "restaurantdining", "fast_food": "burgerkitchen", "cafe": "cafe",
              "bar": "bar", "pub": "bar", "bank": "office", "pharmacy": "pharmacy",
              "police": "policestorage", "hospital": "hospitalroom", "clinic": "medical",
              "school": "classroom", "university": "classroom", "library": "library",
              "fire_station": "firestorage", "place_of_worship": "church", "cinema": "theatre",
              "theatre": "theatre", "fuel": "gasstore", "post_office": "post", "museum": "office",
              "dentist": "dentist", "doctors": "medicaloffice", "kindergarten": "daycare", "gym": "gym",
              "prison": "prisoncells", "marketplace": "grocery", "ice_cream": "icecream", "nightclub": "bar",
              "townhall": "office", "courthouse": "office", "community_centre": "hall", "veterinary": "medical",
              "car_wash": "mechanic", "vehicle_inspection": "mechanic", "food_court": "restaurantdining",
              "arts_centre": "theatre", "social_facility": "hall", "college": "classroom"}
for _k, _v in _SHOP_EXTRA.items():
    SHOP_ROOMS.setdefault(_k, _v)


def room_poi(b, z, k):
    """POI que nomeia o comodo: no terreo de predio com varias lojas, a mais perto do centro do comodo."""
    ps = b.get("pois") or []
    if z != 0 or len(ps) < 2:
        return b.get("poi")
    S = grid_of(b)
    cx, cy = (k[0] + .5) * S - G["rx0"] - CX0 * CS, (k[1] + .5) * S - G["ry0"] - CY0 * CS
    best = min(ps, key=lambda p: ((p[0] - cx) ** 2 + (p[1] - cy) ** 2, 0 if (p[2].get("shop") or
                                                                              p[2].get("amenity") in AMEN_ROOMS) else 1))
    return best[2]


def room_name(b, z, k):
    t = dict(b["tags"])
    poi = room_poi(b, z, k)
    if poi:
        for kk in ("shop", "amenity"):
            t.setdefault(kk, poi.get(kk))
    if b["kind"] == "masp":
        return ("artstore", "office", "storage")[(k[0] + k[1] + z) % 3] if z >= MASP_Z0 else "empty"
    if t.get("amenity") == "police":
        return POLICE_ROOMS[(k[0] * 3 + k[1] + z) % len(POLICE_ROOMS)]
    if b.get("mil"):
        return "armystorage" if (k[0] + k[1] + z) % 3 else "office"
    if b.get("hosp") and z > 0:
        return "hospitalroom" if (k[0] + k[1] + z) % 4 else "medical"
    if t.get("leisure") in ("fitness_centre", "sports_centre") and z == 0:
        return "gym"
    if b["rooms"] == "ind":
        if t.get("shop") in SHOP_ROOMS and z == 0:
            return SHOP_ROOMS[t["shop"]]
        return IND_ROOMS[(k[0] * 5 + k[1] * 3 + z) % len(IND_ROOMS)]
    if b["rooms"] == "res":
        return RES_ROOMS[(k[0] * 3 + k[1] + z) % len(RES_ROOMS)]
    if b["rooms"] == "apt":   # predio residencial: terreo portaria/loja, andares apartamentos
        if z == 0:
            if t.get("shop") in SHOP_ROOMS:
                return SHOP_ROOMS[t["shop"]]
            if t.get("amenity") in AMEN_ROOMS:
                return AMEN_ROOMS[t["amenity"]]
            return "hall" if (k[0] + k[1]) % 2 == 0 else "storage"
        return RES_ROOMS[(k[0] * 3 + k[1] + z) % len(RES_ROOMS)]
    if z == 0:
        if t.get("shop") in SHOP_ROOMS:
            return SHOP_ROOMS[t["shop"]]
        if t.get("amenity") in AMEN_ROOMS:
            return AMEN_ROOMS[t["amenity"]]
        if t.get("building") in BLD_ROOMS:
            return BLD_ROOMS[t["building"]]
        if t.get("building") in ("retail", "commercial"):
            return "generalstore"
    if t.get("amenity") in ("hospital", "clinic"):
        return "hospitalroom"
    if t.get("amenity") in ("school", "university"):
        return "classroom"
    if t.get("building") in ("hotel", "motel") or t.get("tourism") in ("hotel", "motel", "hostel"):
        return "motelroom"
    if t.get("building") in ("apartments", "residential"):
        return RES_ROOMS[(k[0] * 3 + k[1] + z) % len(RES_ROOMS)]
    return "office"


def to_rects(cells_):
    """cells (x,y) locais -> retangulos (x,y,w,h) juntando faixas de linhas iguais."""
    rows = {}
    for x, y in cells_:
        rows.setdefault(int(y), []).append(int(x))
    runs = {}
    for y, xsr in rows.items():
        xsr.sort()
        s = p = xsr[0]
        out = []
        for v in xsr[1:]:
            if v == p + 1:
                p = v
                continue
            out.append((s, p)); s = p = v
        out.append((s, p))
        runs[y] = out
    rects = []
    open_ = {}
    for y in sorted(runs):
        cur = {}
        for r in runs[y]:
            if r in open_ and open_[r][1] + open_[r][2] == y:
                ry0 = open_[r][1]
                cur[r] = (r, ry0, open_[r][2] + 1)
            else:
                cur[r] = (r, y, 1)
        for r, v in open_.items():
            if r not in cur or cur[r][1] != v[1]:
                rects.append((v[0][0], v[1], v[0][1] - v[0][0] + 1, v[2]))
        open_ = cur
    for r, v in open_.items():
        rects.append((v[0][0], v[1], v[0][1] - v[0][0] + 1, v[2]))
    return rects


def finish_cell(cx, cy, sq, names, rooms, bld_rooms, maxz):
    """Escreve lotheader, lotpack e chunkdata de uma celula."""
    zmax = max([k[2] for k in sq] + [0])
    zmin = min([k[2] for k in sq] + [0])          # subsolo (metro) = z negativo
    # lotheader
    hb = bytearray(b"LOTH")
    hb += struct.pack("<ii", 1, len(names))
    for n in names:
        hb += n.encode("latin1") + b"\n"
    hb += struct.pack("<5i", 8, 8, zmin, zmax, len(rooms))
    for name, z, rects in rooms:
        hb += name.encode("latin1") + b"\n"
        hb += struct.pack("<ii", z, len(rects))
        for r in rects:
            hb += struct.pack("<4i", *r)
        hb += struct.pack("<i", 0)
    hb += struct.pack("<i", len(bld_rooms))
    for bi, lst in bld_rooms.items():
        hb += struct.pack("<i", len(lst)) + struct.pack(f"<{len(lst)}i", *lst)
    # densidade de zumbis por chunk (0..4): mais predio = mais zumbi
    dens = bytearray(1024)
    occ = np.zeros((32, 32), np.int32)
    for (x, y, z), t in sq.items():
        if z == 1:
            occ[x // 8, y // 8] += 1
    for ci in range(1024):
        a, b = ci // 32, ci % 32
        dens[ci] = min(2, 1 + occ[a, b] // 32)   # PC fraco: no maximo 2 (RC usa 3); o sandbox ainda pode subir
    hb += dens
    # lotpack
    body = bytearray()
    offs = []
    base = 12 + 8 * 1024
    for ci in range(1024):
        ccx, ccy = ci // 32, ci % 32
        offs.append(base + len(body))
        skip = 0
        for z in range(zmin, zmax + 1):
            for x in range(8):
                for y in range(8):
                    t = sq.get((ccx * 8 + x, ccy * 8 + y, z))
                    if not t:
                        skip += 1
                        continue
                    if skip:
                        body += struct.pack("<ii", -1, skip); skip = 0
                    body += struct.pack("<ii", len(t) + 1, -1) + struct.pack(f"<{len(t)}i", *t)
        if skip:
            body += struct.pack("<ii", -1, skip)
    lp = bytearray(b"LOTP") + struct.pack("<ii", 1, 1024) + struct.pack("<1024q", *offs) + body
    ch = put(f"{cx}_{cy}.lotheader", hb) | put(f"world_{cx}_{cy}.lotpack", lp)   # chunkdata: o export grava
    if ch:
        G.setdefault("changed", []).append((cx, cy))
    return cx, cy, len(names), len(rooms), len(bld_rooms), zmax


def put(name, data):
    """grava so se o conteudo mudou (mantem mtime e evita re-render dos visualizadores)."""
    fp = os.path.join(OUT, name)
    data = bytes(data)
    try:
        if os.path.getsize(fp) == len(data):
            with open(fp, "rb") as f:
                if f.read() == data:
                    return False
    except OSError:
        pass
    with open(fp, "wb") as f:
        f.write(data)
    return True


# ---------------------------------------------------------------- bloco
def block_cells(bk):
    bi_, bj_ = bk
    return [(CX0 + bi_ * BS + i, CY0 + bj_ * BS + j) for i in range(BS) for j in range(BS)
            if bi_ * BS + i < NCX and bj_ * BS + j < NCY]


def process_block(bk):
    """worker (nivel de modulo, spawn): rasteriza o bloco e grava as celulas dele."""
    G["changed"] = []
    r = _process_block(bk)
    return r + (G["changed"],)


def _process_block(bk):
    from .. import progress as PG
    bi_, bj_ = bk
    PG.micro("celulas", f"bloco {bi_}_{bj_}", "rasterizando fontes", 0.0)
    rx0, ry0 = bi_ * BS * CS - MG, bj_ * BS * CS - MG
    G["rx0"], G["ry0"] = rx0, ry0
    Ga, LNa, Ba, Lv, blds, masp, roads, TR = build_rasters(rx0, ry0)
    bb = bld_bbox(Ba, len(blds))
    PG.micro("celulas", f"bloco {bi_}_{bj_}", "planejando escadas, celas, letreiros", 0.15)
    stairs = plan_stairs(Ba, Lv, blds, bb, masp)
    jails = plan_jails(Ba, blds, bb, stairs)
    signs = plan_signs(Ga, Ba, blds, bb, masp)
    G.update(Ga=Ga, LNa=LNa, Ba=Ba, Lv=Lv, blds=blds, stairs=stairs, masp=masp, TR=TR, ntree=int(TR.sum()),
             jails=jails, signs=signs,
             bb={masp: tuple(int(v) for v in bb[masp])} if masp else {})
    res = []
    for c in block_cells(bk):
        PG.micro("celulas", f"bloco {bi_}_{bj_}", f"celula {c[0]}_{c[1]} ({block_cells(bk).index(c) + 1}/{len(block_cells(bk))})",
                 0.2 + 0.75 * block_cells(bk).index(c) / len(block_cells(bk)))
        if shutil.disk_usage(OUT).free < MINFREE:
            res.append((c, None, ""))
            continue
        r = write_cell(c)
        res.append((c, r, ""))  # worldmap: scripts/worldmap.py
    PG.micro("celulas", f"bloco {bi_}_{bj_}", "salvando raster e spawns", 0.97)
    core = (slice(MG, MG + BS * CS), slice(MG, MG + BS * CS))
    os.makedirs(RAS, exist_ok=True)
    # mapa do jogo: classe da via (1 primaria, 2 secundaria, 3 terciaria) e categoria do predio
    R = Image.new("L", (W, H), 0)
    dR = ImageDraw.Draw(R)
    for cls, hws in ((3, None), (2, ("secondary", "secondary_link")),
                     (1, ("motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link"))):
        for wd, code, pts, hw, t in roads:
            if code == G_ASPH and (hws is None or hw in hws) and len(pts) >= 2:
                dR.line([tuple(p) for p in pts], fill=cls, width=max(1, int(wd)))
    Ra = np.array(R, dtype=np.uint8)
    Ra[Ga != G_ASPH] = 0
    Ra[(Ga == G_ASPH) & (Ra == 0)] = 3
    cat = np.array([0] + [bcat(b) for b in blds[1:]], np.uint8)
    Ka = cat[Ba]
    np.savez_compressed(os.path.join(RAS, f"b_{bi_}_{bj_}.npz"), G=Ga[core], L=Lv[core], R=Ra[core], K=Ka[core])
    spawn = []
    lx, ly = MXm - rx0, MYm - ry0
    if 250 <= lx < W - 250 and 250 <= ly < H - 250 and MG <= lx < MG + BS * CS and MG <= ly < MG + BS * CS:
        sub = Ga[ly - 250:ly + 250, lx - 250:lx + 250]
        ys, xs = np.nonzero((sub == G_SIDE) & (Ba[ly - 250:ly + 250, lx - 250:lx + 250] == 0))
        for k in range(0, len(xs), max(1, len(xs) // 24)):
            spawn.append((int(xs[k]) + MX - 250, int(ys[k]) + MY - 250))
        spawn = spawn[:24]
    sp = spawn_points(Ba, blds, stairs, jails)
    sp["center"] = spawn
    with open(os.path.join(RAS, f"sp_{bi_}_{bj_}.json"), "w") as f:
        json.dump(sp, f)
    with open(os.path.join(RAS, f"pts_{bi_}_{bj_}.json"), "w") as f:
        json.dump(G["pts"], f)
    stats = {"blds": len(blds) - 1, "footprints": sum(1 for b in blds[1:] if b["tags"].get("src") == "footprints"),
             "stairs": len(stairs), "trees": int(TR.sum()), "celas": len(jails),
             "ind": sum(1 for b in blds[1:] if b["rooms"] == "ind")}
    return bk, res, spawn, stats


def spawn_points(Ba, blds, stairs, jails):
    """pontos de nascimento por tipo (mundo): casas pobre/media/rica, delegacia, hospital, bombeiro, cela."""
    GX, GY = G["rx0"] + CX0 * CS, G["ry0"] + CY0 * CS
    core = Ba[MG:MG + BS * CS, MG:MG + BS * CS]
    flat = core.ravel()
    nb = len(blds)
    cnt = np.bincount(flat, minlength=nb)
    order = np.argsort(flat, kind="stable")
    start = np.concatenate([[0], np.cumsum(cnt)])
    out = {k: [] for k in ("poor", "medium", "rich", "police", "doctor", "fire", "jail")}
    for i in range(1, nb):
        if cnt[i] < 9:
            continue
        b = blds[i]
        zone = st_set(stairs[i]) if i in stairs else set()
        pick = None
        for frac in (2, 3, 4):
            o = int(order[start[i] + cnt[i] // frac])
            y, x = divmod(o, BS * CS)
            if (x + MG, y + MG) not in zone:
                pick = (x + MG + GX, y + MG + GY); break
        if pick is None:
            continue
        t = btags(b)
        am = t.get("amenity")
        if (b.get("hosp") or b.get("gov")) and cnt[i] >= 60:
            G["pts"].setdefault("gen", []).append((pick[0], pick[1], 0))
        if am == "police":
            out["police"].append(pick)
        elif am in ("hospital", "clinic", "doctors"):
            out["doctor"].append(pick)
        elif am == "fire_station":
            out["fire"].append(pick)
        elif b["rooms"] in ("res", "apt") and h32(i, b["h"], 5) % 6 == 0:
            a = int(cnt[i])
            k = "medium" if b["rooms"] == "apt" else "poor" if a < 90 else "medium" if a < 200 else "rich"
            out[k].append(pick)
    for i, k in jails.items():
        S = grid_of(blds[i])
        for c0, _ in jail_layout(S, k[2]):
            wx, wy = k[0] * S + k[3] + c0 + 2, k[1] * S + k[4] + 3
            if MG <= wx - GX < MG + BS * CS and MG <= wy - GY < MG + BS * CS:
                out["jail"].append((wx, wy))
    return out


PROF = {"unemployed": ("poor", "medium", "rich", "center"), "burglar": ("jail",), "policeofficer": ("police",),
        "fireofficer": ("fire",), "doctor": ("doctor", "rich"), "nurse": ("doctor", "medium"),
        "securityguard": ("medium", "rich"), "parkranger": ("medium",), "chef": ("poor", "medium", "rich"),
        "constructionworker": ("poor", "medium"), "repairman": ("poor", "medium"),
        "burgerflipper": ("poor", "medium"), "carpenter": ("poor", "medium"), "electrician": ("poor", "medium"),
        "engineer": ("medium", "rich"), "farmer": ("poor",), "fisherman": ("poor",),
        "fitnessInstructor": ("medium", "rich"), "lumberjack": ("poor",), "mechanics": ("poor", "medium"),
        "metalworker": ("poor", "medium"), "rancher": ("poor",), "smither": ("poor",), "tailor": ("poor", "medium"),
        "veteran": ("poor", "medium"), "veterinarian": ("medium", "rich")}


def write_spawns():
    """spawnpoints.lua no formato vanilla (tabelas por tipo de casa + merge por profissao)."""
    import glob
    L = {}
    for fn in sorted(glob.glob(os.path.join(RAS, "sp_*.json"))):
        for k, v in json.load(open(fn)).items():
            # bloco de borda passa do limite do mapa: so pontos em celula que existe
            L.setdefault(k, []).extend(tuple(p) for p in v if os.path.exists(
                os.path.join(OUT, f"{p[0] // CS}_{p[1] // CS}.lotheader")))
    cap = {"poor": 300, "medium": 300, "rich": 300, "police": 120, "doctor": 120, "fire": 60, "jail": 120,
           "center": 24}
    for k in list(L):
        v = sorted(set(L[k]), key=lambda p: h32(p[0], p[1], 9))
        L[k] = v[:cap.get(k, 200)]
    for k in cap:
        L.setdefault(k, [])
    fb = L["medium"] or L["poor"] or L["center"] or [(MX, MY)]
    with open(os.path.join(GENDIR, "spawnpoints.lua"), "w") as f:
        f.write("local function merge(...)\n    local r = {}\n    for _, t in ipairs({...}) do\n"
                "        for _, p in ipairs(t) do table.insert(r, p) end\n    end\n    return r\nend\n\n"
                "function SpawnPoints()\n")
        for k in cap:
            v = L[k] or fb
            f.write(f"    local {k} = {{\n" + "".join(f"        {{ posX = {x}, posY = {y}, posZ = 0 }},\n"
                                              for x, y in v) + "    }\n")
        f.write("    return {\n")
        for p, ks in PROF.items():
            f.write(f"        {p} = merge({', '.join(ks)}),\n")
        f.write("    }\nend\n")
    return {k: len(v) for k, v in L.items()}
