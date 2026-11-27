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

from . import genfast as GF  # noqa: E402  rotinas nativas em Rust (pre-compiladas): GF.C (ctypes) e GF.GP (_gfpy)

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
YARD = ["floors_exterior_street_01_17", "floors_exterior_street_01_16"]   # _19 = meia-peca (buraco), _18 = piso preto: nunca usar
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
VITRINE = ("walls_commercial_02_52", "walls_commercial_02_48")   # W, N: parede de vidro do chao ao teto (vanilla, FullWindow)
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
FURN["shopfreezer"] = _f("appliances_refrigeration_01", S=48, E=49, N=50, W=51)
FURN["chair"] = _f("furniture_seating_outdoor_01", E=16, S=17, N=18, W=19)    # cadeira plastica
# hospital/clinica/farmacia (location_community_medical_01, como no vanilla)
_M = "location_community_medical_01"
FURN["firstaid"] = _f(_M, S=88, E=89, N=90, W=91)          # armario de primeiros socorros (medicine)
FURN["widemed"] = _f(_M, E=152, S=154, N=238, W=246)       # armario medico largo (medicine)
FURN["pdrawers"] = _f(_M, E=36, S=37, W=38, N=39)          # criado-mudo de hospital (sidetable)
FURN["iv"] = _f(_M, E=24, S=25, W=26, N=27)                # suporte de soro
FURN["tooltray"] = _f(_M, W=48, S=49, E=50, N=51)          # carrinho de instrumentos
FURN["bloodbank"] = _f(_M, S=102, E=103, N=110, W=111)
FURN["microscope"] = _f(_M, S=136, E=137, W=138, N=139)
FURN["mdesk"] = _f(_M, E=106, S=107)
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
ISLAND.update({k: "desks" for k in ("office", "policeoffice", "classroom", "post", "medicaloffice")})
ISLAND.update({k: "beds" for k in ("hospitalroom", "medical")})
ISLAND.update({k: "dine" for k in ("kitchen", "livingroom")})
DINE_CHAIR = _f("furniture_seating_indoor_02", S=0, E=1, N=2, W=3)   # cadeira de madeira (casa)
TV =_f("appliances_television_01", E=0, S=1, W=2, N=3)
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
    "hbed": {"S": ("location_community_medical_01_73", "location_community_medical_01_72", 0, 1),
             "E": ("location_community_medical_01_74", "location_community_medical_01_75", 1, 0)},
    "hbed2": {"S": ("furniture_bedding_01_65", "furniture_bedding_01_64", 0, 1),
              "E": ("furniture_bedding_01_66", "furniture_bedding_01_67", 1, 0)},
    "stretcher": {"S": ("furniture_bedding_01_57", "furniture_bedding_01_56", 0, 1),
                  "E": ("furniture_bedding_01_58", "furniture_bedding_01_59", 1, 0)},
    "exambed": {"S": ("location_community_medical_01_17", "location_community_medical_01_16", 0, 1),
                "N": ("location_community_medical_01_19", "location_community_medical_01_18", 0, 1),
                "W": ("location_community_medical_01_20", "location_community_medical_01_21", 1, 0),
                "E": ("location_community_medical_01_22", "location_community_medical_01_23", 1, 0)},
    "waiting": {"S": ("location_community_medical_01_58", "location_community_medical_01_59", 1, 0),
                "E": ("location_community_medical_01_57", "location_community_medical_01_56", 0, 1),
                "N": ("location_community_medical_01_62", "location_community_medical_01_63", 1, 0),
                "W": ("location_community_medical_01_61", "location_community_medical_01_60", 0, 1)},
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


_RS = []    # room_style: [(7001 + i, tipo, pool, len)] e {grupo: 1a poltrona}, montados na 1a chamada


def room_style(seed):
    """estilo do comodo: {tipo: dict de faces}; sofa e poltrona do mesmo grupo quando existe.
    h32(seed, 7001 + i) com o 1o passo do hash fixo por comodo (mesmo resultado)."""
    if not _RS:
        _RS.append([(7001 + i, k, pool, len(pool)) for i, (k, pool) in
                    enumerate(sorted(VAR.items()) + sorted(VAR2.items())) if pool])
        arm = {}
        for gn, v in VAR.get("armchair", ()):
            arm.setdefault(gn, v)
        _RS.append(arm)
    hs = ((2166136261 ^ (int(seed) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    st = {k: pool[(((hs ^ c) * 16777619) & 0xFFFFFFFF) % n] for c, k, pool, n in _RS[0]}
    if "couch" in st:
        v = _RS[1].get(st["couch"][0])
        if v is not None:
            st["armchair"] = (st["couch"][0], v)
    return {k: v[1] for k, v in st.items()}
# piso proprio por comodo (azulejo no banheiro, ladrilho na cozinha)
ROOM_FLOOR = {"bathroom": ["floors_interior_tilesandwood_01_5", "floors_interior_tilesandwood_01_11",
                           "floors_interior_tilesandwood_01_2"],
              "kitchen": ["floors_interior_tilesandwood_01_4", "floors_interior_tilesandwood_01_10",
                          "floors_interior_tilesandwood_01_3"]}
# pisos mais comuns por tipo de comodo no vanilla (Muldraugh inteiro, contagem por quadrado de comodo)
_FT, _FC = "floors_interior_tilesandwood_01_", "floors_interior_carpet_01_"
for _rs, _fl in (
        (("hospitalroom", "medclinic", "medical", "laboratory", "medicalstorage", "hospitalstorage", "pharmacy",
          "medicaloffice", "waitingroom", "dentist"), [_FT + "17"]),
        (("office", "post"), [_FC + "3", _FC + "13", _FC + "2"]),
        (("classroom", "daycare"), [_FC + "5", _FC + "1"]),
        (("policeoffice", "evidenceroom"), [_FC + "8"]),
        (("lobby",), [_FC + "9"]),
        (("grocery", "butcher"), [_FT + "8"]),
        (("cornerstore", "gasstore", "liquorstore", "tobaccostore"), [_FT + "17", _FT + "29", _FT + "16"]),
        (("generalstore", "departmentstore", "toolstore"), [_FT + "45"]),
        (("clothingstore", "shoestore", "tailoringstore"), [_FT + "44", _FT + "46"]),
        (("burgerkitchen", "pizzakitchen"), [_FT + "29"]),
        (("restaurantdining",), [_FT + "44", _FT + "23", _FT + "36"]),
        (("bar",), [_FT + "20", _FT + "41"]),
        (("cafe", "icecream"), [_FT + "21", _FT + "4"]),
        (("bakery",), [_FT + "44", _FT + "6"])):
    for _r in _rs:
        ROOM_FLOOR.setdefault(_r, _fl)
# parede interna pelo uso do predio (as mais comuns por comodo no vanilla); a laranja chapada
# (walls_interior_house_02 base 16) sai do sorteio residencial
INT_WALLS_USE = {"hosp": [("walls_interior_house_04", 80), ("walls_interior_house_03", 16)],
                 "school": [("walls_interior_house_03", 32)],
                 "office": [("walls_interior_house_02", 48), ("walls_interior_house_03", 32)],
                 "shop": [("walls_interior_house_03", 16), ("walls_interior_house_02", 48),
                          ("walls_interior_house_04", 64)]}


def int_wall(b):
    t = dict(b["tags"])
    a = t.get("amenity")
    if b.get("hosp") or a in ("hospital", "clinic", "doctors", "pharmacy", "dentist"):
        L = INT_WALLS_USE["hosp"]
    elif a in ("school", "university", "college", "kindergarten"):
        L = INT_WALLS_USE["school"]
    elif t.get("shop") or t.get("building") in ("retail", "commercial", "supermarket") or a in AMEN_ROOMS:
        L = INT_WALLS_USE["shop"]
    elif b["rooms"] in ("res", "apt") or b.get("kind") == "masp":
        L = [w for w in INT_WALLS if w != ("walls_interior_house_02", 16)]
    else:
        L = INT_WALLS_USE["office"]
    return L[b["h"] % len(L)]


REGISTER = _f("location_shop_accessories_01", E=0, S=1, N=2, W=3)   # em cima do 1o balcao da loja
BED = {"S": ("furniture_bedding_01_1", "furniture_bedding_01_0"),   # parede N: cabeceira (0,0) + pe (0,1) ao sul
       "E": ("furniture_bedding_01_2", "furniture_bedding_01_3")}   # parede W: (0,0) + (1,0) a leste
FACE = {"N": "S", "W": "E", "S": "N", "E": "W"}                      # parede -> Facing
# por comodo: (itens fixos, itens que repetem para encher a loja, caixa registradora)
FURNISH = {
    "kitchen": (["counter", "stove", "counter", "fridge", "counter", "counter", "counter", "counter"], ["counter"], 3),
    "bathroom": (["toilet", "sink", "bath", "medicine", "shower", "counter"], ["counter", "mshelf"], 3),
    "bedroom": (["bed", "dresser", "sidetable", "wardrobe", "shelf", "armchair", "sidetable"],
                ["sidetable", "dresser", "shelf", "armchair"], 3),
    "livingroom": (["couch", "tvstand", "bookshelf", "armchair", "sidetable", "couch2", "bookshelf", "armchair"],
                   ["armchair", "sidetable", "bookshelf"], 3),
    "office": (["desk", "filing", "desk", "shelf"], ["filing", "desk"], False),
    "medicaloffice": (["mdesk", "exambed", "filing", "firstaid", "counter"], ["widemed"], 6),
    "classroom": (["desk", "shelf"], ["bench"], 4),
    "hospitalroom": (["firstaid", "widemed"], ["hbed", "pdrawers", "iv", "hbed2", "pdrawers", "stretcher"], 3),
    "hospitalstorage": (["widemed"], ["widemed", "mshelf", "firstaid"], 4),
    "medicalstorage": (["widemed"], ["widemed", "mshelf", "firstaid"], 4),
    "laboratory": (["counter", "microscope"], ["counter", "bloodbank", "microscope"], 4),
    "waitingroom": (["counter", "firstaid"], ["waiting", "stretcher", "waiting"], 4),
    "medical": (["counter", "mdesk", "firstaid"], ["exambed", "widemed", "tooltray", "hbed", "iv"], 4),
    "library": (["counter"], ["shelf"], False),
    "storage": ([], ["mshelf", "shelf"], False),
    "policestorage": (["filing"], ["locker", "mshelf"], False),
    "firestorage": (["toolcab"], ["locker", "mshelf"], False),
    "post": (["counter", "desk"], ["mshelf", "locker"], False),
    "lobby": (["counter"], [], False),
    "theatre": (["counter"], ["shelf", "counter"], 15),
    "church": (["counter"], ["shelf", "sidetable"], 15),
    "hall": (["sidetable"], ["sidetable", "shelf", "bookshelf"], 7),
    "glassesstore": (["counter"], ["display", "shelf"], True),
    "grocery": (["counter", "cooler", "cooler", "shopfreezer", "shopfreezer", "cooler", "shopfreezer", "cooler"],
                ["sshelf", "grocer", "cooler", "shopfreezer"], True),
    # estoque do supermercado: prateleiras metalicas encostadas (o miolo vira fileiras, ISLAND)
    "grocerystorage": (["mshelf", "mshelf"], ["mshelf", "mshelf", "sshelf"], 3),
    "restaurantkitchen": (["counter", "stove", "counter", "fridge", "sink", "counter", "stove"], ["counter", "mshelf"], 4),
    "cafekitchen": (["counter", "stove", "fridge", "sink", "counter"], ["counter", "mshelf"], 4),
    "generalstore": (["counter", "cooler"], ["sshelf", "sshelf", "mshelf"], True),
    "pharmacy": (["counter", "counter", "widemed", "cooler", "mags", "firstaid"], ["sshelf", "sshelf", "widemed"], True),
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
    "burgerkitchen": (["counter", "stove", "fridge", "sink", "counter", "stove"], ["counter", "mshelf"], 4),
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
    "hall": (["sidetable"], ["sidetable", "shelf", "bookshelf"], 7),
    "mall": (["counter"], ["shelf"], True),
}
STOREISH = ("store", "shop", "supply")
HAND_ONLY = {"kitchen", "bathroom", "bedroom", "livingroom", "motelroom"}     # variedade propria (room_style)
HAND_MERGE = {"medicaloffice", "hospitalroom", "hospitalstorage", "medicalstorage", "laboratory", "waitingroom",
              "medical", "pharmacy", "grocery", "grocerystorage", "restaurantkitchen", "cafekitchen",
              "burgerkitchen"}                                              # mao + modelo vanilla
SEATS = ("Chair", "Seat", "Stool", "Seating", "Pew", "Bench")


def _tpl_build():
    """modelos de mobilia por comodo extraidos dos mapas vanilla (scripts/extrai_tpl.py -> room_tpl.json):
    {comodo: dict(fx, rep, per, tops, seat, gond)} e registra cada movel em FURN (1 quadrado) / TWO (2)."""
    try:
        RT = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "room_tpl.json")))
    except OSError:
        return {}
    idx = collections.defaultdict(lambda: collections.defaultdict(dict))
    for n, p_ in _TD.items():
        if p_.get("Facing") and p_.get("CustomName"):
            idx[(n.rsplit("_", 1)[0], p_.get("GroupName", ""), p_["CustomName"])][p_["Facing"]][
                p_.get("SpriteGridPos", "0,0")] = n
    out = {}
    for room, e in RT.items():
        fx, rep, tops, seat, gond, row, wsum = [], [], [], None, None, None, 0.0
        for it in e["items"]:
            if "Corner" in it["group"] or "Left" in it["group"] or "Right" in it["group"]:
                continue
            fs = idx.get((it["sheet"], it["group"], it["name"]))
            if not fs:
                continue
            key = f"v:{it['sheet']}|{it['group']}|{it['name']}"
            p0 = _TD[next(iter(next(iter(fs.values())).values()))]
            nparts = max(len(v) for v in fs.values())
            if nparts == 1:
                FURN[key] = {f: v["0,0"] for f, v in fs.items() if "0,0" in v}
            elif nparts <= 4:              # em linha: (0,0) + (1,0),(2,0).. ou (0,1),(0,2)..
                d = {}
                for f, v in fs.items():
                    for ax, (dx_, dy_) in (("x", (1, 0)), ("y", (0, 1))):
                        ks = [f"{i * dx_},{i * dy_}" for i in range(1, len(v))]
                        if "0,0" in v and ks and all(k in v for k in ks):
                            rest = [v[k] for k in ks]
                            d[f] = (v["0,0"], rest[0] if len(rest) == 1 else rest, dx_, dy_)
                if not d:
                    continue
                TWO[key] = d
            else:
                continue
            if "IsTableTop" in p0:
                if "Register" not in it["name"] and it["rooms"] >= 0.04:
                    (tops.insert(0, key) if it["name"] == "Sink" else tops.append(key))
                continue
            if any(s in it["name"] for s in SEATS) and "container" not in p0:
                if seat is None and nparts == 1 and len(FURN[key]) == 4:
                    seat = key
                if row is None and it["wall"] < 0.5 and it["per100"] >= 0.5:
                    row = key
                if it["rooms"] >= 0.05:          # cadeiras/bancos soltos tambem entram no sorteio
                    rep += [key] * max(1, min(4, round(it["per100"] / 0.4)))
                    wsum += it["per100"] * 0.5   # e na densidade (metade: a mesa ja traz cadeira)
                continue
            if nparts == 2 and it["wall"] < 0.4 and "container" in p0 and gond is None and len(TWO[key]) == 4 \
                    and isinstance(TWO[key]["S"][1], str):
                gond = key
            if it["rooms"] < 0.03:
                continue
            wsum += it["per100"]
            if it["rooms"] >= 0.2 and len(fx) < 4:
                fx.append(key)
            rep += [key] * max(1, min(8, round(it["per100"] / 0.2)))
        if fx or rep:
            out[room] = {"fx": fx, "rep": rep, "per": max(3, min(7, round(100 / max(wsum, 1)))),
                         "tops": tops[:6], "seat": seat, "gond": gond, "row": row or seat}
    return out


TPL = _tpl_build()
# comodo do gerador sem amostra vanilla suficiente: mobilia do equivalente vanilla (o nome/loot continua o nosso)
TPL_ALIAS = {"camerastore": "electronicsstore", "comicstore": "bookstore", "dentist": "medclinic",
             "electronicstore": "electronicsstore", "florist": "gardenstore", "glassesstore": "optometrist",
             "hospitalroom": "medclinic", "laboratory": "medical", "outdoorsupply": "camping",
             "petstore": "generalstore", "restaurantdining": "restaurant", "tailoringstore": "sewingstore",
             "tobaccostore": "cornerstore", "waitingroom": "lobby", "clothingstore": "clothesstore"}
for _a, _b in TPL_ALIAS.items():
    if _b in TPL and (_a not in TPL or _a == "clothingstore"):
        TPL[_a] = TPL[_b]
# miolo "desks"/"beds" (sprites vanilla): (movel principal, cadeira/criado, computador/cortina)
_V = "v:location_community_"
ISL = {"office": ("v:location_business_office_generic_01|Office|Desk", "v:furniture_seating_indoor_01|Black Office|Chair",
                  "v:appliances_com_01|Desktop|Computer"),
       "classroom": (_V + "school_01|Dark|School Bench", "v:furniture_seating_indoor_02|Blue Plastic|Chair", None),
       "beds": (_V + "medical_01|Large Medical|Bed", _V + "medical_01|Pale|Drawers", _V + "medical_01|Blue Hospital|Curtain B")}
TWO["chalkboard"] = {"S": ("location_community_school_01_19", ["location_community_school_01_20",
                                                                 "location_community_school_01_21"], 1, 0),
                     "E": ("location_community_school_01_18", ["location_community_school_01_17",
                                                                 "location_community_school_01_16"], 0, 1)}
EXTRA_FX = {"classroom": ["chalkboard"]}        # lousa na parede
# m2 por item que o modelo vanilla (per 6-7) deixava ralo demais no predio inteiro (rodada 5)
PER_OVR = {"policeoffice": 3, "policestorage": 3, "policelocker": 3, "evidenceroom": 3, "policegunstorage": 3,
           "interrogationroom": 3, "policehall": 4, "lobby": 4, "hall": 4, "storage": 3}
FURNISH["policehall"] = (["sidetable", "filing", "locker"], ["filing", "locker", "sidetable"], 4)


class DoorSet(set):
    """dsq (quadrados de porta, (x, y, z)) + vizinhancas mantidas a cada porta nova: cruz (blocked) e 3x3
    (folga das ilhas; a de 2 e o 3x3 do 3x3). Troca 5-25 consultas por quadrado por 1-9."""
    def __init__(self, it=()):
        super().__init__(); self.cr, self.n9 = set(), set()
        self |= it

    def __ior__(self, o):
        cr, n9 = self.cr, self.n9
        for p in o:
            if p in self:
                continue
            set.add(self, p)
            x, y, z = p
            cr.update(((x, y, z), (x - 1, y, z), (x + 1, y, z), (x, y - 1, z), (x, y + 1, z)))
            n9.update(((x - 1, y - 1, z), (x, y - 1, z), (x + 1, y - 1, z), (x - 1, y, z), (x, y, z), (x + 1, y, z),
                       (x - 1, y + 1, z), (x, y + 1, z), (x + 1, y + 1, z)))
        return self

    def add(self, p):
        self.__ior__((p,))


