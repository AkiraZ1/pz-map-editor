"""spgen: gera um projeto J' PZ MAP STUDIO (celulas B42) a partir de um lugar real (.osm / .osm.pbf).

Copia adaptada de saopaulo/scripts/gen.py + area.py + zones.py + worldmap.py, sem nada fixo de SP e sem
dependencias alem de numpy e PIL (o .pbf e lido em Python puro, ver osmread.py).

    generate(osm_path, bbox=None, out_dir=..., name=..., progress=PG, extra=None) -> dict
    validate(osm_path, bbox=None) -> dict          (rapido, nao gera nada)

bbox = (lat0, lon0, lat1, lon1) em graus (qualquer ordem dos cantos) ou None = tudo que o arquivo tem.
1 tile = 1 m. O centro do bbox vai para o centro do mapa; o mapa tem ceil(largura/256) x ceil(altura/256)
celulas a partir de extra["origin"] (padrao (100, 100)).

Saida em out_dir:
  project.json                     {"name","format":1,"created","cells","spawn":[x,y,0],"mapid","gen":{...}}
  cells/{cx}_{cy}.lotheader        LOTH v1 (B42)
  cells/world_{cx}_{cy}.lotpack    LOTP v1 (B42)
  gen/objects.lua                  zonas: TownZone (cada celula), ParkingStall, Nav, Forest, ZombiesType
  gen/spawnpoints.lua              SpawnPoints() vanilla (poor/medium/rich/police/doctor/fire/jail/center + profissao)
  gen/worldmap.xml                 mapa do jogador (water/highway/building por categoria), coordenada da celula
  gen/worldmap-forest.xml          natural=forest (mata e parque)
  gen/points.json                  pontos extras para Lua (gen = hospitais/governo grandes; mundo, z)
  gen/stats.json                   contagens e tempos da geracao
  gen/raster/b_{i}_{j}.npz         rasters por bloco (G chao, L andares, R classe de via, K categoria de predio)
  gen/raster/sp_*.json, pts_*.json pontos por bloco (intermediarios)
  gen/src.pkl                      fontes ja projetadas (intermediario dos workers; apagado no fim)

extra (tudo opcional):
  rotation   graus (giro do mapa em torno do centro; positivo = anti-horario no mapa). Padrao 0.
  origin     (cx0, cy0) celula do canto NW. Padrao (100, 100).
  footprints caminho de GeoJSON (.geojson/.json, ou .gz) com contornos de predio e altura (height,
             qt_altura_edificacao ou building:levels); entra como no GeoSampa do projeto SP.
  max_cells  teto de celulas (padrao 400). Acima disso generate recusa.
  workers    processos (padrao: nucleos - 1, limitado pela RAM estimada).
  maxl       teto de andares (padrao 8).
  tiles      caminho do tiles.json (padrao: o mais novo do cache de assets).
Progresso (pzms.progress): etapas "ler osm", "celulas", "metadados"; micro por worker na etapa "celulas".
"""
import glob
import json
import math
import os
import pickle
import shutil
import time

from .. import progress as PG

STEPS = ["ler osm", "celulas", "metadados"]
CS = 256


def _find_tiles(extra):
    p = extra.get("tiles") or os.environ.get("PZMS_SPGEN_TILES")
    if p and os.path.exists(p):
        return p
    try:
        from .. import gamedir
        c = sorted(glob.glob(os.path.join(gamedir.cache_dir(), "*", "tiles.json")), key=os.path.getmtime)
        return c[-1] if c else None
    except Exception:
        return None


def _norm_bbox(b):
    return (min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3]))


def _grid(bbox, rot):
    """bbox -> centro e numero de celulas (com giro, a caixa girada inteira cabe no mapa)."""
    lat0, lon0, lat1, lon1 = _norm_bbox(bbox)
    latc, lonc = (lat0 + lat1) / 2, (lon0 + lon1) / 2
    k = math.cos(math.radians(latc))
    w = (lon1 - lon0) * 111320.0 * k
    h = (lat1 - lat0) * 110574.0
    p = math.radians(rot)
    W = abs(w * math.cos(p)) + abs(h * math.sin(p))
    H = abs(w * math.sin(p)) + abs(h * math.cos(p))
    return latc, lonc, max(1, math.ceil(W / CS - 1e-6)), max(1, math.ceil(H / CS - 1e-6)), w, h


