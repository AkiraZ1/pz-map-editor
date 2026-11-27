"""Passo final do instalador do J' PZ MAP STUDIO. Roda com o Python portatil ja extraido.

1. instala as wheels prontas (versao fixa + sha256, --require-hashes, nada e compilado);
2. copia o app/ para junto do runtime e pre-compila os .pyc;
3. monta SO o executavel local:
   - Mac: "J' PZ MAP STUDIO.app" (Info.plist, icone, Contents/MacOS/jpzmapstudio);
   - Windows: "J' PZ MAP STUDIO.exe" = launcher pronto do distlib (w64.exe, que ja vem no pip)
     + shebang para o pythonw.exe + zip com __main__.py (nada de compilador).

Uso (os instaladores chamam):
  python -I launcher/build.py --target mac-arm64 --src <pasta do pacote> --bundle <stage/X.app>
  python -I launcher/build.py --target win-x64   --src <pasta do pacote> --home <pasta de instalacao>
"""
import argparse
import compileall
import io
import os
import plistlib
import shutil
import subprocess
import sys
import zipfile

APP_NAME = "J' PZ MAP STUDIO"
APP_ID = "jpzmapstudio"
BUNDLE_ID = "io.github.jpzmapstudio"
CREDIT = "J' PZ MAP STUDIO — criado por Jemerson Barros"
SKIP_DIRS = {"__pycache__", ".git", ".DS_Store", "graft", ".trail"}


def log(msg):
    print(f"[build] {msg}", flush=True)


def app_version(src):
    ns = {}
    with open(os.path.join(src, "app", "pzms", "__init__.py"), encoding="utf-8") as f:
        exec(f.read(), ns)          # noqa: S102 - arquivo do proprio pacote
    return ns.get("__version__", "0.0.0")


def pip_install(src, target):
    req = os.path.join(src, "tools", f"requirements-{target}.txt")
    vendor = os.path.join(src, "tools", "vendor")
    wheels = os.path.join(src, "wheels", target)
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
           "--no-deps", "--require-hashes", "--only-binary=:all:", "--no-compile",
           "--find-links", vendor, "-r", req]
    if os.path.isdir(wheels):
        cmd[4:4] = ["--no-index", "--find-links", wheels]
        log(f"instalando wheels do pacote ({wheels})")
    else:
        log("wheels nao vieram no pacote: baixando do PyPI (mesmas versoes e hashes)")
    subprocess.check_call(cmd)
    subprocess.check_call([sys.executable, "-c", "import numpy, PIL, webview, bottle, proxy_tools"])


def copy_app(src, dest_app):
    if os.path.isdir(dest_app):
        shutil.rmtree(dest_app)

    def ignore(d, names):
        return [n for n in names if n in SKIP_DIRS or n.endswith((".pyc", ".pyo"))]
    shutil.copytree(os.path.join(src, "app"), dest_app, ignore=ignore)
    compileall.compile_dir(dest_app, quiet=1)
    compileall.compile_dir(os.path.dirname(os.path.dirname(os.__file__)), quiet=1)  # stdlib + site-packages


