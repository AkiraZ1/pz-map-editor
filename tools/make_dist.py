"""Monta o zip de distribuicao do J' PZ MAP STUDIO.

Conteudo: app/ (fontes), install.command, install.cmd, install.ps1, launcher/, os locks
tools/requirements-*.txt, tools/vendor/ e wheels/<alvo>/ (as wheels prontas, ja conferidas pelo hash).
Fica de fora: caches, __pycache__/.pyc, .DS_Store, graft/, .trail/ e QUALQUER coisa do jogo
(.pack, .lotpack, .lotheader, chunkdata, .tbx, .lot, sprites): o app le os assets da instalacao
do proprio usuario.

Uso: python tools/make_dist.py [--no-wheels] [--targets mac-arm64,mac-x64,win-x64] [--out dist]
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = ["mac-arm64", "mac-x64", "win-x64"]
TOP_FILES = ["install.command", "install.cmd", "install.ps1"]
SKIP_DIRS = {"__pycache__", ".git", ".cache", "graft", ".trail", "dist", "node_modules", ".pytest_cache"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}
# extensoes que so podem vir do jogo: o pacote nunca pode carregar nenhuma
GAME_EXT = (".pack", ".lotpack", ".lotheader", ".tbx", ".lot", ".tiles", ".bin", ".zpop")
GAME_NAME = re.compile(r"^(chunkdata_|map_|world_|zpop_)|\.lotpack$|^\d+_\d+\.lotheader$", re.I)
EXEC = {"install.command"}
DATE = (2026, 1, 1, 0, 0, 0)          # data fixa: zip reproduzivel


def version():
    ns = {}
    with open(os.path.join(ROOT, "app", "pzms", "__init__.py"), encoding="utf-8") as f:
        exec(f.read(), ns)            # noqa: S102
    return ns["__version__"]


def walk(base):
    for d, dirs, files in os.walk(base):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(files):
            if f in SKIP_FILES or f.endswith((".pyc", ".pyo")):
                continue
            yield os.path.join(d, f)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def lock_hashes(target):
    out = {}
    with open(os.path.join(ROOT, "tools", f"requirements-{target}.txt"), encoding="utf-8") as f:
        for ln in f:
            m = re.match(r"(\S+)==(\S+) --hash=sha256:([0-9a-f]{64})", ln)
            if m:
                out[m.group(3)] = m.group(1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-wheels", action="store_true", help="sem wheels (o instalador baixa do PyPI)")
    ap.add_argument("--targets", default=",".join(TARGETS))
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    a = ap.parse_args()
    targets = [t for t in a.targets.split(",") if t]
    ver = version()
    top = f"J' PZ MAP STUDIO {ver}"
    files = []                         # (origem, nome no zip)
    for f in TOP_FILES:
        files.append((os.path.join(ROOT, f), f))
    for sub in ("app", "launcher"):
        for p in walk(os.path.join(ROOT, sub)):
            files.append((p, os.path.relpath(p, ROOT)))
    for t in TARGETS:
        files.append((os.path.join(ROOT, "tools", f"requirements-{t}.txt"), f"tools/requirements-{t}.txt"))
    for p in walk(os.path.join(ROOT, "tools", "vendor")):
        files.append((p, os.path.relpath(p, ROOT)))
    if not a.no_wheels:
        subprocess.check_call([sys.executable, os.path.join(ROOT, "tools", "lock_wheels.py"), "--check"])
        for t in targets:
            want = lock_hashes(t)
            d = os.path.join(ROOT, ".cache", "wheels", t)
            got = set()
            for p in walk(d):
                h = sha256(p)
                if h in want:          # so entra wheel que esta no lock (com o hash certo)
                    files.append((p, f"wheels/{t}/{os.path.basename(p)}"))
                    got.add(h)
            vend = {sha256(p) for p in walk(os.path.join(ROOT, "tools", "vendor"))}
            missing = [n for h, n in want.items() if h not in got and h not in vend]
            if missing:
                sys.exit(f"{t}: faltam wheels {missing}; rode tools/lock_wheels.py")
    bad = [n for _, n in files
           if n.lower().endswith(GAME_EXT) or GAME_NAME.search(os.path.basename(n))]
    if bad:
        sys.exit(f"arquivos que parecem do jogo no pacote (nao pode): {bad[:10]}")
    for p, n in files:
        if not os.path.isfile(p):
            sys.exit(f"falta {n}")
    os.makedirs(a.out, exist_ok=True)
    zpath = os.path.join(a.out, f"jpzmapstudio-{ver}.zip")
    tmp = zpath + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p, n in sorted(files, key=lambda x: x[1]):
            zi = zipfile.ZipInfo(f"{top}/{n}", DATE)
            zi.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if n in EXEC else 0o644
            zi.external_attr = (0o100000 | mode) << 16
            zi.create_system = 3       # unix: o unzip/Arquivador do Mac respeita o +x
            with open(p, "rb") as f:
                data = f.read()
            if n.endswith((".cmd",)):
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")   # cmd.exe quer CRLF
            z.writestr(zi, data)
    os.replace(tmp, zpath)
    size = os.path.getsize(zpath) / 1e6
    print(f"{zpath}  ({len(files)} arquivos, {size:.1f} MB, alvos: {', '.join(targets) if not a.no_wheels else 'sem wheels'})")
    print(f"sha256 {sha256(zpath)}")
    return 0


if __name__ == "__main__":
    t0 = time.time()
    sys.exit(main())
