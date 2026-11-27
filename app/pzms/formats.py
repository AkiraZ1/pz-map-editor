"""Formatos binarios do Project Zomboid B42: PZPK (texturepacks), LOTH (lotheader), LOTP (lotpack), chunkdata.

Celula = 256x256 quadrados, 32x32 chunks de 8x8. lotpack: "LOTP", versao 1, 1024 offsets int64,
cada chunk em ordem z, x, y; quadrado vazio = (-1, skip), senao (n+1, -1, n indices de tile).
"""
import struct

CS = 256          # quadrados por celula
CH = 8            # quadrados por chunk
NCH = CS // CH    # chunks por lado (32)


# ---------------------------------------------------------------- PZPK
def parse_pack(path):
    """gera (pagina, alpha, sprites, png_bytes) de um .pack PZPK v1."""
    with open(path, "rb") as f:
        data = f.read()
    pos = 0

    def take(n):
        nonlocal pos
        if n < 0 or pos + n > len(data):
            raise ValueError(f"pack truncado em {pos}")
        r = data[pos:pos + n]; pos += n
        return r

    def i32():
        return struct.unpack("<i", take(4))[0]

    def s():
        return take(i32()).decode("utf-8", "replace")

    if take(4) != b"PZPK" or i32() != 1:
        raise ValueError("nao e PZPK v1: " + str(path))
    for _ in range(i32()):
        page, count, alpha = s(), i32(), i32()
        sprites = []
        for __ in range(count):
            name = s()
            x, y, w, h, ox, oy, cw, ch = struct.unpack("<8i", take(32))
            sprites.append((name, x, y, w, h, ox, oy, cw, ch))
        png = take(i32())
        yield page, alpha, sprites, png


# ---------------------------------------------------------------- LOTH
class Header:
    """lotheader de uma celula."""

    def __init__(self):
        self.version = 1
        self.tiles = []          # nomes de tile (indice = posicao)
        self.w = self.h = 8
        self.zmin = 0
        self.zmax = 0
        self.rooms = []          # [name, z, [(x,y,w,h) locais da celula], [(type,x,y) objetos]]
        self.buildings = []      # [[indices de room]]
        self.density = bytes(1024)


def read_header(data):
    if data[:4] != b"LOTH":
        raise ValueError("nao e LOTH")
    h = Header()
    h.version, n = struct.unpack_from("<ii", data, 4)
    p = 12
    for _ in range(n):
        e = data.index(b"\n", p); h.tiles.append(data[p:e].decode("latin1")); p = e + 1
    h.w, h.h, h.zmin, h.zmax, nr = struct.unpack_from("<5i", data, p); p += 20
    for _ in range(nr):
        e = data.index(b"\n", p); name = data[p:e].decode("latin1"); p = e + 1
        z, nrect = struct.unpack_from("<ii", data, p); p += 8
        rects = [struct.unpack_from("<4i", data, p + 16 * i) for i in range(nrect)]; p += 16 * nrect
        no, = struct.unpack_from("<i", data, p); p += 4
        objs = [struct.unpack_from("<3i", data, p + 12 * i) for i in range(no)]; p += 12 * no
        h.rooms.append([name, z, rects, objs])
    nb, = struct.unpack_from("<i", data, p); p += 4
    for _ in range(nb):
        k, = struct.unpack_from("<i", data, p); p += 4
        h.buildings.append(list(struct.unpack_from(f"<{k}i", data, p))); p += 4 * k
    h.density = bytes(data[p:p + 1024]); p += 1024
    if p != len(data):
        raise ValueError(f"lotheader com {len(data) - p} bytes sobrando")
    return h


def write_header(h):
    b = bytearray(b"LOTH") + struct.pack("<ii", 1, len(h.tiles))
    for n in h.tiles:
        b += n.encode("latin1") + b"\n"
    b += struct.pack("<5i", 8, 8, h.zmin, h.zmax, len(h.rooms))
    for name, z, rects, objs in h.rooms:
        b += name.encode("latin1") + b"\n" + struct.pack("<ii", z, len(rects))
        for r in rects:
            b += struct.pack("<4i", *r)
        b += struct.pack("<i", len(objs))
        for o in objs:
            b += struct.pack("<3i", *o)
    b += struct.pack("<i", len(h.buildings))
    for lst in h.buildings:
        b += struct.pack("<i", len(lst)) + struct.pack(f"<{len(lst)}i", *lst)
    d = bytes(h.density)[:1024]
    b += d + bytes(1024 - len(d))
    return bytes(b)


# ---------------------------------------------------------------- LOTP
def read_pack(data, zmin, zmax, names=None, chunks=None):
    """quadrados da celula: {(x, y, z) local: [indices ou nomes]}. chunks = conjunto de indices de chunk (opcional)."""
    if data[:4] != b"LOTP":
        raise ValueError("nao e LOTP")
    offs = struct.unpack_from("<1024q", data, 12)
    out = {}
    unpack = struct.unpack_from
    for ci in (range(1024) if chunks is None else sorted(chunks)):
        ccx, ccy = divmod(ci, NCH)
        p = offs[ci]; skip = 0
        for z in range(zmin, zmax + 1):
            for x in range(8):
                for y in range(8):
                    if skip:
                        skip -= 1; continue
                    a, b = unpack("<ii", data, p)
                    if a == -1:
                        skip = b - 1; p += 8; continue
                    t = unpack(f"<{a - 1}i", data, p + 8); p += 8 + 4 * (a - 1)
                    out[(ccx * 8 + x, ccy * 8 + y, z)] = [names[i] for i in t] if names else list(t)
    return out


def write_pack(sq, zmin, zmax):
    """sq = {(x, y, z) local: [indices]} -> bytes do lotpack."""
    body = bytearray(); offs = []
    base = 12 + 8 * 1024
    pk = struct.pack
    for ci in range(1024):
        ccx, ccy = divmod(ci, NCH)
        offs.append(base + len(body))
        skip = 0
        for z in range(zmin, zmax + 1):
            for x in range(8):
                for y in range(8):
                    t = sq.get((ccx * 8 + x, ccy * 8 + y, z))
                    if not t:
                        skip += 1; continue
                    if skip:
                        body += pk("<ii", -1, skip); skip = 0
                    body += pk("<ii", len(t) + 1, -1) + pk(f"<{len(t)}i", *t)
        if skip:
            body += pk("<ii", -1, skip)
    return bytes(b"LOTP" + pk("<ii", 1, 1024) + pk("<1024q", *offs) + body)


def chunkdata_blank():
    """chunkdata_X_Y.bin padrao (sem dados de chunk)."""
    return b"\x00\x01" + bytes(1024)


def read_cell_files(hdr_path, pack_path, names=True):
    with open(hdr_path, "rb") as f:
        h = read_header(f.read())
    with open(pack_path, "rb") as f:
        sq = read_pack(f.read(), h.zmin, h.zmax, h.tiles if names else None)
    return h, sq
