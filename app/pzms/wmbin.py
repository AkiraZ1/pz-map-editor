#!/usr/bin/env python3
"""worldmap.xml.bin (formato IGMB v2 do B42, lido por zombie.worldMap.WorldMapBinary).

O jogo carrega <arquivo>.xml.bin no lugar do .xml quando ele existe; o XML vira DOM inteiro na
memoria, e com dezenas de MB o mapa nao aparece. Layout (little-endian):
  'IGMB' int versao=2, int cellSize=256, int largura, int altura (em celulas)
  int nStrings, [short len, bytes utf-8]...
  largura*altura registros (y externo, x interno): int x (-1 = vazio) | int x, int y, int nFeatures,
    feature: short tipo(idx str), byte nAneis, [short nPts, (short x, short y)*nPts]...,
             byte nProps, [short chave(idx), short valor(idx)]...
Uso: python3 -E scripts/wmbin.py <worldmap.xml> [saida.bin] | --dump <arquivo.bin>
"""
import re
import struct
import sys


def write(cells, out):
    """cells: {(cx, cy): [(tipo, [anel[(x, y)...]...], [(k, v)...])...]}"""
    strs, idx = [], {}

    def si(s):
        if s not in idx:
            idx[s] = len(strs); strs.append(s)
        return idx[s]
    for fs in cells.values():
        for t, rings, props in fs:
            si(t)
            for k, v in props:
                si(k); si(v)
    xs = [c[0] for c in cells]; ys = [c[1] for c in cells]
    x0, y0 = min(xs), min(ys)
    w, h = max(xs) - x0 + 1, max(ys) - y0 + 1
    b = bytearray(b"IGMB")
    b += struct.pack("<iiii", 2, 256, w, h)
    b += struct.pack("<i", len(strs))
    for s in strs:
        e = s.encode("utf-8"); b += struct.pack("<h", len(e)) + e
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            fs = cells.get((x, y))
            if not fs:
                b += struct.pack("<i", -1); continue
            b += struct.pack("<iii", x, y, len(fs))
            for t, rings, props in fs:
                rings = rings[:255]
                b += struct.pack("<hB", si(t), len(rings))
                for r in rings:
                    b += struct.pack("<h", len(r))
                    b += struct.pack("<%dh" % (2 * len(r)), *[v for p in r for v in p])
                b += struct.pack("<B", len(props))
                for k, v in props:
                    b += struct.pack("<hh", si(k), si(v))
    open(out, "wb").write(b)
    return w, h, len(strs)


def read(path):
    d = open(path, "rb").read(); o = 0

    def u(fmt):
        nonlocal o
        v = struct.unpack_from("<" + fmt, d, o); o += struct.calcsize("<" + fmt); return v
    assert d[:4] == b"IGMB", "magic"; o = 4
    ver, cs, w, h = u("iiii")
    n, = u("i"); strs = []
    for _ in range(n):
        ln, = u("h"); strs.append(d[o:o + ln].decode("utf-8")); o += ln
    cells = {}
    for _ in range(w * h):
        x, = u("i")
        if x == -1:
            continue
        y, nf = u("ii"); fs = []
        for _ in range(nf):
            t, nr = u("hB"); rings = []
            for _ in range(nr):
                npt, = u("h"); v = u("%dh" % (2 * npt)); rings.append(list(zip(v[::2], v[1::2])))
            np_, = u("B"); props = [tuple(strs[i] for i in u("hh")) for _ in range(np_)]
            fs.append((strs[t], rings, props))
        cells[(x, y)] = fs
    assert o == len(d), f"sobrou {len(d) - o} bytes"
    return dict(ver=ver, cs=cs, w=w, h=h, strs=strs, cells=cells)


PT = re.compile(r'<point x="(-?\d+)" y="(-?\d+)"/>')


def from_xml(path):
    cells, cur = {}, None
    txt = open(path, encoding="utf-8").read()
    for m in re.finditer(r'<cell x="(\d+)" y="(\d+)">(.*?)</cell>', txt, re.S):
        fs = []
        for f in re.finditer(r'<feature>(.*?)</feature>', m.group(3), re.S):
            g = f.group(1)
            t = re.search(r'<geometry type="(\w+)"', g).group(1)
            rings = [[(int(a), int(b)) for a, b in PT.findall(c)] for c in re.findall(r'<coordinates>(.*?)</coordinates>', g, re.S)]
            props = re.findall(r'<property name="([^"]*)" value="([^"]*)"/>', g)
            fs.append((t, rings, props))
        if fs:
            cells[(int(m.group(1)), int(m.group(2)))] = fs
    return cells


if __name__ == "__main__":
    if sys.argv[1] == "--dump":
        r = read(sys.argv[2])
        nf = sum(len(v) for v in r["cells"].values())
        print(f"v{r['ver']} cell {r['cs']} {r['w']}x{r['h']} strs {r['strs']} cells {len(r['cells'])} features {nf}")
        k = min(r["cells"]); print(k, r["cells"][k][0][0], r["cells"][k][0][2], r["cells"][k][0][1][0][:4])
    else:
        src = sys.argv[1]; out = sys.argv[2] if len(sys.argv) > 2 else src + ".bin"
        c = from_xml(src); print(write(c, out), len(c), "celulas ->", out)
