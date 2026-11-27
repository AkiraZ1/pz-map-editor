"""Pacote para a Steam Workshop: capa (preview.png), workshop.txt, .vdf do steamcmd e o comando de envio.

Pasta gerada (formato que o jogo e o steamcmd esperam):
  <Zomboid>/Workshop/<modid>/
      preview.png                 capa (quadrada, 512 px, < 1 MB)
      workshop.txt                o mesmo que o envio de dentro do jogo usa
      workshop_build.vdf          para `steamcmd +login <usuario> +workshop_build_item <vdf> +quit`
      Contents/mods/<modid>/      copia do mod exportado (so o que mudou)
A capa fica no projeto (<projeto>/workshop/preview.png) e tambem vira o poster do mod (42/poster.png).
Nunca escreve numa pasta do Workshop que nao tenha a marca deste app (outros mods do usuario ficam la).
Credenciais da Steam nunca passam por aqui: o comando so leva o nome de usuario, a senha o steamcmd pede.
"""
import base64
import io
import os
import re
import shutil

from . import gamedir

APPID = 108600                       # Project Zomboid
MARK = ".jpzmapstudio"
VIS = {"public": 0, "friends": 1, "private": 2, "unlisted": 3}
MAX = 1024 * 1024


def cover_path(project):
    return os.path.join(project.path, "workshop", "preview.png")


def save_cover(project, data_url):
    """data URL (png/jpg/webp...) -> capa quadrada 512 px (corte central) no projeto."""
    from PIL import Image
    m = re.match(r"^data:image/[\w.+-]+;base64,(.+)$", data_url or "", re.S)
    if not m:
        raise ValueError("imagem invalida")
    raw = base64.b64decode(m.group(1))
    if len(raw) > 30 * MAX:
        raise ValueError("imagem grande demais (max 30 MB)")
    im = Image.open(io.BytesIO(raw))
    im.load()
    im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((512, 512), Image.LANCZOS)
    out = cover_path(project)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im.save(out, optimize=True)
    if os.path.getsize(out) > MAX:           # foto com muito detalhe: sem alfa ja basta
        im.convert("RGB").save(out, optimize=True)
    return cover_info(project)


def cover_info(project):
    p = cover_path(project)
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        b = f.read()
    return {"data": "data:image/png;base64," + base64.b64encode(b).decode(), "bytes": len(b)}


def delete_cover(project):
    p = cover_path(project)
    if os.path.exists(p):
        os.remove(p)


def ws_root(modid, base=None):
    return os.path.join(base or os.path.join(gamedir.zomboid_user_dir(), "Workshop"), modid)


def _vq(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\r", "") + '"'


def _sync(src, dst):
    """copia src -> dst so o que mudou (tamanho+mtime) e apaga o que saiu."""
    seen = set()
    for root, ds, fs in os.walk(src):
        rel = os.path.relpath(root, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for fn in fs:
            if fn == MARK or fn == ".DS_Store":
                continue
            s, d = os.path.join(root, fn), os.path.join(dst, rel, fn)
            seen.add(os.path.normpath(d))
            st = os.stat(s)
            if os.path.exists(d) and os.path.getsize(d) == st.st_size and int(os.path.getmtime(d)) == int(st.st_mtime):
                continue
            shutil.copy2(s, d)
    for root, ds, fs in os.walk(dst, topdown=False):
        for fn in fs:
            p = os.path.normpath(os.path.join(root, fn))
            if p not in seen:
                os.remove(p)
        if root != dst and not os.listdir(root):
            os.rmdir(root)


def _published_id(vdf):
    try:
        with open(vdf, encoding="utf-8") as f:
            m = re.search(r'"publishedfileid"\s+"(\d+)"', f.read())
        return m.group(1) if m and m.group(1) != "0" else ""
    except OSError:
        return ""


def stage(project, mod_root, modid, o):
    """monta a pasta do Workshop e devolve {path, vdf, preview, cmd, published_id}."""
    ws = o.get("ws_dir") or ws_root(modid)
    if os.path.isdir(ws) and os.listdir(ws) and not os.path.exists(os.path.join(ws, MARK)):
        raise ValueError(f"ja existe {ws} que nao foi feito por este app; troque o ID ou a pasta do Workshop")
    os.makedirs(ws, exist_ok=True)
    with open(os.path.join(ws, MARK), "w", encoding="utf-8") as f:
        f.write("gerado pelo J' PZ MAP STUDIO; o export pode reescrever esta pasta\n")
    _sync(mod_root, os.path.join(ws, "Contents", "mods", modid))
    prev = os.path.join(ws, "preview.png")
    cov = cover_path(project)
    poster = os.path.join(mod_root, "42", "poster.png")
    if os.path.exists(cov):
        shutil.copy2(cov, prev)
    elif os.path.exists(poster):                 # sem capa: usa a miniatura do mapa
        shutil.copy2(poster, prev)
    vdf = os.path.join(ws, "workshop_build.vdf")
    pid = re.sub(r"\D", "", str(o.get("published_id") or "")) or _published_id(vdf)
    title = o.get("title") or modid
    desc = o.get("description") or ""
    vis = o.get("visibility") if o.get("visibility") in VIS else "public"
    tags = [t.strip() for t in str(o.get("tags") or "Build 42;Map").split(";") if t.strip()]
    with open(os.path.join(ws, "workshop.txt"), "w", encoding="utf-8") as f:
        f.write("version=1\n")
        if pid:
            f.write(f"id={pid}\n")
        f.write(f"title={title}\n")
        for ln in (desc.splitlines() or [""]):
            f.write(f"description={ln}\n")
        f.write(f"tags={';'.join(tags)}\nvisibility={vis}\n")
    with open(vdf, "w", encoding="utf-8") as f:
        f.write('"workshopitem"\n{\n')
        for k, v in (("appid", APPID), ("publishedfileid", pid or "0"),
                     ("contentfolder", os.path.join(ws, "Contents")), ("previewfile", prev),
                     ("visibility", VIS[vis]), ("title", title), ("description", desc),
                     ("changenote", o.get("changenote") or "")):
            f.write(f"\t{_vq(k)}\t\t{_vq(v)}\n")
        f.write("}\n")
    user = re.sub(r"[^\w.\-@]", "", str(o.get("steam_user") or "")) or "<usuario_steam>"
    cmd = f'steamcmd +login {user} +workshop_build_item "{vdf}" +quit'
    return {"path": ws, "vdf": vdf, "preview": prev if os.path.exists(prev) else None, "cmd": cmd,
            "published_id": pid, "tags": tags}
