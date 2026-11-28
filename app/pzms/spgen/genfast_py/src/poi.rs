//! POI x mapa (auditoria audita_poi = 0): snap do POI no predio do mapa final, lote do posto, comodo garantido
//! por POI (celula do mapa do ponto), predio de um POI de area e lugar de banca. Mesmas regras do Python de
//! referencia no gen.py (GENFAST=0); o hash da saida tem que bater.
use pyo3::prelude::*;
use std::collections::{BTreeMap, BTreeSet, HashMap};

#[inline]
fn ba_at(ba: &[i32], w: usize, x: i64, y: i64) -> i32 { ba[y as usize * w + x as usize] }

/// POI de ponto (xi, yi no raster) -> (predio, x, y) do quadrado de predio dentro do mapa mais perto ate r
/// (o primeiro na ordem linha a linha entre os empatados, como o argmin do numpy); (-1, -1, -1) sem nenhum.
/// ox, oy: canto do raster em coordenada local do mapa; lim: lado do mapa (NC * CS).
#[pyfunction]
pub fn poi_snap(ba: usize, h: usize, w: usize, pts: Vec<(i64, i64)>, r: i64, ox: i64, oy: i64, lim: i64)
    -> Vec<(i64, i64, i64)> {
    let a = unsafe { std::slice::from_raw_parts(ba as *const i32, h * w) };
    let (hh, ww) = (h as i64, w as i64);
    pts.iter().map(|&(xi, yi)| {
        let (ya, xa) = ((yi - r).max(0), (xi - r).max(0));
        let (yb, xb) = ((yi + r + 1).min(hh), (xi + r + 1).min(ww));
        let mut best: Option<(i64, i64, i64)> = None;
        for y in ya..yb {
            let wy = y + oy;
            if wy < 0 || wy >= lim { continue }
            for x in xa..xb {
                let v = ba_at(a, w, x, y);
                if v == 0 { continue }
                let wx = x + ox;
                if wx < 0 || wx >= lim { continue }
                let d = (y - yi) * (y - yi) + (x - xi) * (x - xi);
                if best.map_or(true, |b| d < b.0) { best = Some((d, x, y)) }
            }
        }
        match best {
            Some((d, x, y)) if d <= r * r => (ba_at(a, w, x, y) as i64, x, y),
            _ => (-1, -1, -1),
        }
    }).collect()
}

