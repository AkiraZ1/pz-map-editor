// Renderizador iso WebGL2: sprites instanciados do atlas reduzido, um buffer por chunk 8x8
// (so os chunks alterados sao refeitos). Ordem de desenho do jogo via profundidade:
// (andar, x+y, x, camada no quadrado) e descarte de alfa.
"use strict";

const ISO = { D: 16, HH: 8, FL: 48 };              // losango 32x16, andar 48 px (escala 1/4)
const JUMBO = ["e_americanlindenJUMBO_1_0", "e_redmapleJUMBO_1_0", "e_yellowwoodJUMBO_1_0", "e_riverbirchJUMBO_1_0",
  "e_americanlindenJUMBO_1_1", "e_redmapleJUMBO_1_1", "e_dogwoodJUMBO_1_0", "e_yellowwoodJUMBO_1_1"];

class Atlas {
  constructor(meta, bitmaps) { this.meta = meta; this.sp = meta.sprites; this.bm = bitmaps; }
  get(name) {
    let e = this.sp[name];
    if (!e && name.startsWith("vegetation_trees_01_")) {
      const n = parseInt(name.slice(20)) || 0;
      e = this.sp[JUMBO[n % JUMBO.length]];
    }
    return e || null;                                // [pagina, x, y, w, h, dx, dy]
  }
  // desenha um tile num contexto 2D com o canto do canvas do quadrado em (px, py)
  draw(ctx, name, px, py, s = 1) {
    const e = this.get(name); if (!e) return;
    ctx.drawImage(this.bm[e[0]], e[1], e[2], e[3], e[4], px + e[5] * s, py + e[6] * s, e[3] * s, e[4] * s);
  }
  // miniatura de um conjunto de pecas [[dx,dy,tile]] (ou nomes) ajustada a w x h
  thumb(canvas, parts, w = 112, h = 112) {
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d");
    const P = parts.map(p => typeof p === "string" ? [0, 0, p, 0] : [p[0], p[1], p[2], p[3] || 0]);
    let l = 1e9, t = 1e9, r = -1e9, b = -1e9;
    for (const [x, y, n, z] of P) {
      const e = this.get(n); if (!e) continue;
      const px = (x - y) * ISO.D - ISO.D + e[5], py = (x + y) * ISO.HH - z * ISO.FL - ISO.FL + e[6];
      l = Math.min(l, px); t = Math.min(t, py); r = Math.max(r, px + e[3]); b = Math.max(b, py + e[4]);
    }
    if (l > r) return;
    const s = Math.min(w / (r - l), h / (b - t), 2.5);
    const ox = (w - (r - l) * s) / 2 - l * s, oy = (h - (b - t) * s) / 2 - t * s;
    ctx.imageSmoothingEnabled = s < 1;
    P.sort((a, c) => a[3] - c[3] || (a[0] + a[1]) - (c[0] + c[1]) || a[0] - c[0]);
    for (const [x, y, n, z] of P) {
      const px = ((x - y) * ISO.D - ISO.D) * s + ox, py = ((x + y) * ISO.HH - z * ISO.FL - ISO.FL) * s + oy;
      this.draw(ctx, n, px, py, s);
    }
  }
}

