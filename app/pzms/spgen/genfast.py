"""Rotinas nativas do spgen, so em Rust e pre-compiladas (fonte: genfast_rs/ e genfast_py/, copia de
saopaulo/scripts). Binarios por plataforma em bin/<alvo>/ (alvo = mac-arm64 | mac-x64 | win-x64):
  _genfast_rs.so|.dll   ABI C via ctypes (C): max_rect, poly_area, rectify_one, ground_z0, ring_stats,
                        bld_geom, plan_extras, smooth_ground, sidewalk, drop_small
  _gfpy.so|.pyd         modulo PyO3 abi3 (GP): Cell, Groups, furnish, isl_mask, to_rects, bi_groups,
                        poi_* / kiosk_spot / muro_lote / zone_mask (poi.rs)...
Recompilar: python tools/build_rust.py (precisa de cargo; ver o docstring de la)."""
import ctypes
import importlib.util
import os
import platform
import sys

import numpy as np

_D = os.path.dirname(os.path.abspath(__file__))


def target():
    m = platform.machine().lower()
    if sys.platform == "darwin":
        return "mac-arm64" if m in ("arm64", "aarch64") else "mac-x64"
    if os.name == "nt":
        return "win-x64"
    return f"{sys.platform}-{m}"


BIN = os.path.join(_D, "bin", target())
_WIN = os.name == "nt"
RSLIB = os.path.join(BIN, "_genfast_rs" + (".dll" if _WIN else ".so"))
PYLIB = os.path.join(BIN, "_gfpy" + (".pyd" if _WIN else ".so"))


def _need(p):
    if not os.path.exists(p):
        raise ImportError(f"spgen: falta o binario Rust {os.path.relpath(p, _D)} para {target()} "
                          f"(gere com tools/build_rust.py)")
    return p


def _load_c():
    c = ctypes.CDLL(_need(RSLIB))
    P = ctypes.c_void_p
    c.max_rect.argtypes = [P, ctypes.c_int, ctypes.c_int, P]
    c.rectify_one.argtypes = [P, ctypes.c_int64, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int32]
    c.rectify_one.restype = None
    c.ground_z0.argtypes = [ctypes.c_int, P, P, P, P, P, P, ctypes.c_int64, ctypes.c_int64, ctypes.c_int, P, P]
    c.ring_stats.argtypes = [P, P, ctypes.c_int, P]
    c.ring_stats.restype = None
    c.bld_geom.argtypes = [P, P, P, ctypes.c_int, P, P]
    c.bld_geom.restype = None
    c.poly_area.argtypes = [P, ctypes.c_int]
    c.poly_area.restype = ctypes.c_double
    c.plan_extras.argtypes = [ctypes.c_int, ctypes.c_int, P, P, P, P, P, ctypes.c_int, ctypes.c_int, P, P, P, P]
    c.plan_extras.restype = None
    c.smooth_ground.argtypes = [ctypes.c_int, ctypes.c_int, P, P, P, P]
    c.smooth_ground.restype = None
    c.sidewalk.argtypes = [ctypes.c_int, ctypes.c_int, P, ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint8]
    c.sidewalk.restype = None
    c.drop_small.argtypes = [ctypes.c_int, ctypes.c_int, P, ctypes.c_int, ctypes.c_int]
    c.drop_small.restype = None
    return c


def _load_py():
    spec = importlib.util.spec_from_file_location("_gfpy", _need(PYLIB))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


C = _load_c()
GP = _load_py()
KIND = "rust"
_p = lambda a: a.ctypes.data
WL = tuple(tuple(d for d, m in (("N", 1), ("W", 2), ("S", 4), ("E", 8)) if b & m) for b in range(16))


def ground_z0(Bw, fl, g, gw, tr, hh, wx0, wy0, ntree):
    """chao z0: (o1, o2) int16 (cs x cs), codigos da tabela do gen.py (_GT); o2 = -1 sem segundo tile."""
    cs = g.shape[0]
    Bw, fl = np.ascontiguousarray(Bw, np.int32), np.ascontiguousarray(fl, np.int32)
    g, gw = np.ascontiguousarray(g, np.uint8), np.ascontiguousarray(gw, np.uint8)
    tr, hh = np.ascontiguousarray(tr, np.uint8), np.ascontiguousarray(hh, np.uint32)
    o1, o2 = np.empty((cs, cs), np.int16), np.empty((cs, cs), np.int16)
    C.ground_z0(cs, _p(Bw), _p(fl), _p(g), _p(gw), _p(tr), _p(hh), wx0, wy0, ntree, _p(o1), _p(o2))
    return o1, o2