/// lote do posto: retangulos (x0, y0, x1, y1) ja com folga e recortados no raster. elig[bi]: 0 ignora,
/// 1 sobrado (vira terreo), 2 predio alto (recorta o lote; se o que sobra fica pequeno/fino, terreo).
/// Recorta Ba no lugar. -> [(predio, 1 terreo | 2 recortado)] na ordem crescente de predio.
#[pyfunction]
pub fn posto_carve(ba: usize, h: usize, w: usize, rects: Vec<(i64, i64, i64, i64)>, elig: Vec<u8>) -> Vec<(i64, u8)> {
    let a = unsafe { std::slice::from_raw_parts_mut(ba as *mut i32, h * w) };
    let mut lot = vec![false; h * w];
    for &(x0, y0, x1, y1) in &rects {
        for y in y0.max(0)..y1.min(h as i64) {
            for x in x0.max(0)..x1.min(w as i64) { lot[y as usize * w + x as usize] = true }
        }
    }
    let mut ids = BTreeSet::new();
    for i in 0..h * w { if lot[i] && a[i] > 0 { ids.insert(a[i]); } }
    let cand: Vec<i32> = ids.into_iter().filter(|&b| (b as usize) < elig.len() && elig[b as usize] > 0).collect();
    if cand.is_empty() { return vec![] }
    // caixa e total de cada candidato alto (uma varredura)
    let tall: BTreeSet<i32> = cand.iter().copied().filter(|&b| elig[b as usize] == 2).collect();
    let mut bx: HashMap<i32, (usize, usize, usize, usize, usize)> = HashMap::new();   // x0 y0 x1 y1 tot
    if !tall.is_empty() {
        for y in 0..h {
            for x in 0..w {
                let v = a[y * w + x];
                if v > 0 && tall.contains(&v) {
                    let e = bx.entry(v).or_insert((x, y, x, y, 0));
                    e.0 = e.0.min(x); e.1 = e.1.min(y); e.2 = e.2.max(x); e.3 = e.3.max(y); e.4 += 1;
                }
            }
        }
    }
    let mut out = Vec::with_capacity(cand.len());
    for b in cand {
        if elig[b as usize] == 2 {
            if let Some(&(x0, y0, x1, y1, tot)) = bx.get(&b) {
                let (bw, bh) = (x1 - x0 + 1, y1 - y0 + 1);
                let rest = |x: usize, y: usize| -> bool {
                    x >= x0 && y >= y0 && x <= x1 && y <= y1 && a[y * w + x] == b && !lot[y * w + x]
                };
                // quadrado que pertence a um bloco 2x2 do que sobra
                let mut keep = vec![false; bw * bh];
                for y in y0..y1 {
                    for x in x0..x1 {
                        if rest(x, y) && rest(x + 1, y) && rest(x, y + 1) && rest(x + 1, y + 1) {
                            for (u, v) in [(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)] {
                                keep[(v - y0) * bw + (u - x0)] = true
                            }
                        }
                    }
                }
                let (mut n, mut kx0, mut ky0, mut kx1, mut ky1) = (0usize, usize::MAX, usize::MAX, 0usize, 0usize);
                for v in 0..bh { for u in 0..bw { if keep[v * bw + u] {
                    n += 1; kx0 = kx0.min(u); ky0 = ky0.min(v); kx1 = kx1.max(u); ky1 = ky1.max(v);
                } } }
                if n >= 16.max(tot / 3) && n > 0 && (kx1 - kx0).min(ky1 - ky0) >= 3 {
                    for v in 0..bh { for u in 0..bw {
                        let i = (v + y0) * w + (u + x0);
                        if a[i] == b && !keep[v * bw + u] { a[i] = 0 }
                    } }
                    out.push((b as i64, 2));
                    continue;
                }
            }
        }
        out.push((b as i64, 1));
    }
    out
}

/// celulas da grade (lado s, mundo = raster + (ox, oy)) que o predio bi ocupa dentro da caixa
/// [y0, y1) x [x0, x1), cada uma com as celulas do mapa (lado cs) que toca, em ordem crescente.
#[pyfunction]
pub fn poi_cells(ba: usize, h: usize, w: usize, bi: i32, y0: usize, y1: usize, x0: usize, x1: usize,
                 s: i64, ox: i64, oy: i64, cs: i64) -> Vec<((i64, i64), Vec<(i64, i64)>)> {
    let a = unsafe { std::slice::from_raw_parts(ba as *const i32, h * w) };
    let mut m: BTreeMap<(i64, i64), BTreeSet<(i64, i64)>> = BTreeMap::new();
    for y in y0..y1.min(h) {
        for x in x0..x1.min(w) {
            if a[y * w + x] != bi { continue }
            let (wx, wy) = (x as i64 + ox, y as i64 + oy);
            m.entry((wx.div_euclid(s), wy.div_euclid(s))).or_default().insert((wx.div_euclid(cs), wy.div_euclid(cs)));
        }
    }
    m.into_iter().map(|(k, v)| (k, v.into_iter().collect())).collect()
}