const VS = `#version 300 es
precision highp float;
layout(location=0) in vec2 corner;
layout(location=1) in vec4 pos;    // x, y, z, camada
layout(location=2) in vec4 uv;     // x, y, w, h no atlas (px)
layout(location=3) in vec3 off;    // dx, dy, pagina
uniform vec2 cam; uniform float zoom; uniform vec2 view; uniform float zmax; uniform float zlo; uniform float s0;
uniform float dimz;
out vec2 vuv; flat out float vpage; out float vdim;
void main() {
  if (pos.z > zmax) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
  float sx = (pos.x - pos.y) * 16.0 - 16.0 + off.x + corner.x * uv.z;
  float sy = (pos.x + pos.y) * 8.0 - pos.z * 48.0 - 48.0 + off.y + corner.y * uv.w;
  vec2 p = (vec2(sx, sy) - cam) * zoom;
  float d = (((pos.z - zlo) * 4096.0 + clamp(pos.x + pos.y - s0, 0.0, 4095.0)) * 2.0 + mod(pos.x, 2.0)) * 8.0 + min(pos.w, 7.0);
  gl_Position = vec4(p.x / view.x * 2.0 - 1.0, 1.0 - p.y / view.y * 2.0, 1.0 - 2.0 * d / 4194304.0, 1.0);
  vuv = uv.xy + corner * uv.zw; vpage = off.z;
  vdim = (pos.z < zmax && dimz > 0.5) ? 0.55 : 1.0;
}`;
const FS = `#version 300 es
precision highp float; precision highp sampler2DArray;
uniform sampler2DArray tex; uniform float page;
in vec2 vuv; flat in float vpage; in float vdim; out vec4 o;
void main() {
  vec4 c = texture(tex, vec3(vuv / page, vpage));
  if (c.a < 0.5) discard;
  o = vec4(c.rgb * vdim, 1.0);
}`;