def ring_stats(xy, offs):
    """(area, cx, cy) por anel; xy float64 (N, 2) concatenado, offs int64 (k+1)."""
    xy = np.ascontiguousarray(xy, np.float64); offs = np.ascontiguousarray(offs, np.int64)
    out = np.zeros((len(offs) - 1, 3))
    C.ring_stats(_p(xy), _p(offs), len(offs) - 1, _p(out))
    return out


def bld_geom(xy, offs, nop):
    """snap_poly + perimetro + area + centro de cada predio (ver lib.rs): (xy girado, out (k, 5))."""
    xy = np.ascontiguousarray(xy, np.float64); offs = np.ascontiguousarray(offs, np.int64)
    nop = np.ascontiguousarray(nop, np.int32)
    oxy = np.empty_like(xy); out = np.zeros((len(offs) - 1, 5))
    C.bld_geom(_p(xy), _p(offs), _p(nop), len(offs) - 1, _p(oxy), _p(out))
    return oxy, out


def max_rect(m):
    m = np.ascontiguousarray(m, np.uint8)
    out = np.zeros(4, np.int32)
    if not C.max_rect(_p(m), m.shape[0], m.shape[1], _p(out)):
        return None
    return tuple(int(v) for v in out)


def poly_area(pts):
    a = np.ascontiguousarray(pts, np.float64)
    return C.poly_area(_p(a), len(a))


def plan_extras(Ba, Lv, Ga, apt, okb, gwater, walk_lut):
    """varandas + escada de servico (gen.plan_extras): (BAL u8, BC bool, [(b, x, y, lado 'W'|'N')] na ordem do dict)."""
    H, W = Ba.shape
    Ba = np.ascontiguousarray(Ba, np.int32)
    Lv, Ga = np.ascontiguousarray(Lv, np.uint8), np.ascontiguousarray(Ga, np.uint8)
    apt, okb = np.ascontiguousarray(apt, np.uint8), np.ascontiguousarray(okb, np.uint8)
    lut = np.ascontiguousarray(walk_lut, np.uint8)
    BAL, BC = np.zeros((H, W), np.uint8), np.zeros((H, W), np.uint8)
    nb = len(apt)
    lad = np.empty(nb * 5, np.int64)
    C.plan_extras(H, W, _p(Ba), _p(Lv), _p(Ga), _p(apt), _p(okb), nb, int(gwater), _p(lut), _p(BAL), _p(BC), _p(lad))
    lad = lad.reshape(nb, 5)
    bs = np.nonzero(lad[:, 0] >= 0)[0]
    bs = bs[np.argsort(lad[bs, 4], kind="stable")]
    return BAL, BC.view(bool), [(int(b), int(lad[b, 1]), int(lad[b, 2]), "WN"[lad[b, 3]]) for b in bs]


def smooth_ground(Ga, Ba, keep, grp):
    """gen.smooth_ground nativo: devolve um Ga novo (uint8)."""
    out = np.array(Ga, np.uint8, order="C", copy=True)
    Ba = np.ascontiguousarray(Ba, np.int32)
    keep = np.ascontiguousarray(keep, np.uint8)
    grp = np.ascontiguousarray(grp, np.uint8)
    C.smooth_ground(out.shape[0], out.shape[1], _p(out), _p(Ba), _p(keep), _p(grp))
    return out


def sidewalk(Ga, asph, pave, water, side):
    """anel de calcada (r2 <= 10, wrap) no lugar: Ga uint8 contiguo."""
    assert Ga.dtype == np.uint8 and Ga.flags.c_contiguous
    C.sidewalk(Ga.shape[0], Ga.shape[1], _p(Ga), asph, pave, water, side)


def drop_small(Ba, nb, masp):
    """zera predios com < 16 quadrados ou bbox com lado < 3 (masp fica), no lugar: Ba int32 contiguo."""
    assert Ba.dtype == np.int32 and Ba.flags.c_contiguous
    C.drop_small(Ba.shape[0], Ba.shape[1], _p(Ba), nb, masp or -1)