def make_icon_png(size=1024):
    """icone desenhado aqui (nada do jogo): losango isometrico + J'."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = size
    d.rounded_rectangle((s * .06, s * .06, s * .94, s * .94), radius=s * .2, fill=(21, 23, 26, 255))
    cx, cy, w, h = s * .5, s * .62, s * .36, s * .18
    top = [(cx, cy - h), (cx + w, cy), (cx, cy + h), (cx - w, cy)]
    d.polygon(top, fill=(94, 140, 72, 255))
    d.polygon([(cx - w, cy), (cx, cy + h), (cx, cy + h + s * .08), (cx - w, cy + s * .08)], fill=(70, 98, 56, 255))
    d.polygon([(cx + w, cy), (cx, cy + h), (cx, cy + h + s * .08), (cx + w, cy + s * .08)], fill=(52, 74, 44, 255))
    for i in range(1, 4):
        t = i / 4
        d.line([(cx - w + w * t, cy - h * t), (cx + w * t, cy + h - h * t)], fill=(21, 23, 26, 90), width=max(2, s // 200))
        d.line([(cx + w - w * t, cy - h * t), (cx - w * t, cy + h - h * t)], fill=(21, 23, 26, 90), width=max(2, s // 200))
    try:
        font = ImageFont.load_default(size=int(s * .30))
    except TypeError:
        font = ImageFont.load_default()
    d.text((s * .5, s * .30), "J'", font=font, fill=(232, 196, 92, 255), anchor="mm")
    return im


def build_mac(src, bundle, version):
    c = os.path.join(bundle, "Contents")
    res = os.path.join(c, "Resources")
    macos = os.path.join(c, "MacOS")
    os.makedirs(macos, exist_ok=True)
    copy_app(src, os.path.join(res, "app"))
    make_icon_png().save(os.path.join(res, "icon.icns"))
    info = {
        "CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID, "CFBundleExecutable": APP_ID,
        "CFBundleIconFile": "icon.icns", "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version, "CFBundleVersion": version,
        "CFBundleInfoDictionaryVersion": "6.0", "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True, "NSHumanReadableCopyright": CREDIT,
        "LSApplicationCategoryType": "public.app-category.developer-tools",
    }
    with open(os.path.join(c, "Info.plist"), "wb") as f:
        plistlib.dump(info, f)
    # o binario do Python vai copiado para dentro de Contents/MacOS: assim o processo E o .app
    # (nome e icone certos no Dock/menu). O PYTHONHOME aponta o runtime em Resources/python.
    real = os.path.realpath(sys.executable)
    shutil.copy2(real, os.path.join(macos, f"{APP_ID}-python"))
    sh = f"""#!/bin/sh
# {APP_NAME} {version} - gerado pelo instalador nesta maquina
C="$(cd "$(dirname "$0")/.." && pwd)"
R="$C/Resources"
export PYTHONHOME="$R/python"
unset PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE
LOGD="$HOME/Library/Logs/{APP_ID}"
mkdir -p "$LOGD"
cd "$R/app" || exit 1
exec "$C/MacOS/{APP_ID}-python" -s -m pzms.main "$@" >>"$LOGD/app.log" 2>&1
"""
    p = os.path.join(macos, APP_ID)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(sh)
    os.chmod(p, 0o755)
    log(f"bundle pronto: {bundle}")


WIN_MAIN = r'''# {name} - gerado pelo instalador nesta maquina
import os, runpy, sys
base = os.path.dirname(os.path.abspath(sys.argv[0]))
app = os.path.join(base, "app")
logd = os.path.join(os.environ.get("LOCALAPPDATA") or base, "{app_id}", "logs")
try:
    os.makedirs(logd, exist_ok=True)
    _log = open(os.path.join(logd, "app.log"), "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = _log
    if sys.stderr is None:
        sys.stderr = _log
except OSError:
    pass
sys.path.insert(0, app)
os.chdir(app)
sys.argv[0] = os.path.join(app, "pzms", "main.py")
runpy.run_module("pzms.main", run_name="__main__", alter_sys=True)
'''


def win_launcher_stub():
    import pip._vendor.distlib as dl
    p = os.path.join(os.path.dirname(dl.__file__), "w64.exe")
    with open(p, "rb") as f:
        return f.read()


def build_win(src, home, version):
    copy_app(src, os.path.join(home, "app"))
    ico = os.path.join(home, "icon.ico")
    make_icon_png(256).save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    pyw = os.path.join(home, "python", "pythonw.exe")
    shebang = ('#!"%s"\r\n' % pyw).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("__main__.py", WIN_MAIN.format(name=APP_NAME, app_id=APP_ID))
    exe = os.path.join(home, f"{APP_NAME}.exe")
    data = win_launcher_stub() + shebang + buf.getvalue()
    tmp = exe + ".new"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, exe)
    log(f"executavel pronto: {exe}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, choices=["mac-arm64", "mac-x64", "win-x64"])
    ap.add_argument("--src", required=True)
    ap.add_argument("--bundle")
    ap.add_argument("--home")
    ap.add_argument("--skip-pip", action="store_true")
    a = ap.parse_args()
    src = os.path.abspath(a.src)
    ver = app_version(src)
    if not a.skip_pip:
        pip_install(src, a.target)
    if a.target.startswith("mac"):
        build_mac(src, os.path.abspath(a.bundle), ver)
    else:
        build_win(src, os.path.abspath(a.home), ver)
    return 0


if __name__ == "__main__":
    sys.exit(main())