/// distribui 1 celula por POI distinto (px, py em mundo, mc = celula do mapa do ponto), na ordem dada; quem tem
/// menos celulas na sua celula do mapa escolhe primeiro (ordenacao estavel). -> ([(celula, indice do POI)], ok)
/// ok = todos ganharam celula que toca a sua celula do mapa.
#[pyfunction]
pub fn poi_assign(cells: Vec<((i64, i64), Vec<(i64, i64)>)>, dps: Vec<(i64, i64, (i64, i64))>, s: i64)
    -> (Vec<((i64, i64), usize)>, bool) {
    let touch = |mc: (i64, i64), c: usize| cells[c].1.contains(&mc);
    let mut ord: Vec<usize> = (0..dps.len()).collect();
    ord.sort_by_key(|&i| (0..cells.len()).filter(|&c| touch(dps[i].2, c)).count());
    let mut used = vec![false; cells.len()];
    let (mut own, mut ok) = (Vec::new(), true);
    for i in ord {
        let (px, py, mc) = dps[i];
        let (kx, ky) = (px.div_euclid(s), py.div_euclid(s));
        let mut best: Option<((bool, i64, (i64, i64)), usize)> = None;
        for c in 0..cells.len() {
            if used[c] { continue }
            let k = cells[c].0;
            let key = (!touch(mc, c), (k.0 - kx) * (k.0 - kx) + (k.1 - ky) * (k.1 - ky), k);
            if best.as_ref().map_or(true, |b| key < b.0) { best = Some((key, c)) }
        }
        match best {
            None => return (own, false),
            Some((key, c)) => { used[c] = true; own.push((cells[c].0, i)); ok &= !key.0; }
        }
    }
    (own, ok)
}

/// POI de area: os predios (> 0) dentro da mascara m (mh x mw, canto y0, x0 no raster), em ordem crescente de id;
/// sem nenhum, os da mascara crescida 6 quadrados (vizinhanca 4). -> [(predio, quadrados, x, y)] com x, y = media
/// truncada dos quadrados dele na mascara; vazio sem predio.
#[pyfunction]
pub fn area_pick(ba: usize, h: usize, w: usize, m: usize, mh: usize, mw: usize, y0: i64, x0: i64)
    -> Vec<(i64, usize, i64, i64)> {
    let a = unsafe { std::slice::from_raw_parts(ba as *const i32, h * w) };
    let mk = unsafe { std::slice::from_raw_parts(m as *const u8, mh * mw) };
    let pick = |mask: &dyn Fn(i64, i64) -> bool, ya: i64, xa: i64, yb: i64, xb: i64| -> Vec<(i64, usize, i64, i64)> {
        let mut cnt: BTreeMap<i32, (usize, i64, i64)> = BTreeMap::new();
        for y in ya.max(0)..yb.min(h as i64) {
            for x in xa.max(0)..xb.min(w as i64) {
                let v = ba_at(a, w, x, y);
                if v > 0 && mask(x, y) { let e = cnt.entry(v).or_insert((0, 0, 0)); e.0 += 1; e.1 += x; e.2 += y; }
            }
        }
        cnt.into_iter().map(|(k, (n, sx, sy))| (k as i64, n, (sx as f64 / n as f64) as i64, (sy as f64 / n as f64) as i64))
            .collect()
    };
    let inm = |x: i64, y: i64| -> bool {
        let (u, v) = (x - x0, y - y0);
        u >= 0 && v >= 0 && (u as usize) < mw && (v as usize) < mh && mk[v as usize * mw + u as usize] != 0
    };
    let r = pick(&inm, y0, x0, y0 + mh as i64, x0 + mw as i64);
    if !r.is_empty() { return r }
    // crescida 6 (como o np.pad + 6 passos de vizinhanca 4)
    let (ph, pw) = (mh + 12, mw + 12);
    let mut pd = vec![false; ph * pw];
    for v in 0..mh { for u in 0..mw { if mk[v * mw + u] != 0 { pd[(v + 6) * pw + u + 6] = true } } }
    for _ in 0..6 {
        let p0 = pd.clone();
        for v in 0..ph { for u in 0..pw {
            if p0[v * pw + u] { continue }
            if (v > 0 && p0[(v - 1) * pw + u]) || (v + 1 < ph && p0[(v + 1) * pw + u]) ||
               (u > 0 && p0[v * pw + u - 1]) || (u + 1 < pw && p0[v * pw + u + 1]) { pd[v * pw + u] = true }
        } }
    }
    let (ya, xa) = (y0 - 6, x0 - 6);
    let inp = |x: i64, y: i64| -> bool {
        let (u, v) = (x - xa, y - ya);
        u >= 0 && v >= 0 && (u as usize) < pw && (v as usize) < ph && pd[v as usize * pw + u as usize]
    };
    pick(&inp, ya, xa, ya + ph as i64, xa + pw as i64)
}

