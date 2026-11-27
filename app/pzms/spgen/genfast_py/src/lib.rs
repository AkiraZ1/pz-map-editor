//! Modulo Python (PyO3) com as rotinas do furnish/islands do gen.py. Chamada ~1-2 us (o ctypes custava ~15-25 us
//! por comodo com a conversao para numpy). Mesmas regras do Python do gen.py; o hash da saida tem que bater.
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PySet, PyTuple};

struct Grid { x0: i32, y0: i32, w: usize, h: usize, g: Vec<u8> }

impl Grid {
    fn new(c: &[(i32, i32)], pad: i32) -> Grid {
        let (mut x0, mut y0, mut x1, mut y1) = (i32::MAX, i32::MAX, i32::MIN, i32::MIN);
        for &(x, y) in c { x0 = x0.min(x); x1 = x1.max(x); y0 = y0.min(y); y1 = y1.max(y); }
        let (w, h) = ((x1 - x0 + 1 + 2 * pad) as usize, (y1 - y0 + 1 + 2 * pad) as usize);
        let mut gr = Grid { x0: x0 - pad, y0: y0 - pad, w, h, g: vec![0u8; w * h] };
        for &(x, y) in c { let k = gr.idx(x, y).unwrap(); gr.g[k] |= 1; }
        gr
    }
    #[inline]
    fn idx(&self, x: i32, y: i32) -> Option<usize> {
        let (u, v) = (x - self.x0, y - self.y0);
        if u < 0 || v < 0 || u >= self.w as i32 || v >= self.h as i32 { None } else { Some(v as usize * self.w + u as usize) }
    }
    #[inline]
    fn has(&self, x: i32, y: i32, bit: u8) -> bool { self.idx(x, y).map_or(false, |k| self.g[k] & bit != 0) }
    fn mark(&mut self, x: i32, y: i32, bit: u8) { if let Some(k) = self.idx(x, y) { self.g[k] |= bit } }
    fn any(&self, x: i32, y: i32, r: i32, bit: u8) -> bool {
        for yy in y - r..=y + r { for xx in x - r..=x + r { if self.has(xx, yy, bit) { return true } } }
        false
    }
    fn far(&self, x: i32, y: i32, r: i32) -> bool {
        for yy in y - r..=y + r { for xx in x - r..=x + r { if !self.has(xx, yy, 1) { return false } } }
        true
    }
}

fn pts(s: &Bound<'_, PyAny>) -> PyResult<Vec<(i32, i32)>> {
    let mut v = Vec::new();
    for p in s.try_iter()? { v.push(p?.extract::<(i32, i32)>()?); }
    Ok(v)
}

type Sk = (usize, i32, i32, i32, i32, i32, i32, i64, i64, i64, i64, i64);

/// candidatos de parede do furnish, ordenados como no Python: (x, y, bits N1 W2 S4 E8). gr ja tem C (bit 1).
fn cand_core(gr: &mut Grid, c: &[(i32, i32)], stz: &Bound<'_, PyAny>, cr: &Bound<'_, PySet>, z: i32, sk: Sk, hs: u32)
             -> PyResult<Vec<(i32, i32, usize)>> {
    let (ptr, lw, lh, lx0, ly0, g, ly, offx, offy, sz, k0, k1) = sk;
    let lab = unsafe { std::slice::from_raw_parts(ptr as *const i32, (lw as usize) * (lh as usize)) };
    for (x, y) in pts(stz)? { gr.mark(x, y, 2) }
    let same = |x: i32, y: i32| -> bool {
        if ly != 0 {
            let (u, v) = (x - lx0, y - ly0);
            (if u >= 0 && v >= 0 && u < lw && v < lh { lab[(v * lw + u) as usize] } else { 0 }) == g
        } else {
            let (u, v) = (x + 1, y + 1);
            u >= 0 && v >= 0 && u < lw && v < lh && lab[(v * lw + u) as usize] == g &&
                (x as i64 + offx).div_euclid(sz) == k0 && (y as i64 + offy).div_euclid(sz) == k1
        }
    };
    let mut cs: Vec<(u32, i32, i32, usize)> = Vec::new();
    for &(x, y) in c {
        let k = gr.idx(x, y).unwrap();
        if gr.g[k] & 8 != 0 { continue }
        gr.g[k] |= 8;
        let inc = |x: i32, y: i32| gr.has(x, y, 1);
        if inc(x - 1, y) && inc(x + 1, y) && inc(x, y - 1) && inc(x, y + 1) { continue }   // nao e borda
        if gr.g[k] & 2 != 0 || cr.contains((x, y, z))? { continue }
        let wn = !inc(x, y - 1) && !same(x, y - 1);
        let ws = !inc(x, y + 1) && !same(x, y + 1);
        if wn && ws { continue }
        let ww = !inc(x - 1, y) && !same(x - 1, y);
        let we = !inc(x + 1, y) && !same(x + 1, y);
        if ww && we || !(wn || ww || ws || we) { continue }
        let bits = wn as usize | (ww as usize) << 1 | (ws as usize) << 2 | (we as usize) << 3;
        let hk = (((hs ^ x as u32).wrapping_mul(16777619)) ^ y as u32).wrapping_mul(16777619);
        cs.push((hk, x, y, bits));
    }
    cs.sort_unstable();
    Ok(cs.into_iter().map(|(_, x, y, b)| (x, y, b)).collect())
}

/// gen.furnish: candidatos de parede ja ordenados [(x, y, paredes)]. cr = cruz das portas {(x, y, z)};
/// sk = (ptr do raster int32, lw, lh, lx0, ly0, g, ly, offx, offy, S, k0, k1) (ver gen.furnish/write_cell);
/// wl = 16 tuplas de paredes por bits N1 W2 S4 E8.
#[pyfunction]
fn furn_cand<'py>(py: Python<'py>, cells: &Bound<'py, PyAny>, stz: &Bound<'py, PyAny>, cr: &Bound<'py, PySet>, z: i32,
                  sk: Sk, hs: u32, wl: &Bound<'py, PyTuple>) -> PyResult<Vec<Bound<'py, PyTuple>>> {
    let c = pts(cells)?;
    if c.is_empty() { return Ok(vec![]) }
    let mut gr = Grid::new(&c, 1);
    let cs = cand_core(&mut gr, &c, stz, cr, z, sk, hs)?;
    let mut out = Vec::with_capacity(cs.len());
    for (x, y, b) in cs {
        out.push(PyTuple::new(py, [x.into_pyobject(py)?.into_any(), y.into_pyobject(py)?.into_any(), wl.get_item(b)?])?);
    }
    Ok(out)
}

