"""Makalah pilihan yang ditambahkan secara manual lewat config/manual.toml.

Setiap entri memakai satu pengenal: `arxiv`, `acl` (ID ACL Anthology), `doi`
(diambil lewat OpenAlex), atau `title` (dicari lewat OpenAlex jika tidak ada ID).
Makalah manual ditandai `manual = true`, jadi selalu tampil di situs, diringkas,
dan diberi vektor makna meskipun skor relevansi kata kuncinya rendah atau
umurnya melewati batas `lookback_days`. Entri yang gagal diambil dicoba lagi pada
jalankan berikutnya.
"""

from __future__ import annotations

import os
import re
import tomllib
import urllib.parse
from datetime import date, datetime
from pathlib import Path

from . import acl, arxiv, http, openalex, relevance
from .config import ROOT, Config

DEFAULT_PATH = ROOT / "config" / "manual.toml"
_ARXIV_ID = re.compile(r"^\d{4}\.\d{4,5}$")
_ACL_ID = re.compile(r"^\d{4}\.[a-z0-9]+-[a-z0-9]+\.\d+$")


def load(path: Path = DEFAULT_PATH) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "rb") as fh:
        entries = tomllib.load(fh).get("papers", [])
    for entry in entries:
        kinds = [k for k in ("arxiv", "acl", "doi", "title") if entry.get(k)]
        if not kinds:
            raise ValueError(f"entri manual tanpa pengenal: {entry}")
        if entry.get("arxiv") and not _ARXIV_ID.match(entry["arxiv"]):
            raise ValueError(f"ID arXiv tidak valid: {entry['arxiv']}")
        if entry.get("acl") and not _ACL_ID.match(entry["acl"]):
            raise ValueError(f"ID ACL Anthology tidak valid: {entry['acl']}")
    return entries


def expected_id(entry: dict) -> str | None:
    """ID makalah di papers.json untuk entri ini, jika bisa diketahui tanpa mengambil data."""
    if entry.get("arxiv"):
        return entry["arxiv"]
    if entry.get("acl"):
        return f"acl:{entry['acl']}"
    if entry.get("doi"):
        return f"doi:{entry['doi'].lower()}"
    return None


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


def find_existing(papers: dict, entry: dict) -> str | None:
    """ID makalah yang sudah tersimpan untuk entri ini (termasuk lewat tautan `also` atau judul)."""
    pid = expected_id(entry)
    if pid and pid in papers:
        return pid
    doi = (entry.get("doi") or "").lower()
    key = title_key(entry.get("title", ""))
    for existing_id, paper in papers.items():
        if pid and any(link.get("id") == pid for link in paper.get("also", [])):
            return existing_id
        if doi and (paper.get("doi") or "").lower() == doi:
            return existing_id
        if key and title_key(paper.get("title", "")) == key:
            return existing_id
    return None


def fetch_arxiv(ids: list[str], log=print) -> dict[str, dict]:
    if not ids:
        return {}
    url = f"{arxiv.API_URL}?{urllib.parse.urlencode({'id_list': ','.join(ids), 'max_results': len(ids)})}"
    body = http.request(url, headers=arxiv.HEADERS, timeout=60, retries=4, backoff=10,
                        retry_statuses=arxiv.THROTTLE_STATUSES, log=log)
    return {p["id"]: p for p in arxiv.parse_feed(body)}


def arxiv_via_openalex(aid: str) -> dict | None:
    """Cadangan jika API arXiv menolak (406): ambil lewat DOI arXiv di OpenAlex."""
    paper = fetch_doi(f"{openalex.ARXIV_DOI_PREFIX}arxiv.{aid}")
    if not paper:
        return None
    return {
        **paper,
        "id": aid,
        "source": "arxiv",
        "venue": "arXiv",
        "categories": [],
        "abs_url": f"https://arxiv.org/abs/{aid}",
        "pdf_url": f"https://arxiv.org/pdf/{aid}",
    }


