"""Leitor OSM sem dependencias (so numpy): .osm (XML) e .osm.pbf (protobuf + zlib, decodificado a mao).

read(path, bbox, margin_m) -> {"areas", "ways", "pois", "trees", "bounds", "stats"} no formato que
gen.load_sources() consome (lat/lon em graus):
  areas: [{"id", "tags", "rings": [{"outer": [(lat,lon)...], "inner": [[...], ...]}]}]   (predios e usos do solo)
  ways:  [{"id", "tags", "pts": [(lat,lon)...]}]                                         (vias, rios, trilhos...)
  pois:  [{"id", "lat", "lon", "tags"}]  (nos com shop/amenity/...)     trees: [(lat,lon)] (natural=tree)
Fica so o que encosta no bbox ampliado por margin_m. scan(path) e a leitura rapida usada por validate().
"""
import os
import struct
import zlib
import xml.etree.ElementTree as ET

import numpy as np

# chaves que interessam ao gerador; o resto (rotas, limites, endereco solto) e descartado
KEEP = ("building", "building:part", "highway", "landuse", "leisure", "natural", "amenity", "waterway", "water",
        "railway", "place", "parking", "shop", "man_made", "barrier", "office", "tourism", "historic", "aeroway",
        "power", "military", "public_transport", "craft", "healthcare", "sport", "area:highway")
AREA_KEYS = ("building", "landuse", "leisure", "amenity", "water", "place", "parking", "shop", "man_made",
             "office", "tourism", "historic", "aeroway", "military", "craft", "healthcare", "sport")
LINE_NATURAL = ("coastline", "tree_row", "cliff", "ridge", "arete")
import re
_LL = re.compile(rb'<node\b[^>]*?\blat="(-?[0-9.]+)"[^>]*?\blon="(-?[0-9.]+)"')   # atributo lat antes de lon (padrao)
POI_KEYS = ("shop", "amenity", "craft", "office", "tourism", "healthcare")