/// face de um tipo de movel (indice da face N0 W1 S2 E3). Dois quadrados: t = 1o tile, rest = os seguintes
/// em (dx, dy), flag = mesa (Desk). Um quadrado: t = tile, tv = TV do rack, flag = Desk/School Bench, ctr = balcao.
struct Face { t: Py<PyAny>, rest: Vec<Py<PyAny>>, dx: i32, dy: i32, flag: bool, ctr: bool, tv: Option<Py<PyAny>> }

/// tipo de movel ja resolvido pelo gen.py (_kspec): two = ocupa 2+ quadrados (TWO), f = faces por indice.
#[pyclass(frozen)]
struct Kind { two: bool, f: [Option<Face>; 4] }

#[pymethods]
impl Kind {
    /// faces: 4 itens (N W S E) None ou (t, rest, dx, dy, desk) se two, (t, tv, ctr, deskbench) se nao.
    #[new]
    fn new(two: bool, faces: Vec<Option<Bound<'_, PyTuple>>>) -> PyResult<Kind> {
        let mut f: [Option<Face>; 4] = [None, None, None, None];
        for (i, o) in faces.into_iter().enumerate().take(4) {
            let Some(t) = o else { continue };
            f[i] = Some(if two {
                Face { t: t.get_item(0)?.unbind(), rest: t.get_item(1)?.extract::<Vec<Py<PyAny>>>()?,
                       dx: t.get_item(2)?.extract()?, dy: t.get_item(3)?.extract()?, flag: t.get_item(4)?.extract()?,
                       ctr: false, tv: None }
            } else {
                let tv = t.get_item(1)?;
                Face { t: t.get_item(0)?.unbind(), rest: vec![], dx: 0, dy: 0, flag: t.get_item(3)?.extract()?,
                       ctr: t.get_item(2)?.extract()?, tv: if tv.is_none() { None } else { Some(tv.unbind()) } }
            });
        }
        Ok(Kind { two, f })
    }
}

const FRONT: [(i32, i32); 4] = [(0, -1), (-1, 0), (0, 1), (1, 0)];    // por face N W S E
const FL: [&str; 4] = ["N", "W", "S", "E"];

/// gen.furnish inteiro menos tops/islands: candidatos + laco dos itens. items/alt = [(Kind, lista)], lista 0 = cand,
/// 1 = caixa (perto das portas), 2 = fundo (caixa ao contrario, grocery). seat = 4 tiles da cadeira por parede ou None.
/// Devolve None sem candidatos, senao (adds [(x, y, tile)] na ordem do Python, n, ctr [(x, y, face)], used|keep).

/// catalogo de moveis (montado 1 vez pelo gen.py): por tipo, as variantes de estilo ja resolvidas em Kind.
/// room_style(seed) vira um sorteio aqui: escolha = ((hs ^ c) * P) % n, com hs = 1o passo do hash do comodo.
struct KEnt { slot: Option<(u32, usize)>, tv: bool, arm: bool, kinds: Vec<Py<Kind>> }

#[pyclass]
struct Cat { k: Vec<KEnt>, couch: Option<(u32, usize)>, armv: Vec<Option<Py<Kind>>>, tvs: Option<(u32, usize)> }

#[inline]
fn pick(hs: u32, c: u32, n: usize) -> usize { ((hs ^ c).wrapping_mul(16777619) % n as u32) as usize }

impl Cat {
    fn resolve(&self, py: Python<'_>, kid: usize, hs: u32) -> Py<Kind> {
        let e = &self.k[kid];
        if e.arm {
            if let Some((c, n)) = self.couch {
                if let Some(k) = &self.armv[pick(hs, c, n)] { return k.clone_ref(py) }
            }
        }
        let ds = e.slot.map_or(0, |(c, n)| pick(hs, c, n) + 1);
        let (tv, ntv) = match (e.tv, self.tvs) { (true, Some((c, n))) => (pick(hs, c, n) + 1, n), _ => (0, 0) };
        e.kinds[ds * (ntv + 1) + tv].clone_ref(py)
    }
}

