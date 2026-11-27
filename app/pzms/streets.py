"""Ferramenta Ruas: ruas e avenidas como polilinhas editaveis (pontos arrastaveis), rasterizadas no chao z0.

Cada rua fica em project.meta["streets"]["items"]: {id, name, pts: [[x, y], ...] (cantos de quadrado),
width (asfalto, em quadrados), side (calcada de cada lado), asph/walk (familia do blends_street_01 ou tile),
smooth (curva suave), curbs (meio-fio), lines (faixa central)}.
O que havia no chao antes da rua fica em meta["streets"]["base"]["x,y"]; tirar/mover a rua devolve isso.
Mesmas regras do gerador do mapa SP (spgen/gen.py), para nao serrilhar:
  - asfalto/calcada = familia f do blends_street_01: base f, canto f+1..4 (NW, SE, SW, NE), borda f+8..11
  - na diagonal, a calcada com asfalto em 2 lados vizinhos recebe o CANTO do asfalto (so de um lado da divisa)
  - meio-fio no quadrado de ASFALTO da borda (street_curbs_01_8 N, 9 W, 10 S, 11 E = lado da calcada)
  - grama de fora (blends_natural_01) invade a calcada com overlay de canto/borda
Cada edicao e um comando so de desfazer (quadrados + meta).
"""
import json
import math

from . import formats as F

CS = F.CS
FAMS = (0, 16, 32, 48, 64, 80, 96)
BLEND_IDX = {frozenset("NW"): 1, frozenset("SE"): 2, frozenset("SW"): 3, frozenset("NE"): 4}
BLEND_EDGE = {"N": (8, 12), "W": (9, 13), "E": (10, 14), "S": (11, 15)}
# meio-fio como no vanilla (Muldraugh): o sprite fica na borda S/E do proprio quadrado, entao
# borda de cima/esquerda do asfalto vai no quadrado da CALCADA (8 asfalto ao S, 9 asfalto a E) e
# borda de baixo/direita no do ASFALTO (10 calcada ao S, 11 calcada a E)
CURB_WALK = {"S": "street_curbs_01_8", "E": "street_curbs_01_9"}
CURB_ASPH = {"S": "street_curbs_01_10", "E": "street_curbs_01_11"}
# faixas (street_trafficlines_01, medido nos sprites): cada tile pinta borda(s) do proprio quadrado.
# base+0 W, +2 N, +4 E, +6 S; cantos +1 NW, +3 NE, +5 SE, +7 SW. Cores: base 0 cinza, 8 branca,
# 16 amarela gasta, 24 amarela. Assim a faixa segue curvas e diagonais em escada sem buracos.
LINE_EDGE = {"W": 0, "N": 2, "E": 4, "S": 6}
LINE_CORNER = {frozenset("NW"): 1, frozenset("NE"): 3, frozenset("SE"): 5, frozenset("SW"): 7}
LINE_COLORS = (0, 8, 16, 24)
# variacoes do piso: familias 0 e 16 so tem base+5 (base+6/+7 nao existem e saem pretas no mapa)
FAM_VARS = {0: (5,), 16: (5,)}
POLE = "lighting_outdoor_01_16"
DEF = {"name": "rua", "width": 6, "walk_on": True, "side": 2, "asph": 80, "walk": 48, "smooth": True, "curbs": True,
       "lanes": 1, "dash": 3, "line_color": 16, "poles": False, "pole_every": 12, "pole": POLE}
MAX_AREA = 40_000_000
NB = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}


