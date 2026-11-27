"""Renderizador iso em PIL (miniaturas de predios e previas), usando o atlas reduzido do cache.

Escala 1/4 dos sprites 2x: losango 32x16, andar 48 px.  Quadrado (x, y, z) -> canto do canvas 32x64:
  px = (x - y) * 16 - 16,  py = (x + y) * 8 - z * 48 - 48
"""
from PIL import Image

D, HH, FL = 16, 8, 48


def bounds(xs, ys, zmax):
    """caixa em pixels de um retangulo de quadrados [x0,x1) x [y0,y1), andares 0..zmax."""
    x0, x1 = xs
    y0, y1 = ys
    left = (x0 - (y1 - 1)) * D - D
    right = ((x1 - 1) - y0) * D + D
    top = (x0 + y0) * HH - zmax * FL - FL - 16
    bottom = ((x1 - 1) + (y1 - 1)) * HH + 2 * HH + 8
    return left, top, right, bottom


def render(assets, squares, bg=(0, 0, 0, 0), maxz=None, fit=None):
    """squares: {(x, y, z): [nomes]}.  Devolve imagem RGBA recortada ao conteudo (ou redimensionada para fit)."""
    if not squares:
        return Image.new("RGBA", (8, 8), bg)
    keys = [k for k in squares if maxz is None or k[2] <= maxz]
    xs = [k[0] for k in keys]; ys = [k[1] for k in keys]; zs = [k[2] for k in keys]
    l, t, r, b = bounds((min(xs), max(xs) + 1), (min(ys), max(ys) + 1), max(zs))
    t -= 64                                   # objetos altos (arvores)
    im = Image.new("RGBA", (r - l, b - t), bg)
    for (x, y, z) in sorted(keys, key=lambda k: (k[2], k[0] + k[1], k[0])):
        px = (x - y) * D - D - l
        py = (x + y) * HH - z * FL - FL - t
        for n in squares[(x, y, z)]:
            s = assets.sprite(n) if isinstance(n, str) else None
            if not s:
                continue
            spr, dx, dy = s
            im.alpha_composite(spr, (px + dx, py + dy)) if px + dx >= 0 and py + dy >= 0 else im.paste(spr, (px + dx, py + dy), spr)
    bb = im.getchannel("A").getbbox()
    if bb:
        im = im.crop(bb)
    if fit:
        im.thumbnail(fit, Image.LANCZOS)
    return im