# ---------------------------------------------------------------- protobuf minimo
def _uv(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        if c < 128:
            return r, i
        s += 7


def _fields(b):
    """itera (campo, tipo, valor) de uma mensagem protobuf (valor: int ou bytes)."""
    i, n = 0, len(b)
    while i < n:
        key, i = _uv(b, i)
        wt = key & 7
        if wt == 0:
            v, i = _uv(b, i)
        elif wt == 2:
            ln, i = _uv(b, i)
            v = b[i:i + ln]
            i += ln
        elif wt == 1:
            v = b[i:i + 8]
            i += 8
        elif wt == 5:
            v = b[i:i + 4]
            i += 4
        else:
            raise ValueError("pbf: tipo de campo protobuf invalido")
        yield key >> 3, wt, v


def _uvarints(b):
    """varints empacotados -> np.uint64 (vetorizado)."""
    a = np.frombuffer(b, np.uint8)
    if not len(a):
        return np.zeros(0, np.uint64)
    end = np.flatnonzero(a < 128)
    starts = np.empty(len(end), np.int64)
    starts[0] = 0
    starts[1:] = end[:-1] + 1
    a = a[:end[-1] + 1]
    grp = np.repeat(np.arange(len(end)), end - starts + 1)
    pos = (np.arange(len(a)) - starts[grp]).astype(np.uint64) * np.uint64(7)
    vals = (a & 0x7F).astype(np.uint64) << pos
    return np.add.reduceat(vals, starts)


def _zz(u):
    """zigzag -> int64."""
    return (u >> np.uint64(1)).astype(np.int64) ^ -(u & np.uint64(1)).astype(np.int64)


def _delta_zz(b):
    """sint64 empacotado com delta -> np.int64 (lista curta: python puro, mais rapido que numpy)."""
    if len(b) > 400:
        return np.cumsum(_zz(_uvarints(b)))
    out, i, n, acc = [], 0, len(b), 0
    while i < n:
        r = sh = 0
        while True:
            c = b[i]
            i += 1
            r |= (c & 0x7F) << sh
            if c < 128:
                break
            sh += 7
        acc += (r >> 1) ^ -(r & 1)
        out.append(acc)
    return np.array(out, np.int64)


def _small_uv(b):
    out, i, n = [], 0, len(b)
    while i < n:
        v, i = _uv(b, i)
        out.append(v)
    return out


def _blobs(f):
    """itera (tipo, offset, tamanho) dos blobs de um .pbf sem descompactar."""
    while True:
        h = f.read(4)
        if len(h) < 4:
            return
        hl = struct.unpack(">I", h)[0]
        hdr = f.read(hl)
        typ, size = "", 0
        for fn, _, v in _fields(hdr):
            if fn == 1:
                typ = bytes(v).decode()
            elif fn == 3:
                size = v
        yield typ, f.tell(), size
        f.seek(size, 1)


def _blob_data(raw):
    data = None
    for fn, _, v in _fields(raw):
        if fn == 1:
            data = bytes(v)
        elif fn == 3:
            data = zlib.decompress(v)
        elif fn in (4, 5, 6, 7):
            raise ValueError("pbf: compressao nao suportada (so zlib/sem compressao)")
    return data


def _header_bbox(data):
    for fn, _, v in _fields(data):
        if fn == 1:   # HeaderBBox em nanograus: left, right, top, bottom (sint64)
            d = {}
            for f2, _, v2 in _fields(v):
                d[f2] = (v2 >> 1) ^ -(v2 & 1)
            if len(d) == 4:
                return (d[4] * 1e-9, d[1] * 1e-9, d[3] * 1e-9, d[2] * 1e-9)   # lat0, lon0, lat1, lon1
    return None


def _parse_block(data, want_ways=True, B=None):
    """PrimitiveBlock -> (nodes(id,lat,lon), tagged_nodes, ways, relations). B: so nos com tag dentro dele."""
    st, groups = [], []
    gran, lat_off, lon_off = 100, 0, 0
    for fn, _, v in _fields(memoryview(data)):
        if fn == 1:
            st = [bytes(s).decode("utf-8", "replace") for f2, _, s in _fields(v) if f2 == 1]
        elif fn == 2:
            groups.append(v)
        elif fn == 17:
            gran = v
        elif fn == 19:
            lat_off = (v >> 1) ^ -(v & 1)
        elif fn == 20:
            lon_off = (v >> 1) ^ -(v & 1)
    ids, lats, lons, tnodes, ways, rels = [], [], [], [], [], []
    k = 1e-9 * gran

    def tags_of(ks, vs):
        return {st[a]: st[b] for a, b in zip(ks, vs)}

    for g in groups:
        for fn, _, v in _fields(g):
            if fn == 2:                                      # DenseNodes
                did = dla = dlo = kv = None
                for f2, _, v2 in _fields(v):
                    if f2 == 1:
                        did = v2
                    elif f2 == 8:
                        dla = v2
                    elif f2 == 9:
                        dlo = v2
                    elif f2 == 10:
                        kv = v2
                if did is None:
                    continue
                i_ = np.cumsum(_zz(_uvarints(did)))
                la = (lat_off + gran * np.cumsum(_zz(_uvarints(dla)))) * 1e-9
                lo = (lon_off + gran * np.cumsum(_zz(_uvarints(dlo)))) * 1e-9
                ids.append(i_); lats.append(la); lons.append(lo)
                if kv is not None and len(kv):
                    kva = _uvarints(kv).astype(np.int64)
                    z = np.flatnonzero(kva == 0)
                    s0 = np.concatenate([[0], z[:-1] + 1])
                    has = np.flatnonzero(z > s0)
                    has = has[has < len(i_)]
                    if B is not None and len(has):
                        has = has[(la[has] >= B[0]) & (la[has] <= B[2]) & (lo[has] >= B[1]) & (lo[has] <= B[3])]
                    for n in has:
                        seg = kva[s0[n]:z[n]]
                        tnodes.append((int(i_[n]), float(la[n]), float(lo[n]),
                                       {st[seg[j]]: st[seg[j + 1]] for j in range(0, len(seg) - 1, 2)}))
            elif fn == 1:                                    # Node simples (raro)
                nid, ks, vs, la, lo = 0, [], [], 0, 0
                for f2, _, v2 in _fields(v):
                    if f2 == 1:
                        nid = (v2 >> 1) ^ -(v2 & 1)
                    elif f2 == 2:
                        ks = _small_uv(v2)
                    elif f2 == 3:
                        vs = _small_uv(v2)
                    elif f2 == 8:
                        la = (v2 >> 1) ^ -(v2 & 1)
                    elif f2 == 9:
                        lo = (v2 >> 1) ^ -(v2 & 1)
                la, lo = (lat_off + gran * la) * 1e-9, (lon_off + gran * lo) * 1e-9
                ids.append(np.array([nid], np.int64)); lats.append(np.array([la])); lons.append(np.array([lo]))
                if ks:
                    tnodes.append((nid, la, lo, tags_of(ks, vs)))
            elif fn == 3 and want_ways:                      # Way
                wid, ks, vs, refs = 0, [], [], None
                for f2, _, v2 in _fields(v):
                    if f2 == 1:
                        wid = v2
                    elif f2 == 2:
                        ks = _small_uv(v2)
                    elif f2 == 3:
                        vs = _small_uv(v2)
                    elif f2 == 8:
                        refs = v2
                if refs is None:
                    continue
                t = tags_of(ks, vs)
                if t and not any(kk in t for kk in KEEP):
                    continue                                 # sem tag = talvez membro de multipoligono
                ways.append((wid, t, _delta_zz(refs)))
            elif fn == 4 and want_ways:                      # Relation
                rid, ks, vs, roles, mem, typ = 0, [], [], [], None, []
                for f2, _, v2 in _fields(v):
                    if f2 == 1:
                        rid = v2
                    elif f2 == 2:
                        ks = _small_uv(v2)
                    elif f2 == 3:
                        vs = _small_uv(v2)
                    elif f2 == 8:
                        roles = _small_uv(v2)
                    elif f2 == 9:
                        mem = v2
                    elif f2 == 10:
                        typ = _small_uv(v2)
                t = tags_of(ks, vs)
                if t.get("type") not in ("multipolygon", "building") or mem is None:
                    continue
                mids = _delta_zz(mem).tolist()
                rels.append((rid, t, [(typ[j] if j < len(typ) else 1, mids[j], st[roles[j]] if j < len(roles) else "")
                                      for j in range(len(mids))]))
    return ids, lats, lons, tnodes, ways, rels


def _pbf_job(args):
    """worker (nivel de modulo, spawn-safe): decodifica uma lista de blobs do arquivo."""
    path, items, B = args
    ids, lats, lons, tnodes, ways, rels = [], [], [], [], [], []
    with open(path, "rb") as f:
        for off, sz in items:
            f.seek(off)
            a, b, c, d, e, r = _parse_block(_blob_data(f.read(sz)), B=B)
            ids += a; lats += b; lons += c; tnodes += d; ways += e; rels += r
    i, la, lo = _cat(ids, lats, lons)
    return i, la.astype(np.float64), lo, tnodes, ways, rels


def _read_pbf(path, progress=None, B=None, workers=None):
    bounds = None
    with open(path, "rb") as f:
        lst = list(_blobs(f))
        for typ, off, sz in lst:
            if typ == "OSMHeader":
                f.seek(off)
                bounds = _header_bbox(_blob_data(f.read(sz)))
    data = [(off, sz) for typ, off, sz in lst if typ == "OSMData"]
    nj = max(1, min(len(data), workers or max(1, (os.cpu_count() or 2) - 1), 8))
    nparts = min(len(data), nj * 4)
    jobs = [(path, data[k::nparts], B) for k in range(nparts)]     # intercalado: blocos de way se espalham
    res = []
    if nj == 1 or len(jobs) == 1:
        for n, j in enumerate(jobs):
            res.append(_pbf_job(j))
            if progress:
                progress((n + 1) / len(jobs), f"pbf: parte {n + 1}/{len(jobs)}")
    else:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(nj) as pool:
            for n, r in enumerate(pool.imap(_pbf_job, jobs)):
                res.append(r)
                if progress:
                    progress((n + 1) / len(jobs), f"pbf: parte {n + 1}/{len(jobs)} ({nj} processos)")
    ids, lats, lons, tnodes, ways, rels = [], [], [], [], [], []
    for a, b, c, d, e, r in res:
        ids.append(a); lats.append(b); lons.append(c); tnodes += d; ways += e; rels += r
    return _cat(ids, lats, lons), tnodes, ways, rels, bounds


def _cat(ids, lats, lons):
    if not ids:
        return np.zeros(0, np.int64), np.zeros(0), np.zeros(0)
    i, la, lo = np.concatenate(ids), np.concatenate(lats), np.concatenate(lons)
    if len(i) > 1 and np.any(np.diff(i) < 0):
        o = np.argsort(i, kind="stable")
        i, la, lo = i[o], la[o], lo[o]
    return i, la, lo


def _read_xml(path, progress=None):
    ids, lats, lons, tnodes, ways, rels = [], [], [], [], [], []
    bounds = None
    size = os.path.getsize(path) or 1
    cur = None
    f = open(path, "rb")
    try:
        for n, (ev, el) in enumerate(ET.iterparse(f, events=("start", "end"))):
            tg = el.tag
            if ev == "start":
                if tg in ("node", "way", "relation"):
                    cur = {"t": {}, "nd": [], "m": []}
                elif tg == "bounds":
                    a = el.attrib
                    try:
                        bounds = (float(a["minlat"]), float(a["minlon"]), float(a["maxlat"]), float(a["maxlon"]))
                    except (KeyError, ValueError):
                        pass
                continue
            a = el.attrib
            if tg == "tag" and cur is not None:
                cur["t"][a.get("k", "")] = a.get("v", "")
            elif tg == "nd" and cur is not None:
                cur["nd"].append(int(a["ref"]))
            elif tg == "member" and cur is not None:
                cur["m"].append(({"node": 0, "way": 1, "relation": 2}.get(a.get("type"), 2), int(a["ref"]),
                                 a.get("role", "")))
            elif tg == "node":
                if a.get("action") != "delete" and "lat" in a:
                    nid, la, lo = int(a["id"]), float(a["lat"]), float(a["lon"])
                    ids.append(nid); lats.append(la); lons.append(lo)
                    if cur["t"]:
                        tnodes.append((nid, la, lo, cur["t"]))
                cur = None
            elif tg == "way":
                t = cur["t"]
                if a.get("action") != "delete" and (not t or any(k in t for k in KEEP)):
                    ways.append((int(a["id"]), t, np.array(cur["nd"], np.int64)))
                cur = None
            elif tg == "relation":
                t = cur["t"]
                if a.get("action") != "delete" and t.get("type") in ("multipolygon", "building"):
                    rels.append((int(a["id"]), t, cur["m"]))
                cur = None
            if tg in ("node", "way", "relation"):
                el.clear()
            if progress and n % 200000 == 0:
                progress(f.tell() / size, "osm: lendo xml")
    finally:
        f.close()
    i = [np.array(ids, np.int64)] if ids else []
    return _cat(i, [np.array(lats)] if ids else [], [np.array(lons)] if ids else []), tnodes, ways, rels, bounds


# ---------------------------------------------------------------- montagem
def _is_area(t, closed):
    if not closed:
        return False
    if t.get("area") == "no":
        return False
    if t.get("area") == "yes" and not t.get("highway"):
        return True
    if t.get("highway") or t.get("barrier") or t.get("railway") or t.get("power"):
        return t.get("area") == "yes" and t.get("highway") in ("pedestrian", "footway", "platform") or \
            bool(t.get("area:highway"))
    if t.get("waterway"):
        return t.get("waterway") in ("riverbank", "dock", "boatyard")
    n = t.get("natural")
    if n:
        return n not in LINE_NATURAL
    return any(k in t for k in AREA_KEYS) or bool(t.get("building:part"))


def _join_rings(segs):
    """junta trechos de way (listas de ids) pelas pontas ate fechar aneis."""
    segs = [list(s) for s in segs if len(s) >= 2]
    rings = []
    while segs:
        cur = segs.pop()
        changed = True
        while cur[0] != cur[-1] and changed:
            changed = False
            for k, s in enumerate(segs):
                if s[0] == cur[-1]:
                    cur += s[1:]
                elif s[-1] == cur[-1]:
                    cur += s[-2::-1]
                elif s[-1] == cur[0]:
                    cur = s[:-1] + cur
                elif s[0] == cur[0]:
                    cur = s[:0:-1] + cur
                else:
                    continue
                segs.pop(k)
                changed = True
                break
        if len(cur) >= 4:
            rings.append(cur)
    return rings


def _box(bbox, margin_m):
    lat0, lon0, lat1, lon1 = min(bbox[0], bbox[2]), min(bbox[1], bbox[3]), max(bbox[0], bbox[2]), max(bbox[1], bbox[3])
    dla = margin_m / 110574.0
    dlo = margin_m / (111320.0 * max(0.05, np.cos(np.radians((lat0 + lat1) / 2))))
    return (lat0, lon0, lat1, lon1), (lat0 - dla, lon0 - dlo, lat1 + dla, lon1 + dlo)


def read(path, bbox=None, margin_m=800.0, progress=None, workers=None):
    """bbox = (lat0, lon0, lat1, lon1) ou None (tudo). progress(frac, msg) opcional."""
    pbf = str(path).lower().endswith(".pbf")
    if pbf:
        B0 = _box(bbox, margin_m)[1] if bbox else None
        (nid, nla, nlo), tnodes, ways, rels, bounds = _read_pbf(path, progress, B0, workers)
    else:
        (nid, nla, nlo), tnodes, ways, rels, bounds = _read_xml(path, progress)
    if bbox is None:
        bbox = bounds or ((float(nla.min()), float(nlo.min()), float(nla.max()), float(nlo.max()))
                          if len(nid) else (0, 0, 0, 0))
    (lat0, lon0, lat1, lon1), B = _box(bbox, margin_m)
    if progress:
        progress(0.9, "montando geometrias")

    def coords(refs):
        refs = np.asarray(refs, np.int64)
        if not len(nid):
            return None, None
        k = np.searchsorted(nid, refs)
        k[k >= len(nid)] = 0
        ok = nid[k] == refs
        return nla[k[ok]], nlo[k[ok]]

    def hit(la, lo):
        return la is not None and len(la) and la.max() >= B[0] and la.min() <= B[2] and \
            lo.max() >= B[1] and lo.min() <= B[3]

    wref = {wid: refs for wid, t, refs in ways}     # way com ou sem tag pode ser membro de multipoligono
    tw = [w for w in ways if w[1] and len(w[2])]
    if tw and len(nid):
        allr = np.concatenate([w[2] for w in tw])
        k = np.searchsorted(nid, allr)
        k[k >= len(nid)] = 0
        ok = nid[k] == allr
        la_ = np.where(ok, nla[k], np.nan)
        lo_ = np.where(ok, nlo[k], np.nan)
        st_ = np.concatenate([[0], np.cumsum([len(w[2]) for w in tw])[:-1]])
        inb = (la_ >= B[0]) & (la_ <= B[2]) & (lo_ >= B[1]) & (lo_ <= B[3])
        anyin = np.add.reduceat(inb.astype(np.int32), st_) > 0
        # way grande que envolve o bbox sem ter no dentro: testa a caixa dele
        laf, lof = np.nan_to_num(la_, nan=1e3), np.nan_to_num(lo_, nan=1e3)
        mnla, mnlo = np.minimum.reduceat(laf, st_), np.minimum.reduceat(lof, st_)
        laf, lof = np.nan_to_num(la_, nan=-1e3), np.nan_to_num(lo_, nan=-1e3)
        mxla, mxlo = np.maximum.reduceat(laf, st_), np.maximum.reduceat(lof, st_)
        boxin = (mxla >= B[0]) & (mnla <= B[2]) & (mxlo >= B[1]) & (mnlo <= B[3])
        tw = [w for w, a, b in zip(tw, anyin, boxin) if a or b]
    else:
        tw = []
    areas, lines = [], []
    for wid, t, refs in tw:
        la, lo = coords(refs)
        if not hit(la, lo):
            continue
        pts = list(zip(la.tolist(), lo.tolist()))
        closed = len(refs) >= 4 and refs[0] == refs[-1]
        if _is_area(t, closed):
            areas.append({"id": wid, "tags": t, "rings": [{"outer": pts, "inner": []}]})
        elif any(k in t for k in ("highway", "waterway", "railway", "barrier", "natural", "power", "man_made",
                                   "aeroway", "leisure", "landuse", "amenity")):
            lines.append({"id": wid, "tags": t, "pts": pts})
    for rid, t, mem in rels:
        outer = [wref[r] for ty, r, role in mem if ty == 1 and r in wref and role in ("outer", "")]
        inner = [wref[r] for ty, r, role in mem if ty == 1 and r in wref and role == "inner"]
        if not outer:
            continue
        tt = {k: v for k, v in t.items() if k != "type"}
        if not any(k in tt for k in KEEP):
            continue
        orings, irings = [], []
        for ring in _join_rings([o.tolist() for o in outer]):
            la, lo = coords(ring)
            if la is not None and len(la) >= 3:
                orings.append((la, lo))
        for ring in _join_rings([o.tolist() for o in inner]):
            la, lo = coords(ring)
            if la is not None and len(la) >= 3:
                irings.append((la, lo))
        if not any(hit(*o) for o in orings):
            continue
        rr = []
        for la, lo in orings:
            ins = [list(zip(a.tolist(), b.tolist())) for a, b in irings
                   if a.min() >= la.min() and a.max() <= la.max() and b.min() >= lo.min() and b.max() <= lo.max()]
            rr.append({"outer": list(zip(la.tolist(), lo.tolist())), "inner": ins})
        areas.append({"id": -rid, "tags": tt, "rings": rr})
    pois, trees = [], []
    for i, la, lo, t in tnodes:
        if not (B[0] <= la <= B[2] and B[1] <= lo <= B[3]):
            continue
        if t.get("natural") == "tree":
            trees.append((la, lo))
        elif any(k in t for k in POI_KEYS):
            pois.append({"id": i, "lat": la, "lon": lo, "tags": t})
    return {"areas": areas, "ways": lines, "pois": pois, "trees": trees, "bounds": bounds,
            "bbox": (lat0, lon0, lat1, lon1),
            "stats": {"nodes": int(len(nid)), "ways": len(ways), "relations": len(rels), "areas": len(areas),
                      "lines": len(lines), "pois": len(pois), "trees": len(trees)}}


# ---------------------------------------------------------------- leitura rapida (validate)
def scan(path):
    """formato, bounds, contagem de nos/ways sem montar nada. .pbf: descompacta cada bloco e conta direto no
    protobuf; .osm: conta as tags no texto. -> {"formato", "bounds", "nodes", "ways", "relations"}"""
    pbf = str(path).lower().endswith(".pbf")
    out = {"formato": "pbf" if pbf else "osm", "bounds": None, "nodes": 0, "ways": 0, "relations": 0}
    if pbf:
        ext = [1e9, 1e9, -1e9, -1e9]
        nd = 0
        samp = ([], [])
        with open(path, "rb") as f:
            for typ, off, sz in list(_blobs(f)):
                f.seek(off)
                data = _blob_data(f.read(sz))
                if typ == "OSMHeader":
                    out["bounds"] = _header_bbox(data)
                    continue
                gran, lat_off, lon_off = 100, 0, 0
                groups = []
                for fn, _, v in _fields(memoryview(data)):
                    if fn == 2:
                        groups.append(v)
                    elif fn == 17:
                        gran = v
                    elif fn == 19:
                        lat_off = (v >> 1) ^ -(v & 1)
                    elif fn == 20:
                        lon_off = (v >> 1) ^ -(v & 1)
                for v in groups:
                    for f2, _, v2 in _fields(v):
                        if f2 == 2:
                            nd += 1
                            for f3, _, v3 in _fields(v2):
                                if f3 == 1:
                                    out["nodes"] += int(np.count_nonzero(np.frombuffer(v3, np.uint8) < 128))
                                elif f3 in (8, 9):                     # min/max dos nos + amostra
                                    c = ((lat_off if f3 == 8 else lon_off) + gran * np.cumsum(_zz(_uvarints(v3)))) * 1e-9
                                    if len(c):
                                        k = 0 if f3 == 8 else 1
                                        ext[k] = min(ext[k], float(c.min()))
                                        ext[k + 2] = max(ext[k + 2], float(c.max()))
                                        samp[k].append(c[::50])
                        elif f2 == 1:
                            out["nodes"] += 1
                        elif f2 == 3:
                            out["ways"] += 1
                        elif f2 == 4:
                            out["relations"] += 1
        if ext[0] < 1e8:
            out["extent"] = tuple(ext)
        if samp[0] and len(samp[0]) == len(samp[1]):
            la, lo = np.concatenate(samp[0]), np.concatenate(samp[1])
            n = min(len(la), len(lo))
            out["preview"] = np.stack([la[:n], lo[:n]], 1)
        return out
    tail = b""
    ext, prev, pv = [1e9, 1e9, -1e9, -1e9], [], []
    keys = ((b"<node ", "nodes"), (b"<way ", "ways"), (b"<relation ", "relations"))
    with open(path, "rb") as f:
        head = f.read(4096)
        f.seek(0)
        while True:
            ch = f.read(1 << 22)
            if not ch:
                break
            buf = tail + ch
            for pat, k in keys:
                out[k] += buf.count(pat) - tail.count(pat)
            for m in _LL.finditer(ch):
                prev.append((float(m.group(1)), float(m.group(2))))
            if len(prev) > 200000:
                a = np.array(prev)
                ext = [min(ext[0], a[:, 0].min()), min(ext[1], a[:, 1].min()),
                       max(ext[2], a[:, 0].max()), max(ext[3], a[:, 1].max())]
                pv.append(a[::10]); prev = []
            tail = buf[-16:]
    if prev:
        a = np.array(prev)
        ext = [min(ext[0], a[:, 0].min()), min(ext[1], a[:, 1].min()),
               max(ext[2], a[:, 0].max()), max(ext[3], a[:, 1].max())]
        pv.append(a[::10])
    if ext[0] < 1e8:
        out["extent"] = tuple(float(v) for v in ext)
        out["preview"] = np.concatenate(pv)
    k = head.find(b"<bounds")
    if k >= 0:
        try:
            el = ET.fromstring(head[k:head.index(b">", k) + 1].rstrip(b"/>") + b"/>")
            a = el.attrib
            out["bounds"] = (float(a["minlat"]), float(a["minlon"]), float(a["maxlat"]), float(a["maxlon"]))
        except (ValueError, KeyError, ET.ParseError):
            pass
    if not out["formato"] == "osm" or not head.lstrip().startswith(b"<"):
        out["formato"] = "desconhecido"
    return out