/// lugar da banca n x n mais perto do ponto (xi, yi): varre dy, dx em [-rr, rr] (linha a linha), o primeiro com
/// a menor distancia ao centro; recusa fora do mapa (rx, ry, lim), quadrado mais perto da banca a mais de snap
/// do ponto, predio na banca + 1 de folga e quadrado ruim (bad: janela bh x bw com canto wy0, wx0). -> (x0, y0)
#[pyfunction]
pub fn kiosk_spot(ba: usize, h: usize, w: usize, bad: usize, bh: usize, bw: usize, wy0: i64, wx0: i64,
                  xi: i64, yi: i64, n: i64, rr: i64, snap: i64, rx: i64, ry: i64, lim: i64) -> Option<(i64, i64)> {
    let a = unsafe { std::slice::from_raw_parts(ba as *const i32, h * w) };
    let bd = unsafe { std::slice::from_raw_parts(bad as *const u8, bh * bw) };
    let (hh, ww) = (h as i64, w as i64);
    let mut best: Option<(i64, i64, i64)> = None;
    for dy in -rr..=rr {
        for dx in -rr..=rr {
            let (x0, y0) = (xi + dx - n / 2, yi + dy - n / 2);
            if x0 < 2 || y0 < 2 || x0 + n >= ww - 2 || y0 + n >= hh - 2 { continue }
            let d = dx * dx + dy * dy;
            if best.map_or(false, |b| d >= b.0) { continue }
            if !(0 <= x0 + rx && x0 + n + rx <= lim && 0 <= y0 + ry && y0 + n + ry <= lim) { continue }
            let ex = 0.max(x0 - xi).max(xi - (x0 + n - 1));
            let ey = 0.max(y0 - yi).max(yi - (y0 + n - 1));
            if ex * ex + ey * ey > snap * snap { continue }
            let mut hit = false;
            'b: for y in (y0 - 1).max(0)..(y0 + n + 1).min(hh) {
                for x in (x0 - 1).max(0)..(x0 + n + 1).min(ww) { if ba_at(a, w, x, y) != 0 { hit = true; break 'b } }
            }
            if hit { continue }
            'c: for y in (y0 - wy0).max(0)..(y0 - wy0 + n).min(bh as i64) {
                for x in (x0 - wx0).max(0)..(x0 - wx0 + n).min(bw as i64) {
                    if bd[y as usize * bw + x as usize] != 0 { hit = true; break 'c }
                }
            }
            if hit { continue }
            best = Some((d, x0, y0));
        }
    }
    best.map(|(_, x, y)| (x, y))
}

/// abre o retangulo [x0, x1) x [y0, y1) no predio bi (lote de posto dentro de predio: a cobertura do GeoSampa
/// virou predio). Tira tambem as lascas (fora de bloco 2x2); se o que sobra fica com < 16 quadrados ou lado < 3,
/// o predio sai inteiro. -> quadrados que sobraram.
#[pyfunction]
pub fn carve_rect(ba: usize, h: usize, w: usize, bi: i32, x0: i64, y0: i64, x1: i64, y1: i64) -> usize {
    let a = unsafe { std::slice::from_raw_parts_mut(ba as *mut i32, h * w) };
    let (mut bx0, mut by0, mut bx1, mut by1) = (usize::MAX, usize::MAX, 0usize, 0usize);
    for y in 0..h { for x in 0..w { if a[y * w + x] == bi {
        bx0 = bx0.min(x); by0 = by0.min(y); bx1 = bx1.max(x); by1 = by1.max(y);
    } } }
    if bx0 == usize::MAX { return 0 }
    let inr = |x: usize, y: usize| (x as i64) >= x0 && (x as i64) < x1 && (y as i64) >= y0 && (y as i64) < y1;
    for y in by0..=by1 { for x in bx0..=bx1 { if a[y * w + x] == bi && inr(x, y) { a[y * w + x] = 0 } } }
    let (bw, bh) = (bx1 - bx0 + 1, by1 - by0 + 1);
    let rest = |x: usize, y: usize| x >= bx0 && y >= by0 && x <= bx1 && y <= by1 && a[y * w + x] == bi;
    let mut keep = vec![false; bw * bh];
    for y in by0..by1 { for x in bx0..bx1 {
        if rest(x, y) && rest(x + 1, y) && rest(x, y + 1) && rest(x + 1, y + 1) {
            for (u, v) in [(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)] { keep[(v - by0) * bw + (u - bx0)] = true }
        }
    } }
    let (mut n, mut kx0, mut ky0, mut kx1, mut ky1) = (0usize, usize::MAX, usize::MAX, 0usize, 0usize);
    for v in 0..bh { for u in 0..bw { if keep[v * bw + u] {
        n += 1; kx0 = kx0.min(u); ky0 = ky0.min(v); kx1 = kx1.max(u); ky1 = ky1.max(v);
    } } }
    let whole = n < 16 || (kx1 - kx0).min(ky1 - ky0) < 3;
    for v in 0..bh { for u in 0..bw {
        let i = (v + by0) * w + (u + bx0);
        if a[i] == bi && (whole || !keep[v * bw + u]) { a[i] = 0 }
    } }
    if whole { 0 } else { n }
}

/// quadrados de cobertura de posto (cna > 0) sem predio na janela +-r do ponto: cobertura que ainda pode ter bomba
#[pyfunction]
pub fn canopy_free(cna: usize, ba: usize, h: usize, w: usize, x: i64, y: i64, r: i64) -> usize {
    let c = unsafe { std::slice::from_raw_parts(cna as *const i32, h * w) };
    let a = unsafe { std::slice::from_raw_parts(ba as *const i32, h * w) };
    let mut n = 0;
    for yy in (y - r).max(0)..(y + r + 1).min(h as i64) {
        for xx in (x - r).max(0)..(x + r + 1).min(w as i64) {
            let i = yy as usize * w + xx as usize;
            if c[i] > 0 && a[i] == 0 { n += 1 }
        }
    }
    n
}

/// predio de casa em parque, pedaco por celula do mapa (o jogo e a auditoria leem cada celula sozinha): predios com
/// algum pedaco (predio x celula do mapa, lado cs; mundo = raster + (ox, oy)) >= 50% dentro de um parque e <= 50%
/// coberto por predio residencial do OSM. parks/res: [(ptr u8, y0, x0, mh, mw)] mascaras recortadas no raster.
#[pyfunction]
pub fn park_frags(ba: usize, h: usize, w: usize, parks: Vec<(usize, i64, i64, usize, usize)>,
                  res: Vec<(usize, i64, i64, usize, usize)>, ox: i64, oy: i64, cs: i64) -> Vec<i64> {
    let a = unsafe { std::slice::from_raw_parts(ba as *const i32, h * w) };
    let key = |x: usize, y: usize| -> (i32, i64, i64) {
        (a[y * w + x], (x as i64 + ox).div_euclid(cs), (y as i64 + oy).div_euclid(cs))
    };
    // quadrados de predio na mascara de residencial (uniao)
    let mut resm: HashMap<usize, ()> = HashMap::new();
    for &(p, y0, x0, mh, mw) in &res {
        let m = unsafe { std::slice::from_raw_parts(p as *const u8, mh * mw) };
        for v in 0..mh { for u in 0..mw {
            let (x, y) = (x0 + u as i64, y0 + v as i64);
            if m[v * mw + u] != 0 && x >= 0 && y >= 0 && (x as usize) < w && (y as usize) < h {
                resm.insert(y as usize * w + x as usize, ());
            }
        } }
    }
    let mut out = BTreeSet::new();
    let mut tot: Option<HashMap<(i32, i64, i64), (usize, usize)>> = None;   // pedaco -> (quadrados, em residencial)
    for &(p, y0, x0, mh, mw) in &parks {
        let m = unsafe { std::slice::from_raw_parts(p as *const u8, mh * mw) };
        let mut ins: HashMap<(i32, i64, i64), usize> = HashMap::new();
        for v in 0..mh { for u in 0..mw {
            let (x, y) = (x0 + u as i64, y0 + v as i64);
            if m[v * mw + u] == 0 || x < 0 || y < 0 || x as usize >= w || y as usize >= h { continue }
            let k = key(x as usize, y as usize);
            if k.0 > 0 { *ins.entry(k).or_insert(0) += 1 }
        } }
        if ins.is_empty() { continue }
        let t = tot.get_or_insert_with(|| {
            let mut t: HashMap<(i32, i64, i64), (usize, usize)> = HashMap::new();
            for y in 0..h { for x in 0..w {
                if a[y * w + x] > 0 {
                    let e = t.entry(key(x, y)).or_insert((0, 0));
                    e.0 += 1;
                    if resm.contains_key(&(y * w + x)) { e.1 += 1 }
                }
            } }
            t
        });
        for (k, n) in ins {
            let (nt, nr) = t[&k];
            if n * 2 >= nt && nr * 2 <= nt { out.insert(k.0 as i64); }
        }
    }
    out.into_iter().collect()
}

/// retangulo livre de pelo menos ka x kb (em pe ou deitado) mais perto de (cx, cy) na mascara m (h x w, 1 =
/// livre), crescido ate maxw x maxh (direita, baixo, esquerda, cima, um passo por vez). -> (y0, x0, y1, x1)
/// exclusivo, como o max_rect.
#[pyfunction]
pub fn free_rect5(m: usize, h: usize, w: usize, cx: i64, cy: i64, maxw: usize, maxh: usize, ka: usize, kb: usize)
    -> Option<(usize, usize, usize, usize)> {
    let f = unsafe { std::slice::from_raw_parts(m as *const u8, h * w) };
    if h < ka.min(kb) || w < ka.min(kb) { return None }
    let mut ps = vec![0u32; (h + 1) * (w + 1)];
    for y in 0..h { for x in 0..w {
        ps[(y + 1) * (w + 1) + x + 1] = (f[y * w + x] != 0) as u32 + ps[y * (w + 1) + x + 1] + ps[(y + 1) * (w + 1) + x] - ps[y * (w + 1) + x];
    } }
    let sum = |y0: usize, x0: usize, y1: usize, x1: usize| ps[y1 * (w + 1) + x1] + ps[y0 * (w + 1) + x0] - ps[y0 * (w + 1) + x1] - ps[y1 * (w + 1) + x0];
    let mut best: Option<(i64, usize, usize, usize, usize)> = None;
    for &(ww, hh) in &[(ka, kb), (kb, ka)] {
        if h < hh || w < ww { continue }
        for y in 0..=h - hh { for x in 0..=w - ww {
            if sum(y, x, y + hh, x + ww) as usize == ww * hh {
                let (dx, dy) = (x as i64 + ww as i64 / 2 - cx, y as i64 + hh as i64 / 2 - cy);
                let d = dx * dx + dy * dy;
                if best.map_or(true, |b| d < b.0) { best = Some((d, y, x, ww, hh)) }
            }
        } }
    }
    let (_, mut y0, mut x0, ww, hh) = best?;
    let (mut y1, mut x1) = (y0 + hh, x0 + ww);
    loop {
        let mut grew = false;
        if x1 - x0 < maxw && x1 < w && sum(y0, x1, y1, x1 + 1) as usize == y1 - y0 { x1 += 1; grew = true }
        if y1 - y0 < maxh && y1 < h && sum(y1, x0, y1 + 1, x1) as usize == x1 - x0 { y1 += 1; grew = true }
        if x1 - x0 < maxw && x0 > 0 && sum(y0, x0 - 1, y1, x0) as usize == y1 - y0 { x0 -= 1; grew = true }
        if y1 - y0 < maxh && y0 > 0 && sum(y0 - 1, x0, y0, x1) as usize == x1 - x0 { y0 -= 1; grew = true }
        if !grew { break }
    }
    Some((y0, x0, y1, x1))
}

/// marca em out (h x w, u8) o disco de raio r em volta de cada ponto (x, y): zona de snap de POI
#[pyfunction]
pub fn zone_mask(out: usize, h: usize, w: usize, pts: Vec<(i64, i64)>, r: i64) {
    let o = unsafe { std::slice::from_raw_parts_mut(out as *mut u8, h * w) };
    for (x, y) in pts {
        for yy in (y - r).max(0)..(y + r + 1).min(h as i64) {
            for xx in (x - r).max(0)..(x + r + 1).min(w as i64) {
                if (xx - x) * (xx - x) + (yy - y) * (yy - y) <= r * r { o[yy as usize * w + xx as usize] = 1 }
            }
        }
    }
}

/// lote de escola para o muro: mc (lote OSM) e gc (chao) mh x mw; kind[g]: 1 asfalto/agua, 2 calcada, 0 outro.
/// Fica fora o asfalto/agua; a calcada fica fora, menos onde o lote cobre asfalto a <= 5 (Chebyshev; o lote invade
/// a rua): ali entra, sem o quadrado colado no asfalto (o muro fica na calcada, a 1 do meio-fio). -> u8 mh x mw
#[pyfunction]
pub fn muro_lote<'py>(py: Python<'py>, mc: usize, gc: usize, mh: usize, mw: usize, kind: Vec<u8>)
    -> Bound<'py, pyo3::types::PyBytes> {
    let m = unsafe { std::slice::from_raw_parts(mc as *const u8, mh * mw) };
    let g = unsafe { std::slice::from_raw_parts(gc as *const u8, mh * mw) };
    let k = |i: usize| kind.get(g[i] as usize).copied().unwrap_or(0);
    // asfalto dentro do lote, crescido 5 (prefixo 2D)
    let mut ps = vec![0u32; (mh + 1) * (mw + 1)];
    for y in 0..mh { for x in 0..mw {
        let v = (m[y * mw + x] != 0 && k(y * mw + x) == 1) as u32;
        ps[(y + 1) * (mw + 1) + x + 1] = v + ps[y * (mw + 1) + x + 1] + ps[(y + 1) * (mw + 1) + x] - ps[y * (mw + 1) + x];
    } }
    let near = |x: usize, y: usize| -> bool {
        let (x0, y0, x1, y1) = (x.saturating_sub(5), y.saturating_sub(5), (x + 6).min(mw), (y + 6).min(mh));
        ps[y1 * (mw + 1) + x1] + ps[y0 * (mw + 1) + x0] - ps[y0 * (mw + 1) + x1] - ps[y1 * (mw + 1) + x0] > 0
    };
    let asf = |x: i64, y: i64| x >= 0 && y >= 0 && (x as usize) < mw && (y as usize) < mh && k(y as usize * mw + x as usize) == 1;
    let mut out = vec![0u8; mh * mw];
    for y in 0..mh { for x in 0..mw {
        let i = y * mw + x;
        if m[i] == 0 || k(i) == 1 { continue }
        if k(i) == 2 {
            let (xi, yi) = (x as i64, y as i64);
            if !near(x, y) || asf(xi - 1, yi) || asf(xi + 1, yi) || asf(xi, yi - 1) || asf(xi, yi + 1) { continue }
        }
        out[i] = 1;
    } }
    pyo3::types::PyBytes::new(py, &out)
}