#[pymethods]
impl Cat {
    #[new]
    fn new() -> Cat { Cat { k: vec![], couch: None, armv: vec![], tvs: None } }
    /// couch: (c, n) do sofa; armv[i] = poltrona do grupo do sofa i (ou None); tvs = (c, n) do sorteio da TV
    fn setup(&mut self, couch: Option<(u32, usize)>, armv: Vec<Option<Py<Kind>>>, tvs: Option<(u32, usize)>) {
        self.couch = couch; self.armv = armv; self.tvs = tvs;
    }
    /// registra o proximo tipo (id = ordem): kinds[ds * (ntv + 1) + tv], ds 0 = padrao, i + 1 = variante i do estilo
    fn reg(&mut self, slot: Option<(u32, usize)>, tv: bool, arm: bool, kinds: Vec<Py<Kind>>) -> usize {
        self.k.push(KEnt { slot, tv, arm, kinds }); self.k.len() - 1
    }
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn furnish<'py>(py: Python<'py>, cells: &Bound<'py, PyAny>, stz: &Bound<'py, PyAny>, cr: &Bound<'py, PySet>,
                n9: &Bound<'py, PySet>, z: i32, sk: Sk, hs: u32, fx: Vec<(usize, usize)>,
                rep: Vec<(usize, usize)>, hashed: bool, cap: usize,
                alt: Vec<(usize, usize)>, h813: u32, dsq: Option<Bound<'py, PySet>>, grocery: bool,
                seat: Option<Vec<Option<Py<PyAny>>>>, cat: PyRef<'py, Cat>, gi: Option<usize>,
                cell: Option<Bound<'py, Cell>>)
                -> PyResult<Option<(Vec<(i32, i32, Py<PyAny>)>, i64, Vec<(i32, i32, &'static str)>, Vec<(i32, i32)>)>> {
    // cells: lista de (x, y), ou Groups + gi (quadrados do comodo ja em Rust); cell: grava os moveis direto no registro
    let c = match gi { Some(i) => cells.cast::<Groups>()?.borrow().cells[i].clone(), None => pts(cells)? };
    if c.is_empty() { return Ok(None) }
    let mut gr = Grid::new(&c, 3);
    let cand = cand_core(&mut gr, &c, stz, cr, z, sk, hs)?;
    if cand.is_empty() { return Ok(None) }
    // itens: fx + sorteio de rep (h32(seed, 811, i) se hashed, senao ciclico) ate cap
    let rs = |v: &Vec<(usize, usize)>| -> Vec<(Py<Kind>, usize)> { v.iter().map(|&(k, l)| (cat.resolve(py, k, hs), l)).collect() };
    let (fx, rep, alt) = (rs(&fx), rs(&rep), rs(&alt));
    let mut items: Vec<(Py<Kind>, usize)> = fx.iter().map(|(k, l)| (k.clone_ref(py), *l)).collect();
    if !rep.is_empty() {
        let h811 = (hs ^ 811).wrapping_mul(16777619);
        for i in 0..cap.saturating_sub(fx.len()) {
            let j = if hashed { (h811 ^ i as u32).wrapping_mul(16777619) as usize % rep.len() } else { i % rep.len() };
            items.push((rep[j].0.clone_ref(py), rep[j].1));
        }
    }
    let lim = items.len() * 2;
    let mut doors = Vec::new();
    if let Some(d) = &dsq {
        let mut seen = std::collections::HashSet::new();
        for &(x, y) in &c { if seen.insert((x, y)) && d.contains((x, y, z))? { doors.push((x, y)) } }
    }
    // bits do gr: 1 = C, 2 = stz, 8 = visto (cand_core); 16 = used, 32 = keep
    let mut lists: Vec<Vec<(i32, i32, usize)>> = vec![cand];
    let mut real = [0usize, 0, 0];
    if !doors.is_empty() {
        let mut ck = lists[0].clone();
        ck.sort_by_key(|&(x, y, _)| doors.iter().map(|&(a, b)| (x - a).abs() + (y - b).abs()).min().unwrap());
        lists.push(ck);
        real[1] = 1;
        if grocery {
            let mut r = lists[1].clone();
            r.reverse();
            lists.push(r);
            real[2] = 2;
        }
    }
    let mut pr = vec![usize::MAX; lists.len()];
    let (mut nused, mut nkeep) = (0usize, 0usize);
    let mut adds: Vec<(i32, i32, Py<PyAny>)> = Vec::new();
    let mut ctr = Vec::new();
    let mut n = 0i64;
    let mut i = 0;
    let nd = |x: i32, y: i32| n9.contains((x, y, z));
    while i < items.len() {
        let (kind, lid) = (items[i].0.clone_ref(py), real[items[i].1]);
        i += 1;
        let k = kind.get();
        let nu = nused + nkeep;
        if nu != 0 && pr[lid] != nu {
            let g = &gr;
            lists[lid].retain(|&(x, y, _)| !g.has(x, y, 16 | 32));
            pr[lid] = nu;
            if lists[lid].is_empty() { break }
        }
        let mut placed = false;
        for ci in 0..lists[lid].len() {
            let (x, y, walls) = lists[lid][ci];
            if gr.has(x, y, 16 | 32) { continue }
            if k.two {
                let mut ok = None;
                for w in 0..4 {
                    if walls >> w & 1 == 0 { continue }
                    let fi = (w + 2) % 4;
                    let Some(fc) = &k.f[fi] else { continue };
                    let mut good = true;
                    for j in 0..fc.rest.len() as i32 {
                        let (qx, qy) = (x + fc.dx * (j + 1), y + fc.dy * (j + 1));
                        if !gr.has(qx, qy, 1) || gr.has(qx, qy, 16 | 32 | 2) || cr.contains((qx, qy, z))? {
                            good = false; break
                        }
                    }
                    if good { ok = Some((w, fi, fc)); break }
                }
                let Some((w, fi, fc)) = ok else { continue };
                adds.push((x, y, fc.t.clone_ref(py)));
                let nr = fc.rest.len() as i32;
                for (j, t) in fc.rest.iter().enumerate() {
                    let j = j as i32;
                    adds.push((x + fc.dx * (j + 1), y + fc.dy * (j + 1), t.clone_ref(py)));
                }
                let (a, b) = FRONT[fi];
                for j in 0..=nr {
                    let (qx, qy) = (x + fc.dx * j, y + fc.dy * j);
                    let kq = gr.idx(qx, qy).unwrap();
                    if gr.g[kq] & 16 == 0 { gr.g[kq] |= 16; nused += 1 }
                }
                for j in 0..=nr {
                    let (qx, qy) = (x + fc.dx * j + a, y + fc.dy * j + b);
                    let kq = gr.idx(qx, qy).unwrap();
                    if gr.g[kq] & 32 == 0 { gr.g[kq] |= 32; nkeep += 1 }
                }
                if fc.flag {
                    if let Some(st) = &seat {
                        let (qx, qy) = if nr > 0 { (x + fc.dx + a, y + fc.dy + b) } else { (x + a, y + b) };
                        if let Some(s) = &st[w] {
                            if gr.has(qx, qy, 1) && !gr.has(qx, qy, 16) && !nd(qx, qy)? {
                                adds.push((qx, qy, s.clone_ref(py)));
                                let kq = gr.idx(qx, qy).unwrap();
                                gr.g[kq] |= 16; nused += 1;
                            }
                        }
                    }
                }
                n += 1;
                placed = true;
                break
            }
            let Some((w, fi)) = (0..4).filter(|&w| walls >> w & 1 != 0).map(|w| (w, (w + 2) % 4))
                .find(|&(_, fi)| k.f[fi].is_some()) else { continue };
            let fc = k.f[fi].as_ref().unwrap();
            adds.push((x, y, fc.t.clone_ref(py)));
            if let Some(tv) = &fc.tv { adds.push((x, y, tv.clone_ref(py))) }
            let (a, b) = FRONT[fi];
            if fc.ctr { ctr.push((x, y, FL[fi])) }
            let kq = gr.idx(x, y).unwrap();
            if gr.g[kq] & 16 == 0 { gr.g[kq] |= 16; nused += 1 }
            let (fx, fy) = (x + a, y + b);
            if fc.flag {
                if let Some(st) = &seat {
                    if gr.has(fx, fy, 1) && !gr.has(fx, fy, 16) && !nd(fx, fy)? {
                        if let Some(s) = &st[w] { adds.push((fx, fy, s.clone_ref(py))) }
                        let kq = gr.idx(fx, fy).unwrap();
                        gr.g[kq] |= 16; nused += 1;
                    }
                }
            }
            let kq = gr.idx(fx, fy).unwrap();
            if gr.g[kq] & 32 == 0 { gr.g[kq] |= 32; nkeep += 1 }
            n += 1;
            placed = true;
            break
        }
        if !placed && !alt.is_empty() && items.len() < lim {
            let h = ((h813 ^ items.len() as u32).wrapping_mul(16777619)) as usize % alt.len();
            items.push((alt[h].0.clone_ref(py), alt[h].1));
        }
    }
    let mut uk = Vec::new();
    for v in 0..gr.h { for u in 0..gr.w {
        if gr.g[v * gr.w + u] & (16 | 32) != 0 { uk.push((u as i32 + gr.x0, v as i32 + gr.y0)) }
    } }
    if let Some(cl) = cell {
        let mut cl = cl.borrow_mut();
        for (x, y, t) in adds.drain(..) {
            let t = t.bind(py).cast::<pyo3::types::PyString>()?.to_cow()?;
            let i = cl.ti(&t); cl.put(x, y, z, i);
        }
    }
    Ok(Some((adds, n, ctr, uk)))
}

/// gen.islands: miolo [(x, y)] na ordem de C. dine: stz sem folga + n9; margin 1: stz com folga 1 + n9;
/// margin 2: stz com folga 2 + n9 no 3x3. n9 = 3x3 das portas {(x, y, z)}.
#[pyfunction]
fn isl_mask(cells: &Bound<'_, PyAny>, busy: &Bound<'_, PyAny>, stz: &Bound<'_, PyAny>, n9: &Bound<'_, PySet>, z: i32,
            margin: i32, dine: bool) -> PyResult<Vec<(i32, i32)>> {
    let c = pts(cells)?;
    if c.is_empty() { return Ok(vec![]) }
    let mut gr = Grid::new(&c, 3);
    for (x, y) in pts(busy)? { gr.mark(x, y, 2) }
    for (x, y) in pts(stz)? { gr.mark(x, y, 4) }
    let (rs, rf, rn) = if dine { (0, 1, 0) } else if margin == 1 { (1, 1, 0) } else { (margin, margin, 1) };
    let mut out = Vec::new();
    for &(x, y) in &c {
        if gr.has(x, y, 2) || gr.any(x, y, rs, 4) || !gr.far(x, y, rf) { continue }
        let mut door = false;
        'a: for yy in y - rn..=y + rn { for xx in x - rn..=x + rn {
            if n9.contains((xx, yy, z))? { door = true; break 'a }
        } }
        if !door { out.push((x, y)) }
    }
    Ok(out)
}


// ---------------------------------------------------------------- registro de tiles da celula (gen.SqLog + names)
#[derive(Default, Clone, Copy)]
struct Fnv(u64);
impl std::hash::Hasher for Fnv {
    fn finish(&self) -> u64 { self.0 }
    fn write(&mut self, b: &[u8]) { let mut h = if self.0 == 0 { 0xcbf29ce484222325 } else { self.0 }; for &c in b { h = (h ^ c as u64).wrapping_mul(0x100000001b3) } self.0 = h }
}
type FB = std::hash::BuildHasherDefault<Fnv>;

/// gen.SqLog em Rust: eventos ((z+64)<<16 | y<<8 | x) << 24 | nome, por segmento com rank (0 chao, 1 bordas, 2 resto);
/// trocas de piso e limpezas guardadas com a posicao no registro. names na ordem do 1o uso (= tabela do lotheader).
#[pyclass]
struct Cell { names: Vec<String>, nidx: std::collections::HashMap<String, u32, FB>, segs: Vec<(Vec<i64>, u8)>,
              e: Vec<i64>, nseg: usize, rep: Vec<(i64, usize, u32)>, clr: Vec<(i64, usize)>, drop: Option<String> }

impl Cell {
    #[inline]
    fn ti(&mut self, n: &str) -> u32 {
        if let Some(&i) = self.nidx.get(n) { return i }
        let i = self.names.len() as u32;
        self.names.push(n.to_string()); self.nidx.insert(n.to_string(), i);
        i
    }
    #[inline]
    fn put(&mut self, x: i32, y: i32, z: i32, i: u32) {
        self.e.push(((((z as i64 + 64) << 16) | ((y as i64) << 8) | x as i64) << 24) | i as i64)
    }
    fn fl(&mut self) {
        if !self.e.is_empty() { let a = std::mem::take(&mut self.e); self.nseg += a.len(); self.segs.push((a, 2)) }
    }
    fn pos_(&self) -> usize { self.nseg + self.e.len() }
}

/// ordena u64 pelos 32 bits altos, estavel (os baixos ja vem crescentes): LSD de 11 bits
fn radix_hi(k: &mut Vec<u64>) {
    let mx = k.iter().map(|e| e >> 32).max().unwrap_or(0);
    let mut tmp = vec![0u64; k.len()];
    let mut sh = 32;
    while sh < 64 && (mx >> (sh - 32)) > 0 {
        let mut c = [0usize; 2049];
        for e in k.iter() { c[((e >> sh) & 2047) as usize + 1] += 1 }
        for i in 0..2048 { c[i + 1] += c[i] }
        for &e in k.iter() { let d = ((e >> sh) & 2047) as usize; tmp[c[d]] = e; c[d] += 1 }
        std::mem::swap(k, &mut tmp);
        sh += 11;
    }
}

impl Cell {
    /// eventos -> (x, y, z, lens, tiles) na ordem (chave, rank, posicao), com limpezas e trocas de piso aplicadas
    fn build(&mut self) -> (Vec<i32>, Vec<i32>, Vec<i32>, Vec<i32>, Vec<i32>) {
        self.fl();
        let mut key: Vec<u64> = Vec::with_capacity(self.nseg);     // (K*4+R) << 32 | Q
        let mut tid: Vec<u32> = Vec::with_capacity(self.nseg);
        for (a, r) in &self.segs {
            for &v in a {
                key.push(((((v >> 24) * 4 + *r as i64) as u64) << 32) | tid.len() as u64);
                tid.push((v & 0xFFFFFF) as u32);
            }
        }
        radix_hi(&mut key);
        let mut clr = self.clr.clone(); clr.sort_unstable();
        let mut rep = self.rep.clone(); rep.sort_unstable_by_key(|e| (e.0, e.1));
        let fi: Vec<bool> = self.names.iter().map(|n| n.starts_with("floors_interior")).collect();
        let rm = self.remap();
        let (mut xs, mut ys, mut zs, mut ls, mut ts) = (vec![], vec![], vec![], vec![], Vec::with_capacity(key.len()));
        let mut last = i64::MIN;
        let (mut ck, mut cdead, mut rlo, mut rhi, mut cj) = (i64::MIN, usize::MAX, 0usize, 0usize, 0usize);
        for kq in key {
            let k = (kq >> 34) as i64;
            let qe = (kq & 0xFFFF_FFFF) as usize;
            if k != ck {        // por chave (crescente): ultima limpeza e faixa de trocas, ponteiros so avancam
                ck = k;
                while cj < clr.len() && clr[cj].0 < k { cj += 1 }
                cdead = 0;
                while cj < clr.len() && clr[cj].0 == k { cdead = clr[cj].1; cj += 1 }
                rlo = rhi.max(rlo);
                while rlo < rep.len() && rep[rlo].0 < k { rlo += 1 }
                rhi = rlo; while rhi < rep.len() && rep[rhi].0 == k { rhi += 1 }
            }
            if qe < cdead { continue }
            let mut cur = tid[qe];
            for r in &rep[rlo..rhi] { if r.1 > qe && fi[cur as usize] { cur = r.2 } }
            let cur = rm[cur as usize];
            if cur < 0 { continue }     // sprite fora do vanilla (drop): o quadrado so existe se sobrar tile
            if k != last {
                xs.push((k & 255) as i32); ys.push(((k >> 8) & 255) as i32); zs.push(((k >> 16) - 64) as i32); ls.push(0i32);
                last = k;
            }
            *ls.last_mut().unwrap() += 1;
            ts.push(cur);
        }
        (xs, ys, zs, ls, ts)
    }
    /// indice novo de cada nome (-1 = descartado pelo prefixo drop); a ordem do 1o uso dos que ficam nao muda
    fn remap(&self) -> Vec<i32> {
        let mut k = 0i32;
        self.names.iter().map(|n| match &self.drop {
            Some(p) if n.starts_with(p.as_str()) => -1,
            _ => { k += 1; k - 1 }
        }).collect()
    }
}

#[pymethods]
impl Cell {
    #[new]
    #[pyo3(signature = (drop=None))]
    fn new(drop: Option<String>) -> Cell {
        Cell { names: vec![], nidx: Default::default(), segs: vec![], e: vec![], nseg: 0, rep: vec![], clr: vec![], drop }
    }
    fn t(&mut self, n: &str) -> u32 { self.ti(n) }
    fn get(&self, n: &str) -> Option<u32> { self.nidx.get(n).copied() }
    /// chao z0 nativo: a = 1o tile de cada quadrado (rank 0), b = 2o ou -1, int32 em ordem y, x
    fn ground(&mut self, pa: usize, pb: usize, n: usize) {
        self.fl();
        let a = unsafe { std::slice::from_raw_parts(pa as *const i32, n * n) };
        let b = unsafe { std::slice::from_raw_parts(pb as *const i32, n * n) };
        let k = |i: usize| (((i / n) as i64) << 8 | (i % n) as i64 | 64 << 16) << 24;
        let f: Vec<i64> = (0..n * n).map(|i| k(i) | a[i] as i64).collect();
        let r: Vec<i64> = (0..n * n).filter(|&i| b[i] >= 0).map(|i| k(i) | b[i] as i64).collect();
        if !f.is_empty() { self.nseg += f.len(); self.segs.push((f, 0)) }
        if !r.is_empty() { self.nseg += r.len(); self.segs.push((r, 2)) }
    }
    fn add(&mut self, x: i32, y: i32, z: i32, n: &str) { let i = self.ti(n); self.put(x, y, z, i) }
    fn addi(&mut self, x: i32, y: i32, z: i32, i: u32) { self.put(x, y, z, i) }
    /// eventos int64 ja empacotados (ponteiro de um array numpy contiguo), com rank
    fn push(&mut self, ptr: usize, n: usize, rank: u8) {
        self.fl();
        if n > 0 {
            let a = unsafe { std::slice::from_raw_parts(ptr as *const i64, n) }.to_vec();
            self.nseg += n; self.segs.push((a, rank));
        }
    }
    fn flush(&mut self) { self.fl() }
    fn pos(&self) -> usize { self.pos_() }
    fn replace(&mut self, x: i32, y: i32, z: i32, rf: u32) {
        let p = self.pos_(); self.rep.push((((z as i64 + 64) << 16) | ((y as i64) << 8) | x as i64, p, rf))
    }
    fn clear(&mut self, x: i32, y: i32, z: i32) {
        let p = self.pos_(); self.clr.push((((z as i64 + 64) << 16) | ((y as i64) << 8) | x as i64, p))
    }
    /// fallback do chao em Python (ground_first): o ultimo segmento e o chao; o 1o de cada quadrado vira rank 0
    fn ground_first(&mut self) {
        self.fl();
        if let Some((a, _)) = self.segs.pop() {
            self.nseg -= a.len();
            let mut seen = std::collections::HashSet::new();
            let (mut f, mut r) = (vec![], vec![]);
            for v in a { if seen.insert(v >> 24) { f.push(v) } else { r.push(v) } }
            if !f.is_empty() { self.nseg += f.len(); self.segs.push((f, 0)) }
            if !r.is_empty() { self.nseg += r.len(); self.segs.push((r, 2)) }
        }
    }
    /// telhado plano do andar z (laco do write_cell): fl[y*n+x] bits 1 = topo, 2 = vao da escada do heliponto (pula),
    /// 4 = heliponto (so o piso); bw = Bw (n+2)^2 com borda; res[bi] = casa; hh = h32_grid(..., 5)
    #[allow(clippy::too_many_arguments)]
    fn roof(&mut self, z: i32, n: usize, pfl: usize, pbw: usize, phh: usize, res: Vec<bool>, masp: i64,
            roof: &str, dish: (String, String), big: Vec<String>) {
        let fl = unsafe { std::slice::from_raw_parts(pfl as *const u8, n * n) };
        let bw = unsafe { std::slice::from_raw_parts(pbw as *const i32, (n + 2) * (n + 2)) };
        let hh = unsafe { std::slice::from_raw_parts(phh as *const u32, n * n) };
        let w = n + 2;
        for y in 0..n {
            for x in 0..n {
                let f = fl[y * n + x];
                if f & 1 == 0 || f & 2 != 0 { continue }
                let i = self.ti(roof); self.put(x as i32, y as i32, z, i);
                if f & 4 != 0 { continue }
                let bi = bw[(y + 1) * w + x + 1];
                if bi as i64 == masp || !(bw[y * w + x + 1] == bi && bw[(y + 2) * w + x + 1] == bi
                                          && bw[(y + 1) * w + x] == bi && bw[(y + 1) * w + x + 2] == bi) { continue }
                let h = hh[y * n + x];
                let t = if res[bi as usize] { if h % 23 == 0 { Some(if (h >> 8) & 1 == 0 { &dish.0 } else { &dish.1 }) } else { None } }
                        else if h % 19 == 0 { Some(&big[(h >> 8) as usize % big.len()]) }
                        else if h % 151 == 0 { Some(if (h >> 8) & 1 == 0 { &dish.0 } else { &dish.1 }) } else { None };
                if let Some(t) = t { let i = self.ti(t); self.put(x as i32, y as i32, z, i) }
            }
        }
    }
    /// bordas do chao z0 (gen.ground_edges + o laco do write_cell): mascaras n x n ja calculadas em numpy;
    /// monta {(x, y): [tiles]} na ordem do dict do Python e grava como rank 1, pulando quadrado de predio.
    #[allow(clippy::too_many_arguments)]
    fn edges(&mut self, n: usize, pm: (usize, usize, usize), pmw: usize, pk: usize, pcode: usize, pcurb: usize,
             ppc: usize, phh: usize, pbl: usize, blend: Vec<Vec<u32>>, asph_fam: u32, curb_diag: Vec<String>,
             pcs: Vec<Vec<String>>, lines: Vec<String>) {
        let nn = n * n;
        let u8s = |p: usize| unsafe { std::slice::from_raw_parts(p as *const u8, nn) };
        let (ma, mn, mm_, mw, kc, code, curb, pc, bl) = (u8s(pm.0), u8s(pm.1), u8s(pm.2), u8s(pmw), u8s(pk), u8s(pcode),
                                                          u8s(pcurb), u8s(ppc), u8s(pbl));
        let hh = unsafe { std::slice::from_raw_parts(phh as *const u32, nn) };
        let mut lst: Vec<Vec<String>> = vec![Vec::new(); nn];
        let mut ord: Vec<usize> = Vec::new();
        let mut seen = vec![false; nn];     // setdefault do Python: a chave entra mesmo com lista vazia
        macro_rules! mark { ($i:expr) => {{ let i_ = $i; if !seen[i_] { seen[i_] = true; ord.push(i_) } }} }
        macro_rules! put { ($i:expr, $t:expr) => {{ let i_ = $i; mark!(i_); lst[i_].push($t) }} }
        for (src, kind) in [(ma, 0u8), (mn, 1), (mm_, 2)] {
            for i in 0..nn {
                let m = src[i];
                if m == 0 { continue }
                let (base, f) = if kind == 0 { ("blends_natural_02_", 0) }
                                else { ("blends_natural_01_", if kind == 2 || mw[i] & m != 0 { 16 } else { 32 }) };
                if blend[m as usize].is_empty() { mark!(i) }
                for &k in &blend[m as usize] {
                    put!(i, format!("{base}{}", f + if k >= 8 && hh[i] & 1 != 0 { k + 4 } else { k }));
                }
            }
        }
        for i in 0..nn { if kc[i] > 0 { put!(i, format!("blends_street_01_{}", asph_fam + kc[i] as u32)) } }
        for i in 0..nn { if kc[i] == 1 || kc[i] == 2 { put!(i, curb_diag[kc[i] as usize].clone()) } }
        for i in 0..nn { if curb[i] != 0 { for t in &pcs[code[i] as usize] { put!(i, t.clone()) } } }
        for i in 0..nn { if pc[i] > 0 { put!(i, lines[pc[i] as usize].clone()) } }
        self.fl();
        let mut ev = Vec::new();
        for i in ord {
            if bl[i] != 0 { continue }
            let k = ((64i64 << 16) | (((i / n) as i64) << 8) | (i % n) as i64) << 24;
            for t in &lst[i] { let j = self.ti(t); ev.push(k | j as i64) }
        }
        if !ev.is_empty() { self.nseg += ev.len(); self.segs.push((ev, 1)) }
    }
    /// finish_cell em Rust: (lotpack inteiro "LOTP"..., zmin, zmax, densidade de zumbis 1024 u8)
    fn finish<'py>(&mut self, py: Python<'py>) -> (Bound<'py, PyBytes>, i32, i32, Bound<'py, PyBytes>) {
        let (xs, ys, zs, ls, ts) = self.build();
        let n = xs.len();
        let zmax = zs.iter().copied().max().unwrap_or(0).max(0);
        let zmin = zs.iter().copied().min().unwrap_or(0).min(0);
        let mut occ = [0u32; 1024];
        for i in 0..n { if zs[i] == 1 { occ[((xs[i] >> 3) * 32 + (ys[i] >> 3)) as usize] += 1 } }
        let dens: Vec<u8> = occ.iter().map(|&o| (1 + o / 32).min(2) as u8).collect();
        let tot = (zmax - zmin + 1) as i64 * 64;
        let mut st = Vec::with_capacity(n + 1); let mut a = 0usize;
        for &l in &ls { st.push(a); a += l as usize }
        let mut ek: Vec<u64> = (0..n).map(|i| {
            let ci = ((xs[i] >> 3) * 32 + (ys[i] >> 3)) as i64;
            (((ci * (tot + 1) + (zs[i] - zmin) as i64 * 64 + ((xs[i] & 7) * 8 + (ys[i] & 7)) as i64) as u64) << 32) | i as u64
        }).collect();
        radix_hi(&mut ek);      // chaves unicas: estavel ou nao da no mesmo
        let ent: Vec<(i64, usize)> = ek.iter().map(|e| ((e >> 32) as i64, (e & 0xFFFF_FFFF) as usize)).collect();
        let base = 12 + 8 * 1024i64;
        let mut out: Vec<u8> = Vec::with_capacity(base as usize + 4 * (4 * n + ts.len() + 2048));
        out.extend_from_slice(b"LOTP"); out.extend_from_slice(&1i32.to_le_bytes()); out.extend_from_slice(&1024i32.to_le_bytes());
        out.resize(base as usize, 0);
        let mut body: Vec<i32> = Vec::with_capacity(4 * n + ts.len() + 2048);
        let mut j = 0usize;
        for c in 0..1024i64 {
            let o = base + 4 * body.len() as i64;
            out[12 + 8 * c as usize..20 + 8 * c as usize].copy_from_slice(&o.to_le_bytes());
            let mut prev = 0i64;
            while j < n && ent[j].0 / (tot + 1) == c {
                let (key, i) = ent[j]; j += 1;
                let k = key % (tot + 1);
                if k > prev { body.push(-1); body.push((k - prev) as i32) }
                let l = ls[i] as usize;
                body.push(l as i32 + 1); body.push(-1);
                body.extend_from_slice(&ts[st[i]..st[i] + l]);
                prev = k + 1;
            }
            if tot > prev { body.push(-1); body.push((tot - prev) as i32) }
        }
        out.extend_from_slice(unsafe { std::slice::from_raw_parts(body.as_ptr() as *const u8, body.len() * 4) });
        (PyBytes::new(py, &out), zmin, zmax, PyBytes::new(py, &dens))
    }
    /// paredes internas da grade de comodos (write_cell, caso sem planta LY): candidatos px/py (int64, ja
    /// filtrados), id do predio em idp ((w x w) int32, com moldura de 1). Grava na ordem do laco do Python e
    /// devolve as portas (x, y, z) para o dsq.
    #[allow(clippy::too_many_arguments)]
    fn int_walls(&mut self, px: usize, py_: usize, n: usize, ox: i64, oy: i64, gx: i64, gy: i64, s: i64, bi: i32,
                 idp: usize, w: usize, stz: Vec<(i64, i64)>, z: i32, sh: &str, bs: i32, fr: (String, String),
                 dr: (String, String), jail: Option<(i64, i64)>) -> Vec<(i32, i32, i32)> {
        let (xs, ys) = unsafe { (std::slice::from_raw_parts(px as *const i64, n), std::slice::from_raw_parts(py_ as *const i64, n)) };
        let id = unsafe { std::slice::from_raw_parts(idp as *const i32, w * w) };
        let mut tc: [Option<u32>; 3] = [None; 3];     // nomes registrados no 1o uso (ordem da tabela)
        macro_rules! wt { ($k:expr) => {{ let k_: i32 = $k; match tc[k_ as usize] { Some(t) => t,
            None => { let t = self.ti(&format!("{sh}_{}", bs + k_)); tc[k_ as usize] = Some(t); t } } }} }
        let mut doors = Vec::new();
        for i in 0..n {
            let (x, y) = (xs[i], ys[i]);
            let (wx, wy) = (x + ox, y + oy);
            if stz.iter().any(|&(a, b)| a == wx && b == wy) { continue }
            let ww = x > 0 && (wx + gx).rem_euclid(s) == 0 && id[(y + 1) as usize * w + x as usize] == bi;
            let wn = y > 0 && (wy + gy).rem_euclid(s) == 0 && id[y as usize * w + x as usize + 1] == bi;
            if !(ww || wn) { continue }
            let dw = ww && (wy + gy).rem_euclid(s) == s / 2;
            let dn = wn && (wx + gx).rem_euclid(s) == s / 2 &&
                     !(z == 0 && jail == Some(((wx + gx).div_euclid(s), (wy + gy).div_euclid(s))));
            let (xi, yi) = (x as i32, y as i32);
            if ww && wn { let t = wt!(2); self.put(xi, yi, z, t) }
            else if ww {
                if dw { let (a, b) = (self.ti(&fr.0), self.ti(&dr.0)); self.put(xi, yi, z, a); self.put(xi, yi, z, b);
                        doors.push((xi, yi, z)); doors.push((xi - 1, yi, z)) }
                else { let t = wt!(0); self.put(xi, yi, z, t) }
            } else if dn { let (a, b) = (self.ti(&fr.1), self.ti(&dr.1)); self.put(xi, yi, z, a); self.put(xi, yi, z, b);
                           doors.push((xi, yi, z)); doors.push((xi, yi - 1, z)) }
            else { let t = wt!(1); self.put(xi, yi, z, t) }
        }
        doors
    }
    fn names(&self) -> Vec<String> {
        let rm = self.remap();
        self.names.iter().zip(rm).filter(|(_, r)| *r >= 0).map(|(n, _)| n.clone()).collect()
    }
    fn nnames(&self) -> usize { self.names.len() }
    /// SqLog.arrays: (x, y, z, lens, tiles) int32 em bytes, quadrados em ordem de chave
    fn arrays<'py>(&mut self, py: Python<'py>) -> (Bound<'py, PyBytes>, Bound<'py, PyBytes>, Bound<'py, PyBytes>,
                                                   Bound<'py, PyBytes>, Bound<'py, PyBytes>) {
        let (xs, ys, zs, ls, ts) = self.build();
        let b = |v: Vec<i32>| { let mut o = Vec::with_capacity(v.len() * 4); for x in v { o.extend_from_slice(&x.to_le_bytes()) } PyBytes::new(py, &o) };
        (b(xs), b(ys), b(zs), b(ls), b(ts))
    }
}


