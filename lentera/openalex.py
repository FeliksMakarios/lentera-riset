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

import json
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
        # from_created_date hanya untuk paket berbayar, jadi dipakai tanggal terbit.
        f"from_publication_date:{since}",
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


class QuotaExhausted(Exception):
    """OpenAlex menolak (429) dan tidak layak dicoba lagi pada jalankan ini."""


def describe_429(exc: http.HttpError) -> str:
    """Ringkas alasan penolakan OpenAlex dari isi respons dan header batasnya."""
    try:
        detail = json.loads(exc.body)
        message = detail.get("message") or detail.get("error") or exc.body
    except (ValueError, AttributeError):
        message = exc.body
    headers = {k.lower(): v for k, v in exc.headers.items()}
    parts = [" ".join(str(message).split())[:300]]
    for name in ("retry-after", "x-ratelimit-remaining", "x-ratelimit-limit", "x-ratelimit-credits-required"):
        if name in headers:
            parts.append(f"{name}={headers[name]}")
    return "; ".join(parts)


def get_page(url: str, sleep=time.sleep) -> dict:
    """Ambil satu halaman hasil. 429 sementara (Retry-After pendek) dicoba ulang hingga dua kali."""
    for attempt in range(3):
        try:
            return http.get_json(url, timeout=60)
        except http.HttpError as exc:
            if exc.status != 429:
                raise
            wait = float({k.lower(): v for k, v in exc.headers.items()}.get("retry-after") or 0)
            if attempt == 2 or not 0 < wait <= 90:
                raise QuotaExhausted(describe_429(exc)) from exc
            sleep(wait + 1)
    raise AssertionError("tidak terjangkau")


def search(topic: Topic, since: str, api_key: str, max_results: int, sleep=time.sleep) -> list[dict]:
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
        data = get_page(f"{API}?{urllib.parse.urlencode(params)}", sleep=sleep)
        results += data.get("results", [])
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not data.get("results"):
            break
    return results[:max_results]


def rate_limit_status(api_key: str) -> str:
    """Sisa kredit harian menurut OpenAlex, untuk membantu mendiagnosis penolakan."""
    try:
        data = http.get_json(f"https://api.openalex.org/rate-limit?{urllib.parse.urlencode({'api_key': api_key})}", timeout=30)
    except http.HttpError as exc:
        return f"status kuota tidak bisa dibaca (HTTP {exc.status}: {' '.join(exc.body.split())[:200]})".replace(api_key, "***")
    except Exception as exc:
        return f"status kuota tidak bisa dibaca ({exc.__class__.__name__})"
    data = {k: v for k, v in data.items() if k != "api_key"}
    return "status kuota: " + json.dumps(data)[:400]


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
        except QuotaExhausted as exc:
            log(f"  [OpenAlex] ditolak (429): {str(exc).replace(api_key, '***')}")
            log(f"  [OpenAlex] {rate_limit_status(api_key)}")
            log("  [OpenAlex] topik lain dilewati pada jalankan ini")
            break
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
