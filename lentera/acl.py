"""Makalah baru dari ACL Anthology.

ACL Anthology tidak punya API web, tetapi seluruh metadatanya (judul, penulis,
abstrak) tersedia terbuka sebagai berkas XML di repositori GitHub
acl-org/acl-anthology, satu berkas per kumpulan prosiding. Setiap volume punya
atribut `ingest-date`, yaitu tanggal volume itu masuk ke Anthology.

Cara kerja: cari berkas XML yang berubah sejak pemeriksaan terakhir lewat
GitHub API, unduh berkas itu, lalu ambil volume yang `ingest-date`-nya masih
dalam rentang `lookback_days`.
"""

from __future__ import annotations

import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

from . import http

API = "https://api.github.com/repos/acl-org/acl-anthology"
RAW = "https://raw.githubusercontent.com/acl-org/acl-anthology/{ref}/{path}"
SITE = "https://aclanthology.org"
# Naikkan angka ini jika cara penelusuran berubah, supaya rentang `lookback_days`
# diperiksa ulang dari awal pada jalankan berikutnya.
STATE_VERSION = 2
_YEAR_RE = re.compile(r"^data/xml/(\d{4})\.")


def collection_year(path: str) -> int:
    """Tahun kumpulan dari nama berkas ("data/xml/2026.acl.xml" -> 2026), 0 untuk format lama."""
    match = _YEAR_RE.match(path)
    return int(match.group(1)) if match else 0


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return " ".join("".join(el.itertext()).split())


def changed_xml_files(since: datetime, max_commits: int = 300, log=print) -> tuple[list[str], str | None]:
    """Berkas data/xml/*.xml yang diubah sejak `since`, dan SHA commit terbaru."""
    iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    shas: list[str] = []
    for page in range(1, 11):
        query = urllib.parse.urlencode({"path": "data/xml", "since": iso, "per_page": 100, "page": page})
        batch = http.get_json(f"{API}/commits?{query}", headers=_headers())
        shas += [c["sha"] for c in batch]
        if len(batch) < 100:
            break
    head = shas[0] if shas else None
    files: set[str] = set()
    for sha in shas[:max_commits]:
        detail = http.get_json(f"{API}/commits/{sha}", headers=_headers())
        for f in detail.get("files", []):
            name = f.get("filename", "")
            if name.startswith("data/xml/") and name.endswith(".xml") and f.get("status") != "removed":
                files.add(name)
    if len(shas) > max_commits:
        log(f"  [ACL] {len(shas)} commit, hanya {max_commits} yang diperiksa")
    return sorted(files), head


def parse_collection(xml_bytes: bytes, since: date) -> list[dict]:
    """Ambil makalah dari volume yang masuk ke Anthology pada atau setelah `since`."""
    root = ET.fromstring(xml_bytes)
    collection = root.get("id", "")
    if "." not in collection:
        # Kumpulan lama berformat ID lain (misalnya "P19"), bukan makalah baru.
        return []
    papers = []
    for volume in root.findall("volume"):
        ingest = volume.get("ingest-date", "")
        try:
            ingested = date.fromisoformat(ingest)
        except ValueError:
            continue
        if ingested < since:
            continue
        meta = volume.find("meta")
        booktitle = _text(meta.find("booktitle")) if meta is not None else ""
        venues = [_text(v) for v in meta.findall("venue")] if meta is not None else []
        published = f"{ingested.isoformat()}T00:00:00Z"
        for paper in volume.findall("paper"):
            anth_id = f"{collection}-{volume.get('id')}.{paper.get('id')}"
            url_text = _text(paper.find("url"))
            has_pdf = paper.find("pdf") is not None or url_text == anth_id
            doi = _text(paper.find("doi"))
            authors = [
                " ".join(x for x in (_text(a.find("first")), _text(a.find("last"))) if x)
                for a in paper.findall("author")
            ]
            papers.append(
                {
                    "id": f"acl:{anth_id}",
                    "source": "acl",
                    "anthology_id": anth_id,
                    "version": 1,
                    "title": _text(paper.find("title")),
                    "abstract": _text(paper.find("abstract")),
                    "authors": [a for a in authors if a],
                    "published": published,
                    "updated": published,
                    "primary_category": venues[0] if venues else "acl",
                    "categories": venues,
                    "venue": booktitle,
                    "comment": "",
                    "journal_ref": booktitle,
                    "doi": doi,
                    "abs_url": f"{SITE}/{anth_id}/",
                    "pdf_url": f"{SITE}/{anth_id}.pdf" if has_pdf else "",
                }
            )
    return papers


def fetch_candidates(config: dict, state: dict, now: datetime | None = None, log=print) -> dict[str, dict]:
    """Makalah ACL baru. `state` (misalnya {"checked_at": ...}) diperbarui jika berhasil."""
    now = now or datetime.now(timezone.utc)
    lookback = int(config.get("lookback_days", 120))
    oldest = now - timedelta(days=lookback)
    since = oldest
    if state.get("checked_at") and state.get("version") == STATE_VERSION:
        # Tumpang tindih dua hari supaya commit yang tertunda tidak terlewat.
        since = max(oldest, datetime.fromisoformat(state["checked_at"]) - timedelta(days=2))
    changed, head = changed_xml_files(since, int(config.get("max_commits", 300)), log=log)
    # Volume baru hampir selalu masuk ke kumpulan tahun berjalan atau tahun lalu.
    # Berkas lama (misalnya P19.xml) sering ikut berubah karena perbaikan massal,
    # jadi dilewati supaya tidak menghabiskan jatah unduhan.
    min_year = oldest.year - 1
    files = sorted((f for f in changed if collection_year(f) >= min_year), key=lambda f: (collection_year(f), f), reverse=True)
    max_files = int(config.get("max_files_per_run", 150))
    log(f"  [ACL] {len(changed)} berkas berubah, {len(files)} dari kumpulan {min_year} ke atas")
    if len(files) > max_files:
        log(f"  [ACL] hanya {max_files} berkas terbaru yang diproses")
        files = files[:max_files]
    found: dict[str, dict] = {}
    failures = 0
    for path in files:
        try:
            body = http.request(RAW.format(ref=head or "master", path=path), timeout=120)
            papers = parse_collection(body, oldest.date())
        except Exception as exc:
            failures += 1
            log(f"  [ACL] {path} gagal: {str(exc)[:120]}")
            if failures >= 5:
                log("  [ACL] terlalu banyak galat, sisa berkas dilewati")
                return found
            continue
        for p in papers:
            found[p["id"]] = p
    state["checked_at"] = now.isoformat(timespec="seconds")
    state["version"] = STATE_VERSION
    if head:
        state["commit"] = head
    log(f"  [ACL] {len(files)} berkas diperiksa, {len(found)} makalah dari volume baru")
    return found