/// gen.to_rects: quadrados (x, y) -> retangulos (x, y, w, h) juntando faixas iguais de linhas seguidas (mesma ordem)
fn rects_of(c: &[(i32, i32)]) -> Vec<(i32, i32, i32, i32)> {
    let mut v: Vec<(i32, i32)> = c.iter().map(|&(x, y)| (y, x)).collect();
    v.sort_unstable();
    let mut rects = Vec::new();
    let mut open: Vec<((i32, i32), i32, i32)> = Vec::new();     // (faixa, y0, altura) na ordem do dict
    let mut i = 0;
    while i < v.len() {
        let y = v[i].0;
        let mut runs: Vec<(i32, i32)> = Vec::new();
        let (mut s, mut p) = (v[i].1, v[i].1);
        i += 1;
        while i < v.len() && v[i].0 == y {
            let x = v[i].1; i += 1;
            if x == p + 1 { p = x; continue }
            runs.push((s, p)); s = x; p = x;
        }
        runs.push((s, p));
        let mut cur: Vec<((i32, i32), i32, i32)> = Vec::with_capacity(runs.len());
        for r in runs {
            let nv = match open.iter().find(|o| o.0 == r) {
                Some(o) if o.1 + o.2 == y => (r, o.1, o.2 + 1),
                _ => (r, y, 1),
            };
            match cur.iter_mut().find(|c| c.0 == r) { Some(c) => *c = nv, None => cur.push(nv) }
        }
        for o in &open {
            let keep = cur.iter().find(|c| c.0 == o.0).map_or(false, |c| c.1 == o.1);
            if !keep { rects.push((o.0 .0, o.1, o.0 .1 - o.0 .0 + 1, o.2)) }
        }
        open = cur;
    }
    for o in &open { rects.push((o.0 .0, o.1, o.0 .1 - o.0 .0 + 1, o.2)) }
    rects
}

