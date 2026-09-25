"""Pengelompokan makalah per bahasa untuk halaman bahasa.

Bahasa sebuah makalah diambil dari dua sumber:
1. Nama bahasa (`aliases` di [[languages]]) yang disebut di judul atau abstrak.
2. Daftar `languages_studied` yang dicatat Gemini saat meringkas.

Nama yang lebih panjang dicocokkan lebih dulu dan bagian teks yang sudah cocok
ditutup, jadi "Papuan Malay" tidak ikut dihitung sebagai "Malay" dan
"Dayak Ngaju" tidak ikut dihitung sebagai "Dayak".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from .config import Config, Language


@dataclass
class LanguagePage:
    id: str
    name_id: str
    name_en: str
    group: str
    papers: list[dict] = field(default_factory=list)


def _aliases(lang: Language) -> list[str]:
    names = list(lang.aliases)
    # Nama Indonesia ("Bahasa Jawa") juga dicari, untuk makalah berbahasa Indonesia.
    local = re.sub(r"\s*\(.*?\)", "", lang.name_id).strip()
    if local.lower().startswith("bahasa ") and local not in names:
        names.append(local)
    return names


def _key(text: str) -> str:
    return " ".join(re.split(r"[\s\-]+", text.strip().lower()))


@lru_cache(maxsize=8)
def _matcher(pairs: tuple[tuple[str, str], ...]) -> tuple[re.Pattern, dict[str, str]]:
    """Satu pola untuk semua nama. Nama terpanjang dicoba lebih dulu di setiap posisi,
    jadi "Papuan Malay" menang atas "Malay" dan bagian yang cocok tidak dipakai lagi."""
    by_key = {_key(alias): lid for alias, lid in pairs}
    names = sorted(by_key, key=len, reverse=True)
    body = "|".join(r"[\s\-]+".join(re.escape(part) for part in name.split(" ")) for name in names)
    return re.compile(rf"(?<!\w)(?:{body})s?(?!\w)", re.IGNORECASE), by_key


def find(config: Config, text: str) -> list[str]:
    """ID bahasa yang disebut di `text`, sesuai urutan kemunculan pertama."""
    pairs = tuple((alias, lang.id) for lang in config.languages for alias in _aliases(lang))
    if not pairs:
        return []
    pattern, by_key = _matcher(pairs)
    found: list[str] = []
    for m in pattern.finditer(text):
        key = _key(m.group(0))
        lid = by_key.get(key) or by_key.get(key[:-1])
        if lid and lid not in found:
            found.append(lid)
    return found


def slug(name: str) -> str:
    return "x-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def detect(config: Config, paper: dict) -> tuple[list[str], list[str]]:
    """Kembalikan (ID bahasa di konfigurasi, nama bahasa lain dari ringkasan Gemini)."""
    ids = find(config, f"{paper.get('title', '')}\n{paper.get('abstract', '')}")
    ignore = {n.lower() for n in config.search.get("ignore_languages", [])}
    extra: list[str] = []
    for name in (paper.get("summary") or {}).get("languages_studied") or []:
        if name.lower() in ignore:
            continue
        mapped = find(config, name)
        if mapped:
            ids += [lid for lid in mapped if lid not in ids]
        elif name not in extra:
            extra.append(name)
    return ids, extra


def group_papers(config: Config, papers: list[dict]) -> dict[str, LanguagePage]:
    """Halaman bahasa beserta makalahnya (urutan makalah mengikuti `papers`).

    Bahasa di konfigurasi mendapat halaman jika punya minimal satu makalah; bahasa
    lain dari ringkasan Gemini jika punya minimal `auto_language_min_papers` makalah.
    """
    pages = {
        lang.id: LanguagePage(lang.id, lang.name_id, lang.name_en, lang.group)
        for lang in config.languages
    }
    auto: dict[str, LanguagePage] = {}
    for paper in papers:
        ids, extra = detect(config, paper)
        paper["languages"] = list(ids)
        for lid in ids:
            pages[lid].papers.append(paper)
        for name in extra:
            key = slug(name)
            page = auto.setdefault(key, LanguagePage(key, name, name, "other"))
            if paper not in page.papers:
                page.papers.append(paper)
                paper["languages"].append(key)
    min_auto = int(config.search.get("auto_language_min_papers", 2))
    result = {lid: p for lid, p in pages.items() if p.papers}
    result.update({lid: p for lid, p in auto.items() if len(p.papers) >= min_auto})
    # Tautan hanya ke bahasa yang punya halaman.
    for paper in papers:
        paper["languages"] = [lid for lid in paper.get("languages", []) if lid in result]
    return result
