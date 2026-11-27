//! Mesmas rotinas de scripts/genfast.c, em Rust (ABI C, carregadas por ctypes em scripts/genfast.py).
//! Compilar: cargo build --release --manifest-path scripts/genfast_rs/Cargo.toml
use std::slice;

#[no_mangle]
pub unsafe extern "C" fn max_rect(m: *const u8, h: i32, w: i32, out: *mut i32) -> i32 {
    let (h, w) = (h as usize, w as usize);
    let m = slice::from_raw_parts(m, h * w);
    let out = slice::from_raw_parts_mut(out, 4);
    let mut hist = vec![0i32; w];
    let mut ss: Vec<i32> = Vec::with_capacity(w + 1);
    let mut sh: Vec<i32> = Vec::with_capacity(w + 1);
    let mut best: i64 = 0;
    let mut found = 0;
    for y in 0..h {
        let row = &m[y * w..(y + 1) * w];
        for x in 0..w {
            hist[x] = if row[x] != 0 { hist[x] + 1 } else { 0 };
        }
        ss.clear();
        sh.clear();
        for x in 0..=w {
            let hh = if x < w { hist[x] } else { 0 };
            let mut start = x as i32;
            while let Some(&top) = sh.last() {
                if top < hh {
                    break;
                }
                let s0 = ss.pop().unwrap();
                sh.pop();
                let a = top as i64 * (x as i64 - s0 as i64);
                if a > best {
                    best = a;
                    found = 1;
                    out[0] = y as i32 - top + 1;
                    out[1] = s0;
                    out[2] = y as i32 + 1;
                    out[3] = x as i32;
                }
                start = s0;
            }
            ss.push(start);
            sh.push(hh);
        }
    }
    found
}

#[no_mangle]
pub unsafe extern "C" fn poly_area(xy: *const f64, n: i32) -> f64 {
    let n = n as usize;
    let p = slice::from_raw_parts(xy, 2 * n);
    let (mut s, mut c) = (0f64, 0f64);
    for i in 0..n {
        let j = (i + 1) % n;
        let x = p[2 * i] * p[2 * j + 1] - p[2 * j] * p[2 * i + 1];
        let t = s + x;
        if s.abs() >= x.abs() { c += (s - t) + x } else { c += (x - t) + s }
        s = t;
    }
    if c != 0.0 && c.is_finite() {
        s += c;
    }
    s.abs() / 2.0
}

#[no_mangle]
pub unsafe extern "C" fn lotpack_body(n: i32, xs: *const i32, ys: *const i32, zs: *const i32, lens: *const i32,
                                      tiles: *const i32, zmin: i32, zmax: i32, base: i64, offs: *mut i64,
                                      body: *mut i32) -> i64 {
    let n = n as usize;
    let (xs, ys, zs, lens) = (slice::from_raw_parts(xs, n), slice::from_raw_parts(ys, n),
                              slice::from_raw_parts(zs, n), slice::from_raw_parts(lens, n));
    let ntiles: usize = lens.iter().map(|&l| l as usize).sum();
    let tiles = slice::from_raw_parts(tiles, ntiles);
    let offs = slice::from_raw_parts_mut(offs, 1024);
    let body = slice::from_raw_parts_mut(body, 4 * n + ntiles + 2048);
    let tot = (zmax - zmin + 1) as i64 * 64;
    let mut ent: Vec<(i64, usize, usize)> = Vec::with_capacity(n); // (chave, inicio dos tiles, i)
    let mut acc = 0usize;
    for i in 0..n {
        let ci = ((xs[i] >> 3) * 32 + (ys[i] >> 3)) as i64;
        let k = (zs[i] - zmin) as i64 * 64 + ((xs[i] & 7) * 8 + (ys[i] & 7)) as i64;
        ent.push((ci * (tot + 1) + k, acc, i));
        acc += lens[i] as usize;
    }
    ent.sort_unstable_by_key(|e| e.0);
    let mut p = 0usize;
    let mut j = 0usize;
    for c in 0..1024i64 {
        offs[c as usize] = base + 4 * p as i64;
        let mut prev = 0i64;
        while j < n && ent[j].0 / (tot + 1) == c {
            let (key, t0, i) = ent[j];
            j += 1;
            let k = key % (tot + 1);
            if k > prev {
                body[p] = -1;
                body[p + 1] = (k - prev) as i32;
                p += 2;
            }
            let l = lens[i] as usize;
            body[p] = l as i32 + 1;
            body[p + 1] = -1;
            p += 2;
            body[p..p + l].copy_from_slice(&tiles[t0..t0 + l]);
            p += l;
            prev = k + 1;
        }
        if tot > prev {
            body[p] = -1;
            body[p + 1] = (tot - prev) as i32;
            p += 2;
        }
    }
    p as i64
}

