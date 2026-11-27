"""Nomes que o jogador ve, em ingles e portugues, tirados das traducoes vanilla
(media/lua/shared/Translate/{EN,PTBR}/ItemName.json e Moveables.json)."""
import json
import os
import unicodedata

_cache = {}


def _load(media, lang, fname):
    k = (media, lang, fname)
    if k not in _cache:
        d = {}
        try:
            with open(os.path.join(media, "lua", "shared", "Translate", lang, fname), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            pass
        _cache[k] = d if isinstance(d, dict) else {}
    return _cache[k]


def fold(s):
    """minusculo e sem acento (busca acha 'machado' em 'Machado' e 'acucar' em 'Açúcar')."""
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def items(media):
    """{"Base.Axe": ("Axe", "Machado")}"""
    if not media:
        return {}
    en, pt = _load(media, "EN", "ItemName.json"), _load(media, "PTBR", "ItemName.json")
    return {k: (en.get(k) or "", pt.get(k) or "") for k in set(en) | set(pt)}


def moveable(media, group, custom):
    """(en, pt) de um movel/tile pelo GroupName + CustomName, como o jogo monta a chave."""
    if not media or not (group or custom):
        return "", ""
    en, pt = _load(media, "EN", "Moveables.json"), _load(media, "PTBR", "Moveables.json")
    for key in (" ".join(x for x in (group, custom) if x), custom or ""):
        k = key.replace(" ", "_")
        if k and (k in en or k in pt):
            return en.get(k) or "", pt.get(k) or ""
    return "", ""