def furnish(add, rname, cells_, same, z, dsq, stz, seed, sk, grp=None):
    """Poe conteineres encostados nas paredes do comodo, sem bloquear porta, escada nem passagem."""
    # tudo em Rust (_gfpy.furnish + Cat); config por nome de comodo memoizada
    cf = _FCFG.get(rname)
    if cf is None:
        cf = _FCFG[rname] = _fcfg(rname)
    if not cf:
        return 0
    fx, rep, per, reg, tp, tpl, alt, seat, grocery, hashed = cf
    if grp is not None:     # (Groups, i, Cell): quadrados do comodo ja em Rust (unicos), moveis direto no registro
        G_, gi, cell = grp
        nC = G_.size(gi)
        C = set(G_.cells(gi)) if ISLAND.get(rname) or rname in ROWS else None    # so as ilhas usam
        cells_ = G_
    else:
        gi = cell = None
        C = set(cells_)
        nC = len(C)
    if not nC:
        return 0
    if not isinstance(dsq, DoorSet):
        dsq = DoorSet(dsq)
    hs = ((2166136261 ^ (int(seed) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    r = GF.GP.furnish(cells_, stz, dsq.cr, dsq.n9, z, sk, hs, fx, rep, hashed, max(len(fx), min(nC // per, 40)),
                      alt, ((hs ^ 813) * 16777619) & 0xFFFFFFFF, dsq if reg else None, grocery, seat, _CAT[0],
                      gi, cell)
    if r is None:
        return 0
    adds, n, ctr, uk = r
    for x, y, t_ in adds:
        add(x, y, z, t_)
    return n + _furn_tail(add, rname, C, z, dsq, stz, seed, reg, tpl, tp, ctr, uk)


def _furn_tail(add, rname, C, z, dsq, stz, seed, reg, tpl, tp, ctr, busy):
    """fim do furnish: tampos dos balcoes e ilhas/fileiras no miolo."""
    n = 0
    # em cima dos balcoes: caixa registradora e o que o vanilla poe (cafeteira, soda, chopeira...)
    tops = ([REGISTER] if reg else []) + [FURN[k] for k in (tpl["tops"] if tpl else ())
                                          if h32(seed, 812, len(k)) % 3 or rname == "kitchen"]
    for (x, y, f), t_ in zip(ctr, tops):
        if f in t_:
            add(x, y, z, t_[f]); n += 1
    mode = ISLAND.get(rname) or ("rows" if rname in ROWS else None)
    if mode:
        n += islands(add, mode, C, set(busy), z, dsq, stz, seed,
                     gond=TWO.get(tp["gond"]) if tp and tp["gond"] else None,
                     seat=(FURN.get(tp["row"]) or TWO.get(tp["row"])) if tp and tp["row"] else None,
                     rname=rname)
    return n


_SEAT = {}
_CAT = []       # [_gfpy.Cat, {tipo: id}, {tipo: (c, pool) do room_style}]
_FCFG = {}      # nome do comodo -> config do furnish (Rust), ou False sem movel


def _mkind(k, d, tv):
    """tipo de movel resolvido para o Rust (mesmas regras do laco do furnish em Python)."""
    fs = []
    for f in "NWSE":
        if f not in d:
            fs.append(None)
        elif k in TWO:
            t1, t2, dx, dy = d[f]
            fs.append((t1, t2 if isinstance(t2, list) else [t2], dx, dy, _TD.get(t1, {}).get("CustomName") == "Desk"))
        else:
            p_ = _TD.get(d[f], {})
            fs.append((d[f], tv.get(f) if tv else None,
                       k == "counter" or (p_.get("container") == "counter" and "IsTable" in p_),
                       p_.get("CustomName") in ("Desk", "School Bench")))
    return GF.GP.Kind(k in TWO, fs)


def _kid(k):
    """id do tipo no catalogo Rust: o padrao (FURN/TWO) e uma variante por item do pool do room_style
    (x as da TV no tvstand); a poltrona segue o grupo do sofa quando existe (como room_style)."""
    if not _CAT:
        room_style(0)
        sl = {k_: (c, pool) for c, k_, pool, n in _RS[0]}
        cat = GF.GP.Cat()
        _CAT.extend([cat, {}, sl])
        cp, tvp = sl.get("couch"), sl.get("tv")
        armv = []
        if cp:
            for gn, _ in cp[1]:
                v = _RS[1].get(gn)
                armv.append(_mkind("armchair", v, None) if v else None)    # sty.get(k) or FURN[k]
        cat.setup((cp[0], len(cp[1])) if cp else None, armv, (tvp[0], len(tvp[1])) if tvp else None)
    cat, ids, sl = _CAT
    i = ids.get(k)
    if i is None:
        two = k in TWO
        base = TWO[k] if two else FURN[k]
        sp = sl.get(k)
        usetv = k == "tvstand" and not two
        tvs = [TV] + [v or TV for _, v in sl["tv"][1]] if usetv and "tv" in sl else [TV if usetv else None]
        ds = [base] + [v or base for _, v in sp[1]] if sp else [base]
        kinds = [_mkind(k, d, tv) for d in ds for tv in tvs]
        i = ids[k] = cat.reg((sp[0], len(sp[1])) if sp else None, usetv and "tv" in sl,
                             k == "armchair" and not two and bool(sl.get("couch")), kinds)
    return i


def _fcfg(rname):
    """parte do furnish que so depende do nome do comodo (mesmas regras do Python)."""
    shop = any(s in rname for s in STOREISH)
    dflt = (["counter"], ["sshelf", "mshelf"], True) if shop else ([], ["mshelf", "shelf"], 8)
    tpl = TPL.get(rname)
    tp = tpl if rname not in HAND_ONLY else None
    if tp and rname not in HAND_MERGE:
        fx, rep, reg = tp["fx"], tp["rep"], tp["per"]
    else:
        fx, rep, reg = FURNISH.get(rname, dflt)
        if tp:
            fx = list(fx) + [k for k in tp["fx"] if k not in fx]
            rep = list(rep) + tp["rep"]
    per = reg if isinstance(reg, int) and not isinstance(reg, bool) else 5
    per = PER_OVR.get(rname, 4 if shop and per > 4 else per)
    reg = reg is True or bool(tp and (shop or rname in REG_ROOMS))
    if reg and tp and "counter" not in fx:
        fx = ["counter"] + list(fx)
    fx = EXTRA_FX.get(rname, []) + list(fx)
    if not fx and not rep:
        return False
    grocery = rname == "grocery"
    ks = lambda L: [(_kid(k), 1 if k == "counter" and reg else 2 if grocery and k in ("cooler", "shopfreezer") else 0)
                    for k in L]
    alt = [k for k in dict.fromkeys(list(fx) + list(rep)) if k in FURN and len(FURN[k]) >= 3]
    seat = None
    if tp and tp["seat"]:
        seat = _SEAT.get(tp["seat"])
        if seat is None:
            sd = FURN[tp["seat"]]
            seat = _SEAT[tp["seat"]] = [sd.get(d) for d in "NWSE"]
    return ks(fx), ks(rep), per, reg, tp, tpl, ks(alt), seat, grocery, bool(tp and rep)


REG_ROOMS = {"gasstore", "cafe", "bar", "bakery", "icecream", "pharmacy", "grocery", "burgerkitchen", "pizzakitchen",
             "restaurantdining", "candystore", "jewelrystore", "liquorstore"}
ROWS = {"classroom", "theatre", "church", "auditorium", "meetingroom", "lecturehall", "waitingroom"}


def islands(add, mode, C, busy, z, dsq, stz, seed, gond=None, seat=None, rname=None):
    """miolo do comodo (>= 2 tiles de qualquer parede, porta ou escada): gondolas duplas em fileiras com
    corredor de 2, e/ou mesas redondas com 2 cadeiras plasticas."""
    if not isinstance(dsq, DoorSet):
        dsq = DoorSet(dsq)
    # Enfermarias comuns sao pequenas: dois tiles de margem impediam os leitos com cortina.
    margin = 1 if mode in ("beds", "dine") else 2
    I = GF.GP.isl_mask(C, busy, stz, dsq.n9, z, margin, mode == "dine")     # miolo em Rust (_gfpy.isl_mask)
    if mode != "dine":
        I = set(I)
    if mode == "dine":   # casa: mesa de jantar com cadeiras no miolo (cozinha/sala, como no vanilla)
        I = sorted(I, key=lambda c: h32(seed, 95, c[0], c[1]))
        tb = ROUND_TABLES[h32(seed, 91) % len(ROUND_TABLES)]
        for x, y in I[:6]:
            ch = [(x + a, y + b, f) for a, b, f in ((-1, 0, "E"), (1, 0, "W"), (0, -1, "S"), (0, 1, "N"))
                  if (x + a, y + b) in C and (x + a, y + b) not in busy]
            if len(ch) >= 2:
                add(x, y, z, tb)
                for cx, cy, f in ch:
                    add(cx, cy, z, DINE_CHAIR[f])
                return 1 + len(ch)
        return 0
    if len(I) < 4:
        return 0
    xs, ys = [c[0] for c in I], [c[1] for c in I]
    x0, y0 = min(xs), min(ys)
    occ, n = set(), 0
    if mode in ("desks", "beds"):
        # desks: mesa virada p/ sul + cadeira ao sul olhando p/ norte + computador; fileiras com corredor de 1
        # beds: leito (2 quadrados N-S) + criado ao lado + cortina divisoria; 1 coluna livre entre leitos
        a_, b_, c_ = ISL["beds"] if mode == "beds" else ISL.get(rname) or ISL["office"]
        m0, m1, m2 = TWO.get(a_) or FURN.get(a_), FURN.get(b_), FURN.get(c_) if c_ else None
        if not m0 or not m1 or "S" not in m0:
            return 0
        if isinstance(m0["S"], tuple):
            t1, rest, dx, dy = m0["S"]
            rest = rest if isinstance(rest, list) else [rest]
            main = [((0, 0), t1)] + [((dx * (i + 1), dy * (i + 1)), t_) for i, t_ in enumerate(rest)]
        else:
            main = [((0, 0), m0["S"])]
        wd = max(p[0] for p, _ in main) + 1
        if mode == "desks":
            pat = main + [((wd // 2, 1), m1.get("N"))] + ([((0, 0), m2["S"])] if m2 and "S" in m2 else [])
            sx, sy = wd + (wd == 1), 3
        else:
            cur = m2.get("E") if m2 else None
            pat = main + [((wd, 0), m1.get("S"))] + ([((wd + 1, 0), cur), ((wd + 1, 1), cur)] if cur else [])
            sx, sy = wd + 3, 3
        pat = [(p, t_) for p, t_ in pat if t_]
        for (x, y) in sorted(I, key=lambda c: (c[1], c[0])):
            if (x - x0) % sx or (y - y0) % sy:
                continue
            cs = {(x + p[0], y + p[1]) for p, _ in pat}
            if not cs <= I or cs & occ:
                continue
            for (px, py), t_ in pat:
                add(x + px, y + py, z, t_)
            occ |= cs
            n += 1
        return n
    if mode == "rows":       # fileiras de cadeiras/bancos olhando para o norte (sala de aula, cinema, igreja)
        if not seat:
            return 0
        if isinstance(next(iter(seat.values())), tuple):     # banco comprido (Church Pew): N quadrados em x
            f = next((k for k in ("S", "N") if k in seat and seat[k][2] == 1), None)
            if not f:
                return 0
            t1, rest, _, _ = seat[f]
            rest = rest if isinstance(rest, list) else [rest]
            for (x, y) in sorted(I):
                ps = [(x + i, y) for i in range(len(rest) + 1)]
                if (y - y0) % 2 == 0 and (x - x0) % (len(ps) + 1) == 0 and all(q in I and q not in occ for q in ps):
                    for q, t_ in zip(ps, [t1] + rest):
                        add(q[0], q[1], z, t_)
                    occ |= set(ps); n += 1
            return n
        f = "N" if "N" in seat else next(iter(seat))
        for (x, y) in sorted(I):
            if (y - y0) % 2 == 0 and (x - x0) % 5 != 4:
                add(x, y, z, seat[f]); n += 1
        return n
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
    # gondolas ao longo do eixo mais comprido; pares costas com costas e corredor de 1
    horiz = (max(xs) - x0) >= (max(ys) - y0)
    for (x, y) in sorted(I):
        u, v = (x - x0, y - y0) if horiz else (y - y0, x - x0)
        if v % 3 not in (0, 1) or u % 10 not in (0, 2, 4):
            continue
        if horiz:
            f = "N" if v % 3 == 0 else "S"
        else:
            f = "W" if v % 3 == 0 else "E"
        t1, t2, dx, dy = (gond or GONDOLA)[f]
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



# ---- bordas do chao (autotile com mascara de vizinhos, tabela tirada do vanilla por scripts/blend_lut.py)
_LUT = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "blend_lut.json")))
BLEND_LUT = [[]] + [_LUT["blend"].get(str(m), []) for m in range(1, 16)]   # mascara N1 E2 S4 W8 -> pecas
CURB_LUT = _LUT["curb"]                       # "<R|A><E><SE><S>" -> street_curbs_01_<n> (no quadrado N/W)
NAT_G = (G_DEF, G_GRASS, G_PARK, G_WOOD)      # chao natural (G_DEF tambem e grama)
# meio-fio na diagonal (degrau de 1 quadrado com asfalto meio a meio): k do asfalto -> peca
CURB_DIAG = {1: "street_curbs_01_diag_2_41", 2: "street_curbs_01_diag_2_40",
             3: None, 4: None}            # 45 graus na vertical da tela: o tileset nao tem peca (so a meia-peca)
LINE_PC = {1: 2, 2: 0, 3: 1}                  # faixa: borda N -> 2, borda W -> 0, as duas (cruzamento) -> 1



def smooth_ground(Ga, Ba, keep):
    """Tira o dente de serra do raster: quadrado com 3+ vizinhos (N/S/E/W) de outro grupo vira esse grupo.
    Grupos: asfalto, agua, natural, piso duro. Predio e `keep` (postos) ficam como estao."""
    grp = np.zeros(256, np.uint8)
    grp[G_ASPH], grp[G_WATER] = 1, 2
    grp[list(NAT_G)] = 3
    grp[[G_SIDE, G_PAVE, G_YARD]] = 4
    for _ in range(2):
        P = np.pad(Ga, 1, mode="edge")
        nbs = [P[:-2, 1:-1], P[2:, 1:-1], P[1:-1, :-2], P[1:-1, 2:]]       # N S W E
        gn = [grp[v] for v in nbs]
        g0 = grp[Ga]
        free = (g0 > 0) & (Ba == 0) & ~keep
        out = Ga.copy()
        for g in (1, 2, 3, 4):
            cnt = sum((v == g).astype(np.uint8) for v in gn)
            m = free & (cnt >= 3) & (g0 != g)
            if not m.any():
                continue
            pick = np.where(gn[0] == g, nbs[0], np.where(gn[1] == g, nbs[1], np.where(gn[2] == g, nbs[2], nbs[3])))
            out[m] = pick[m]
        Ga = out
    return Ga


def _winpad(A, oy, ox, n, p):
    """A[oy-p:oy+n+p, ox-p:ox+n+p], repetindo a borda fora do raster."""
    H_, W_ = A.shape
    ya, yb, xa, xb = oy - p, oy + n + p, ox - p, ox + n + p
    sub = A[max(ya, 0):min(yb, H_), max(xa, 0):min(xb, W_)]
    return np.pad(sub, ((max(0, -ya), max(0, yb - H_)), (max(0, -xa), max(0, xb - W_))), mode="edge")


def ground_edges(Ga, LNa, oy, ox, n, HH, wx0, wy0, cell, Bm):
    """Pecas de borda do chao z0 de uma celula, vetorizado (mascaras em numpy, pecas no Cell.edges do Rust).
    - natural invade o vizinho (grama sobre calcada/terra, mata sobre grama, agua sobre grama): blends 1-4/8-15
    - asfalto em degrau de 1 quadrado: meia-peca de asfalto + meio-fio diagonal
    - meio-fio: no quadrado N/W da divisa asfalto x alto, peca da CURB_LUT (vanilla)
    - faixas pintadas: bordas N/W encadeadas (sem tracinho solto na diagonal)"""
    W2 = _winpad(Ga, oy, ox, n, 2)
    A = W2 == G_ASPH
    bld = W2 == 255
    wat = W2 == G_WATER
    R = ~A & ~bld & ~wat
    nat = np.isin(W2, NAT_G)
    wood = W2 == G_WOOD

    def sh(M, dy, dx, p=1):        # vizinho (dy,dx) do miolo com margem p-1
        h_, w_ = M.shape
        return M[p + dy:h_ - p + dy, p + dx:w_ - p + dx]

    # degrau diagonal (margem 1): R com exatamente 2 lados vizinhos de asfalto
    aN, aS, aW, aE = sh(A, -1, 0), sh(A, 1, 0), sh(A, 0, -1), sh(A, 0, 1)
    R1 = sh(R, 0, 0)
    K = np.zeros(R1.shape, np.uint8)
    K[R1 & aN & aW & ~aS & ~aE] = 1
    K[R1 & aS & aE & ~aN & ~aW] = 2
    K[R1 & aS & aW & ~aN & ~aE] = 3
    K[R1 & aN & aE & ~aS & ~aW] = 4
    # Rust (Cell.edges): so as mascaras aqui; o dict e o laco do write_cell la
    return _edges_rs(cell, n, K, wat, nat, wood, A, R, LNa, oy, ox, HH, wx0, wy0, Bm, sh, natc_of=None)

def _edges_rs(cell, n, K, wat, nat, wood, A, R, LNa, oy, ox, HH, wx0, wy0, Bm, sh, natc_of=None):
    """mascaras do ground_edges (mesmas contas) -> Cell.edges."""
    c = (slice(1, -1), slice(1, -1))
    Kc = K[c]
    bit = lambda M: (sh(M, -1, 0, 2).astype(np.uint8) | sh(M, 0, 1, 2) * 2 | sh(M, 1, 0, 2) * 4 | sh(M, 0, -1, 2) * 8)
    natc, woodc, Ac, Rc = sh(nat, 0, 0, 2), sh(wood, 0, 0, 2), sh(A, 0, 0, 2), sh(R, 0, 0, 2)
    mwood = bit(wood)
    ms = []
    for src, rec in ((wat, natc), (nat, (Rc | Ac) & ~natc), (wood, natc & ~woodc)):
        m = bit(src)
        m[~rec] = 0
        ms.append(np.ascontiguousarray(m, np.uint8))
    Ke, Ks, Kse = sh(K, 0, 1), sh(K, 1, 0), sh(K, 1, 1)
    hiE, hiS, hiSE = (np.where(Ac, ~sh(R, dy, dx, 2), sh(A, dy, dx, 2)) for dy, dx in ((0, 1), (1, 0), (1, 1)))
    eA = hiE | (Ke == 1) | (Ke == 3)
    sA = hiS | (Ks == 1) | (Ks == 4)
    seA = hiSE | (Kse == 1)
    code = np.where(Ac, 8, 0) + eA * 4 + seA * 2 + sA * 1
    code[~(Ac | Rc) | (Kc > 0)] = 16
    if not _EDG:
        keys = [("A" if i & 8 else "R") + f"{(i >> 2) & 1}{(i >> 1) & 1}{i & 1}" for i in range(16)]
        pcs = [[f"street_curbs_01_{p}" for p in CURB_LUT.get(k, [])] for k in keys] + [[]]
        _EDG.extend([pcs, np.array([bool(p) for p in pcs], bool), [[int(k) for k in b] for b in BLEND_LUT],
                     ["", CURB_DIAG[1], CURB_DIAG[2]],
                     [""] + [f"street_trafficlines_01_{LINE_PC[i]}" for i in (1, 2, 3)]])
    pcs, curbv, blend, cdiag, lines = _EDG
    curb = curbv[code]
    L2 = _winpad(LNa, oy, ox, n, 2)
    jj, ii = np.mgrid[0:n + 4, 0:n + 4]
    on = (L2 > 0) & ((L2 < 3) | (((np.where(L2 == 3, ii + wx0, jj + wy0) - 2) // 3) % 2 == 0)) & A
    Lx, Ly = on & ((L2 == 1) | (L2 == 3)), on & ((L2 == 2) | (L2 == 4))
    eN = sh(Lx, 0, 0) & (sh(Lx, 0, 1) | sh(Lx, 0, -1))
    eW = sh(Ly, 0, 0) & (sh(Ly, 1, 0) | sh(Ly, -1, 0))
    pc = eN[c].astype(np.uint8) | eW[c] * 2
    pc[~Ac | curb] = 0
    u8 = lambda v: np.ascontiguousarray(v, np.uint8)
    keep = [ms[0], ms[1], ms[2], u8(mwood), u8(Kc), u8(code), u8(curb), u8(pc),
            np.ascontiguousarray(HH, np.uint32), u8(Bm)]
    p_ = [a_.ctypes.data for a_ in keep]
    cell.edges(n, (p_[0], p_[1], p_[2]), p_[3], p_[4], p_[5], p_[6], p_[7], p_[8], p_[9], blend, ASPH_FAM, cdiag,
               pcs, lines)
    return None


_EDG = []   # ground_edges Rust: (pecas de meio-fio por codigo, tem peca?, BLEND_LUT, CURB_DIAG, faixas)


def h32(*a):
    """hash deterministico pequeno para variacoes."""
    x = 2166136261
    for v in a:
        x = ((x ^ (int(v) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    return x



def h32_grid(x0, y0, n, *extra, arr=False):
    """h32(x0 + x, y0 + y, *extra) para a grade n x n, como lista [y][x] (o laco por quadrado chamava h32 milhoes de vezes)."""
    M, P = np.uint64(0xFFFFFFFF), np.uint64(16777619)
    a = (np.arange(x0, x0 + n, dtype=np.int64) & 0xFFFFFFFF).astype(np.uint64)
    b = (np.arange(y0, y0 + n, dtype=np.int64) & 0xFFFFFFFF).astype(np.uint64)
    x = ((np.uint64(2166136261) ^ a) * P) & M
    x = ((x[None, :] ^ b[:, None]) * P) & M
    for e in extra:
        x = ((x ^ np.uint64(int(e) & 0xFFFFFFFF)) * P) & M
    return x.astype(np.uint32) if arr else x.tolist()


_GK = {}   # chaves (x, y, 0) da grade, por tamanho
_GT = []   # tabela de codigos do chao z0 nativo (ordem fixa, ver genfast_rs/src/lib.rs::ground_z0)


def ground_native(Bw, g, gw, tr, wx0, wy0, ntree, blds, T, sq):
    """chao z0 do write_cell em Rust: preenche sq[(x, y, 0)] (ordem de nomes = primeiro uso)."""
    if not _GT:
        assert [len(v) for v in (ASPHALT, SIDEWALK, PAVING, YARD, GRASS, GRASS2, WATER, TREES)] == [8, 8, 2, 2, 4, 4, 4, 7]
        _GT.extend(ASPHALT + SIDEWALK + PAVING + YARD + GRASS + GRASS2 + WATER + TREES + [LAMP] + FLOORS_RES + FLOORS_COM)
    fl = np.zeros(int(Bw.max()) + 1, np.int32)
    for bi in np.unique(Bw).tolist():
        if bi:
            b = blds[bi]
            fl[bi] = -1 if b["kind"] == "masp" else (40 + b["h"] % len(FLOORS_RES) if b["kind"] == "res" else
                                                     40 + len(FLOORS_RES) + b["h"] % len(FLOORS_COM))
    o1, o2 = GF.ground_z0(Bw, fl, g, gw, tr, h32_grid(wx0, wy0, g.shape[0], arr=True), wx0, wy0, ntree)
    seq = np.stack([o1.ravel(), o2.ravel()], 1).ravel()
    seq = seq[seq >= 0]
    u, first = np.unique(seq, return_index=True)
    lut = np.full(len(_GT), -1, np.int32)
    for c in u[np.argsort(first, kind="stable")].tolist():    # primeiro uso, como o add() do laco
        lut[c] = T(_GT[c])
    a_, b_ = lut[o1].ravel(), np.where(o2 >= 0, lut[np.maximum(o2, 0)], -1).ravel()     # ordem y, x
    a_, b_ = np.ascontiguousarray(a_, np.int32), np.ascontiguousarray(b_, np.int32)
    sq.ground(a_.ctypes.data, b_.ctypes.data, g.shape[0])


def sqpush(sq, ev, rank=2):
    """push no registro Rust (genfast_py.Cell: ponteiro + tamanho)."""
    ev = np.ascontiguousarray(ev, np.int64)
    sq.push(ev.ctypes.data, len(ev), rank)


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
    from ._ndi import ndimage     # scipy se houver; senao numpy (editor sem scipy)
    yy_, xx_ = np.mgrid[-3:4, -3:4]
    near = ndimage.binary_dilation(np.pad(asph, 3, mode="wrap"), structure=(xx_ * xx_ + yy_ * yy_ <= 10))[3:-3, 3:-3]
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
    gsel = list(GB.sel(*box))
    if gsel:       # area e centro de todos os aneis numa chamada nativa
        gr = [GB.rings[i][0] for i in gsel]
        goff = np.zeros(len(gr) + 1, np.int64); np.cumsum([len(r) for r in gr], out=goff[1:])
        gxy = np.concatenate(gr) - off
        gst = GF.ring_stats(gxy.astype(np.float64), goff).tolist()
        gxy = gxy.tolist(); goff = goff.tolist()
    for gk, i in enumerate(gsel):
        o = list(map(tuple, gxy[goff[gk]:goff[gk + 1]]))
        ar, cxf, cyf = gst[gk]
        if len(o) < 3 or ar < 12:
            continue
        cx_ = int(cxf); cy_ = int(cyf)
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
    items += synth_kiosks(S, rx0, ry0, W, H, OBa > 0, GSa, CNa, Ga, pub)
    del OBa, GSa
    B = Image.new("I", (W, H), 0)
    dB = ImageDraw.Draw(B)
    blds = [None]
    masp = None
    masp_rect = None
    items.sort(key=lambda z: -z[0])
    cls = [o + [o[0]] if o[0] != o[-1] else o for _, o, *_r in items]
    if items:      # snap_poly + perimetro + area + centro de todos os predios numa chamada nativa
        boff = np.zeros(len(cls) + 1, np.int64); np.cumsum([len(c) for c in cls], out=boff[1:])
        bxy = np.array([q for c in cls for q in c], np.float64).reshape(-1, 2)
        bxy2, bgeo = GF.bld_geom(bxy, boff, [len(it[1]) for it in items])
        bgeo = bgeo.tolist(); boff = boff.tolist()
    for ik, (ar, o, t, ismasp, inner, fid) in enumerate(items):
        if ismasp and masp is not None:
            continue                            # MASP: um volume so
        idx = len(blds)
        closed = cls[ik]
        rot_, per_, carea_, cxf_, cyf_ = bgeo[ik]
        o2 = list(map(tuple, bxy2[boff[ik]:boff[ik + 1]].tolist())) if rot_ else closed
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
        cxp = min(W - 1, max(0, int(cxf_)))
        cyp = min(H - 1, max(0, int(cyf_)))
        # predio muito alto so na Paulista e no centro perto do MASP; fora, 1 em 12 passa de 8 andares
        mxl, myl = rx0 + cxp, ry0 + cyp
        lv = min(lv, MAXL)
        circ = 4 * math.pi * carea_ / max(per_ * per_, 1e-6)
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
    # (as 4 voltas antigas de np.roll davam sempre a mesma mascara: o quadrado e o canto NW de um 2x2;
    #  aqui ela e calculada uma vez so, com o mesmo enrolamento nas bordas)
    a1 = np.roll(Ba, -1, 0)
    keep = (Ba > 0) & (Ba == np.roll(Ba, -1, 1)) & (Ba == a1) & (Ba == np.roll(a1, -1, 1))
    del a1
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
                d_ = (ys_ + max(0, yi - r_) - yi) ** 2 + (xs_ + max(0, xi - r_) - xi) ** 2
                j_ = int(d_.argmin()) if len(xs_) else -1
                if j_ >= 0 and d_[j_] <= r_ * r_:
                    bi = int(win[ys_[j_], xs_[j_]])
                    xi, yi = int(xs_[j_]) + max(0, xi - r_), int(ys_[j_]) + max(0, yi - r_)   # ponto no predio
                else:   # o predio perto caiu (lasca/fino/via publica): loja pequena no lugar livre mais perto
                    kq = kiosk_tardio(Ba, Ga, CNa, pub, blds, xi, yi, pt, (3, int(k)))
                    if not kq:
                        continue
                    bi, xi, yi = kq
            b_ = blds[bi]
            if b_["tags"].get("src") == "poi" and any(
                    (q[2].get("shop"), q[2].get("amenity")) != (pt.get("shop"), am_) for q in b_.get("pois") or ()):
                kq = kiosk_tardio(Ba, Ga, CNa, pub, blds, xi, yi, pt, (3, int(k)))   # loja criada e de 1 POI so
                if kq:
                    bi, xi, yi = kq
                    b_ = blds[bi]
            b_.setdefault("pois", []).append((xi, yi, pt))
            # o POI "principal" do predio: o 1o com loja/servico (nao sobrescreve um que ja nomeia o predio)
            if b_["poi"] is None or (not (b_["poi"].get("shop") or b_["poi"].get("amenity")) and
                                     (pt.get("shop") or pt.get("amenity"))):
                b_["poi"] = pt
    poi_areas(S, box, off, Ba, Ga, CNa, pub, blds)            # lote OSM de loja/servico/escola e predio de parque
    posto_predios(Ba, blds, canop, CNa)         # predio no lote do posto vira a loja de 1 andar
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
    PST = plan_postos(Ba, Ga, blds, canop, CNa, fuel_sources(S, box, off), fuel_sources(S, box, off, True))
    plan_muro_escola(Ba, Ga, PST)
    Ga = smooth_ground(Ga, Ba, PST)   # degrau de 1 quadrado some antes do autotile de bordas
    Ga[Ba > 0] = 255   # chao sob predio (o piso vem do predio)
    # arvores reais (GeoSampa) fora de predio e de asfalto
    TR = np.zeros((H, W), bool)
    TXY = S["TXY"]
    if len(TXY):
        sel = (TXY[:, 0] >= rx0) & (TXY[:, 0] < rx0 + W) & (TXY[:, 1] >= ry0) & (TXY[:, 1] < ry0 + H)
        tx = (TXY[sel, 0] - rx0).astype(np.int32); ty = (TXY[sel, 1] - ry0).astype(np.int32)
        TR[ty, tx] = True
        TR &= (Ba == 0) & (Ga != G_ASPH) & ~PST
        for qx, qy, qw, qh in G.get("pfarea", ()):
            TR[qy:qy + qh, qx:qx + qw] = False
    return Ga, LNa, Ba, Lv, blds, masp, roads, TR


POI_SNAP = 6        # tiles: POI na calcada ainda nomeia o predio da frente
FEIRA_ROOMS = ("producestorage", "hotdogstand", "producestorage")   # hortifruti, pastel, hortifruti


def _prefabs():
    """prefabs recortados do mapa vanilla (scripts/prefab.py): tiles, moveis, containers e comodos prontos."""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefabs")
    out = {}
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith(".json"):
                j = json.load(open(os.path.join(d, f)))
                j["sq"] = {tuple(map(int, k.split(","))): v for k, v in j["sq"].items()}
                out[f[:-5]] = j
    return out


PREFABS = _prefabs()


def _sem_marca(pfs):
    """posto de SP nao tem Fossoil/Gas2Go: paredes com a pintura da marca viram parede comercial clara vanilla
    (walls_commercial_01 base 48, mesmo papel W/N/canto/pilar/janela/porta) e logo/faixa/letreiro da marca sai.
    Moveis, piso e bombas ficam (interior e de outro no; bomba e so cor, sem nome)."""
    c = "walls_commercial_01_"
    fo, g2 = "location_shop_fossoil_01_", "location_shop_gas2go_01_"
    troca = {fo + "0": [c + "57", WIN_N], fo + "2": [c + "56", WIN_W], fo + "4": [c + "50"], fo + "5": [c + "49"],
             fo + "6": [c + "48"], fo + "7": [c + "51"], fo + "8": [c + "58"], fo + "9": [c + "59"],
             g2 + "0": [c + "48"], g2 + "1": [c + "49"], g2 + "2": [c + "50"], g2 + "3": [c + "51"],
             g2 + "10": [c + "58"], g2 + "11": [c + "59"]}
    tira = {fo + str(i) for i in (30, 40, 41, 42, 44, 45, 53)} | {g2 + str(i) for i in range(32, 54) if i not in (38, 39)}
    for pf in pfs.values():
        for k, ts in pf["sq"].items():
            pf["sq"][k] = [n for t in ts if t not in tira for n in troca.get(t, [t])]


_sem_marca(PREFABS)
KIOSK_SHOPS = {"newsagent", "kiosk", "lottery", "ticket", "tobacco"}
SMALL_AMEN = {"restaurant", "fast_food", "cafe", "bar", "pub", "bank", "pharmacy", "ice_cream",
              "bureau_de_change", "post_office", "dentist", "doctors", "veterinary"}


def synth_kiosks(S, rx0, ry0, W, H, ob, gs, CNa, Ga, pub):
    """loja/servico marcado no OSM sem predio a menos de POI_SNAP: cria o predio pequeno no ponto
    (banca/loterica 4x4 na calcada, loja 6x6 no lote; feira = 3 barracas 4x4 em linha), para o local existir."""
    PXY, PT = S["PXY"], S["PT"]
    if not len(PXY):
        return []
    sel = np.nonzero((PXY[:, 0] >= rx0 + 2) & (PXY[:, 0] < rx0 + W - 2) &
                     (PXY[:, 1] >= ry0 + 2) & (PXY[:, 1] < ry0 + H - 2))[0]
    if not len(sel):
        return []
    occ = ob | gs | (CNa > 0)
    hard = pub | np.isin(Ga, (G_ASPH, G_WATER))
    side = Ga == G_SIDE
    out, semlugar = [], []
    r_ = POI_SNAP
    for k in sel.tolist():
        pt = PT[k]
        sh, am = pt.get("shop"), pt.get("amenity")
        if not (sh and sh not in ("vacant", "no")) and am not in SMALL_AMEN and am != "marketplace":
            continue
        xi, yi = int(PXY[k, 0] - rx0), int(PXY[k, 1] - ry0)
        if occ[max(0, yi - r_):yi + r_ + 1, max(0, xi - r_):xi + r_ + 1].any():
            continue
        feira = am == "marketplace" and not sh
        kiosk = sh in KIOSK_SHOPS or feira
        n = 4 if kiosk else 6
        nw = 3 * 4 + 2 if feira else n          # feira: 3 barracas 4x4 lado a lado (1 de corredor)
        # feira livre fecha a rua de verdade: so agua e proibida
        bad = (Ga == G_WATER) if feira else (hard | side if not kiosk else hard)
        rr = 10 if feira else r_
        best = None
        for vert in ((False, True) if feira else (False,)):
            bw, bh = (n, nw) if vert else (nw, n)
            for dy in range(-rr, rr + 1):
                for dx in range(-rr, rr + 1):
                    x0, y0 = xi + dx - bw // 2, yi + dy - bh // 2
                    if x0 < 1 or y0 < 1 or x0 + bw >= W - 1 or y0 + bh >= H - 1:
                        continue
                    d = dx * dx + dy * dy
                    if best and d >= best[0]:
                        continue
                    # 1 quadrado de folga em volta: nao cola em predio nem fecha a via
                    if occ[y0 - 1:y0 + bh + 1, x0 - 1:x0 + bw + 1].any() or bad[y0:y0 + bh, x0:x0 + bw].any():
                        continue
                    best = (d, x0, y0, vert)
        if not best:
            semlugar.append(sh or am)
            continue
        _, x0, y0, vert = best
        bw, bh = (n, nw) if vert else (nw, n)
        occ[y0 - 1:y0 + bh + 1, x0 - 1:x0 + bw + 1] = True
        if feira:   # barracas da feira livre: comodos vanilla de banca (Distributions)
            for j, room in enumerate(FEIRA_ROOMS):
                xa, ya = (x0, y0 + j * (n + 1)) if vert else (x0 + j * (n + 1), y0)
                o = [(xa, ya), (xa + n, ya), (xa + n, ya + n), (xa, ya + n)]
                out.append((float(n * n), o, {"building": "kiosk", "building:levels": "1", "src": "poi",
                                              "amenity": "marketplace", "_room": room}, False, [], (4, k * 4 + j)))
            continue
        o = [(x0, y0), (x0 + n, y0), (x0 + n, y0 + n), (x0, y0 + n)]
        t = {"building": "kiosk" if kiosk else "retail", "building:levels": "1", "src": "poi"}
        out.append((float(n * n), o, t, False, [], (3, k)))
    if os.environ.get("ONLY"):
        print("predios criados para POI sem predio:", len(out), "de", len(sel), "POIs no bloco; sem lugar:", semlugar)
    return out


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


def fuel_sources(S, box, off, todos=False):
    """postos (areas, predios e pontos do OSM) com bandeira, em coordenada de raster: [(x, y, bandeira)].
    todos=True: tambem os sem bandeira (bandeira None)."""
    out = []
    for st in (S["OB"], S["OA"]):
        for i in st.sel(*box):
            t = st.tags[i]
            if t.get("amenity") == "fuel" and t.get("building") != "roof":
                b = fuel_brand(t)
                if b is not None or todos:
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
                if b is not None or todos:
                    out.append((float(PXY[k, 0] - off[0]), float(PXY[k, 1] - off[1]), b))
    return out


POSTO_R = 30        # quadrados: ponto de posto a menos disso de uma cobertura = mesmo posto


def synth_canopies(Ba, Ga, canop, CNa, pts):
    """posto marcado no OSM (ponto/area) sem cobertura desenhada: cria cobertura no maior retangulo livre
    (sem predio, rua, agua nem calcada) perto do ponto, para o posto existir no mapa."""
    H_, W_ = Ba.shape
    n0 = len(canop)
    for px, py, br in pts:
        x, y = int(px), int(py)
        if not (0 <= x < W_ and 0 <= y < H_):
            continue
        ya, yb, xa, xb = max(0, y - POSTO_R), min(H_, y + POSTO_R + 1), max(0, x - POSTO_R), min(W_, x + POSTO_R + 1)
        if CNa[ya:yb, xa:xb].any():
            continue
        # sem cobertura e sem predio perto: posto vanilla inteiro (loja + cobertura) no lote livre mais perto
        pf = PREFABS.get(POSTO_PF)
        if pf and not (Ba[max(0, y - 12):y + 13, max(0, x - 12):x + 13] > 0).any():
            pw, ph = pf["w"], pf["h"]
            bad = (Ba > 0) | np.isin(Ga, (G_ASPH, G_WATER)) | (CNa > 0)
            for qx, qy, qw, qh in G["pfarea"]:
                bad[qy - 1:qy + qh + 1, qx - 1:qx + qw + 1] = True
            best = None
            for dy in range(-POSTO_R, POSTO_R + 1, 2):
                for dx in range(-POSTO_R, POSTO_R + 1, 2):
                    x0, y0 = x + dx - pw // 2, y + dy - ph // 2
                    d = dx * dx + dy * dy
                    if (best and d >= best[0]) or x0 < 1 or y0 < 1 or x0 + pw >= W_ - 1 or y0 + ph >= H_ - 1:
                        continue
                    if not bad[y0:y0 + ph, x0:x0 + pw].any():
                        best = (d, x0, y0)
            if os.environ.get("ONLY") and not best:
                print("  posto sem predio e sem lote", pw, "x", ph, "em", G["rx0"] + x, G["ry0"] + y)
            if best:
                _, x0, y0 = best
                G["pfarea"].append((x0, y0, pw, ph))
                stamp_prefab(x0, y0, POSTO_PF)
                if os.environ.get("ONLY"):
                    print("  posto vanilla em", G["rx0"] + x0, G["ry0"] + y0)
                continue
        r = 14
        ya, yb, xa, xb = max(0, y - r), min(H_, y + r + 1), max(0, x - r), min(W_, x + r + 1)
        g = Ga[ya:yb, xa:xb]
        free = (Ba[ya:yb, xa:xb] == 0) & ~np.isin(g, (G_ASPH, G_WATER, G_SIDE))
        rc = max_rect(free)
        if not rc:
            continue
        y0, x0, y1, x1 = rc
        if (y1 - y0) < 5 or (x1 - x0) < 5:
            continue
        # recorta ate 14x10 no lado mais perto do ponto
        w_, h_ = min(x1 - x0, 14), min(y1 - y0, 10)
        cx, cy = x - xa, y - ya
        x0 = min(max(x0, cx - w_ // 2), x1 - w_); y0 = min(max(y0, cy - h_ // 2), y1 - h_)
        j = len(canop) + 1
        CNa[ya + y0:ya + y0 + h_, xa + x0:xa + x0 + w_] = j
        o = [(xa + x0, ya + y0), (xa + x0 + w_, ya + y0), (xa + x0 + w_, ya + y0 + h_), (xa + x0, ya + y0 + h_)]
        canop.append((o, {"amenity": "fuel", "_br": br}, w_ * h_))
    if os.environ.get("ONLY") and len(canop) > n0:
        print("postos sem cobertura no OSM, cobertura criada:", len(canop) - n0)


RES_B = ("house", "detached", "apartments", "residential", "terrace", "semidetached_house", "bungalow", "dormitory")
POSTO_LOJA_B = ("yes", "commercial", "retail", "roof", "kiosk", "service")
# muro de escola publica de SP (vanilla, fencing_01): frente para a rua = grade sobre mureta de concreto (com poste a
# cada 3), divisa com vizinho = muro de concreto. Indices conferidos montando a linha: W, N, canto NW, W/N com poste.
MURO_ESC = {"grade": ("fencing_01_50", "fencing_01_49", "fencing_01_52", "fencing_01_51", "fencing_01_48"),
            "muro": ("fencing_01_40", "fencing_01_41", "fencing_01_42", "fencing_01_40", "fencing_01_41")}


def area_crop(ring, holes, off, W_, H_):
    """poligono OSM -> (y0, x0, mascara recortada no bbox), em coordenada de raster; None fora do bloco."""
    r = ring - off
    x0, y0 = max(0, int(r[:, 0].min())), max(0, int(r[:, 1].min()))
    x1, y1 = min(W_, int(r[:, 0].max()) + 2), min(H_, int(r[:, 1].max()) + 2)
    if x1 - x0 < 2 or y1 - y0 < 2 or len(r) < 3:
        return None
    im = Image.new("L", (x1 - x0, y1 - y0), 0)
    d = ImageDraw.Draw(im)
    d.polygon([tuple(p) for p in (r - (x0, y0)).tolist()], fill=1)
    for h in holes:
        if len(h) >= 3:
            d.polygon([tuple(p) for p in (h - off - (x0, y0)).tolist()], fill=0)
    return y0, x0, np.array(im, bool)


def poi_areas(S, box, off, Ba, Ga, CNa, pub, blds):
    """lote OSM (area sem building) e predio OSM de loja/servico/escola: o predio do mapa que esta >= 50% dentro
    dele (ou cobre >= 50% dele) recebe o POI; sem nenhum, loja pequena no lugar livre mais perto.
    Predio dentro de parque/area de lazer sem tag de casa nao e casa: vira centro comunitario (ou o tipo da tag).
    Guarda os lotes de escola em G['escolas'] para o muro."""
    H_, W_ = Ba.shape
    nb = len(blds)
    tot = np.bincount(Ba.ravel(), minlength=nb)
    G["escolas"] = []
    na = npk = nk = 0
    for st, isb in ((S["OA"], False), (S["OB"], True)):
        for i in st.sel(*box):
            t = st.tags[i]
            am, sh = t.get("amenity"), t.get("shop")
            park = not isb and (t.get("leisure") == "park" or t.get("landuse") == "recreation_ground")
            poi = bool(sh and sh not in ("vacant", "no")) or am in AMEN_ROOMS or am in CIVIC_MIX or am == "marketplace"
            if not (park or poi) or (isb and t.get("building") == "roof"):
                continue
            c = area_crop(st.rings[i][0], st.rings[i][1:], off, W_, H_)
            if c is None:
                continue
            y0, x0, m = c
            if am in ("school", "kindergarten") and not isb:
                G["escolas"].append(c)
            sub = Ba[y0:y0 + m.shape[0], x0:x0 + m.shape[1]]
            ins = np.bincount(sub[m].ravel(), minlength=nb)[:nb]   # loja criada aqui mesmo (>= nb) ja tem POI
            ins[0] = 0
            hit = np.nonzero((ins * 2 > tot) | (ins * 2 > m.sum()))[0].tolist()
            if poi and not hit and ins.any() and am != "marketplace":   # lote dividido: o que mais ocupa (feira e na rua)
                hit = [int(ins.argmax())]
            for bi in hit:
                b = blds[bi]
                if b["kind"] == "masp" or (park and not poi and b["tags"].get("building") in RES_B):
                    continue
                bt = b["tags"]
                tagged = b.get("poi") or bt.get("amenity") or bt.get("shop") or bt.get("leisure")
                if poi and (t.get("name"), sh, am) not in {(q[2].get("name"), q[2].get("shop"), q[2].get("amenity"))
                                                           for q in b.get("pois") or ()}:
                    ys, xs = np.nonzero((sub == bi) & m)
                    b.setdefault("pois", []).append((int(xs.mean()) + x0, int(ys.mean()) + y0, t))
                    if not tagged:
                        b["poi"] = t
                        na += 1
                    tagged = True
                if park:
                    if not tagged:
                        b["tags"] = dict(bt, amenity="community_centre")
                        npk += 1
                    if b["rooms"] in ("res", "apt"):
                        b["kind"] = b["rooms"] = "com"
            if poi and not hit and (sh or am in SMALL_AMEN or am == "marketplace"):
                ys, xs = np.nonzero(m)
                nk += bool(kiosk_tardio(Ba, Ga, CNa, pub, blds, int(xs.mean()) + x0, int(ys.mean()) + y0, t,
                                        (4 + isb, int(i))))
    if os.environ.get("ONLY"):
        print("POI de area/predio OSM em predio:", na, "| loja criada:", nk, "| predio de parque -> centro comunitario:",
              npk, "| lotes de escola:", len(G["escolas"]))


def kiosk_tardio(Ba, Ga, CNa, pub, blds, xi, yi, pt, fid):
    """POI sem predio no mapa final (o do OSM/GeoSampa caiu como lasca, fino ou via publica): loja de 1 andar
    (banca 4x4 / loja 6x6) no lugar livre mais perto, ate POI_SNAP. -> (predio, x, y) ou None."""
    H_, W_ = Ba.shape
    sh = pt.get("shop")
    # mascaras so na janela que a busca alcanca (eram 3 isin do raster inteiro por POI)
    R_ = POI_SNAP + 12
    wy0, wx0 = max(0, yi - R_), max(0, xi - R_)
    sw = (slice(wy0, max(wy0, min(H_, yi + R_ + 1))), slice(wx0, max(wx0, min(W_, xi + R_ + 1))))
    Gw, Cw, pw = Ga[sw], CNa[sw], pub[sw]
    hard = pw | np.isin(Gw, (G_ASPH, G_WATER)) | (Cw > 0)
    rua = pt.get("amenity") == "marketplace"     # feira livre fecha a rua de verdade (como em synth_kiosks)
    for n, bad in ((4 if sh in KIOSK_SHOPS else 6, hard | (Gw == G_SIDE)), (4, hard),
                   (4, np.isin(Gw, (G_ASPH, G_WATER)) | (Cw > 0)),     # patio/estacionamento servem
                   (4, (Gw == G_WATER) if rua else np.isin(Gw, (G_ASPH, G_WATER)) | (Cw > 0))):
        best = None
        rr = POI_SNAP + 2 if bad is not hard and n == 4 else POI_SNAP   # ultima tentativa: borda ainda a <= 6
        for dy in range(-rr, rr + 1):
            for dx in range(-rr, rr + 1):
                x0, y0 = xi + dx - n // 2, yi + dy - n // 2
                if x0 < 2 or y0 < 2 or x0 + n >= W_ - 2 or y0 + n >= H_ - 2:
                    continue
                d = dx * dx + dy * dy
                if best and d >= best[0]:
                    continue
                if Ba[y0 - 1:y0 + n + 1, x0 - 1:x0 + n + 1].any() or bad[y0 - wy0:y0 - wy0 + n, x0 - wx0:x0 - wx0 + n].any():
                    continue
                best = (d, x0, y0)
        if best:
            _, x0, y0 = best
            bi = len(blds)
            Ba[y0:y0 + n, x0:x0 + n] = bi
            blds.append({"lv": 1, "kind": "com", "rooms": "com", "poi": pt, "pois": [(x0 + n // 2, y0 + n // 2, pt)],
                         "tags": {"building": "kiosk" if n == 4 else "retail", "building:levels": "1", "src": "poi"},
                         "h": h32(fid[0], fid[1] & 0x7FFFFFFF, 77), "fid": fid, "keep": False, "obel": False})
            return bi, x0 + n // 2, y0 + n // 2
    return None


def posto_predios(Ba, blds, canop, CNa):
    """predio OSM com fuel, ou sem tag, encostado (<= 3) na cobertura do posto: e a loja de conveniencia, 1 andar,
    nunca sobrado/predio residencial. O que ele cobre da cobertura volta a ser patio aberto."""
    nb = len(blds)
    tot = np.bincount(Ba.ravel(), minlength=nb)
    n = 0
    from ._ndi import ndimage     # scipy se houver; senao numpy (editor sem scipy)
    fo = ndimage.find_objects(CNa, max_label=len(canop))     # caixa de cada cobertura (era um nonzero do bloco inteiro)
    for j in range(len(canop)):
        sl = fo[j] if j < len(fo) else None
        if sl is None:
            continue
        x0, x1 = max(0, sl[1].start - 3), sl[1].stop - 1 + 4
        y0, y1 = max(0, sl[0].start - 3), sl[0].stop - 1 + 4
        sub, ms = Ba[y0:y1, x0:x1], CNa[y0:y1, x0:x1] == j + 1
        dm = ms.copy()
        for _ in range(3):
            d2 = dm.copy()
            d2[1:] |= dm[:-1]; d2[:-1] |= dm[1:]; d2[:, 1:] |= dm[:, :-1]; d2[:, :-1] |= dm[:, 1:]
            dm = d2
        for bi in np.unique(sub[dm]).tolist():
            if not bi or tot[bi] > 800:
                continue
            b = blds[bi]
            bt = b["tags"]
            fuel = bt.get("amenity") == "fuel" or (b.get("poi") or {}).get("amenity") == "fuel"
            semtag = bt.get("building", "yes") in POSTO_LOJA_B and not bt.get("name") and \
                not bt.get("amenity") and not bt.get("shop") and "leisure" not in bt
            if b["kind"] == "masp" or not (fuel or semtag):
                continue
            sub[(sub == bi) & ms] = 0
            n += b["lv"] > 1 or b["rooms"] != "com"
            b["lv"] = 1
            b["kind"] = b["rooms"] = "com"
            b["tags"] = dict(bt, amenity="fuel")
    if os.environ.get("ONLY"):
        print("predio no lote do posto -> loja de 1 andar:", n)


def plan_muro_escola(Ba, Ga, PST):
    """muro no contorno do lote amenity=school/kindergarten (G['escolas']): grade na frente, concreto na divisa, sem cruzar
    predio, rua, agua nem posto; portao de 2 quadrados a cada 24 ao longo do muro."""
    xsq = G["xsq"]
    H_, W_ = Ba.shape
    n = 0
    for y0, x0, mc in G.get("escolas", ()):
        L = np.zeros((mc.shape[0] + 2, mc.shape[1] + 2), bool)
        # lote OSM que invade rua/calcada: o muro fica na divisa com a calcada, nao some
        gc = Ga[y0:y0 + mc.shape[0], x0:x0 + mc.shape[1]]
        L[1:-1, 1:-1] = mc & ~np.isin(gc, (G_ASPH, G_WATER, G_SIDE))
        Y0, X0 = y0 - 1, x0 - 1
        walls = {}
        ys, xs = np.nonzero(L[:, 1:] != L[:, :-1])          # parede W do quadrado (x+1, y)
        for y, x in zip((ys + Y0).tolist(), (xs + X0 + 1).tolist()):
            walls[(x, y)] = walls.get((x, y), 0) | 1
        ys, xs = np.nonzero(L[1:, :] != L[:-1, :])          # parede N do quadrado (x, y+1)
        for y, x in zip((ys + Y0 + 1).tolist(), (xs + X0).tolist()):
            walls[(x, y)] = walls.get((x, y), 0) | 2
        for (x, y), f in walls.items():
            if not (1 <= x < W_ - 1 and 1 <= y < H_ - 1) or Ba[y, x] or PST[y, x]:
                continue
            ok = 0
            for bit, (qx, qy), along in ((1, (x - 1, y), y), (2, (x, y - 1), x)):
                if not f & bit or Ba[qy, qx] or PST[qy, qx] or (along // 2) % 12 == 0:
                    continue
                if {int(Ga[y, x]), int(Ga[qy, qx])} & {G_ASPH, G_WATER}:
                    continue
                ok |= bit
            if ok:
                frente = np.isin(Ga[max(0, y - 2):y + 3, max(0, x - 2):x + 3], (G_ASPH, G_SIDE)).any()
                tp = MURO_ESC["grade" if frente else "muro"]
                i = {1: 0, 2: 1, 3: 2}[ok]
                if i < 2 and (y if i == 0 else x) % 3 == 0:
                    i += 3                       # poste da grade
                xsq.setdefault((x, y, 0), []).append(tp[i])
                n += 1
    if os.environ.get("ONLY") and G.get("escolas"):
        print("muro de escola:", n, "quadrados em", len(G["escolas"]), "lotes")


def stamp_prefab(fx, fy, nm):
    """carimba um prefab vanilla em coordenada de raster: tiles em G['xsq'] (com patio proprio limpa o chao do
    gen), comodos em G['xrooms'] agrupados no predio vanilla de origem (G['xbld'])."""
    pf = PREFABS[nm]
    xsq, xclr, xrooms = G["xsq"], G["xclr"], G["xrooms"]
    H_, W_ = G["Ba"].shape if "Ba" in G and G["Ba"] is not None else (1 << 30, 1 << 30)
    for (dx, dy, dz), ts in pf["sq"].items():
        x, y = fx + dx, fy + dy
        if 0 <= x < W_ and 0 <= y < H_:
            if pf.get("floor") and dz == 0:
                xclr.add((x, y, 0))
            xsq.setdefault((x, y, dz), []).extend(ts)
    for k, (rname, rz, rects, *bid) in enumerate(pf["rooms"]):
        xrooms.append((rname, rz, {(fx + rx + i, fy + ry + j) for rx, ry, rw, rh in rects
                                   for i in range(rw) for j in range(rh)}))
        G["xbld"][len(xrooms) - 1] = ("pf", fx, fy, bid[0] if bid and bid[0] >= 0 else -1 - k)


LOJA_PF = ("loja_posto", "loja_posto_p")          # so a loja de conveniencia do posto vanilla (fossoil, gasstore, deposito, banheiros)
POSTO_PF = "posto_fossoil"      # posto vanilla completo (loja com interior + cobertura + bombas + patio)


def posto_loja(Ba, Ga, CNa, used, x0, y0, x1, y1):
    """carimba a maior loja de posto vanilla (LOJA_PF) que caiba em lote livre a ate 10 da cobertura."""
    H_, W_ = Ba.shape
    bad = (Ba > 0) | np.isin(Ga, (G_ASPH, G_WATER)) | (CNa > 0) | used
    for qx, qy, qw, qh in G["pfarea"]:
        bad[max(0, qy - 1):qy + qh + 1, max(0, qx - 1):qx + qw + 1] = True
    for nm in (n for n in LOJA_PF if n in PREFABS):
        pw, ph = PREFABS[nm]["w"], PREFABS[nm]["h"]
        best = None
        for qy in range(max(1, y0 - ph - 10), min(H_ - ph - 1, y1 + 11)):
            for qx in range(max(1, x0 - pw - 10), min(W_ - pw - 1, x1 + 11)):
                d = max(x0 - (qx + pw), qx - x1, 0) + max(y0 - (qy + ph), qy - y1, 0)
                if (best and d >= best[0]) or bad[qy:qy + ph, qx:qx + pw].any():
                    continue
                best = (d, qx, qy, nm)
        if best:
            _, qx, qy, _ = best
            G["pfarea"].append((qx, qy, pw, ph))
            used[qy:qy + ph, qx:qx + pw] = True
            stamp_prefab(qx, qy, nm)
            return best
    return None


def plan_postos(Ba, Ga, blds, canop, CNa, srcs, todos=()):
    """posto aberto sob cada cobertura do OSM: piso de pedra, bombas vanilla, pilares, cobertura z1 na cor da
    bandeira (borda) e branca (miolo), totem na calcada e letreiro na loja mais perto. Devolve mascara (sem arvore)."""
    H_, W_ = Ba.shape
    synth_canopies(Ba, Ga, canop, CNa, todos)
    xsq = G["xsq"]
    used = np.zeros((H_, W_), bool)
    nb = len(blds)
    stat = [0] * 5

    def put(x, y, z, *ts):
        if 0 <= x < W_ and 0 <= y < H_:
            xsq.setdefault((x, y, z), []).extend(ts)

    from ._ndi import ndimage     # scipy se houver; senao numpy (editor sem scipy)
    fo = ndimage.find_objects(CNa, max_label=len(canop))     # caixa de cada cobertura: nonzero so nela
    for j, (o, t, ar) in enumerate(canop):
        sl = fo[j] if j < len(fo) else None
        if sl is None:
            continue
        mw = (CNa[sl] == j + 1) & (Ba[sl] == 0)
        ys, xs = np.nonzero(mw)
        if len(xs) < 6:
            continue
        ys += sl[0].start; xs += sl[1].start
        m = np.zeros((H_, W_), bool); m[sl] = mw
        # cobertura e retangulo: o poligono OSM (girado/recortado pela loja) rasterizado sai em escada.
        # Vale o maior retangulo livre na caixa dele (sem predio, rua, calcada, agua); sobra vira patio.
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
        fr = (Ba[y0:y1 + 1, x0:x1 + 1] == 0) & ~np.isin(Ga[y0:y1 + 1, x0:x1 + 1], (G_ASPH, G_WATER, G_SIDE))
        fr &= (CNa[y0:y1 + 1, x0:x1 + 1] == 0) | (CNa[y0:y1 + 1, x0:x1 + 1] == j + 1)
        rc = max_rect(fr)
        if not rc or (rc[2] - rc[0]) * (rc[3] - rc[1]) * 2 < len(xs):
            rc = max_rect(m[y0:y1 + 1, x0:x1 + 1])
        if rc and (rc[2] - rc[0]) >= 3 and (rc[3] - rc[1]) >= 3:
            Ga[m] = G_PAVE                       # patio onde o poligono passava
            used |= m
            m = np.zeros_like(m)
            m[y0 + rc[0]:y0 + rc[2], x0 + rc[1]:x0 + rc[3]] = True
            ys, xs = np.nonzero(m)
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
        # letreiro: so na conveniencia do proprio lote (predio de posto: tag/POI fuel, ja de 1 andar por
        # posto_predios) a ate 8 quadrados; sem ela a testeira da cobertura basta (nada de galpao vizinho)
        ya, yb, xa, xb = max(0, y0 - 8), min(H_, y1 + 9), max(0, x0 - 8), min(W_, x1 + 9)
        sub = Ba[ya:yb, xa:xb]
        if sub.any():
            yy, xx = np.nonzero(sub)
            d = np.maximum(np.maximum(x0 - (xx + xa), (xx + xa) - x1), np.maximum(y0 - (yy + ya), (yy + ya) - y1))
            for q in np.argsort(d, kind="stable").tolist():
                bi = int(sub[yy[q], xx[q]])
                b_ = blds[bi] if 0 < bi < nb else None
                if b_ and b_.get("posto") is None and b_["lv"] <= 1 and (
                        b_["tags"].get("amenity") == "fuel" or (b_.get("poi") or {}).get("amenity") == "fuel"):
                    b_["posto"] = br
                    break
        else:   # posto sem predio perto: loja de conveniencia vanilla (interior completo) ao lado, a maior que couber
            best = posto_loja(Ba, Ga, CNa, used, x0, y0, x1, y1)
            G["nloja"] = G.get("nloja", 0) + bool(best)
            if os.environ.get("ONLY"):
                print("  posto sem predio em", G["rx0"] + x0, G["ry0"] + y0, "->", best[3] if best else "sem lugar")
    if os.environ.get("ONLY") and canop:
        print("postos:", len(canop), "coberturas, bandeiras BR/Shell/Ipiranga/ALE/sem:", stat)
    return used


def max_rect(m):
    """maior retangulo de True na mascara (histograma por linha) -> (y0, x0, y1, x1) ou None."""
    w = m.shape[1]
    hist = [0] * w
    best, bb = 0, None
    for y, row in enumerate(m.tolist()):
        hist = [h + 1 if v else 0 for h, v in zip(hist, row)]
        sx, sh = [], []
        x = 0
        for hh in hist + [0]:
            start = x
            while sh and sh[-1] >= hh:
                h0 = sh.pop(); s0 = sx.pop()
                if h0 * (x - s0) > best:
                    best, bb = h0 * (x - s0), (y - h0 + 1, s0, y + 1, x)
                start = s0
            sx.append(start); sh.append(hh)
            x += 1
    return bb

def rectify(Ba, blds):
    """Paredes retas: predio nao circular vira uniao de ate 4 retangulos dentro do contorno real
    (o contorno rasterizado torto/diagonal virava escadinha). Circulares e estruturas do Ibirapuera ficam."""
    from ._ndi import ndimage     # scipy se houver; senao numpy (editor sem scipy)
    fo = ndimage.find_objects(Ba)
    assert Ba.dtype == np.int32 and Ba.flags.c_contiguous      # Rust: 1 chamada por predio, no lugar
    p_, st_, ro = Ba.ctypes.data, Ba.shape[1], GF.C.rectify_one
    for i, sl in enumerate(fo, 1):
        if sl is None or i >= len(blds) or blds[i]["keep"]:
            continue
        ro(p_, st_, sl[0].start, sl[1].start, sl[0].stop - sl[0].start, sl[1].stop - sl[1].start, i)


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
    G["xbld"], G["pfarea"] = {}, []
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
    """(x0, y0, x1, y1) inclusivo por predio; ausente = (2^30, 2^30, -1, -1). find_objects: uma passada em C
    (o np.minimum/maximum.at sobre todos os quadrados de predio custava ~0,4 s por chamada)."""
    from ._ndi import ndimage     # scipy se houver; senao numpy (editor sem scipy)
    bb = np.zeros((nb, 4), np.int32)
    bb[:, 0] = bb[:, 1] = 1 << 30
    bb[:, 2] = bb[:, 3] = -1
    for i, sl in enumerate(ndimage.find_objects(Ba, max_label=nb - 1), 1):
        if sl is not None:
            bb[i] = (sl[1].start, sl[0].start, sl[1].stop - 1, sl[0].stop - 1)
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


_ST_MEMO = {}


def st_set(st):
    k = ("s",) + tuple(st)
    r = _ST_MEMO.get(k)
    if r is None:
        r = _ST_MEMO[k] = frozenset((a, b) for a, b, _ in stair_cells(st))
    return r


def st_zone(st):
    """escada + patamares (sem parede interna); memorizado (so se testa pertinencia)."""
    k = ("z",) + tuple(st)
    r = _ST_MEMO.get(k)
    if r is None:
        r = _ST_MEMO[k] = frozenset(_st_zone(st))
    return r


def _st_zone(st):
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


# plantas por tipo (rodada 3 dos interiores): no lugar da grade de 14, como nos predios vanilla.
# supermercado = salao aberto + faixa de fundo (estoque/escritorio/banheiro); restaurante = salao + cozinha
# e banheiro ao fundo; escola = salas dos dois lados de um corredor; delegacia = recepcao na frente + salas
# e celas; loja pequena = salao com estoque/banheiro no fundo. Coordenadas do raster; a frente e o lado
# com mais rua/calcada. Devolve {bi: dict(x0, y0, Z, names, doors, extra, zmax)}.
LAY_KITCHEN = {"restaurantdining": "restaurantkitchen", "cafe": "cafekitchen", "burgerkitchen": "burgerkitchen",
               "pizzakitchen": "pizzakitchen"}
_LAY_TABLE = "v:location_restaurant_pileocrepe_01|Light Wood Restaurant|Table"
_LAY_CHAIR = "v:location_restaurant_pileocrepe_01|Pile o' Crepe|Chair"
# paleta vanilla (delegacia de Muldraugh, cozinhas de restaurante)
_V_ = "v:"
LAY_KIT_WALL = [_V_ + "appliances_refrigeration_01|Industrial|Fridge", _V_ + "fixtures_counters_01|Steel|Counter",
                _V_ + "appliances_cooking_01|Industrial|Oven", _V_ + "fixtures_counters_01|Steel|Counter", "stove",
                _V_ + "fixtures_counters_01|Steel|Counter", _V_ + "fixtures_sinks_01|Large Industrial|Sink",
                _V_ + "fixtures_counters_01|Steel|Counter", _V_ + "fixtures_counters_01|Steel|Counter",
                _V_ + "trashcontainers_01|Grey Garbage|Bin"]
LAY_STOOL = _V_ + "location_restaurant_bar_01||Bar Stool"
LAY_DESK = _V_ + "fixtures_counters_01|Dark|Counter"
LAY_PC = _V_ + "appliances_com_01|Desktop|Computer"
LAY_OCHAIR = _V_ + "furniture_seating_indoor_01|Black Office|Chair"
_LAY_SIDES = {"N": ((0, -1), "S"), "S": ((0, 1), "N"), "W": ((-1, 0), "E"), "E": ((1, 0), "W")}  # frente -> fundo


def lay_kind(b, area):
    if b["kind"] == "masp" or b.get("obel") or b.get("hosp") or b.get("mil") or len(b.get("pois") or ()) >= 2:
        return None
    t = btags(b)
    a, s = t.get("amenity"), t.get("shop")
    if a == "police":
        return "police" if area >= 24 else None
    if a in ("school", "university", "college"):
        return "school" if area >= 80 else None
    if a in AMEN_ROOMS and AMEN_ROOMS[a] in LAY_KITCHEN:
        return "rest" if area >= 30 else None
    if s in SHOP_ROOMS:
        if SHOP_ROOMS[s] == "grocery" and (s in ("supermarket", "wholesale") or area >= 200):
            return "super" if area >= 60 else None
        if area <= 400:
            return "shop"
    return None


def plan_layouts(Ba, Ga, blds, bb, stairs, jails):
    GX, GY = G["rx0"] + CX0 * CS, G["ry0"] + CY0 * CS
    H_, W_ = Ba.shape
    out = {}
    for i in range(1, len(blds)):
        if bb[i, 2] < 0:
            continue
        b = blds[i]
        x0, y0, x1, y1 = (int(v) for v in bb[i])
        if x0 < 1 or y0 < 1 or x1 >= W_ - 1 or y1 >= H_ - 1:
            continue
        M = Ba[y0:y1 + 1, x0:x1 + 1] == i
        area = int(M.sum())
        kind = lay_kind(b, area)
        if not kind:
            continue
        L = _lay_one(i, b, kind, M, x0, y0, Ba, Ga, stairs.get(i), jails.get(i), GX, GY)
        if L:
            out[i] = L
    return out


def _lay_one(bi, b, kind, M, x0, y0, Ba, Ga, st, jail, GX, GY, _front=None):
    h, w = M.shape
    # frente: lado com mais rua/calcada/piso encostado
    best, front = -1, "S"
    for f, ((dx, dy), _) in (() if _front else _LAY_SIDES.items()):
        sub = Ba[y0 + dy:y0 + dy + h, x0 + dx:x0 + dx + w]
        g = Ga[y0 + dy:y0 + dy + h, x0 + dx:x0 + dx + w]
        edge = M & (sub != bi)
        sc = int(sum(int(edge[g == c].sum()) * v for c, v in OUT_SCORE.items() if v >= 2))
        if sc > best:
            best, front = sc, f
    front = _front or front
    back = _LAY_SIDES[front][1]
    yy, xx = np.mgrid[0:h, 0:w]
    if front == "N":
        d, u, D, Wd = yy, xx, h, w
    elif front == "S":
        d, u, D, Wd = h - 1 - yy, xx, h, w
    elif front == "W":
        d, u, D, Wd = xx, yy, w, h
    else:
        d, u, D, Wd = w - 1 - xx, yy, w, h
    Z = np.zeros((h, w), np.int16)
    names, pairs, extra, extra_up = {}, [], {}, {}
    Z[M] = 1
    base = room_name(b, 0, (0, 0))
    fx = FACE[front]                      # movel encostado na frente olha para dentro
    zmax = 0

    def band(z_id, m):
        Z[M & m] = z_id

    def cut_u(lo, hi, n_min, width):      # fatias de ~width ao longo de u em [lo, hi)
        n = max(1, round((hi - lo) / width))
        if (hi - lo) / n < n_min:
            n = max(1, (hi - lo) // n_min)
        e = [lo + round(k * (hi - lo) / n) for k in range(n + 1)]
        return list(zip(e[:-1], e[1:]))

    def at(dd, uu):                       # (d, u) -> raster
        if front == "N":
            return x0 + uu, y0 + dd
        if front == "S":
            return x0 + uu, y0 + h - 1 - dd
        if front == "W":
            return x0 + dd, y0 + uu
        return x0 + w - 1 - dd, y0 + uu

    def face_to(T, C):                    # direcao de C para T
        return "E" if T[0] > C[0] else "W" if T[0] < C[0] else "S" if T[1] > C[1] else "N"

    def fget(k, f_):
        F = FURN[k]
        return F.get(f_) or F.get("S") or next(iter(F.values()))

    def tables(g, dmax=None, lim=12, step=4, sides=((0, -1), (0, 1), (-1, 0), (1, 0))):
        """mesas em grade com cadeiras viradas para a mesa; passo 4 deixa 1 vao de circulacao"""
        inn = Z == g
        inn = inn & np.roll(inn, 1, 0) & np.roll(inn, -1, 0) & np.roll(inn, 1, 1) & np.roll(inn, -1, 1)
        sel = inn & (d % step == 1) & (u % step == 1)
        if dmax is not None:
            sel &= d < dmax
        ys_, xs_ = np.nonzero(sel)
        out = []
        for y_, x_ in zip(ys_[:lim], xs_[:lim]):
            dd_, uu_ = int(d[y_, x_]), int(u[y_, x_])
            T = at(dd_, uu_)
            out.append((T, FURN[_LAY_TABLE]["S"], None))
            for dd2, du in sides:
                C = at(dd_ + dd2, uu_ + du)
                out.append((C, FURN[_LAY_CHAIR][face_to(T, C)], None))
        return out

    def along_walls(g, seq, every=1, lim=40):
        """itens encostados nas paredes da zona g, seguindo a parede, virados para dentro"""
        out, i_ = [], 0
        ys_, xs_ = np.nonzero(Z == g)
        cand = []
        for y_, x_ in zip(ys_, xs_):
            for side, (dx_, dy_) in (("N", (0, -1)), ("W", (-1, 0)), ("S", (0, 1)), ("E", (1, 0))):
                yy_, xx_ = y_ + dy_, x_ + dx_
                if not (0 <= yy_ < h and 0 <= xx_ < w) or Z[yy_, xx_] != g:
                    cand.append((int(d[y_, x_]), int(u[y_, x_]), x_, y_, side)); break
        cand.sort(key=lambda e: (e[4], e[0], e[1]))
        for k_, (_, _, x_, y_, side) in enumerate(cand):
            if k_ % every or len(out) >= lim:
                continue
            out.append(((x0 + int(x_), y0 + int(y_)), fget(seq[i_ % len(seq)], FACE[side]), None)); i_ += 1
        return out

    if kind == "super":
        names[1] = "grocery"
        sd = 5 if D >= 18 else 4 if D >= 11 else 0
        if sd:
            m = d >= D - sd
            band(2, m); names[2] = "grocerystorage"; pairs.append((1, 2))
            if Wd >= 10:
                band(3, m & (u < 4)); names[3] = "bathroom"; pairs.append((1, 3))
            if Wd >= 16:
                band(4, m & (u >= 4) & (u < 9)); names[4] = "office"; pairs.append((2, 4))
        # fileira de caixas na entrada: balcao de 2 com caixa registradora, um a cada 4 tiles
        ck = []
        for uu in range(2, Wd - 3, 4):
            ck += [(2, uu, REGISTER), (2, uu + 1, None)]
        extra[1] = [(at(dd, uu), FURN["counter"][fx], r_ and r_[fx]) for dd, uu, r_ in ck[:12] if D >= 8]
    elif kind == "rest":
        names[1] = base
        kd = 5 if D >= 14 else 4 if D >= 9 else 0
        if kd:
            m = d >= D - kd
            band(2, m); names[2] = LAY_KITCHEN.get(base, "restaurantkitchen"); pairs.append((1, 2))
            if Wd >= 9:
                band(3, m & (u < 3)); names[3] = "bathroom"; pairs.append((1, 3))
            # balcao do salao encostado na parede da cozinha, deixando 3 tiles livres na ponta da porta
            dd = D - kd - 1
            u0 = 3 if Wd >= 9 else 0
            row = [uu for uu in range(u0 + 1, Wd - 1) if uu < u0 + 1 + max(3, (Wd - u0) // 2)]
            extra[1] = [(at(dd, uu), FURN["counter"][FACE[back]], REGISTER[FACE[back]] if k_ == 1 else None)
                        for k_, uu in enumerate(row)]
            extra[1] += [(at(dd - 1, uu), FURN[LAY_STOOL]["S"], None) for k_, uu in enumerate(row) if k_ != 1]
            extra[2] = along_walls(2, LAY_KIT_WALL)              # cozinha: bancadas continuas + fogao/forno/pia
        extra.setdefault(1, []).extend(tables(1, D - kd - 3 if kd else None))   # salao: mesa + 4 cadeiras
    elif kind == "school":
        zmax = 9
        nid = [1]

        def new(n0, nup):
            nid[0] += 1; names[nid[0]] = (n0, nup); return nid[0]
        names[1] = ("hall", "hall")
        if D >= 13:
            a_ = (D - 3) // 2
            bands = [(0, a_), (a_ + 3, D)]
            band(1, (d >= a_) & (d < a_ + 3))
        elif D >= 8:
            bands = [(2, D)]
            band(1, d < 2)
        else:
            bands = [(0, D)]
        first = True
        for (lo, hi) in bands:
            segs = cut_u(0, Wd, 5, 8)
            ncaf = 0                                     # refeitorio no fundo: 2 fatias se couber, 1 em predio menor
            if lo == bands[-1][0] and hi - lo >= 4:
                ncaf = 2 if len(segs) >= 4 else 1 if (len(segs) >= 2 and len(bands) > 1) or len(segs) >= 4 else 0
            for si, (ua, ub) in enumerate(segs):
                m = (d >= lo) & (d < hi) & (u >= ua) & (u < ub)
                if lo == 0 and first and si == len(segs) // 2 and len(segs) >= 3:
                    g = new("office", "office")          # secretaria, na frente do meio
                elif si == 0 and lo == bands[0][0]:
                    g = new("bathroom", "bathroom")
                elif ncaf and si >= len(segs) - ncaf:
                    g = new("cafeteria", "classroom")    # refeitorio (2 fatias do fundo, junta abaixo)
                else:
                    g = new("classroom", "classroom")
                band(g, m)
                pairs.append((1, g) if len(bands) > 1 or D >= 8 else (g, g))
            first = False
        caf = [g for g, n in names.items() if n[0] == "cafeteria"]
        for g in caf[1:]:                                # refeitorio: uma sala so
            Z[Z == g] = caf[0]; del names[g]
        for g, n in names.items():                       # carteiras em grade (2 do contorno, 1 de corredor)
            if "classroom" not in n:
                continue
            inn = Z == g
            for _ in range(2):
                inn = inn & np.roll(inn, 1, 0) & np.roll(inn, -1, 0) & np.roll(inn, 1, 1) & np.roll(inn, -1, 1)
            ys_, xs_ = np.nonzero(inn & (d % 2 == 1) & (u % 2 == 0))
            grid = [(at(int(d[y_, x_]), int(u[y_, x_])), FURN["bench"][fx], None) for y_, x_ in zip(ys_[:16], xs_[:16])]
            if n[0] == "classroom":
                extra[g] = grid
            elif n[0] == "cafeteria":
                extra[g] = tables(g, lim=10)
            if n[1] == "classroom":
                extra_up[g] = grid
    elif kind == "police":
        names[1] = "lobby"
        if D >= 10:
            band(1, d < 5)
            lo = 5
            if D >= 16:
                band(2, (d >= 5) & (d < 7)); names[2] = "hall"; lo = 7; pairs.append((1, 2))
            seq = ["policeoffice", "policelocker", "interrogationroom", "policegunstorage", "policeoffice",
                   "evidenceroom", "policestorage"]
            segs = cut_u(0, Wd, 4, 6)
            for si, (ua, ub) in enumerate(segs):
                g = 10 + si
                band(g, (d >= lo) & (u >= ua) & (u < ub))
                names[g] = "bathroom" if si == len(segs) - 1 and len(segs) >= 3 else seq[si % len(seq)]
                pairs.append((2 if lo == 7 else 1, g))
            # balcao da recepcao: fileira no meio da recepcao, aberta nas pontas
            row = [uu for uu in range(2, Wd - 2) if abs(uu - Wd // 2) > 1]
            extra[1] = [(at(2, uu), FURN[LAY_DESK][fx], REGISTER[fx] if k_ == 0 else LAY_PC and
                         FURN[LAY_PC][fx] if k_ % 3 == 1 else None) for k_, uu in enumerate(row[:8])]
            extra[1] += [(at(3, uu), FURN[LAY_OCHAIR][face_to(at(2, uu), at(3, uu))], None)
                         for k_, uu in enumerate(row[:8]) if k_ % 3 == 1]
            for g in [g for g in names if g >= 10]:
                n_ = names[g]
                if n_ == "policeoffice":                 # mesas com computador + cadeira, arquivos na parede
                    inn = Z == g
                    inn = inn & np.roll(inn, 1, 0) & np.roll(inn, -1, 0) & np.roll(inn, 1, 1) & np.roll(inn, -1, 1)
                    ys_, xs_ = np.nonzero(inn & (d % 3 == 0) & (u % 3 == 1))
                    lst = []
                    for y_, x_ in zip(ys_[:6], xs_[:6]):
                        dd_, uu_ = int(d[y_, x_]), int(u[y_, x_])
                        T, C = at(dd_, uu_), at(dd_ + 1, uu_)
                        lst += [(T, FURN[LAY_DESK][fx], FURN[LAY_PC][fx]),
                                (C, FURN[LAY_OCHAIR][face_to(T, C)], None)]
                    extra[g] = lst + along_walls(g, ["filing"], every=2, lim=6)
                elif n_ in ("policelocker", "policegunstorage", "evidenceroom"):   # fileiras de armarios
                    extra[g] = along_walls(g, ["locker"] if n_ == "policelocker" else ["mlocker", "locker", "filing"])
                elif n_ == "interrogationroom":          # mesa + 2 cadeiras no meio
                    extra[g] = tables(g, lim=1, step=3, sides=((0, -1), (0, 1)))
        elif D >= 5 and Wd >= 4:                         # posto pequeno: recepcao com balcao + sala do fundo
            k0 = 3 if D >= 7 else 2
            band(10, d >= k0); names[10] = "policestorage" if D * Wd < 60 else "policelocker"; pairs.append((1, 10))
            extra[1] = [(at(k0 - 1, uu), FURN["counter"][FACE[back]], REGISTER[FACE[back]] if uu == 1 else None)
                        for uu in range(1, Wd - 1) if uu != Wd // 2][:6]
        if jail:                                         # celas da plan_jails: fora dos comodos e das paredes
            S = grid_of(b)
            jx, jy = jail[0] * S - GX + jail[3] - x0, jail[1] * S - GY + jail[4] - y0
            jw = jail_layout(S, jail[2])[-1][1]
            ys_, xs_ = np.nonzero(M)
            inj = (xs_ - jx >= 0) & (xs_ - jx <= jw) & (ys_ - jy >= 0) & (ys_ - jy < 5)
            Z[ys_[inj], xs_[inj]] = -1
            cor = (xs_ - jx >= 0) & (xs_ - jx <= jw) & (ys_ - jy >= 5) & (ys_ - jy < 7)
            Z[ys_[cor], xs_[cor]] = 30; names[30] = "hall"
    elif kind == "shop":
        names[1] = base
        if D >= 9 and Wd >= 4:
            m = d >= D - 3
            stn = base + "storage" if base + "storage" in TPL else base.replace("store", "storestorage") \
                if base.replace("store", "storestorage") in TPL else "storage"
            band(2, m); names[2] = stn; pairs.append((1, 2))
            if Wd >= 8:
                band(3, m & (u < 3)); names[3] = "bathroom"; pairs.append((2, 3))
        # vitrine: expositores encostados na fachada, longe da porta (a porta e decidida na celula)
        extra[1] = [(at(0, uu), FURN["display"][fx], None) for uu in range(1, Wd - 1, 3) if Wd >= 5][:4]
    # zonas minusculas (forma irregular) voltam para o salao
    for g in [g for g in np.unique(Z) if g > 1]:
        if int((Z == g).sum()) < 6:
            Z[Z == g] = 1
    if kind != "school":
        names = {g: (n, n) for g, n in names.items()}
    zs = [int(g) for g in np.unique(Z) if g > 0]
    if len(zs) < 2 and kind not in ("super", "shop", "rest"):
        return None
    for g in zs:
        names.setdefault(g, names.get(1, (base, base)))
    # POI: o comodo principal (o que a auditoria espera) fica no ponto; senao vira a planta (frente <-> fundo)
    pp = (b.get("pois") or [None])[0]
    if pp and kind in ("super", "rest", "shop") and not _front:
        ys_, xs_ = np.nonzero(Z > 0)
        k_ = int(np.argmin((xs_ + x0 - pp[0]) ** 2 + (ys_ + y0 - pp[1]) ** 2))
        if names[int(Z[ys_[k_], xs_[k_]])][0] != names[1][0]:
            return _lay_one(bi, b, kind, M, x0, y0, Ba, Ga, st, jail, GX, GY, _front=back)
    doors = _lay_doors(Z, x0, y0, pairs, st)
    def clip(E):
        return {g: [(X, Y, s1, s2) for (X, Y), s1, s2 in lst
                    if 0 <= Y - y0 < h and 0 <= X - x0 < w and Z[Y - y0, X - x0] == g] for g, lst in E.items()}
    return {"x0": x0, "y0": y0, "Z": Z, "names": names, "doors": doors, "extra": clip(extra),
            "extra_up": clip(extra_up), "zmax": zmax}


def _lay_doors(Z, x0, y0, pairs, st):
    """uma porta por par pedido (no meio da parede comum, longe das quinas) e, depois, uma para cada zona
    que ficou sem caminho ate o salao (arvore a partir da zona 1)."""
    zone = st_zone(st) if st else frozenset()
    edges = collections.defaultdict(list)       # (a, b) -> [(X, Y, lado)]
    a_, b_ = Z[:, :-1], Z[:, 1:]                 # lado W do tile da direita
    for y, x in zip(*np.nonzero((a_ != b_) & (a_ > 0) & (b_ > 0))):
        p = tuple(sorted((int(a_[y, x]), int(b_[y, x]))))
        edges[p].append((x0 + int(x) + 1, y0 + int(y), "W"))
    a_, b_ = Z[:-1, :], Z[1:, :]
    for y, x in zip(*np.nonzero((a_ != b_) & (a_ > 0) & (b_ > 0))):
        p = tuple(sorted((int(a_[y, x]), int(b_[y, x]))))
        edges[p].append((x0 + int(x), y0 + int(y) + 1, "N"))
    doors = set()
    linked = collections.defaultdict(set)

    def put(p):
        es = edges.get(p)
        if not es:
            return False
        es_set = set(es)
        ok = [e for e in es if (e[0], e[1]) not in zone and
              all(q in es_set for q in (((e[0], e[1] - 1, "W"), (e[0], e[1] + 1, "W")) if e[2] == "W"
                                         else ((e[0] - 1, e[1], "N"), (e[0] + 1, e[1], "N"))))]
        ok = ok or [e for e in es if (e[0], e[1]) not in zone]
        if not ok:
            return False
        ok.sort()
        doors.add(ok[len(ok) // 2])
        linked[p[0]].add(p[1]); linked[p[1]].add(p[0])
        return True
    for p in pairs:
        p = tuple(sorted(p))
        if p[0] != p[1]:
            put(p)
    zs = sorted(int(g) for g in np.unique(Z) if g > 0)
    root = 1 if 1 in zs else zs[0]
    for _ in range(len(zs)):
        seen, stack = {root}, [root]
        while stack:
            g = stack.pop()
            for h_ in linked[g]:
                if h_ not in seen:
                    seen.add(h_); stack.append(h_)
        miss = [g for g in zs if g not in seen]
        if not miss:
            break
        prog = False
        for g in miss:
            for p in sorted((p for p in edges if g in p and (p[0] in seen or p[1] in seen)),
                            key=lambda p: -len(edges[p])):
                if put(p):
                    prog = True
                    break
            if prog:
                break
        if not prog:
            break
    return doors


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


def bi_cells(Idc):
    """(bi, ys, xs) por predio, na ordem de np.unique e de np.nonzero(Idc == bi), num argsort so (era um nonzero por predio)."""
    Ic = np.ascontiguousarray(Idc, np.int32)      # Rust: agrupamento sem o argsort
    u, st, ys, xs = (np.frombuffer(b_, t_) for b_, t_ in
                     zip(GF.GP.bi_groups(Ic.ctypes.data, *Ic.shape),
                         (np.int32, np.int64, np.int64, np.int64)))
    for i, bi in enumerate(u):
        yield bi, ys[st[i]:st[i + 1]], xs[st[i]:st[i + 1]]


def st_cell(ox, oy):
    """escadas com tile na celula (ox, oy): [(bi, [(x, y, sprite)])] na ordem de stairs e de stair_cells;
    indice feito 1 vez por bloco (antes cada celula percorria todas as escadas do bloco 3 vezes)."""
    st_ = G["stairs"]
    memo = G.get("_st_idx")
    if memo is None or memo[0] is not st_:
        idx, rx, ry = {}, G["rx0"], G["ry0"]
        for bi, st in st_.items():
            for c in stair_cells(st):
                d = idx.setdefault(((c[0] + rx) // CS, (c[1] + ry) // CS), {})
                d.setdefault(bi, []).append(c)
        memo = G["_st_idx"] = (st_, idx)
    return memo[1].get(((ox + G["rx0"]) // CS, (oy + G["ry0"]) // CS), {})


def xsq_cell(ox, oy):
    """itens de G["xsq"] que caem na celula (ox, oy), na ordem do dict; o indice por celula e feito 1 vez por bloco
    (antes cada celula percorria o xsq do bloco inteiro)."""
    xs_ = G["xsq"]
    memo = G.get("_xsq_idx")
    if memo is None or memo[0] is not xs_:
        idx = {}
        for k, ts in xs_.items():
            idx.setdefault((k[0] // CS, k[1] // CS), []).append((k, ts))
        memo = G["_xsq_idx"] = (xs_, idx)
    return memo[1].get((ox // CS, oy // CS), ()) if ox % CS == 0 and oy % CS == 0 else list(xs_.items())


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
    SGN = G.get("signs", {})
    lads = {(lx - ox, ly - oy): v for (lx, ly), v in G["ladders"].items()
            if 0 <= lx - ox < CS and 0 <= ly - oy < CS}
    maxz = int(Lw[1:-1, 1:-1].max()) if Lw.size else 0
    maxz = max(maxz, int(BALw.max()), max((v[1] for v in lads.values()), default=0))
    sq = GF.GP.Cell(DROP)      # registro de tiles + tabela de nomes em Rust (genfast_py: Cell)
    T, add, nget = sq.t, sq.add, sq.get

    heli_ = G["heli"]
    jails = G.get("jails", {})
    mst = stairs.get(masp) if masp is not None else None
    mzone = st_zone(mst) if mst else set()

    def nofl(bi_, z, wx, wy):   # MASP: vao livre de pe-direito duplo (so o patamar da escada tem piso)
        return bi_ == masp and 0 < z < MASP_Z0 and (wx, wy) not in mzone

    # ---- chao z0 (listas python: indexar numpy escalar por quadrado era o gargalo)
    Bl = Bw.tolist()
    ground_native(Bw, g, gw, TRw[oy:oy + CS, ox:ox + CS], ox + GX, oy + GY, ntree, blds, T, sq)

    # ---- bordas: blends, meio-fio (reto/canto/diagonal) e faixas, autotile vetorizado (ground_edges)
    ground_edges(Ga, LNa, oy, ox, CS, h32_grid(ox + GX, oy + GY, CS, 3, arr=True), ox + GX, oy + GY,
                 cell=sq, Bm=Bw[1:-1, 1:-1] != 0)     # Rust: pecas e laco dentro do Cell.edges

    # escadas que caem nesta celula: (z limite, [(x, y, sprite)]), na ordem de stairs e de stair_cells
    st_here = []
    stc_ = st_cell(ox, oy)
    for bi, cl_ in stc_.items():
        cs_ = []
        for sx, sy, spr in cl_:
            lx, ly = sx - ox, sy - oy
            if Bw[ly + 1, lx + 1] == bi:
                cs_.append((lx, ly, spr))
        if cs_:
            b = blds[bi]
            st_here.append((min(b["lv"], FULL) - (1 if "heli" in b else 2), cs_))

    # piso dos andares de cima em numpy (quadrado interno sem parede): por predio, indice do nome do piso
    # (ja registrado pelo chao z0, entao a ordem dos nomes nao muda), andar maximo e vao de escada
    ub_ = np.unique(Bw).tolist()
    nb_ = (ub_[-1] if ub_ else 0) + 1
    flix, accz, vok = np.zeros(nb_, np.int64), np.zeros(nb_, np.int64), np.zeros(nb_, bool)
    for bi in ub_:
        if bi:
            b = blds[bi]
            fl = FLOORS_RES if b["kind"] == "res" else FLOORS_COM
            i_ = nget(fl[b["h"] % len(fl)])
            if b["kind"] != "masp" and i_ is not None:
                vok[bi], flix[bi], accz[bi] = True, i_, min(FULL, b.get("acc", FULL))
    SVz = np.full((CS, CS), -1, np.int64)        # vao da escada: sem piso ate z <= SVz
    for bi, cl_ in stc_.items():
        if bi < nb_ and vok[bi]:
            zl_ = min(blds[bi]["lv"], FULL) - 1
            for sx, sy, _ in cl_:
                lx, ly = sx - ox, sy - oy
                if Bw[ly + 1, lx + 1] == bi:
                    SVz[ly, lx] = zl_
    kyx_ = (np.arange(CS, dtype=np.int64)[:, None] << 8) | np.arange(CS, dtype=np.int64)[None, :]
    # muros em numpy: nomes numa tabela local (LN), registrados no fim de cada andar na ordem da 1a aparicao
    LN, LI = [], {}

    def L(n):
        i = LI.get(n)
        if i is None:
            i = LI[n] = len(LN); LN.append(n)
        return i
    for n_ in (AC_WALL["W"], AC_WALL["N"], DOOR_EXT[0], DOOR_EXT[1], WIN_W, WIN_N):
        L(n_)
    wfl, wacc = np.full(nb_, -1, np.int64), np.zeros(nb_, np.int64)
    wsty = np.zeros((nb_, 12), np.int64)
    wmasp, wobel, wind = np.zeros(nb_, bool), np.zeros(nb_, bool), np.zeros(nb_, bool)
    for bi in ub_:
        if bi:
            b = blds[bi]
            fl = FLOORS_RES if b["kind"] == "res" else FLOORS_COM
            wfl[bi], wacc[bi] = L(fl[b["h"] % len(fl)]), min(FULL, b.get("acc", FULL))
            sh, bs = wall_style(b)
            for k_ in (0, 1, 2, 3, 8, 9, 10, 11):
                wsty[bi, k_] = L(f"{sh}_{bs + k_}")
            wmasp[bi], wobel[bi], wind[bi] = b["kind"] == "masp", bool(b.get("obel")), b["rooms"] == "ind"
    SV2 = np.full((CS, CS), -1, np.int64)        # vao da escada (todo predio): sem piso ate z <= SV2
    for bi, cl_ in stc_.items():
        if 0 < bi < nb_:
            zl_ = min(blds[bi]["lv"], FULL) - 1
            for sx, sy, _ in cl_:
                lx, ly = sx - ox, sy - oy
                if Bw[ly + 1, lx + 1] == bi:
                    SV2[ly, lx] = zl_
    SGl, LDl = np.zeros((CS, CS), bool), np.zeros((CS, CS), bool)
    for px, py in SGN:
        if 0 <= px - ox < CS and 0 <= py - oy < CS:
            SGl[py - oy, px - ox] = True
    for lx, ly in lads:
        LDl[ly, lx] = True
    ORw, ORn = np.zeros((CS, CS), bool), np.zeros((CS, CS), bool)

    # ---- predios, andar a andar
    rf_ = None        # telhado Rust: (Bw int32, casa por predio, h32_grid 5, mascara do heliponto), 1 vez por celula
    rooms = []                       # (name, z, rects)
    bld_rooms = {}                   # bi -> [room idx]
    doors_done = set()
    dsq = DoorSet()                  # quadrados de porta (dos dois lados), por z: mobilia nao encosta
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
            # loja de rua: vitrine (vidro do chao ao teto, vanilla) dos dois lados de cada porta externa do terreo
            vit = set()
            for (vx, vy, vs), op_ in opening.items():
                if op_ != "door":
                    continue
                vb = blds[int(Id[vy + 1, vx + 1] or (Id[vy + 1, vx] if vs == "W" else Id[vy, vx + 1]))]
                if vb["kind"] == "masp" or vb.get("obel") or not (
                        vb.get("pois") or vb["tags"].get("shop") or vb["tags"].get("amenity") in SMALL_AMEN):
                    continue
                for d_ in (-1, 1):
                    q_ = (vx, vy + d_, "W") if vs == "W" else (vx + d_, vy, "N")
                    if q_ not in opening:
                        vit.add(q_)
        if z == 0:
            for (vx, vy, vs) in list(opening) + list(vit):
                if 0 <= vx < CS and 0 <= vy < CS:
                    (ORw if vs == "W" else ORn)[vy, vx] = True
        # bordas: wallW[y,x] entre (x-1,y) e (x,y); wallN entre (x,y-1) e (x,y)  (coords com borda)
        eW = Id[:, 1:] != Id[:, :-1]           # shape (CS+2, CS+1): coluna j = borda entre j e j+1
        eN = Id[1:, :] != Id[:-1, :]
        cand = Id[1:-1, 1:-1] > 0
        cand = cand | eW[1:-1, 0:CS] | eN[0:CS, 1:-1] | eW[0:CS, 0:CS] | eN[0:CS, 0:CS]
        Idl = Id.tolist()
        Id32 = np.ascontiguousarray(Id, np.int32); Id32p = Id32.ctypes.data
        Id32 = np.ascontiguousarray(Id, np.int32); Idp = Id32.ctypes.data   # raster do same() p/ o _gfpy
        Idc = Id[1:-1, 1:-1]
        simple = vok[Idc] & ~eW[1:-1, 0:CS] & ~eN[0:CS, 1:-1]     # so o piso (o laco faria o mesmo, 1 tile)
        if z > 0:
            fm = simple & (z <= accz[Idc]) & (z > SVz)
            sqpush(sq, (((z + 64) << 16 | kyx_[fm]) << 24) | flix[Idc[fm]])
        cand &= ~simple
        cy_, cx_ = np.nonzero(cand)
        Ya, Xa = cy_ + 1, cx_ + 1
        hW, hN, ins = eW[Ya, Xa - 1], eN[Ya - 1, Xa], Id[Ya, Xa]
        aW, aN = np.where(hW, Id[Ya, Xa - 1], 0), np.where(hN, Id[Ya - 1, Xa], 0)
        e0 = ~(hW | hN)
        o1, o2, o3 = Id[Ya - 1, Xa - 1], Id[Ya, Xa - 1], Id[Ya - 1, Xa]
        pil = e0 & (eN[Ya - 1, Xa - 1] | eW[Ya - 1, Xa - 1]) & (ins == 0)
        own = np.where(e0, np.where(pil, np.where(o1 > 0, o1, np.where(o2 > 0, o2, o3)), 0),
                       np.where(ins > 0, ins, np.where(aW > 0, aW, aN)))
        rare = wmasp[own] | wmasp[ins]                 # MASP: laco Python
        exW, exN = hW & ((aW == 0) | (ins == 0)), hN & ((aN == 0) | (ins == 0))
        Wo, No = hW & ~hN, hN & ~hW
        if z == 0:                                     # portas/portoes do plano e vitrines: laco Python
            rare |= (Wo & exW & ORw[cy_, cx_]) | (No & exN & ORn[cy_, cx_])
        flo = (ins > 0) & (z > 0) & (z <= wacc[ins]) & (~e0 | (z > SV2[cy_, cx_]))
        zacc = (z > 0) & (z < wacc[own])
        oxW = np.where(ins == 0, Xa, Xa - 1)
        dW = Wo & exW & zacc & BCw[Ya, oxW] & (BALw[Ya, oxW] > z)      # porta da varanda
        oyN = np.where(ins == 0, Ya, Ya - 1)
        dN = No & exN & zacc & BCw[oyN, Xa] & (BALw[oyN, Xa] > z)
        sg1 = SGl[cy_, cx_] if z == 1 else np.zeros(len(cy_), bool)
        wx_, wy_ = cx_ + ox, cy_ + oy
        wiW = Wo & exW & ~dW & ~wobel[own] & ((wy_ + GY) % 3 == 1) & ~sg1
        wiN = No & exN & ~dN & ~wobel[own] & ((wx_ + GX) % 3 == 1) & ~sg1
        acb = (ins == 0) & (z > 0) & (BALw[Ya, Xa] == 0) & ~wind[own] & ~wobel[own] & ~LDl[cy_, cx_] & ~sg1
        acW, acN = Wo & exW & ~dW & ~wiW & acb, No & exN & ~dN & ~wiN & acb
        acm = acW | acN
        if acm.any():
            hm = h32v(wx_[acm] + GX, wy_[acm] + GY, z, 11) % 9 == 0
            acW[acm] &= hm; acN[acm] &= hm
        M4 = np.full((len(cy_), 4), -1, np.int64)      # piso, parede, ar-condicionado, porta/janela
        M4[:, 0] = np.where(flo, wfl[ins], -1)
        kk = np.where(e0, 3, np.where(hW & hN, 2, np.where(Wo, 0, 1) + np.where(dW | dN, 10, np.where(wiW | wiN, 8, 0))))
        M4[:, 1] = np.where((~e0 | pil) & (own > 0), wsty[own, kk], -1)
        M4[:, 2] = np.where(acW, 0, np.where(acN, 1, -1))
        M4[:, 3] = np.where(dW, 2, np.where(dN, 3, np.where(wiW, 4, np.where(wiN, 5, -1))))
        for x, y in zip(cx_[dW].tolist(), cy_[dW].tolist()):
            dsq |= {(x, y, z), (x - 1, y, z)}
        for x, y in zip(cx_[dN].tolist(), cy_[dN].tolist()):
            dsq |= {(x, y, z), (x, y - 1, z)}
        ri = np.nonzero(rare)[0]
        rl = []
        if len(ri):
            M4[ri] = -1

            def ar(x_, y_, z_, n):
                ev_.append(L(n))
            eWl, eNl = eW.tolist(), eN.tolist()
            for i_, y, x in zip(ri.tolist(), cy_[ri].tolist(), cx_[ri].tolist()):
                ev_ = []; rl.append((i_, ev_))
                if True:
                    X, Y = x + 1, y + 1
                    hasW = eWl[Y][X - 1]
                    hasN = eNl[Y - 1][X]
                    inside = Idl[Y][X]
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
                                ar(x, y, z, fl[b["h"] % len(fl)])
                        if (eNl[Y - 1][X - 1] or eWl[Y - 1][X - 1]) and not inside:
                            owner = Idl[Y - 1][X - 1] or Idl[Y][X - 1] or Idl[Y - 1][X]
                            if owner and blds[owner]["kind"] == "masp":
                                if z >= MASP_Z0:
                                    ar(x, y, z, M1 + "11")       # quina da caixa
                            elif owner:
                                sh, bs = wall_style(blds[owner])
                                ar(x, y, z, f"{sh}_{bs + 3}")
                        continue
                    a = Idl[Y][X - 1] if hasW else 0
                    n_ = Idl[Y - 1][X] if hasN else 0
                    owner = inside or a or n_
                    b = blds[owner]
                    if inside and 0 < z <= min(FULL, blds[inside].get("acc", FULL)) and \
                            not nofl(inside, z, ox + x, oy + y):  # <= : forro no 1o nivel sem acesso
                        fl = FLOORS_RES if b["kind"] == "res" else FLOORS_COM
                        ar(x, y, z, fl[b["h"] % len(fl)])
                    if b["kind"] == "masp":   # vao livre embaixo, caixa toda de vidro em cima
                        if z >= MASP_Z0:
                            ar(x, y, z, MASP_GLASS[2] if hasW and hasN else MASP_GLASS[0] if hasW else MASP_GLASS[1])
                            if z in (MASP_Z0, MASP_LV - 1):          # vigas laterais na base e no topo da caixa
                                o_ = 0 if z == MASP_Z0 else 2
                                if hasW:
                                    ar(x, y, z, M2 + str(o_))
                                if hasN:
                                    ar(x, y, z, M2 + str(o_ + 1))
                        continue
                    sh, bs = wall_style(b)
                    wx, wy = ox + x, oy + y
                    exterior_w = hasW and (a == 0 or inside == 0)
                    exterior_n = hasN and (n_ == 0 or inside == 0)
                    if hasW and hasN:
                        ar(x, y, z, f"{sh}_{bs + 2}")
                        continue
                    if hasW:
                        op = opening.get((x, y, "W")) if z == 0 and exterior_w else None
                        if op and op != "door":   # portao de garagem (o sprite ja e a parede)
                            ar(x, y, z, op); dsq |= {(x, y, z), (x - 1, y, z)}
                            continue
                        door = op == "door"
                        out_ = (Y, X) if inside == 0 else (Y, X - 1)
                        if exterior_w and 0 < z < min(FULL, b.get("acc", FULL)) and BCw[out_] and BALw[out_] > z:
                            door = True                        # porta da varanda
                        if z == 0 and exterior_w and not door and (x, y, "W") in vit:
                            ar(x, y, z, VITRINE[0]); continue
                        win = exterior_w and not door and not b.get("obel") and ((wy + GY) % 3 == 1 or b["kind"] == "masp") \
                            and not (z == 1 and (wx, wy) in SGN)
                        ar(x, y, z, f"{sh}_{bs + (10 if door else 8 if win else 0)}")
                        if exterior_w and inside == 0 and z > 0 and not door and not win and not BALw[Y, X] and \
                                b["rooms"] != "ind" and not b.get("obel") and (x, y) not in lads and not (z == 1 and (wx, wy) in SGN) and h32(wx + GX, wy + GY, z, 11) % 9 == 0:
                            ar(x, y, z, AC_WALL["W"])
                        if door:
                            ar(x, y, z, DOOR_EXT[0]); dsq |= {(x, y, z), (x - 1, y, z)}
                        elif win:
                            ar(x, y, z, WIN_W)
                    else:
                        op = opening.get((x, y, "N")) if z == 0 and exterior_n else None
                        if op and op != "door":
                            ar(x, y, z, op); dsq |= {(x, y, z), (x, y - 1, z)}
                            continue
                        door = op == "door"
                        out_ = (Y, X) if inside == 0 else (Y - 1, X)
                        if exterior_n and 0 < z < min(FULL, b.get("acc", FULL)) and BCw[out_] and BALw[out_] > z:
                            door = True
                        if z == 0 and exterior_n and not door and (x, y, "N") in vit:
                            ar(x, y, z, VITRINE[1]); continue
                        win = exterior_n and not door and not b.get("obel") and ((wx + GX) % 3 == 1 or b["kind"] == "masp") \
                            and not (z == 1 and (wx, wy) in SGN)
                        ar(x, y, z, f"{sh}_{bs + 1 + (10 if door else 8 if win else 0)}")
                        if exterior_n and inside == 0 and z > 0 and not door and not win and not BALw[Y, X] and \
                                b["rooms"] != "ind" and not b.get("obel") and (x, y) not in lads and not (z == 1 and (wx, wy) in SGN) and h32(wx + GX, wy + GY, z, 11) % 9 == 0:
                            ar(x, y, z, AC_WALL["N"])
                        if door:
                            ar(x, y, z, DOOR_EXT[1]); dsq |= {(x, y, z), (x, y - 1, z)}
                        elif win:
                            ar(x, y, z, WIN_N)
        for i_, ev_ in rl:
            M4[i_, :len(ev_)] = ev_
        V = M4 >= 0
        seq = M4[V]
        if len(seq):
            u, first = np.unique(seq, return_index=True)
            lut = np.zeros(len(LN), np.int64)
            for c in u[np.argsort(first, kind="stable")].tolist():    # 1o uso, como o add() do laco
                lut[c] = T(LN[c])
            key = ((z + 64) << 16) | (cy_.astype(np.int64) << 8) | cx_
            sqpush(sq, (np.broadcast_to(key[:, None], M4.shape)[V] << 24) | lut[seq])
        # paredes internas (grade de comodos) + comodos
        for bi, ys, xs in (bi_cells(Id[1:-1, 1:-1]) if z < FULL else ()):
            if bi == 0:
                continue
            b = blds[bi]
            if z >= b.get("acc", FULL):
                continue
            S = grid_of(b)
            if b["kind"] == "masp" or b.get("obel"):
                S = 1000                          # MASP e obelisco: um salao por andar
            gx = ((xs + ox + GX) // S).tolist(); gy = ((ys + oy + GY) // S).tolist()
            LY = G.get("lays", {}).get(bi)
            if LY and z > LY["zmax"]:
                LY = None
            if LY:                                # planta do tipo (plan_layouts): zona no lugar do bloco
                Zl, lx0, ly0 = LY["Z"], LY["x0"] - ox, LY["y0"] - oy
                zh, zw = Zl.shape
                zof = lambda xx, yy: int(Zl[yy - ly0, xx - lx0]) if 0 <= yy - ly0 < zh and 0 <= xx - lx0 < zw else 0
                Zl32 = np.ascontiguousarray(Zl, np.int32); Zlp = Zl32.ctypes.data
                gx = ["L"] * len(xs); gy = Zl[ys - ly0, xs - lx0].tolist()
            # so os quadrados que podem ter parede interna (o laco abaixo refaz o teste completo, mesma ordem)
            if b["kind"] == "masp" or b.get("obel"):
                pre = np.zeros(len(xs), bool)
            elif LY:
                Zp = np.pad(Zl, 1)
                gv = np.asarray(gy)
                gwv, gnv = Zp[ys - ly0 + 1, xs - lx0], Zp[ys - ly0, xs - lx0 + 1]
                pre = (gv > 0) & (((gwv > 0) & (gwv != gv)) | ((gnv > 0) & (gnv != gv)))
            else:
                pre = (((xs + ox + GX) % S == 0) & (xs > 0)) | (((ys + oy + GY) % S == 0) & (ys > 0))
            pre &= ~(eW[ys + 1, xs] | eN[ys, xs + 1])     # nao sobrepor parede externa
            pi_ = np.nonzero(pre)[0]
            pxs, pys = xs[pi_].tolist(), ys[pi_].tolist()
            pgx, pgy = [gx[i] for i in pi_.tolist()], [gy[i] for i in pi_.tolist()]
            xs_n, ys_n = xs, ys
            xs, ys = xs.tolist(), ys.tolist()
            sh, bs = int_wall(b)
            st = stairs.get(bi)
            stz_ = st_zone(st) if st else ()
            # bordas internas entre blocos
            if not LY and not (b["kind"] == "masp" or b.get("obel")):   # Rust: mesmo laco (Cell.int_walls)
                pxa, pya = np.ascontiguousarray(xs_n[pi_], np.int64), np.ascontiguousarray(ys_n[pi_], np.int64)
                jl = jails.get(bi, ())[:2] if z == 0 else ()
                dd = sq.int_walls(pxa.ctypes.data, pya.ctypes.data, len(pxa), ox, oy, GX, GY, S, int(bi), Id32p, CS + 2,
                                  list(stz_), z, sh, bs, FRAME_INT, DOOR_INT, tuple(jl) if len(jl) == 2 else None)
                if dd:
                    dsq |= dd
                pxs = ()
            for (x, y, wgx, wgy) in zip(pxs, pys, pgx, pgy):
                wx, wy = x + ox, y + oy
                if (wx, wy) in stz_:
                    continue
                if LY:
                    g_ = wgy
                    gw_, gn_ = zof(x - 1, y), zof(x, y - 1)
                    wW = g_ > 0 and gw_ > 0 and gw_ != g_
                    wN = g_ > 0 and gn_ > 0 and gn_ != g_
                else:
                    wW = bool(((wx + GX) % S == 0) and Idl[y + 1][x] == bi) if x > 0 else False
                    wN = bool(((wy + GY) % S == 0) and Idl[y][x + 1] == bi) if y > 0 else False
                if b["kind"] == "masp" or b.get("obel"):
                    wW = wN = False
                if not (wW or wN):
                    continue
                if LY:
                    dW = wW and (wx, wy, "W") in LY["doors"]
                    dN = wN and (wx, wy, "N") in LY["doors"]
                else:
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
            svc = not LY and z == 0 and btags(b).get("shop") == "supermarket" and len(b.get("pois") or ()) < 2
            # agrupamento em Rust (Groups); listas so nos casos raros
            ga_ = np.zeros(len(xs_n), np.int64) if LY else np.ascontiguousarray((xs_n + ox + GX) // S, np.int64)
            gb_ = np.ascontiguousarray(Zl[ys_n - ly0, xs_n - lx0] if LY else (ys_n + oy + GY) // S, np.int64)
            xa_, ya_ = np.ascontiguousarray(xs_n, np.int64), np.ascontiguousarray(ys_n, np.int64)
            G_ = GF.GP.group_rooms(xa_.ctypes.data, ya_.ctypes.data, ga_.ctypes.data, gb_.ctypes.data, len(xa_))
            kl = G_.keys()
            if LY:
                kl = [("L", k2) for _, k2 in kl]
            keys = {k: G_.cells(i) for i, k in enumerate(kl)} if svc else None
            service_rooms = {}
            if svc:
                eligible = [k for k, cs in keys.items() if len(cs) >= 9 and
                            max(p[0] for p in cs) - min(p[0] for p in cs) >= 2 and
                            max(p[1] for p in cs) - min(p[1] for p in cs) >= 2]
                if len(eligible) >= 4:
                    eligible.sort(key=lambda k: (len(keys[k]), k))
                    service_rooms = dict(zip(eligible[:3], ("bathroom", "office", "storage")))
            for gi, k in enumerate(kl):
                cells_ = keys[k] if keys is not None else None
                grp = cells_ is None              # quadrados ainda so no Groups (Rust)
                if b["kind"] == "masp" and z < MASP_Z0:
                    continue
                if LY and k[1] <= 0:              # cela (desenhada pela put_jail) / fora do predio
                    continue
                if not LY and z == 0 and jails.get(bi, ())[:2] == k:
                    if grp:
                        cells_, grp = G_.cells(gi), False
                    jk = jails[bi]; jw = jail_layout(S, jk[2])[-1][1]
                    cells_ = [(x_, y_) for x_, y_ in cells_
                              if not (0 <= (x_ + ox + GX) % S - jk[3] <= jw and 0 <= (y_ + oy + GY) % S - jk[4] < 5)]
                    if not cells_:
                        continue
                rects = G_.rects(gi) if grp else to_rects(cells_)
                rname = LY["names"][k[1]][0 if z == 0 else 1] if LY else service_rooms.get(k) or room_name(b, z, k)
                stz = {(a_ - ox, b_ - oy) for a_, b_ in st_zone(st)} if st else set()
                same = lambda xx, yy, bi=bi, k=k, S=S: Idl[yy + 1][xx + 1] == bi and \
                    ((xx + ox + GX) // S, (yy + oy + GY) // S) == k
                sk = (Idp, Id32.shape[1], Id32.shape[0], 0, 0, bi, 0, ox + GX, oy + GY, S, k[0], k[1])   # o mesmo same() p/ o furn_cand
                if LY:
                    same = lambda xx, yy, g=k[1], zof=zof: zof(xx, yy) == g
                    sk = (Zlp, zw, zh, lx0, ly0, k[1], 1, 0, 0, 1, 0, 0)
                    k = (7919, k[1])              # chave inteira para os hashes de piso/mobilia
                    EXl = LY["extra"] if z == 0 else LY.get("extra_up", {})
                    if EXl:                       # caixas, balcao, vitrine, mesas, carteiras: fixos da planta
                        CC = set(G_.cells(gi) if grp else cells_)
                        for X_, Y_, s1, s2 in EXl.get(k[1], ()):
                            q = (X_ - ox, Y_ - oy)
                            if q not in CC or q in stz or any((q[0] + a_, q[1] + b_, z) in dsq
                                                              for a_, b_ in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))):
                                continue
                            add(q[0], q[1], z, s1)
                            if s2:
                                add(q[0], q[1], z, s2)
                            stz.add(q); nfurn += 1
                if b["kind"] == "masp":            # pinacoteca: acervo em grade, sem mobilia comum
                    for x_, y_ in (G_.cells(gi) if grp else cells_):
                        spr = masp_art(x_ + ox + GX, y_ + oy + GY)
                        if spr and (x_, y_) not in stz and (x_, y_, z) not in dsq and \
                                same(x_ + 1, y_) and same(x_, y_ + 1) and same(x_ - 1, y_) and same(x_, y_ - 1):
                            add(x_, y_, z, spr); nfurn += 1
                elif not b.get("obel"):            # obelisco: so a escada por dentro
                    if rname in ROOM_FLOOR:
                        rf = T(ROOM_FLOOR[rname][h32(bi, k[0], k[1]) % len(ROOM_FLOOR[rname])])
                        if grp:
                            G_.replace(gi, sq, z, rf)
                        else:
                            for x_, y_ in cells_:
                                sq.replace(x_, y_, z, rf)
                    nfurn += furnish(add, rname, cells_, same, z, dsq, stz, h32(bi, z, k[0], k[1]), sk=sk,
                                     grp=(G_, gi, sq) if grp else None)
                bld_rooms.setdefault(bi, []).append(len(rooms))
                rooms.append((rname, z, rects))
        # escadas neste nivel (so as da celula: st_here, calculado 1 vez por celula)
        for zl, cs_ in st_here:
            if z > zl:   # heliponto: escada sobe ao telhado
                continue
            for lx, ly, spr in cs_:
                add(lx, ly, z, spr)
        # varandas: piso + mureta so nas bordas livres da varanda
        if z > 0:
            bz = BALw > z
            cz = (bz[1:-1, 1:-1] | bz[1:-1, :-2] | bz[:-2, 1:-1]) & (Bw[1:-1, 1:-1] == 0)
            bzl = bz.tolist() if cz.any() else None    # listas: indexar numpy escalar por quadrado era lento
            for y, x in zip(*(v.tolist() for v in np.nonzero(cz))):
                Y, X = y + 1, x + 1
                me = bzl[Y][X]
                if me:
                    add(x, y, z, BAL_FLOOR)
                lw_ = me != bzl[Y][X - 1] and not Bl[Y][X - 1]
                ln_ = me != bzl[Y - 1][X] and not Bl[Y - 1][X]
                if lw_ and ln_:
                    add(x, y, z, LOW_NW)
                elif lw_:
                    add(x, y, z, LOW_W)
                elif ln_:
                    add(x, y, z, LOW_N)
        # telhado plano no topo, com condensadoras/exaustores (comercio) ou antena (casa)
        topm = (Bw[1:-1, 1:-1] > 0) & (Lw[1:-1, 1:-1] == z) if z > 0 else None
        if topm is not None and topm.any():    # Rust (Cell.roof)
            if rf_ is None:
                bwi = np.ascontiguousarray(Bw, np.int32)
                ub = np.unique(bwi).tolist()
                resv = [False] * (ub[-1] + 1)
                for bi in ub:
                    if bi:
                        resv[bi] = blds[bi]["kind"] == "res"
                hg = np.ascontiguousarray(h32_grid(ox + GX, oy + GY, CS, 5, arr=True), np.uint32)
                hm = np.zeros((CS, CS), np.uint8)       # 2 = vao da escada do heliponto, 4 = heliponto
                for bi in ub:
                    st_ = stairs.get(bi) if bi else None
                    if st_ and "heli" in blds[bi]:
                        for wx_, wy_ in st_set(st_):
                            if 0 <= wx_ - ox < CS and 0 <= wy_ - oy < CS and Bl[wy_ - oy + 1][wx_ - ox + 1] == bi:
                                hm[wy_ - oy, wx_ - ox] |= 2
                for wx_, wy_ in heli_:
                    if 0 <= wx_ - ox < CS and 0 <= wy_ - oy < CS:
                        hm[wy_ - oy, wx_ - ox] |= 4
                rf_ = (bwi, resv, hg, hm)
            bwi, resv, hg, hm = rf_
            flr = np.ascontiguousarray(hm | topm.astype(np.uint8))
            sq.roof(z, CS, flr.ctypes.data, bwi.ctypes.data, hg.ctypes.data, resv, -1 if masp is None else masp,
                    ROOF, tuple(DISH), list(ROOF_BIG))
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
    for (px, py, pz), ts in xsq_cell(ox, oy):
        lx, ly = px - ox, py - oy
        if 0 <= lx < CS and 0 <= ly < CS:
            if (px, py, pz) in G["xclr"]:
                sq.clear(lx, ly, pz)
            for n in ts:
                add(lx, ly, pz, n)
    for ri, (rname, rz, cells_) in enumerate(G["xrooms"]):
        loc = [(px - ox, py - oy) for px, py in cells_ if 0 <= px - ox < CS and 0 <= py - oy < CS]
        if loc:
            if ri in G.get("xbld", {}):   # prefab vanilla: comodos do mesmo predio vanilla num predio so
                bld_rooms.setdefault(G["xbld"][ri], []).append(len(rooms))
            elif rz < 0:   # subsolo precisa de predio proprio: comodo orfao nunca e "visto" e fica preto
                bld_rooms.setdefault(("x", rname, len(rooms)), []).append(len(rooms))
            rooms.append((rname, rz, to_rects(loc)))
    return finish_cell(cx, cy, sq, rooms, bld_rooms, maxz)


def wall_style(b):
    if b["rooms"] == "ind":
        return IND_WALLS
    if b["kind"] == "res":
        return RES_WALLS[b["h"] % len(RES_WALLS)]
    return COM_WALLS[b["h"] % len(COM_WALLS)]


GARAGE_W = ("walls_garage_01_2", "walls_garage_01_1", "walls_garage_01_0")   # norte -> sul (igual RC)
GARAGE_N = ("walls_garage_01_3", "walls_garage_01_4", "walls_garage_01_5")   # oeste -> leste
OUT_SCORE = {G_SIDE: 3, G_PAVE: 3, G_ASPH: 3, G_YARD: 2, G_PARK: 1, G_GRASS: 1, G_DEF: 1}


def h32v(*a):
    """h32 em arrays (uint64 -> int64), mesmo resultado que h32 elemento a elemento."""
    M, P = np.uint64(0xFFFFFFFF), np.uint64(16777619)
    x = np.uint64(2166136261)
    for v in a:
        x = ((x ^ (np.asarray(v, np.int64) & 0xFFFFFFFF).astype(np.uint64)) * P) & M
    return np.asarray(x).astype(np.int64)


def plan_openings(Id, gw, blds, ox, oy, GX, GY):
    """Portas externas e portao de garagem no terreo, por predio na celula (padrao Raccoon City:
    todo predio com entrada, ~2-3 portas por casa, portao de garagem em parte das casas).
    Devolve {(x, y, lado): "door" | sprite do portao}. Lado W = parede oeste do quadrado, N = norte.
    Bordas candidatas em numpy (era edge() por quadrado); mesma ordem de candidatos do laco (y, x, W antes de N)."""
    C = Id.shape[0] - 2
    eW = Id[:, 1:] != Id[:, :-1]
    eN = Id[1:, :] != Id[:-1, :]
    Ip = Id.astype(np.int64)
    lut = np.zeros(256, np.int64)
    for k_, v_ in OUT_SCORE.items():
        lut[k_] = v_
    b_, gb = Ip[1:C + 1, 1:C + 1], gw[1:C + 1, 1:C + 1]
    ismasp = np.zeros(len(blds), bool)
    for bi in np.unique(Ip).tolist():
        if bi:
            ismasp[bi] = blds[bi]["kind"] == "masp"
    sides = []
    for W in (True, False):
        if W:
            v = eW[1:C + 1, 0:C] & ~eN[0:C, 1:C + 1]; a_, ga = Ip[1:C + 1, 0:C], gw[1:C + 1, 0:C]
        else:
            v = eN[0:C, 1:C + 1] & ~eW[1:C + 1, 0:C]; a_, ga = Ip[0:C, 1:C + 1], gw[0:C, 1:C + 1]
        v = v & ((a_ == 0) != (b_ == 0))
        bi = np.where(v, a_ + b_, 0)
        sc = np.where(b_ == 0, lut[gb], lut[ga])
        P_ = np.pad(bi, 1)
        nb = (P_[0:C, 1:C + 1] == bi) & (P_[2:, 1:C + 1] == bi) if W else (P_[1:C + 1, 0:C] == bi) & (P_[1:C + 1, 2:] == bi)
        ok = v & ~ismasp[bi]
        sides.append((ok, bi, sc, ok & (sc > 0) & nb))
    per = collections.Counter(dict(enumerate(
        (np.bincount(sides[0][1][sides[0][0]], minlength=len(blds)) +
         np.bincount(sides[1][1][sides[1][0]], minlength=len(blds))).tolist())))
    ys_, xs_, ss_ = [], [], []
    for si, (_, bi, sc, cm) in enumerate(sides):
        y_, x_ = np.nonzero(cm)
        ys_.append(y_); xs_.append(x_); ss_.append(np.full(len(y_), si))
    ys, xs, ss = np.concatenate(ys_), np.concatenate(xs_), np.concatenate(ss_)
    pos = (ys * C + xs) * 2 + ss
    o = np.argsort(pos, kind="stable"); ys, xs, ss, pos = ys[o], xs[o], ss[o], pos[o]
    bis = np.where(ss == 0, sides[0][1][ys, xs], sides[1][1][ys, xs])
    scs = np.where(ss == 0, sides[0][2][ys, xs], sides[1][2][ys, xs])
    hk = h32v(bis, xs + ox + GX, ys + oy + GY)
    _, fi = np.unique(bis, return_index=True)
    rank = np.zeros(len(blds), np.int64); rank[bis[fi]] = np.argsort(np.argsort(fi))
    o = np.lexsort((np.arange(len(bis)), hk, -scs, rank[bis]))
    cand = {}
    for bi, sc, x, y, si in zip(bis[o].tolist(), scs[o].tolist(), xs[o].tolist(), ys[o].tolist(), ss[o].tolist()):
        l_ = cand.get(bi)
        if l_ is None:
            l_ = cand[bi] = []
        l_.append((sc, x, y, "W" if si == 0 else "N"))
    area = np.bincount(Id[1:-1, 1:-1].ravel(), minlength=len(blds) + 1)
    plan = {}
    for bi, cs in cand.items():     # cs ja em (-score, h32(bi, x, y), ordem do laco)
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
CIVIC_MIX = {   # (terreo, andares): como no vanilla, o predio civico nao e um comodo so
    "fire_station": (["firestorage", "firestorage", "kitchen", "bathroom", "office"],
                     ["bedroom", "bedroom", "bathroom", "office"]),
    "hotel": (["lobby", "office", "kitchen", "laundry"], ["motelroom", "motelroom", "motelroom", "storage"]),
    "motel": (["lobby", "motelroom", "motelroom", "laundry"], ["motelroom"]),
    "townhall": (["lobby", "office", "office", "breakroom"], ["office", "office", "breakroom"]),
    "courthouse": (["lobby", "office", "breakroom"], ["office", "breakroom"]),
    "library": (["library", "library", "office"], ["library", "office"]),
    "post_office": (["post", "post", "poststorage"], ["poststorage", "office"]),
    "bus_station": (["lobby", "waitingroom", "office"], ["office"]),
    "train_station": (["lobby", "waitingroom", "office"], ["office"]),
    # escola publica: salas, secretaria, banheiros, refeitorio e quadra (gym) no terreo; salas em cima
    "school": (["classroom", "classroom", "office", "bathroom", "cafeteria", "classroom", "gym", "cafeteriakitchen"],
               ["classroom", "classroom", "bathroom", "classroom", "office"]),
    "kindergarten": (["daycare", "daycare", "kitchen", "bathroom", "office", "daycare"], ["daycare", "bathroom"]),
    # predio de parque/praca sem tag de casa: centro comunitario (salao, banheiros, copa, administracao)
    "community_centre": (["hall", "bathroom", "kitchen", "office", "hall"], ["hall", "office"]),
    "toilets": (["bathroom"], ["bathroom"]),
}
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
              "ice_cream": "icecream", "pastry": "bakery", "wine": "liquorstore", "storage_rental": "storageunit",
              # tipos comuns em SP que caiam na loja generica
              "newsagent": "cornerstore", "hairdresser": "aesthetic", "beauty_salon": "aesthetic",
              "lottery": "cornerstore", "chocolate": "candystore", "bed": "furniturestore", "gas": "generalstore",
              "lighting": "housewarestore", "interior_decoration": "furniturestore", "erotic": "giftstore",
              "ticket": "office", "tattoo": "aesthetic", "water": "grocery", "coffee": "cafe",
              "travel_agency": "office", "baby_goods": "toystore", "massage": "aesthetic", "boat": "sportstore",
              "motorcycle_repair": "mechanic", "nutrition_supplements": "pharmacy", "party": "giftstore",
              "wholesale": "grocery", "locksmith": "toolstore", "carpet": "furniturestore",
              "swimming_pool": "toolstore", "fashion_accessories": "clothingstore",
              "hairdresser_supply": "pharmacy", "tiles": "toolstore", "market": "grocery", "tea": "cafe",
              "charity": "pawnshop", "games": "toystore", "candles": "giftstore", "health_food": "grocery",
              "grocery": "grocery", "pet_grooming": "petstore", "bathroom_furnishing": "housewarestore",
              "money_lender": "office", "frame": "artstore", "country_store": "generalstore",
              "antiques": "pawnshop", "sewing": "tailoringstore", "leather": "clothingstore",
              "video": "electronicstore", "hifi": "electronicstore", "telecommunication": "electronicstore",
              "fishing": "outdoorsupply", "textiles": "tailoringstore", "funeral_directors": "office"}
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
              "arts_centre": "theatre", "social_facility": "hall", "college": "classroom",
              "bureau_de_change": "office", "toilets": "bathroom"}
for _k, _v in _SHOP_EXTRA.items():
    SHOP_ROOMS.setdefault(_k, _v)


def room_poi(b, z, k):
    """POI que nomeia o comodo: no terreo de predio com varias lojas, a mais perto do centro do comodo."""
    ps = b.get("pois") or []
    if z != 0 or len(ps) < 2:
        return b.get("poi")
    S = grid_of(b)
    cx, cy = (k[0] + .5) * S - G["rx0"] - CX0 * CS, (k[1] + .5) * S - G["ry0"] - CY0 * CS
    # cada loja garante 1 comodo: o do seu ponto (ja dentro do predio) ou o livre mais perto; o resto, a mais perto
    pk = b.get("_pk")
    if pk is None or pk[0] != S:
        ox_, oy_ = G["rx0"] + CX0 * CS, G["ry0"] + CY0 * CS
        Ba = G["Ba"]
        bi = next((int(Ba[p[1], p[0]]) for p in ps if 0 <= p[1] < Ba.shape[0] and 0 <= p[0] < Ba.shape[1]
                   and Ba[p[1], p[0]]), 0)
        own = {}
        if bi:
            fo = G.get("_fo_ba")
            if fo is None or fo[0] is not Ba:
                from ._ndi import ndimage     # scipy se houver; senao numpy (editor sem scipy)
                fo = G["_fo_ba"] = (Ba, ndimage.find_objects(Ba))
            sl = fo[1][bi - 1]
            ys, xs = np.nonzero(Ba[sl] == bi); ys += sl[0].start; xs += sl[1].start
            cells = set(zip(((xs + ox_) // S).tolist(), ((ys + oy_) // S).tolist()))
            for p in sorted(ps, key=lambda p: 0 if (p[2].get("shop") or p[2].get("amenity") in AMEN_ROOMS) else 1):
                free = cells - set(own)
                if not free:
                    break
                kx, ky = (p[0] + ox_) // S, (p[1] + oy_) // S
                own[min(free, key=lambda c: ((c[0] - kx) ** 2 + (c[1] - ky) ** 2, c))] = p[2]
        pk = b["_pk"] = (S, own)
    if tuple(k) in pk[1]:
        return pk[1][tuple(k)]
    best = min(ps, key=lambda p: ((p[0] - cx) ** 2 + (p[1] - cy) ** 2, 0 if (p[2].get("shop") or
                                                                              p[2].get("amenity") in AMEN_ROOMS) else 1))
    return best[2]


HOSP_ROOMS_0 = ("waitingroom", "medical", "hospitalroom", "medicaloffice", "medicalstorage", "medical")
HOSP_ROOMS_UP = ("hospitalroom", "hospitalroom", "medical", "hospitalroom", "laboratory", "hospitalroom",
                 "hospitalstorage", "medicaloffice")


def room_name(b, z, k):
    t = dict(b["tags"])
    poi = room_poi(b, z, k)
    if poi:
        for kk in ("shop", "amenity"):
            t.setdefault(kk, poi.get(kk))
    if t.get("_room"):
        return t["_room"]
    if b["kind"] == "masp":
        return ("artstore", "office", "storage")[(k[0] + k[1] + z) % 3] if z >= MASP_Z0 else "empty"
    if t.get("amenity") == "police":
        return POLICE_ROOMS[(k[0] * 3 + k[1] + z) % len(POLICE_ROOMS)]
    # mix de comodos dos predios civicos de Rosewood/Muldraugh/Riverside (fonte/vanilla/inventario_cidades.json)
    civ = CIVIC_MIX.get(t.get("amenity")) or CIVIC_MIX.get(t.get("building"))
    if civ is None and t.get("tourism") in ("hotel", "motel", "hostel", "guest_house"):
        civ = CIVIC_MIX["hotel"]
    if civ:
        rr = civ[0] if z == 0 else civ[1]
        if z == 0 and t.get("amenity") in ("school", "kindergarten") and any(
                int((p[0] + G["rx0"] + CX0 * CS) // grid_of(b)) == k[0] and
                int((p[1] + G["ry0"] + CY0 * CS) // grid_of(b)) == k[1] for p in b.get("pois") or ()):
            return rr[0]                # o comodo do ponto da escola e sala de aula/creche
        return rr[(k[0] * 3 + k[1] + z) % len(rr)]
    if b.get("mil"):
        return "armystorage" if (k[0] + k[1] + z) % 3 else "office"
    if b.get("hosp") or t.get("amenity") in ("hospital", "clinic"):
        rr = HOSP_ROOMS_UP if z > 0 else HOSP_ROOMS_0
        return rr[(k[0] * 3 + k[1] + z) % len(rr)]
    if t.get("leisure") in ("fitness_centre", "sports_centre") and z == 0:
        return "gym"
    if z == 0 and b["rooms"] in ("res", "ind"):   # casa/galpao com loja marcada (ponto ou tag): o terreo e a loja
        for q in (poi or {}, t):
            if q.get("shop") in SHOP_ROOMS:
                return SHOP_ROOMS[q["shop"]]
            if q.get("amenity") in AMEN_ROOMS:
                return AMEN_ROOMS[q["amenity"]]
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
    return GF.GP.to_rects(cells_)


DROP = "saopaulo_"      # folhas proprias do projeto SP: nao existem no jogo vanilla (o tile some, o resto do quadrado fica)


def finish_cell(cx, cy, sq, rooms, bld_rooms, maxz):
    """Escreve lotheader, lotpack e chunkdata de uma celula (registro em Rust: lotpack, z e densidade prontos)."""
    lp, zmin, zmax, dens = sq.finish()
    names = sq.names()
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
    hb += dens      # densidade de zumbis por chunk (0..4): mais predio = mais zumbi
    return _finish_put(cx, cy, hb, lp, names, rooms, bld_rooms, zmax)


def _finish_put(cx, cy, hb, lp, names, rooms, bld_rooms, zmax):
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
    lays = plan_layouts(Ba, Ga, blds, bb, stairs, jails)
    signs = plan_signs(Ga, Ba, blds, bb, masp)
    G.update(Ga=Ga, LNa=LNa, Ba=Ba, Lv=Lv, blds=blds, stairs=stairs, masp=masp, TR=TR, ntree=int(TR.sum()),
             jails=jails, signs=signs, lays=lays,
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