/// bi_cells: ids int32 (h x w) -> (ids unicos int32, inicios int64, ys int64, xs int64), predio a predio em ordem
/// de id e, dentro dele, em ordem de varredura (igual ao argsort estavel + np.unique do Python)
#[pyfunction]
fn bi_groups<'py>(py: Python<'py>, ptr: usize, h: usize, w: usize)
    -> (Bound<'py, PyBytes>, Bound<'py, PyBytes>, Bound<'py, PyBytes>, Bound<'py, PyBytes>) {
    let a = unsafe { std::slice::from_raw_parts(ptr as *const i32, h * w) };
    let mut cnt: std::collections::HashMap<i32, usize, FB> = Default::default();
    for &v in a { *cnt.entry(v).or_insert(0) += 1 }
    let mut u: Vec<i32> = cnt.keys().copied().collect(); u.sort_unstable();
    let mut st: Vec<i64> = Vec::with_capacity(u.len() + 1);
    let mut acc = 0usize;
    for id in &u { st.push(acc as i64); let c = cnt.get_mut(id).unwrap(); let n_ = *c; *c = acc; acc += n_ }
    st.push(acc as i64);
    let (mut ys, mut xs) = (vec![0i64; a.len()], vec![0i64; a.len()]);
    for (i, &v) in a.iter().enumerate() {
        let p = cnt.get_mut(&v).unwrap(); ys[*p] = (i / w) as i64; xs[*p] = (i % w) as i64; *p += 1;
    }
    (le_bytes(py, &u), le_bytes(py, &st), le_bytes(py, &ys), le_bytes(py, &xs))
}

