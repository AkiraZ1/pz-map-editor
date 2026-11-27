"""Compila os modulos Rust do spgen para os 3 alvos do dist e grava em app/pzms/spgen/bin/<alvo>/.

  mac-arm64  aarch64-apple-darwin     _genfast_rs.so   _gfpy.so
  mac-x64    x86_64-apple-darwin      _genfast_rs.so   _gfpy.so
  win-x64    x86_64-pc-windows-gnu    _genfast_rs.dll  _gfpy.pyd

Precisa: cargo + rustup target add x86_64-apple-darwin x86_64-pc-windows-gnu, e o linker mingw-w64
(brew install mingw-w64). O _gfpy e abi3 (Python >= 3.9), entao um binario serve para qualquer Python do alvo.

Uso: python tools/build_rust.py [--targets mac-arm64,mac-x64,win-x64]
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SP = os.path.join(ROOT, "app", "pzms", "spgen")
T = {"mac-arm64": "aarch64-apple-darwin", "mac-x64": "x86_64-apple-darwin", "win-x64": "x86_64-pc-windows-gnu"}
# (pasta do crate, nome do artefato do cargo sem prefixo/extensao, nome final sem extensao)
CRATES = [("genfast_rs", "genfast", "_genfast_rs"), ("genfast_py", "_gfpy", "_gfpy")]


def artifact(triple, stem):
    if "windows" in triple:
        return f"{stem}.dll"
    return f"lib{stem}.dylib"


def final(alvo, name, py):
    if alvo.startswith("win"):
        return name + (".pyd" if py else ".dll")
    return name + ".so"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=",".join(T))
    a = ap.parse_args()
    env = dict(os.environ, PYO3_PYTHON=sys.executable)
    if shutil.which("x86_64-w64-mingw32-gcc"):
        env["CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER"] = "x86_64-w64-mingw32-gcc"
    for alvo in a.targets.split(","):
        triple = T[alvo]
        out = os.path.join(SP, "bin", alvo)
        os.makedirs(out, exist_ok=True)
        e = dict(env)
        if alvo.startswith("win"):
            e["PYO3_CROSS"] = "1"          # abi3 + generate-import-lib: nao precisa de Python do Windows
        for crate, stem, name in CRATES:
            d = os.path.join(SP, crate)
            subprocess.run(["cargo", "build", "--release", "--quiet", "--target", triple], cwd=d, env=e, check=True)
            src = os.path.join(d, "target", triple, "release", artifact(triple, stem))
            dst = os.path.join(out, final(alvo, name, crate == "genfast_py"))
            shutil.copy(src, dst + ".tmp")
            os.replace(dst + ".tmp", dst)
            print(alvo, os.path.relpath(dst, ROOT), os.path.getsize(dst))


if __name__ == "__main__":
    main()
