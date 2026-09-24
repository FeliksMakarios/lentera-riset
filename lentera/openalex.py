"""Makalah jurnal dan konferensi (termasuk IEEE) dari OpenAlex.

OpenAlex adalah katalog ilmiah terbuka. Sejak Februari 2026 API-nya mewajibkan
kunci API gratis (https://openalex.org/settings/api), dengan jatah 100.000
kredit per hari; satu permintaan pencarian memakai 10 kredit. Jika
OPENALEX_API_KEY tidak diisi, sumber ini dilewati.

Pracetak (arXiv dan sejenisnya) diabaikan karena sudah diambil dari arXiv.
Pencarian dibatasi ke bidang ilmu komputer supaya makalah dari bidang lain
yang kebetulan menyebut kata seperti "Indonesian" tidak ikut masuk.
"""

from __future__ import annotations

import os
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

from . import http
from .config import Config, Topic

API = "https://api.openalex.org/works"
# Bidang "Computer Science" pada taksonomi topik OpenAlex.
COMPUTER_SCIENCE_FIELD = "17"
ARXIV_DOI_PREFIX = "10.48550/"
SELECT = ",".join([
    "id", "doi", "display_name", "publication_date", "created_date", "authorships",
    "abstract_inverted_index", "primary_location", "best_oa_location", "type",
])


def rebuild_abstract(inverted: dict | None) -> str:
    """OpenAlex menyimpan abstrak sebagai indeks terbalik {kata: [posisi, ...]}."""
    if not inverted:
        return ""
    positions: dict[int, str] = {}
    for word, idx in inverted.items():
        for i in idx:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def build_filter(topic: Topic, since: str) -> str:
    terms = " OR ".join(f'"{kw}"' for kw in topic.keywords)
    return ",".join([
        f"title_and_abstract.search:({terms})",
        f"from_created_date:{since}",
        f"topics.field.id:{COMPUTER_SCIENCE_FIELD}",
        "type:article",
    ])


def to_paper(work: dict) -> dict | None:
    """Ubah satu work OpenAlex menjadi kamus makalah, atau None jika harus dilewati."""
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    doi = (work.get("doi") or "").removeprefix("https://doi.org/").lower()
    if doi.startswith(ARXIV_DOI_PREFIX) or source.get("type") not in ("journal", "conference"):
        return None
    title = work.get("display_name") or ""
    if not title:
        return None
    today = datetime.now(timezone.utc).date().isoformat()
    published = work.get("publication_date") or work.get("created_date") or today
    if published > today:
        published = work.get("created_date") or today
    oa = work.get("best_oa_location") or {}
    openalex_id = (work.get("id") or "").rsplit("/", 1)[-1]
    venue = source.get("display_name") or ""
    return {
        "id": f"doi:{doi}" if doi else f"openalex:{openalex_id}",
        "source": "openalex",
        "openalex_id": openalex_id,
        "version": 1,
        "title": " ".join(title.split()),
        "abstract": rebuild_abstract(work.get("abstract_inverted_index")),
        "authors": [
            (a.get("author") or {}).get("display_name", "")
            for a in work.get("authorships") or []
            if (a.get("author") or {}).get("display_name")
        ],
        "published": f"{published[:10]}T00:00:00Z",
        "updated": f"{published[:10]}T00:00:00Z",
        "primary_category": source.get("host_organization_name") or "",
        "categories": [],
        "venue": venue,
        "comment": "",
        "journal_ref": venue,
        "doi": doi,
        "abs_url": f"https://doi.org/{doi}" if doi else (primary.get("landing_page_url") or work.get("id", "")),
        "pdf_url": oa.get("pdf_url") or "",
    }


def search(topic: Topic, since: str, api_key: str, max_results: int) -> list[dict]:
    results: list[dict] = []
    cursor = "*"
    while cursor and len(results) < max_results:
        params = {
            "filter": build_filter(topic, since),
            "select": SELECT,
            "per-page": min(100, max_results),
            "cursor": cursor,
            "api_key": api_key,
        }
        data = http.get_json(f"{API}?{urllib.parse.urlencode(params)}", timeout=60)
        results += data.get("results", [])
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not data.get("results"):
            break
    return results[:max_results]


def fetch_candidates(config: Config, state: dict, now: datetime | None = None, log=print) -> dict[str, dict]:
    api_key = os.environ.get("OPENALEX_API_KEY", "")
    if not api_key:
        log("  [OpenAlex] OPENALEX_API_KEY tidak diisi, sumber ini dilewati")
        return {}
    settings = config.openalex
    now = now or datetime.now(timezone.utc)
    oldest = now - timedelta(days=int(settings.get("lookback_days", 60)))
    since = oldest
    if state.get("checked_at"):
        since = max(oldest, datetime.fromisoformat(state["checked_at"]) - timedelta(days=2))
    max_results = int(settings.get("max_results_per_topic", 200))
    found: dict[str, dict] = {}
    ok = False
    for topic in (t for t in config.topics if t.query):
        try:
            works = search(topic, since.date().isoformat(), api_key, max_results)
        except Exception as exc:
            # Pesan galat memuat URL; kunci API jangan sampai tercetak di log.
            log(f"  [OpenAlex] topik {topic.id} gagal: {str(exc).replace(api_key, '***')[:200]}")
            continue
        ok = True
        kept = 0
        for work in works:
            paper = to_paper(work)
            if paper:
                found.setdefault(paper["id"], paper)
                kept += 1
        log(f"  [OpenAlex] topik {topic.id}: {len(works)} hasil, {kept} makalah jurnal/konferensi")
        time.sleep(0.2)
    if ok:
        state["checked_at"] = now.isoformat(timespec="seconds")
    return found