class IsoGL {
  constructor(canvas, atlas, pageImgs) {
    this.cv = canvas; this.atlas = atlas;
    const gl = this.gl = canvas.getContext("webgl2", { antialias: false, alpha: false, premultipliedAlpha: false });
    if (!gl) throw new Error("WebGL2 indisponivel");
    this.prog = this._prog(VS, FS);
    this.u = {};
    for (const n of ["cam", "zoom", "view", "zmax", "zlo", "s0", "tex", "page", "dimz"]) this.u[n] = gl.getUniformLocation(this.prog, n);
    const P = atlas.meta.page;
    this.tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D_ARRAY, this.tex);
    gl.texStorage3D(gl.TEXTURE_2D_ARRAY, 1, gl.RGBA8, P, P, pageImgs.length);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    pageImgs.forEach((im, i) => gl.texSubImage3D(gl.TEXTURE_2D_ARRAY, 0, 0, 0, i, P, P, 1, gl.RGBA, gl.UNSIGNED_BYTE, im));
    this.setFilter(true);
    gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this.quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
    this.chunks = new Map();          // "cx,cy,ci" -> {vao, buf, n, wx, wy}
    this.cam = { x: 0, y: 0, zoom: 1 };
    this.zmax = 0; this.dim = true; this.ghost = null;
  }
  _prog(vs, fs) {
    const gl = this.gl, p = gl.createProgram();
    for (const [t, s] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]]) {
      const sh = gl.createShader(t); gl.shaderSource(sh, s); gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
      gl.attachShader(p, sh);
    }
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    return p;
  }
  setFilter(linear) {
    const gl = this.gl, f = linear ? gl.LINEAR : gl.NEAREST;
    gl.bindTexture(gl.TEXTURE_2D_ARRAY, this.tex);
    gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_MIN_FILTER, f);
    gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_MAG_FILTER, f);
    this._lin = linear;
  }
  // instancias de uma lista de quadrados [[wx, wy, z, [nomes]]...]
  build(squares) {
    const A = this.atlas, out = [];
    for (const [x, y, z, names] of squares) {
      for (let li = 0; li < names.length; li++) {
        const e = A.get(names[li]); if (!e) continue;
        out.push(x, y, z, li, e[1], e[2], e[3], e[4], e[5], e[6], e[0]);
      }
    }
    return new Float32Array(out);
  }
  _vao(data) {
    const gl = this.gl, vao = gl.createVertexArray(), buf = gl.createBuffer();
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    const S = 44;
    gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.FLOAT, false, S, 0); gl.vertexAttribDivisor(1, 1);
    gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 4, gl.FLOAT, false, S, 16); gl.vertexAttribDivisor(2, 1);
    gl.enableVertexAttribArray(3); gl.vertexAttribPointer(3, 3, gl.FLOAT, false, S, 32); gl.vertexAttribDivisor(3, 1);
    gl.bindVertexArray(null);
    return { vao, buf, n: data.length / 11 };
  }
  setChunk(key, data) {
    this.dropChunk(key);
    if (data.length) this.chunks.set(key, this._vao(data));
  }
  dropChunk(key) {
    const c = this.chunks.get(key); if (!c) return;
    this.gl.deleteBuffer(c.buf); this.gl.deleteVertexArray(c.vao); this.chunks.delete(key);
  }
  dropCell(cx, cy) {
    const pre = `${cx},${cy},`;
    for (const k of [...this.chunks.keys()]) if (k.startsWith(pre)) this.dropChunk(k);
  }
  setGhost(data) {
    if (this.ghost) { this.gl.deleteBuffer(this.ghost.buf); this.gl.deleteVertexArray(this.ghost.vao); this.ghost = null; }
    if (data && data.length) this.ghost = this._vao(data);
  }
  resize() {
    const r = this.cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    this.vw = r.width; this.vh = r.height; this.dpr = dpr;
    this.cv.width = Math.round(r.width * dpr); this.cv.height = Math.round(r.height * dpr);
  }
  // mundo (quadrado) -> tela (px CSS) do centro do losango no andar z
  toScreen(x, y, z = 0) {
    const sx = (x - y) * ISO.D, sy = (x + y) * ISO.HH - z * ISO.FL + ISO.HH;
    return [(sx - this.cam.x) * this.cam.zoom, (sy - this.cam.y) * this.cam.zoom];
  }
  // tela -> quadrado (fracionario) no andar z
  toWorld(px, py, z = 0) {
    const X = px / this.cam.zoom + this.cam.x, Y = py / this.cam.zoom + this.cam.y;
    const u = X / ISO.D, v = (Y + z * ISO.FL - ISO.HH) / ISO.HH;
    return [(u + v) / 2 + 0.5, (v - u) / 2 + 0.5];
  }
  visibleDiag() {
    const z = this.zmax;
    const c = [[0, 0], [this.vw, 0], [0, this.vh], [this.vw, this.vh]].map(([a, b]) => this.toWorld(a, b, z));
    return Math.floor(Math.min(...c.map(p => p[0] + p[1]))) - 8;
  }
  draw() {
    const gl = this.gl;
    gl.viewport(0, 0, this.cv.width, this.cv.height);
    gl.clearColor(0.05, 0.055, 0.063, 1); gl.clearDepth(1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LESS);
    gl.useProgram(this.prog);
    const want = this.cam.zoom < 1;
    if (want !== this._lin) this.setFilter(want);
    gl.uniform2f(this.u.cam, this.cam.x, this.cam.y);
    gl.uniform1f(this.u.zoom, this.cam.zoom);
    gl.uniform2f(this.u.view, this.vw, this.vh);
    gl.uniform1f(this.u.zmax, this.zmax);
    gl.uniform1f(this.u.zlo, Math.min(0, this.zmax) - 16);
    gl.uniform1f(this.u.s0, this.visibleDiag() - 64);
    gl.uniform1f(this.u.page, this.atlas.meta.page);
    gl.uniform1f(this.u.dimz, this.dim ? 1 : 0);
    gl.uniform1i(this.u.tex, 0);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D_ARRAY, this.tex);
    for (const c of this.chunks.values()) {
      gl.bindVertexArray(c.vao); gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, c.n);
    }
    if (this.ghost) {
      gl.clear(gl.DEPTH_BUFFER_BIT);
      gl.bindVertexArray(this.ghost.vao); gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, this.ghost.n);
    }
    gl.bindVertexArray(null);
  }
}

window.Atlas = Atlas; window.IsoGL = IsoGL; window.ISO = ISO;