def validate(osm_path, bbox=None):
    """-> {ok, formato, nodes, ways, cobre_bbox, celulas_estimadas, segundos_estimados, avisos[]}"""
    from . import osmread
    av = []
    out = {"ok": False, "formato": None, "nodes": 0, "ways": 0, "cobre_bbox": None, "celulas_estimadas": 0,
           "segundos_estimados": 0, "avisos": av, "bounds": None, "preview": []}
    if not osm_path or not os.path.isfile(osm_path):
        av.append("arquivo nao encontrado")
        return out
    low = str(osm_path).lower()
    if not (low.endswith(".osm") or low.endswith(".osm.pbf") or low.endswith(".pbf") or low.endswith(".xml")):
        av.append("extensao inesperada (use .osm ou .osm.pbf)")
    try:
        s = osmread.scan(osm_path)
    except Exception as e:  # arquivo corrompido / formato errado
        av.append(f"nao consegui ler: {e}")
        return out
    out.update(formato=s["formato"], nodes=s["nodes"], ways=s["ways"])
    if s["formato"] == "desconhecido" or not s["nodes"]:
        av.append("nao parece OSM (nenhum no)")
        return out
    bd = s.get("bounds") or s.get("extent")
    if bd:
        out["bounds"] = [round(float(v), 7) for v in _norm_bbox(bd)]
    pv = s.get("preview")
    if pv is not None and len(pv):
        step = max(1, -(-len(pv) // 4000))
        out["preview"] = [[round(float(a), 6), round(float(b), 6)] for a, b in pv[::step][:4000]]
    if bbox is None:
        if not bd:
            av.append("sem bbox e o arquivo nao informa os limites")
            return out
        bbox = bd
        av.append("sem bbox: usando a area inteira do arquivo")
    bbox = _norm_bbox(bbox)
    if bd:
        b = _norm_bbox(bd)
        tol = 1e-4
        out["cobre_bbox"] = bool(b[0] - tol <= bbox[0] and b[1] - tol <= bbox[1] and
                                 b[2] + tol >= bbox[2] and b[3] + tol >= bbox[3])
        if not out["cobre_bbox"]:
            inter = not (b[2] < bbox[0] or b[0] > bbox[2] or b[3] < bbox[1] or b[1] > bbox[3])
            av.append("o arquivo cobre so parte do bbox" if inter else "o bbox esta fora do arquivo")
    else:
        av.append("o arquivo nao informa os limites: cobertura do bbox nao verificada")
    if not (-85 < bbox[0] < 85 and -85 < bbox[2] < 85 and -180 <= bbox[1] <= 180 and -180 <= bbox[3] <= 180):
        av.append("bbox fora de lat/lon validos (ordem esperada: lat0, lon0, lat1, lon1)")
        return out
    _, _, ncx, ncy, w, h = _grid(bbox, 0)
    n = ncx * ncy
    out["celulas_estimadas"] = n
    if w < 50 or h < 50:
        av.append("bbox muito pequeno (menos de 50 m)")
    if n > 400:
        av.append(f"{n} celulas: acima do teto padrao (400); reduza o bbox ou passe extra['max_cells']")
    elif n > 100:
        av.append(f"{n} celulas: geracao longa e mapa grande")
    mb = os.path.getsize(osm_path) / 1e6
    ler = mb * (1.0 if s["formato"] == "pbf" else 0.25) + 2
    out["segundos_estimados"] = int(round(ler + 6 + n * 2.5 / max(1, min(8, (os.cpu_count() or 2) - 1)) + n * 0.3))
    out["ok"] = (out["cobre_bbox"] is not False) and n <= 400 and w >= 50 and h >= 50 and \
        not any(a.startswith("bbox fora") for a in av)
    return out


def _winit(cfg, pkl):
    """inicializador do worker (nivel de modulo, spawn): geometria + fontes projetadas."""
    from . import gen
    gen.configure(cfg)
    with open(pkl, "rb") as f:
        gen.G["src"] = pickle.load(f)


def _wblock(bk):
    from . import gen
    try:
        return gen.process_block(bk)
    finally:
        PG.micro_done()


def generate(osm_path, bbox=None, out_dir=None, name="Mapa", progress=PG, extra=None):
    """gera o projeto (ver docstring do modulo). Devolve {"ok","out_dir","cells","spawn","segundos",...}."""
    extra = dict(extra or {})
    PGm = progress or PG
    t0 = time.time()
    if not out_dir:
        raise ValueError("out_dir obrigatorio")
    out_dir = os.path.abspath(out_dir)
    cells_dir, gen_dir = os.path.join(out_dir, "cells"), os.path.join(out_dir, "gen")
    for d in (cells_dir, gen_dir):
        os.makedirs(d, exist_ok=True)
    shutil.rmtree(os.path.join(gen_dir, "raster"), ignore_errors=True)
    tiles = _find_tiles(extra)
    if tiles:
        os.environ["PZMS_SPGEN_TILES"] = tiles        # gen.py le na importacao (e os workers herdam)
    if extra.get("maxl"):
        os.environ["MAXL"] = os.environ["FULL"] = str(int(extra["maxl"]))
    from . import osmread
    from . import gen
    from . import meta
    tm = {}

    # 1) ler osm
    PGm.mark("ler osm", 0, 100, os.path.basename(osm_path))
    PGm.log(f"spgen: lendo {osm_path}")
    t = time.time()
    d = osmread.read(osm_path, bbox, margin_m=800.0,
                     progress=lambda f, m: PGm.mark("ler osm", int(f * 90), 100, m),
                     workers=extra.get("workers"))
    bbox = d["bbox"]
    rot = float(extra.get("rotation", 0.0))
    latc, lonc, ncx, ncy, wm, hm = _grid(bbox, rot)
    if ncx * ncy > int(extra.get("max_cells", 400)):
        raise ValueError(f"bbox gera {ncx * ncy} celulas (teto {extra.get('max_cells', 400)})")
    cx0, cy0 = (int(v) for v in extra.get("origin", (100, 100)))
    nmax = max(ncx, ncy)
    bs = 2 if ncx * ncy <= 16 else 4 if ncx * ncy <= 144 else 6
    cfg = {"lat0": latc, "lon0": lonc, "phi": rot, "ncx": ncx, "ncy": ncy, "cx0": cx0, "cy0": cy0,
           "out": cells_dir, "gen": gen_dir, "bs": min(bs, nmax), "mg": 512}
    gen.configure(cfg)
    PGm.mark("ler osm", 92, 100, "projetando fontes")
    S = gen.load_sources(d, extra)
    pkl = os.path.join(gen_dir, "src.pkl")
    with open(pkl, "wb") as f:
        pickle.dump(S, f, protocol=pickle.HIGHEST_PROTOCOL)
    del S
    tm["ler osm"] = round(time.time() - t, 1)
    PGm.log(f"spgen: {d['stats']} -> {ncx}x{ncy} celulas ({wm:.0f} x {hm:.0f} m)")
    PGm.finish("ler osm", f"{d['stats']['areas']} areas, {d['stats']['lines']} linhas, {d['stats']['pois']} pontos")

    # 2) celulas, por bloco BS x BS (um processo por bloco)
    t = time.time()
    BS = gen.BS
    blocks = [(i, j) for i in range((ncx + BS - 1) // BS) for j in range((ncy + BS - 1) // BS)]
    total = ncx * ncy
    done, cells, spawn_c, stats = 0, [], [], {}
    # RAM por worker ~ raster do bloco (W*H) x ~40 bytes + fontes
    ram_w = (gen.W * gen.H * 40 + os.path.getsize(pkl) * 3) / 1e9
    nw = int(extra.get("workers") or max(1, min(len(blocks), (os.cpu_count() or 2) - 1, int(12 / max(ram_w, 0.3)))))
    PGm.mark("celulas", 0, total, f"{len(blocks)} blocos de {BS}x{BS}, {nw} processos")

    def take(r):
        nonlocal done
        bk, res, sp, st, _ch = r
        for c, rr, _ in res:
            if rr is not None:
                cells.append([int(c[0]), int(c[1])])
        spawn_c.extend(sp)
        for k, v in st.items():
            stats[k] = stats.get(k, 0) + v
        done += len(res)
        PGm.mark("celulas", done, total, f"bloco {bk[0]}_{bk[1]} pronto")

    if nw <= 1 or len(blocks) == 1:
        _winit(cfg, pkl)
        for bk in blocks:
            take(_wblock(bk))
    else:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(nw, initializer=_winit, initargs=(cfg, pkl)) as pool:
            for r in pool.imap_unordered(_wblock, blocks):
                take(r)
    tm["celulas"] = round(time.time() - t, 1)
    PGm.finish("celulas", f"{len(cells)} celulas")

    # 3) metadados
    t = time.time()
    PGm.mark("metadados", 0, 4, "spawnpoints.lua")
    nsp = gen.write_spawns()
    PGm.mark("metadados", 1, 4, "objects.lua")
    nz = meta.objects_lua(d, os.path.join(gen_dir, "objects.lua"))
    PGm.mark("metadados", 2, 4, "worldmap.xml")
    nwm = meta.worldmap(os.path.join(gen_dir, "worldmap.xml"), os.path.join(gen_dir, "worldmap-forest.xml"))
    PGm.mark("metadados", 3, 4, "project.json")
    pts = {}
    for fn in sorted(glob.glob(os.path.join(gen.RAS, "pts_*.json"))):
        with open(fn, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                pts.setdefault(k, []).extend(v)
    with open(os.path.join(gen_dir, "points.json"), "w", encoding="utf-8") as f:
        json.dump(pts, f)
    try:
        os.remove(pkl)
    except OSError:
        pass
    cells.sort()
    sp = spawn_c[len(spawn_c) // 2] if spawn_c else (gen.MX, gen.MY)
    pj_path = os.path.join(out_dir, "project.json")
    old = {}
    if os.path.exists(pj_path):
        try:
            with open(pj_path, encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError):
            old = {}
    meta_ = {"name": name, "format": 1, "created": old.get("created", time.time()), "cells": cells,
             "spawn": [int(sp[0]), int(sp[1]), 0],
             "mapid": "".join(ch for ch in name if ch.isalnum()) or "MeuMapa",
             "gen": {"fonte": os.path.abspath(osm_path), "bbox": list(bbox), "centro": [latc, lonc],
                     "rotacao": rot, "origem": [cx0, cy0], "tamanho": [ncx, ncy], "metros": [round(wm), round(hm)],
                     "footprints": extra.get("footprints"), "tiles": tiles, "quando": time.time(),
                     "arquivos": ["gen/objects.lua", "gen/spawnpoints.lua", "gen/worldmap.xml",
                                  "gen/worldmap-forest.xml", "gen/points.json"]}}
    for k, v in old.items():                     # mantem o que o editor ja tinha (ex.: config de export)
        meta_.setdefault(k, v)
    tmp = pj_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta_, f, indent=1)
    os.replace(tmp, pj_path)
    tm["metadados"] = round(time.time() - t, 1)
    st = {"osm": d["stats"], "gen": stats, "spawns": nsp, "zonas": nz, "worldmap_celulas": nwm,
          "tempos": tm, "segundos": round(time.time() - t0, 1)}
    with open(os.path.join(gen_dir, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)
    PGm.finish("metadados", f"{len(cells)} celulas em {st['segundos']} s")
    PGm.log(f"spgen: pronto em {st['segundos']} s: {stats}")
    return {"ok": True, "out_dir": out_dir, "cells": cells, "spawn": meta_["spawn"], "mapid": meta_["mapid"],
            "tamanho": [ncx, ncy], "segundos": st["segundos"], "stats": st}