def h32(*a):
    x = 2166136261
    for v in a:
        x = ((x ^ (int(v) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    return x


def get(project):
    st = project.meta.get("streets") or {}
    items = []
    for it in st.get("items") or []:
        try:
            items.append(norm(it))                     # ruas de versoes antigas ganham os campos novos
        except (ValueError, TypeError):
            items.append(it)
    return {"items": items, "base": dict(st.get("base") or {})}


def norm(it, old=None):
    """valida/limpa uma rua vinda do cliente."""
    o = dict(DEF)
    o.update(old or {})
    leg = {**(old or {}), **(it or {})}
    if "lines" in leg and "lanes" not in leg:
        o["lanes"] = 2 if leg["lines"] else 1                 # ruas da 0.2 (faixa central liga/desliga)
    o.pop("lines", None)
    o.update({k: v for k, v in (it or {}).items() if k in DEF or k in ("id", "pts")})
    pts = [[int(round(float(p[0]))), int(round(float(p[1])))] for p in o.get("pts") or []]
    pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    if len(pts) < 2:
        raise ValueError("a rua precisa de pelo menos 2 pontos")
    o["pts"] = pts
    o["width"] = max(1, min(40, int(o["width"])))
    o["side"] = max(0, min(10, int(o["side"])))
    o["lanes"] = max(1, min(8, int(o["lanes"])))
    o["dash"] = max(0, min(20, int(o["dash"])))
    o["pole_every"] = max(3, min(80, int(o["pole_every"])))
    o["pole"] = str(o.get("pole") or POLE)[:120]
    o["line_color"] = int(o.get("line_color", 16)) if int(o.get("line_color", 16)) in LINE_COLORS else 16
    for k in ("asph", "walk"):
        v = o[k]
        if isinstance(v, str) and not v.isdigit():
            o[k] = v[:120]
        else:
            v = int(v)
            o[k] = v if v in FAMS else DEF[k]
    for k in ("smooth", "curbs", "walk_on", "poles"):
        o[k] = bool(o[k])
    o["name"] = str(o.get("name") or "rua")[:60]
    o["id"] = str(o.get("id") or "")[:40]
    return o


def path(it):
    """pontos (float, ja com meio quadrado de ajuste p/ largura impar) e suavizados se smooth."""
    off = 0.5 if it["width"] % 2 else 0.0
    P = [(x + off, y + off) for x, y in it["pts"]]
    if it.get("smooth") and len(P) > 2:
        for _ in range(3):                                   # Chaikin: curva passa perto dos pontos
            Q = [P[0]]
            for (ax, ay), (bx, by) in zip(P, P[1:]):
                Q += [(0.75 * ax + 0.25 * bx, 0.75 * ay + 0.25 * by), (0.25 * ax + 0.75 * bx, 0.25 * ay + 0.75 * by)]
            Q.append(P[-1])
            P = Q
    return P


def side_of(it):
    return it["side"] if it.get("walk_on", True) else 0


def _snap_ends(it, P, items):
    """ponta da rua que cai dentro de outra rua (asfalto ou calcada) vai ate o eixo dela, ao longo da propria
    direcao: o asfalto atravessa a calcada da outra e vira um T/cruzamento limpo (parava na calcada, serrilhado)."""
    if len(P) < 2 or not items:
        return P
    P = list(P)
    for e, nb in ((0, 1), (len(P) - 1, len(P) - 2)):
        ex, ey = P[e]
        ux, uy = ex - P[nb][0], ey - P[nb][1]
        lu = math.hypot(ux, uy)
        if lu < 1e-9:
            continue
        ux, uy = ux / lu, uy / lu
        best = None
        for o in items:
            if o is it or o.get("id") == it.get("id"):
                continue
            Ro = o["width"] / 2 + side_of(o)
            Q = path(o)
            for (ax, ay), (bx, by) in zip(Q, Q[1:]):
                dx, dy = bx - ax, by - ay
                L2 = dx * dx + dy * dy
                if L2 < 1e-9:
                    continue
                t = max(0.0, min(1.0, ((ex - ax) * dx + (ey - ay) * dy) / L2))
                d = math.hypot(ex - ax - t * dx, ey - ay - t * dy)
                if d > Ro + 1:
                    continue
                L = math.sqrt(L2)
                nx, ny = -dy / L, dx / L                     # normal do eixo da outra rua
                un = ux * nx + uy * ny
                if abs(un) < 0.35:                           # quase paralela: nao e emenda
                    continue
                sd = ((ax - ex) * nx + (ay - ey) * ny) / un  # quanto andar na direcao da rua ate o eixo
                if abs(sd) <= Ro + 1.5 and (best is None or d < best[0]):
                    best = (d, sd)
        if best:
            P[e] = (ex + ux * best[1], ey + uy * best[1])
    return P


def _raster(it, items=None):
    """{(x, y): (dist, axis, lado, ao_longo)} dos quadrados ate width/2+calcada da linha.
    axis = 'x'/'y' no trecho reto ou None; lado = distancia com sinal (+ a esquerda de quem anda na rua);
    ao_longo = metros desde o 1o ponto (para tracejado e postes). Ponta da rua reta (corte perpendicular), e
    emendada no eixo de outra rua quando cai dentro dela (items = todas as ruas)."""
    import numpy as np
    P = _snap_ends(it, path(it), items)
    R = it["width"] / 2 + side_of(it)
    out = {}
    run = 0.0
    last = len(P) - 2
    for si, ((ax, ay), (bx, by)) in enumerate(zip(P, P[1:])):
        x0, x1 = int(math.floor(min(ax, bx) - R)) - 1, int(math.ceil(max(ax, bx) + R)) + 1
        y0, y1 = int(math.floor(min(ay, by) - R)) - 1, int(math.ceil(max(ay, by) + R)) + 1
        if (x1 - x0) * (y1 - y0) > MAX_AREA:
            raise ValueError("rua grande demais")
        X, Y = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy or 1e-9
        L = math.sqrt(L2)
        t0 = ((X - ax) * dx + (Y - ay) * dy) / L2
        t = np.clip(t0, 0, 1)
        D = np.hypot(X - (ax + t * dx), Y - (ay + t * dy))
        SG = ((X - ax) * dy - (Y - ay) * dx) / L
        AL = run + t * L
        if si == 0:
            AL = np.where(t <= 0, -1.0, AL)                  # ponta da rua: sem faixa nem poste
        if si == last:
            AL = np.where(t >= 1, -1.0, AL)
        ang = abs(math.degrees(math.atan2(dy, dx))) % 180
        axis = "x" if ang < 15 or ang > 165 else "y" if abs(ang - 90) < 15 else None
        LAT = (X - (ax + t * dx)) if axis == "y" else (Y - (ay + t * dy))
        M = D < R
        if si == 0:
            M &= t0 >= 0                                     # ponta reta: sem o semicirculo (serrilhava)
        if si == last:
            M &= t0 <= 1
        ys, xs = np.nonzero(M)
        for j, i in zip(ys.tolist(), xs.tolist()):
            k = (x0 + i, y0 + j)
            d = float(D[j, i])
            if k not in out or d < out[k][0]:
                out[k] = (d, axis, float(SG[j, i]), float(AL[j, i]), float(LAT[j, i]))
        run += L
    return out


def classify(items):
    """{(x, y): (classe 'a'|'s', indice da rua, dist, axis)}: asfalto ganha da calcada; depois a rua mais perto."""
    cls = {}
    na = {}
    for n, it in enumerate(items):
        half = it["width"] / 2
        for k, (d, axis, sg, al, lat) in _raster(it, items).items():
            c = "a" if d < half else "s"
            if c == "a":
                na.setdefault(k, []).append((n, al))
            cur = cls.get(k)
            if cur is None or (c == "a" and cur[0] == "s") or (c == cur[0] and d < cur[2]):
                cls[k] = (c, n, d, axis, sg, al, lat)
    span = {}                                                # cruzamento: trecho de cada rua sob o asfalto de outra
    for v in na.values():
        if len(v) > 1:
            for n, al in v:
                lo, hi = span.get(n, (al, al))
                span[n] = (min(lo, al), max(hi, al))
    if span:                                                 # ali sem faixa nem poste (a faixa nao cruza a outra rua)
        for k, c in cls.items():
            r = span.get(c[1])
            if c[0] == "a" and r and r[0] - 0.5 <= c[5] <= r[1] + 0.5:
                cls[k] = c[:5] + (-1.0,) + c[6:]
    return cls


def _fam_tile(v, hh, base_only=False):
    if isinstance(v, str):
        return v
    if base_only:
        return f"blends_street_01_{v}"
    k = hh % 16
    vs = FAM_VARS.get(v, (5, 6, 7))
    return f"blends_street_01_{v + (vs[k % len(vs)] if k < 3 else 0)}"   # base na maioria, variacao rara


def _nat_family(tiles):
    for t in tiles or []:
        if t.startswith("blends_natural_01_"):
            try:
                return (int(t.rsplit("_", 1)[1]) // 16) * 16
            except ValueError:
                return None
        break
    return None


def _grass(x, y, nb, base_of):
    """grama de fora invade a borda da rua (canto se 2 lados vizinhos, senao borda)."""
    fams = {}
    for s, (dx, dy) in NB.items():
        if nb[s] is None:
            f = _nat_family(base_of((x + dx, y + dy)))
            if f is not None:
                fams[s] = f
    if not fams:
        return None
    ds = frozenset(fams)
    f = max(fams.values())
    kk = next((v for pr, v in BLEND_IDX.items() if pr <= ds), None)
    if kk is None:
        kk = BLEND_EDGE[sorted(ds)[0]][h32(x, y, 3) & 1]
    return f"blends_natural_01_{f + kk}"


def _dashed(it, al):
    return al < 0 or (it["dash"] and int(al // it["dash"]) % 2)


def lane_edges(it, n, k, cls):
    """bordas do quadrado k que levam faixa: a divisoria i (deslocamento o_i do eixo) passa entre dois quadrados
    de asfalto vizinhos da mesma rua quando o lado (sg) dos dois fica um de cada lado de o_i. A borda vai para o
    quadrado com sg menor (lado fixo), entao numa curva em escada os dois lados de um degrau caem no mesmo
    quadrado e viram um tile de canto."""
    L, w = it["lanes"], it["width"]
    if L < 2:
        return set()
    offs = [-w / 2 + i * w / L for i in range(1, L)]
    x, y = k
    me = cls[k]
    out = set()
    for s, (dx, dy) in NB.items():
        o = cls.get((x + dx, y + dy))
        if not o or o[0] != "a" or o[1] != n:
            continue
        if me[3] is None or o[3] is None:              # diagonal/curva: lane_diag usa os tiles vanilla de angulo
            continue
        a, b = me[4], o[4]
        if a >= b or _dashed(it, min(me[5], o[5])) or me[5] < 0 or o[5] < 0:
            continue
        if any(a < off <= b for off in offs):
            out.add(s)
    return out


def lane_diag(it, n, k, cls):
    """faixa em trecho diagonal/curvo: a reta sg = off cortada no quadrado vira o sprite vanilla de mesmo angulo.
    O gradiente de sg sai dos vizinhos da mesma rua (diferenca central), entao segue a curva quadrado a quadrado."""
    from . import lanelines as LL
    L, w = it["lanes"], it["width"]
    me = cls[k]
    if L < 2 or me[3] is not None or _dashed(it, me[5]):
        return []
    x, y = k

    def sg(dx, dy):
        o = cls.get((x + dx, y + dy))
        return o[4] if o and o[1] == n else None

    def grad(dx, dy):
        a, b = sg(dx, dy), sg(-dx, -dy)
        if a is not None and b is not None:
            return (a - b) / 2
        if a is not None:
            return a - me[4]
        if b is not None:
            return me[4] - b
        return 0.0
    gx, gy = grad(1, 0), grad(0, 1)
    if abs(gx) + abs(gy) < 1e-6:
        return []
    out = []
    for i in range(1, L):
        off = -w / 2 + i * w / L
        seg = LL.clip(me[4] - off, gx, gy)
        if not seg or math.hypot(seg[2] - seg[0], seg[3] - seg[1]) < 0.08:
            continue
        b = LL.best(seg)
        if b is None:
            b = LL.best(seg, tol=0.35)                         # angulo raso: o sprite vanilla mais proximo
        if b is not None:
            out.append(LL.tile(it["line_color"], b))
    return out


def line_tiles(it, edges):
    base, out, left = it["line_color"], [], set(edges)
    for pr, v in LINE_CORNER.items():
        if pr <= left:
            out.append(f"street_trafficlines_01_{base + v}")
            left -= pr
    out += [f"street_trafficlines_01_{base + LINE_EDGE[s]}" for s in ("N", "W", "S", "E") if s in left]
    return out


def _straight(cls, k, s, me, other):
    """a borda s do quadrado k (classe me, vizinho classe other) continua reta em pelo menos um dos lados?
    Degrau isolado de diagonal fica sem meio-fio (o vanilla nao tem meio-fio diagonal)."""
    x, y = k
    dx, dy = NB[s]
    for ex, ey in ((dy, dx), (-dy, -dx)):                  # vizinhos ao longo da borda
        a = cls.get((x + ex, y + ey))
        b = cls.get((x + ex + dx, y + ey + dy))
        if a and b and a[0] == me and b[0] == other:
            return True
    return False


def pole_here(it, d, sg, al):
    """poste na 1a fileira da calcada, a cada `pole_every`, lados alternados (meio passo de diferenca)."""
    half = it["width"] / 2
    if not it["poles"] or not side_of(it) or al < 0 or not (half <= d < half + 1):
        return False
    e = it["pole_every"]
    ph = 0 if sg > 0 else e // 2
    return int(al) % e == ph


def tiles_for(k, cls, items, base_of):
    """lista de tiles do quadrado k (dentro da rua)."""
    c, n, d, axis, sg, al, lat = cls[k]
    it = items[n]
    x, y = k
    hh = h32(x, y)
    nb = {s: cls.get((x + dx, y + dy)) for s, (dx, dy) in NB.items()}
    if c == "a":
        out = [_fam_tile(it["asph"], hh)]
        if it["curbs"]:
            out += [CURB_ASPH[s] for s in ("S", "E") if nb[s] and nb[s][0] == "s" and _straight(cls, k, s, "a", "s")]
        out += line_tiles(it, lane_edges(it, n, k, cls)) + lane_diag(it, n, k, cls)
        if not side_of(it):
            g = _grass(x, y, nb, base_of)
            if g:
                out.insert(1, g)
        return out
    out = [_fam_tile(it["walk"], hh >> 3)]
    asph = frozenset(s for s, v in nb.items() if v and v[0] == "a")
    if len(asph) == 2 and asph in BLEND_IDX:            # degrau da diagonal: canto do asfalto, meio a meio
        af = items[next(v for v in nb.values() if v and v[0] == "a")[1]]["asph"]
        if not isinstance(af, str):
            out.append(f"blends_street_01_{af + BLEND_IDX[asph]}")
    g = _grass(x, y, nb, base_of)
    if g:
        out.append(g)
    if it["curbs"]:
        out += [CURB_WALK[s] for s in ("S", "E") if nb[s] and nb[s][0] == "a" and items[nb[s][1]]["curbs"]
                and _straight(cls, k, s, "s", "a")]
    if pole_here(it, d, sg, al):
        out.append(it["pole"])
    return out


def apply(project, items, label):
    """grava a nova lista de ruas: reescreve so a regiao das ruas que mudaram (com 1 quadrado de margem),
    guarda/devolve o chao original, e empilha UM comando de desfazer. Retorna changed."""
    with project.lock:
        old = get(project)
        base = old["base"]
        by_id_old = {it["id"]: it for it in old["items"]}
        by_id_new = {it["id"]: it for it in items}
        touched = [it for i in set(by_id_old) | set(by_id_new)
                   for it in (by_id_old.get(i), by_id_new.get(i)) if it is not None
                   and json.dumps(by_id_old.get(i), sort_keys=True) != json.dumps(by_id_new.get(i), sort_keys=True)]
        region = set()
        for it in touched:
            for (x, y) in _raster(it, items) | _raster(it, old["items"]):
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        region.add((x + dx, y + dy))
        cls_new = classify(items)
        rec = {}
        changed = {}
        newbase = dict(base)

        def cur(k):
            return project.get(k[0], k[1], 0)

        def base_of(k):
            s = f"{k[0]},{k[1]}"
            return newbase[s] if s in newbase else cur(k)

        for k in region:                                     # guarda o chao de antes da rua (1a vez)
            s = f"{k[0]},{k[1]}"
            if k in cls_new and s not in newbase and (k[0] // CS, k[1] // CS) in project.cellset:
                newbase[s] = cur(k)
        for k in sorted(region):
            if (k[0] // CS, k[1] // CS) not in project.cellset:
                continue
            s = f"{k[0]},{k[1]}"
            if k in cls_new:
                new = tiles_for(k, cls_new, items, base_of)
            elif s in newbase:
                new = newbase.pop(s)                         # a rua saiu daqui: volta o chao de antes
            else:
                continue
            now = cur(k)
            if new != now:
                rec[(k[0], k[1], 0)] = (now, list(new))
                project._set(k[0], k[1], 0, new, changed)
        value = {"items": items, "base": newbase}
        cmd = {"label": label, "sq": [(k, o, n) for k, (o, n) in rec.items()], "rooms": {},
               "meta": {"streets": (json.dumps(project.meta.get("streets")), json.dumps(value))}}
        project.meta["streets"] = value
        project.meta_dirty = True
        project._push(cmd)
        return changed


def summary(items):
    out = []
    for it in items:
        P = path(it)
        L = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(P, P[1:]))
        out.append({"id": it["id"], "len": round(L)})
    return out