/// Vec numerico -> bytes little-endian (sem copia por elemento)
fn le_bytes<'py, T: Copy>(py: Python<'py>, v: &[T]) -> Bound<'py, PyBytes> {
    PyBytes::new(py, unsafe { std::slice::from_raw_parts(v.as_ptr() as *const u8, std::mem::size_of_val(v)) })
}

#[pyfunction]
fn to_rects(c: Vec<(i32, i32)>) -> Vec<(i32, i32, i32, i32)> { rects_of(&c) }


/// quadrados de um predio num andar agrupados por comodo (chave (gx, gy)), na ordem de 1a aparicao (= dict do gen.py)
#[pyclass(frozen)]
struct Groups { keys: Vec<(i64, i64)>, cells: Vec<Vec<(i32, i32)>> }

#[pymethods]
impl Groups {
    fn keys(&self) -> Vec<(i64, i64)> { self.keys.clone() }
    fn cells(&self, i: usize) -> Vec<(i32, i32)> { self.cells[i].clone() }
    fn size(&self, i: usize) -> usize { self.cells[i].len() }
    fn rects(&self, i: usize) -> Vec<(i32, i32, i32, i32)> { rects_of(&self.cells[i]) }
    /// piso proprio do comodo (ROOM_FLOOR): sq.replace em cada quadrado, na ordem
    fn replace(&self, i: usize, mut cell: PyRefMut<'_, Cell>, z: i32, rf: u32) {
        for &(x, y) in &self.cells[i] { cell.replace(x, y, z, rf) }
    }
}

