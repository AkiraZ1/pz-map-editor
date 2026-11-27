"""scipy.ndimage quando instalado; senao as 3 rotinas que o gen.py usa, em numpy, com o mesmo resultado
(o editor nao leva scipy no instalador)."""
try:
    from scipy import ndimage  # noqa: F401
except ImportError:
    import types

    import numpy as np

    def find_objects(a, max_label=0):
        """caixa (slice y, slice x) de cada rotulo 1..max_label (None se ausente); a 2D inteiro."""
        a = np.asarray(a)
        n = int(max_label) if max_label else int(a.max(initial=0))
        out = [None] * n
        if n <= 0:
            return out
        ys, xs = np.nonzero((a > 0) & (a <= n))
        lab = a[ys, xs].astype(np.int64)
        ymin = np.full(n + 1, np.iinfo(np.int64).max); ymax = np.full(n + 1, -1)
        xmin = ymin.copy(); xmax = ymax.copy()
        np.minimum.at(ymin, lab, ys); np.maximum.at(ymax, lab, ys)
        np.minimum.at(xmin, lab, xs); np.maximum.at(xmax, lab, xs)
        for i in np.nonzero(ymax[1:] >= 0)[0].tolist():
            out[i] = (slice(int(ymin[i + 1]), int(ymax[i + 1]) + 1), slice(int(xmin[i + 1]), int(xmax[i + 1]) + 1))
        return out

    def _shifts(st):
        st = np.asarray(st, bool)
        cy, cx = st.shape[0] // 2, st.shape[1] // 2
        return [(dy - cy, dx - cx) for dy, dx in zip(*np.nonzero(st))]

    def _shift(m, dy, dx, fill):
        """r[y, x] = m[y + dy, x + dx] (fora = fill)."""
        h, w = m.shape
        r = np.full(m.shape, fill, bool)
        ya, yb, xa, xb = max(0, -dy), min(h, h - dy), max(0, -dx), min(w, w - dx)
        if ya < yb and xa < xb:
            r[ya:yb, xa:xb] = m[ya + dy:yb + dy, xa + dx:xb + dx]
        return r

    def binary_erosion(m, structure=None, border_value=0):
        m = np.asarray(m, bool)
        st = np.ones((3, 3), bool) if structure is None else structure
        r = np.ones(m.shape, bool)
        for dy, dx in _shifts(st):
            r &= _shift(m, dy, dx, bool(border_value))
        return r

    def binary_dilation(m, structure=None, iterations=1):
        m = np.asarray(m, bool)
        st = np.asarray(np.ones((3, 3), bool) if structure is None else structure, bool)[::-1, ::-1]   # refletida
        for _ in range(iterations):
            r = np.zeros(m.shape, bool)
            for dy, dx in _shifts(st):
                r |= _shift(m, dy, dx, False)
            m = r
        return m

    ndimage = types.SimpleNamespace(find_objects=find_objects, binary_erosion=binary_erosion,
                                    binary_dilation=binary_dilation)
