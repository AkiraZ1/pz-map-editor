"""Rotinas nativas do spgen, so em Rust e pre-compiladas (fonte: genfast_rs/ e genfast_py/, copia de
saopaulo/scripts). Binarios por plataforma em bin/<alvo>/ (alvo = mac-arm64 | mac-x64 | win-x64):
  _genfast_rs.so|.dll   ABI C via ctypes (C): max_rect, rectify_one, ground_z0, ring_stats, bld_geom
  _gfpy.so|.pyd         modulo PyO3 abi3 (GP): Cell, Groups, furnish, isl_mask, to_rects, bi_groups...
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
