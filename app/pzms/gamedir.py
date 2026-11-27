"""Localiza a instalacao do Project Zomboid (Steam) no Mac e no Windows, e as pastas do app."""
import json
import os
import re
import sys

APP = "jpzmapstudio"
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"


def data_dir():
    """pasta de dados do usuario (config, cache, projetos)."""
    if os.environ.get("PZMS_HOME"):
        d = os.environ["PZMS_HOME"]
    elif IS_WIN:
        d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP)
    elif IS_MAC:
        d = os.path.expanduser(f"~/Library/Application Support/{APP}")
    else:
        d = os.path.expanduser(f"~/.local/share/{APP}")
    os.makedirs(d, exist_ok=True)
    return d


def cache_dir():
    d = os.path.join(data_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


def projects_dir():
    d = os.path.join(os.path.expanduser("~"), "J' PZ MAP STUDIO Projects")
    os.makedirs(d, exist_ok=True)
    return d


def zomboid_user_dir():
    """~/Zomboid (onde ficam mods locais: ~/Zomboid/mods)."""
    return os.path.join(os.path.expanduser("~"), "Zomboid")


def _cfg_path():
    return os.path.join(data_dir(), "config.json")


def load_config():
    try:
        with open(_cfg_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    tmp = _cfg_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)
    os.replace(tmp, _cfg_path())


def media_of(root):
    """dado um caminho escolhido pelo usuario (pasta do jogo, .app, Contents/Java ou media), devolve a pasta media."""
    if not root:
        return None
    root = os.path.abspath(os.path.expanduser(root))
    cands = [root, os.path.join(root, "media"),
             os.path.join(root, "Contents", "Java", "media"),
             os.path.join(root, "Project Zomboid.app", "Contents", "Java", "media"),
             os.path.join(root, "ProjectZomboid", "media"),
             os.path.join(root, "ProjectZomboid", "Project Zomboid.app", "Contents", "Java", "media")]
    for c in cands:
        if os.path.isdir(os.path.join(c, "texturepacks")) and os.path.isdir(os.path.join(c, "maps")):
            return c
    return None


def _steam_roots():
    roots = []
    if IS_WIN:
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for name in ("SteamPath", "InstallPath"):
                            try:
                                roots.append(winreg.QueryValueEx(k, name)[0])
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                roots.append(os.path.join(os.environ[env], "Steam"))
        for drv in "CDEFGH":
            roots += [f"{drv}:\\Steam", f"{drv}:\\SteamLibrary", f"{drv}:\\Games\\Steam"]
    else:
        roots += [os.path.expanduser("~/Library/Application Support/Steam"),
                  os.path.expanduser("~/.steam/steam"), os.path.expanduser("~/.local/share/Steam")]
    libs = []
    for r in roots:
        r = os.path.normpath(r)
        if not os.path.isdir(r) or r in libs:
            continue
        libs.append(r)
        vdf = os.path.join(r, "steamapps", "libraryfolders.vdf")
        try:
            txt = open(vdf, encoding="utf-8", errors="replace").read()
            for p in re.findall(r'"path"\s+"([^"]+)"', txt):
                p = os.path.normpath(p.replace("\\\\", "\\"))
                if p not in libs:
                    libs.append(p)
        except OSError:
            pass
    return libs


def candidates():
    out = []
    for lib in _steam_roots():
        m = media_of(os.path.join(lib, "steamapps", "common", "ProjectZomboid"))
        if m and m not in out:
            out.append(m)
    for extra in (os.path.expanduser("~/pz-ws-sandbox/game"), "/Applications/Project Zomboid.app"):
        for sub in ("", "steamapps/common/ProjectZomboid"):
            m = media_of(os.path.join(extra, sub)) if sub else media_of(extra)
            if m and m not in out:
                out.append(m)
    return out


def _ver_from_core(b):
    """new GameVersion(42, NN, "sufixo") no bytecode de zombie/core/Core.class."""
    m = re.search(rb"\xbb..\x59\x10(.)\x10(.)", b, re.S)
    if m and m.group(1)[0] in (41, 42, 43):
        return f"{m.group(1)[0]}.{m.group(2)[0]}"
    return None


def game_version(media):
    """versao do jogo (ex.: '42.22'), lida do bytecode do jogo; None se nao achar."""
    import zipfile
    base = os.path.dirname(media)
    try:
        with zipfile.ZipFile(os.path.join(base, "projectzomboid.jar")) as z:
            v = _ver_from_core(z.read("zombie/core/Core.class"))
            if v:
                return v
    except (OSError, KeyError, zipfile.BadZipFile):
        pass
    p = os.path.join(base, "zombie", "core", "Core.class")      # Windows antigo: classes soltas
    if os.path.exists(p):
        with open(p, "rb") as f:
            return _ver_from_core(f.read())
    return None


def find_media():
    cfg = load_config()
    m = media_of(cfg.get("game_path"))
    if m:
        return m
    c = candidates()
    return c[0] if c else None
