"""Gera os locks de wheels (versao fixa + sha256) por alvo e baixa as wheels em .cache/wheels/<alvo>.
So o dono roda isto (na maquina de desenvolvimento). O usuario final nunca compila nada:
o instalador instala exatamente estas wheels, com --require-hashes.

Uso: python tools/lock_wheels.py            (baixa + escreve tools/requirements-<alvo>.txt)
     python tools/lock_wheels.py --check    (so confere os hashes das wheels ja baixadas)
"""
import argparse
import hashlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYVER = "3.12"

COMMON = ["numpy==2.5.5", "pillow==13.0.0", "pywebview==6.2.1", "bottle==0.13.4",
          "typing_extensions==4.16.0"]
MAC = ["pyobjc-core==13.1", "pyobjc-framework-Cocoa==13.1", "pyobjc-framework-Quartz==13.1",
       "pyobjc-framework-WebKit==13.1", "pyobjc-framework-Security==13.1",
       "pyobjc-framework-UniformTypeIdentifiers==13.1"]
WIN = ["pythonnet==3.2.1", "clr_loader==0.3.1", "cffi==2.1.1", "pycparser==3.12"]

# alvo -> (plataforma da wheel, lista)
TARGETS = {
    "mac-arm64": ("macosx_11_0_arm64", COMMON + MAC),
    "mac-x64": ("macosx_10_13_x86_64", COMMON + MAC),
    "win-x64": ("win_amd64", COMMON + WIN),
}
# proxy_tools (dep do pywebview) so existe como sdist no PyPI: a wheel pura (py3-none-any)
# foi construida uma vez e vai versionada em tools/vendor.
VENDOR = os.path.join(ROOT, "tools", "vendor")


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def norm(n):
    return n.lower().replace("-", "_").replace(".", "_")


def build_vendor():
    os.makedirs(VENDOR, exist_ok=True)
    if not any(f.startswith("proxy_tools-") for f in os.listdir(VENDOR)):
        subprocess.check_call([sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", VENDOR,
                               "proxy_tools==0.1.0"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    build_vendor()
    vend = [os.path.join(VENDOR, f) for f in os.listdir(VENDOR) if f.endswith(".whl")]
    for tgt, (plat, reqs) in TARGETS.items():
        d = os.path.join(ROOT, ".cache", "wheels", tgt)
        os.makedirs(d, exist_ok=True)
        if not a.check:
            subprocess.check_call([sys.executable, "-m", "pip", "download", "-q", "--no-deps",
                                   "--only-binary=:all:", "--platform", plat, "--python-version", PYVER,
                                   "--implementation", "cp", "-d", d] + reqs)
        files = {}
        for f in os.listdir(d):
            if f.endswith(".whl"):
                files.setdefault(norm(f.split("-")[0]), []).append(os.path.join(d, f))
        lines = [f"# lock {tgt} ({plat}, CPython {PYVER}) gerado por tools/lock_wheels.py - nao editar a mao"]
        for r in reqs + ["proxy_tools==0.1.0"]:
            name, ver = r.split("==")
            got = [p for p in files.get(norm(name), []) if f"-{ver}-" in os.path.basename(p)]
            if norm(name) == "proxy_tools":
                got = [p for p in vend if os.path.basename(p).startswith("proxy_tools-")]
            if len(got) != 1:
                sys.exit(f"{tgt}: esperava 1 wheel de {r}, achei {got}")
            lines.append(f"{name}=={ver} --hash=sha256:{sha256(got[0])}")
        out = os.path.join(ROOT, "tools", f"requirements-{tgt}.txt")
        txt = "\n".join(lines) + "\n"
        if a.check:
            with open(out) as f:
                if f.read() != txt:
                    sys.exit(f"{out} difere das wheels baixadas")
        else:
            with open(out, "w") as f:
                f.write(txt)
        print(f"{tgt}: {len(lines) - 1} wheels ok")


if __name__ == "__main__":
    main()