def fetch_acl(ids: list[str], log=print) -> dict[str, dict]:
    """Ambil makalah ACL Anthology dari berkas XML kumpulannya (misalnya data/xml/2025.acl.xml)."""
    found: dict[str, dict] = {}
    by_collection: dict[str, list[str]] = {}
    for anth_id in ids:
        by_collection.setdefault(anth_id.split("-", 1)[0], []).append(anth_id)
    for collection, wanted in by_collection.items():
        try:
            body = http.request(acl.RAW.format(ref="master", path=f"data/xml/{collection}.xml"), timeout=120)
        except Exception as exc:
            log(f"  [Manual] kumpulan ACL {collection} gagal diambil: {str(exc)[:150]}")
            continue
        for paper in acl.parse_collection(body, date.min):
            if paper["anthology_id"] in wanted:
                found[paper["anthology_id"]] = paper
    return found


def _openalex_url(path: str, **params) -> str:
    key = os.environ.get("OPENALEX_API_KEY", "")
    if key:
        params["api_key"] = key
    params["select"] = openalex.SELECT
    return f"{openalex.API}{path}?{urllib.parse.urlencode(params)}"


def fetch_doi(doi: str) -> dict | None:
    work = openalex.get_page(_openalex_url(f"/doi:{doi}"))
    return openalex.to_paper(work, strict=False)


def fetch_title(title: str) -> dict | None:
    """Cari judul di OpenAlex dan ambil hasil yang judulnya sama persis (tanpa tanda baca)."""
    data = openalex.get_page(_openalex_url("", search=title, **{"per-page": 5}))
    key = title_key(title)
    for work in data.get("results", []):
        if title_key(work.get("display_name") or "") == key:
            return openalex.to_paper(work, strict=False)
    return None


def fetch(config: Config, papers: dict, now: datetime, entries: list[dict] | None = None, log=print) -> int:
    """Tandai makalah manual yang sudah ada, ambil yang belum. Kembalikan jumlah makalah baru."""
    entries = load() if entries is None else entries
    if not entries:
        return 0
    missing: list[dict] = []
    for entry in entries:
        existing = find_existing(papers, entry)
        if existing:
            papers[existing]["manual"] = True
        else:
            missing.append(entry)
    if not missing:
        log(f"  [Manual] {len(entries)} makalah pilihan sudah tersimpan")
        return 0

    log(f"  [Manual] mengambil {len(missing)} makalah pilihan...")
    fetched: dict[int, dict] = {}
    try:
        arxiv_found = fetch_arxiv([e["arxiv"] for e in missing if e.get("arxiv")], log=log)
    except Exception as exc:
        log(f"  [Manual] arXiv gagal: {str(exc)[:150]}")
        arxiv_found = {}
    acl_found = fetch_acl([e["acl"] for e in missing if e.get("acl") and not e.get("arxiv")], log=log)
    for i, entry in enumerate(missing):
        paper = None
        try:
            if entry.get("arxiv"):
                paper = arxiv_found.get(entry["arxiv"]) or arxiv_via_openalex(entry["arxiv"])
            elif entry.get("acl"):
                paper = acl_found.get(entry["acl"])
            elif entry.get("doi"):
                paper = fetch_doi(entry["doi"])
            else:
                paper = fetch_title(entry["title"])
        except Exception as exc:
            log(f"  [Manual] {expected_id(entry) or entry.get('title')} gagal: {str(exc)[:150]}")
        if paper:
            fetched[i] = paper
        else:
            log(f"  [Manual] tidak ditemukan: {expected_id(entry) or entry.get('title')}")

    added = 0
    for paper in fetched.values():
        entry_twin = find_existing(papers, {"title": paper["title"], "doi": paper.get("doi", "")})
        if entry_twin:
            twin = papers[entry_twin]
            twin["manual"] = True
            links = twin.setdefault("also", [])
            if paper["id"] != entry_twin and not any(link["id"] == paper["id"] for link in links):
                links.append({"id": paper["id"], "source": paper.get("source", "arxiv"),
                              "url": paper.get("abs_url", ""), "venue": paper.get("venue", "")})
            continue
        papers[paper["id"]] = {
            **paper,
            **relevance.score_paper(config, paper),
            "manual": True,
            "signals": {},
            "summary": None,
            "first_seen": now.isoformat(timespec="seconds"),
        }
        added += 1
    log(f"  [Manual] {added} makalah pilihan baru ditambahkan")
    return added