/// chao z0 do write_cell (mesmos codigos de genfast.c::ground_z0).
#[no_mangle]
pub unsafe extern "C" fn ground_z0(cs: i32, b: *const i32, fl: *const i32, g: *const u8, gw: *const u8, tr: *const u8,
                                   hh: *const u32, wx0: i64, wy0: i64, ntree: i32, o1: *mut i16, o2: *mut i16) {
    let cs = cs as usize;
    let w2 = cs + 2;
    let (b, g, gw, tr, hh) = (slice::from_raw_parts(b, w2 * w2), slice::from_raw_parts(g, cs * cs),
                              slice::from_raw_parts(gw, w2 * w2), slice::from_raw_parts(tr, cs * cs),
                              slice::from_raw_parts(hh, cs * cs));
    let (o1, o2) = (slice::from_raw_parts_mut(o1, cs * cs), slice::from_raw_parts_mut(o2, cs * cs));
    const GA: u8 = 1; const GS: u8 = 2; const GGR: u8 = 3; const GWO: u8 = 4; const GPA: u8 = 5;
    const GYA: u8 = 6; const GPK: u8 = 7; const GWA: u8 = 8;
    for y in 0..cs {
        for x in 0..cs {
            let i = y * cs + x;
            let h = hh[i];
            let bi = b[(y + 1) * w2 + x + 1];
            let (mut a, mut bb): (i32, i32) = (-1, -1);
            if bi != 0 {
                let f = *fl.add(bi as usize);
                a = if f < 0 { 16 + (h & 1) as i32 } else { f };
            } else {
                let c = g[i];
                let tree = 32 + ((h >> 5) % 7) as i32;
                match c {
                    GA => a = (h & 7) as i32,
                    GS => {
                        a = 8 + ((h >> 3) & 7) as i32;
                        let t = gw[y * w2 + x + 1] == GA || gw[(y + 2) * w2 + x + 1] == GA
                            || gw[(y + 1) * w2 + x] == GA || gw[(y + 1) * w2 + x + 2] == GA;
                        if t {
                            if ((wx0 + x as i64) * 3 + (wy0 + y as i64) * 5).rem_euclid(23) == 0 { bb = 39 }
                        } else if tr[i] != 0 || (ntree == 0 && h % 13 == 0) { bb = tree }
                    }
                    GPA => a = 16 + ((h >> 2) & 1) as i32,
                    GYA => a = 18 + ((h >> 2) & 1) as i32,
                    GPK | GGR => { a = 20 + (h & 3) as i32; if c == GPK && h % 9 == 0 { bb = tree } }
                    GWA => a = 28 + (h & 3) as i32,
                    GWO => { a = 24 + (h & 3) as i32; if h % 3 == 0 { bb = tree } }
                    _ => a = 20 + (h & 3) as i32,
                }
            }
            o1[i] = a as i16;
            o2[i] = bb as i16;
        }
    }
}