/// agrupa (xs, ys) por (gx, gy): ponteiros de arrays int64 contiguos de tamanho n
#[pyfunction]
fn group_rooms(px: usize, py_: usize, pgx: usize, pgy: usize, n: usize) -> Groups {
    let f = |p: usize| unsafe { std::slice::from_raw_parts(p as *const i64, n) };
    let (xs, ys, gx, gy) = (f(px), f(py_), f(pgx), f(pgy));
    let mut m: std::collections::HashMap<(i64, i64), usize, FB> = Default::default();
    let (mut keys, mut cells): (Vec<(i64, i64)>, Vec<Vec<(i32, i32)>>) = (vec![], vec![]);
    for j in 0..n {
        let k = (gx[j], gy[j]);
        let i = *m.entry(k).or_insert_with(|| { keys.push(k); cells.push(vec![]); keys.len() - 1 });
        cells[i].push((xs[j] as i32, ys[j] as i32));
    }
    Groups { keys, cells }
}

#[pymodule]
fn _gfpy(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(furn_cand, m)?)?;
    m.add_function(wrap_pyfunction!(isl_mask, m)?)?;
    m.add_function(wrap_pyfunction!(furnish, m)?)?;
    m.add_class::<Kind>()?;
    m.add_class::<Cell>()?;
    m.add_class::<Cat>()?;
    m.add_class::<Groups>()?;
    m.add_function(wrap_pyfunction!(group_rooms, m)?)?;
    m.add_function(wrap_pyfunction!(to_rects, m)?)?;
    m.add_function(wrap_pyfunction!(bi_groups, m)?)?;
    Ok(())
}