/// rectify do gen.py para um predio: ba (int32, linhas de `stride`), caixa (y0, x0, h, w), rotulo lab.
/// Ate 4 retangulos maximos cobrem o predio; o que sobra vira 0. Mesmos cortes e desempates do Python.
#[no_mangle]
pub unsafe extern "C" fn rectify_one(ba: *mut i32, stride: i64, y0: i32, x0: i32, h: i32, w: i32, lab: i32) {
    let (h, w) = (h as usize, w as usize);
    let base = ba.offset((y0 as i64 * stride + x0 as i64) as isize);
    let at = |y: usize, x: usize| base.offset((y as i64 * stride + x as i64) as isize);
    let mut m = vec![0u8; h * w];
    let mut n0: i64 = 0;
    for y in 0..h {
        for x in 0..w {
            if *at(y, x) == lab {
                m[y * w + x] = 1;
                n0 += 1;
            }
        }
    }
    if n0 < 16 {
        return;
    }
    let mut rem = m.clone();
    let mut cov = vec![0u8; h * w];
    let mut remn = n0;
    let mut r = [0i32; 4];
    for k in 0..4 {
        if max_rect(rem.as_ptr(), h as i32, w as i32, r.as_mut_ptr()) == 0 {
            break;
        }
        let (ry0, rx0, ry1, rx1) = (r[0] as usize, r[1] as usize, r[2] as usize, r[3] as usize);
        let area = ((ry1 - ry0) * (rx1 - rx0)) as f64;
        if (ry1 - ry0).min(rx1 - rx0) < 3 || (k > 0 && area < f64::max(16.0, 0.12 * n0 as f64)) {
            break;
        }
        for y in ry0..ry1 {
            for x in rx0..rx1 {
                cov[y * w + x] = 1;
                if rem[y * w + x] != 0 {
                    rem[y * w + x] = 0;
                    remn -= 1;
                }
            }
        }
        if (remn as f64) < 0.08 * n0 as f64 {
            break;
        }
    }
    for y in 0..h {
        for x in 0..w {
            if m[y * w + x] != 0 && cov[y * w + x] == 0 {
                *at(y, x) = 0;
            }
        }
    }
}

// ---- geometria dos predios em lote (build_rasters), bit a bit igual ao Python 3.12+ ----
// sum() de floats do CPython: soma compensada de Neumaier
#[inline]
fn nsum(it: impl Iterator<Item = f64>) -> f64 {
    let (mut s, mut c) = (0f64, 0f64);
    for x in it {
        let t = s + x;
        if s.abs() >= x.abs() { c += (s - t) + x } else { c += (x - t) + s }
        s = t;
    }
    if c != 0.0 && c.is_finite() { s += c }
    s
}

// math.hypot(x, y) do CPython (vector_norm: escala por potencia de 2, quadrados exatos, correcao diferencial)
#[inline]
fn py_hypot(x: f64, y: f64) -> f64 {
    let (ax, ay) = (x.abs(), y.abs());
    if ax.is_infinite() || ay.is_infinite() { return f64::INFINITY }
    if ax.is_nan() || ay.is_nan() { return f64::NAN }
    let mx = ax.max(ay);
    if mx == 0.0 { return mx }
    let bits = mx.to_bits();
    let ef = ((bits >> 52) & 0x7ff) as i64;
    if ef == 0 { return (x * x + y * y).sqrt() }     // subnormal: nao ocorre em coordenadas
    let e = ef - 1022;                                 // frexp: mx = m * 2^e, m em [0.5, 1)
    let scale = f64::from_bits(((1023 - e) as u64) << 52);
    let (mut csum, mut f1, mut f2) = (1.0f64, 0f64, 0f64);
    for v in [ax, ay] {
        let v = v * scale;
        let hi = v * v; let lo = v.mul_add(v, -hi);
        let s = csum + hi; let sl = (csum - s) + hi;
        csum = s; f1 += lo; f2 += sl;
    }
    let mut h = (csum - 1.0 + (f1 + f2)).sqrt();
    let hi = -h * h; let lo = (-h).mul_add(h, -hi);
    let s = csum + hi; let sl = (csum - s) + hi;
    csum = s; f1 += lo; f2 += sl;
    let x = csum - 1.0 + (f1 + f2);
    h += x / (2.0 * h);
    h / scale
}

fn area_of(p: &[f64]) -> f64 {
    let n = p.len() / 2;
    if n == 0 { return 0.0 }
    nsum((0..n).map(|i| { let j = (i + 1) % n; p[2 * i] * p[2 * j + 1] - p[2 * j] * p[2 * i + 1] })).abs() / 2.0
}

/// por anel k (pontos xy[offs[k]..offs[k+1]]): out[3k..] = (area, cx, cy) como poly_area() e sum(p[0])/len
#[no_mangle]
pub unsafe extern "C" fn ring_stats(xy: *const f64, offs: *const i64, nobj: i32, out: *mut f64) {
    let offs = slice::from_raw_parts(offs, nobj as usize + 1);
    let all = slice::from_raw_parts(xy, 2 * offs[nobj as usize] as usize);
    let out = slice::from_raw_parts_mut(out, 3 * nobj as usize);
    for k in 0..nobj as usize {
        let p = &all[2 * offs[k] as usize..2 * offs[k + 1] as usize];
        let n = p.len() / 2;
        out[3 * k] = area_of(p);
        if n > 0 {
            out[3 * k + 1] = nsum((0..n).map(|i| p[2 * i])) / n as f64;
            out[3 * k + 2] = nsum((0..n).map(|i| p[2 * i + 1])) / n as f64;
        }
    }
}

/// por predio k: anel fechado em xy[offs[k]..offs[k+1]], os nop[k] primeiros sao o contorno aberto `o`.
/// oxy recebe snap_poly(fechado); out[5k..] = (girou?, perimetro, poly_area(fechado[:-1]), cx(o), cy(o))
#[no_mangle]
pub unsafe extern "C" fn bld_geom(xy: *const f64, offs: *const i64, nop: *const i32, nobj: i32, oxy: *mut f64, out: *mut f64) {
    let nb = nobj as usize;
    let offs = slice::from_raw_parts(offs, nb + 1);
    let nop = slice::from_raw_parts(nop, nb);
    let tot = 2 * offs[nb] as usize;
    let all = slice::from_raw_parts(xy, tot);
    let oall = slice::from_raw_parts_mut(oxy, tot);
    let out = slice::from_raw_parts_mut(out, 5 * nb);
    let r2d = 180.0 / std::f64::consts::PI;
    for k in 0..nb {
        let (a, b) = (2 * offs[k] as usize, 2 * offs[k + 1] as usize);
        let p = &all[a..b];
        let o = &mut oall[a..b];
        let n = p.len() / 2;
        o.copy_from_slice(p);
        let mut rot = 0.0;
        if n >= 4 {
            let (mut num, mut den) = (0f64, 0f64);
            for i in 0..n - 1 {
                let (dx, dy) = (p[2 * i + 2] - p[2 * i], p[2 * i + 3] - p[2 * i + 1]);
                let l = py_hypot(dx, dy);
                if l < 1e-6 { continue }
                let an = dy.atan2(dx) * 4.0;
                num += l * an.sin(); den += l * std::hint::black_box(an).cos();   // sem fundir em __sincos (1 ulp != do Python)
            }
            let al = num.atan2(den) / 4.0;
            if !((al * r2d).abs() > 20.0 || al.abs() < 1e-3) {
                let cx = nsum((0..n).map(|i| p[2 * i])) / n as f64;
                let cy = nsum((0..n).map(|i| p[2 * i + 1])) / n as f64;
                let (c, s) = ((-al).cos(), std::hint::black_box(-al).sin());
                for i in 0..n {
                    let (x, y) = (p[2 * i], p[2 * i + 1]);
                    o[2 * i] = cx + (x - cx) * c - (y - cy) * s;
                    o[2 * i + 1] = cy + (x - cx) * s + (y - cy) * c;
                }
                rot = 1.0;
            }
        }
        out[5 * k] = rot;
        out[5 * k + 1] = nsum((0..n.saturating_sub(1)).map(|i| py_hypot(p[2 * i + 2] - p[2 * i], p[2 * i + 3] - p[2 * i + 1])));
        out[5 * k + 2] = area_of(&p[..2 * n.saturating_sub(1)]);
        let m = nop[k] as usize;
        out[5 * k + 3] = nsum((0..m).map(|i| p[2 * i])) / m as f64;
        out[5 * k + 4] = nsum((0..m).map(|i| p[2 * i + 1])) / m as f64;
    }
}
