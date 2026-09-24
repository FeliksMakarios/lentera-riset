"""Mengambil dan mengurai makalah dari arXiv API.

Thank you to arXiv for use of its open access interoperability.
"""

from __future__ import annotations

import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime

from . import http
from .config import Config, Topic

API_URL = "https://export.arxiv.org/api/query"
RSS_URL = "https://rss.arxiv.org/rss/{categories}"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "dc": "http://purl.org/dc/elements/1.1/",
}
_ID_RE = re.compile(r"arxiv\.org/abs/(?P<id>.+?)(?:v(?P<ver>\d+))?$")
_RSS_ID_RE = re.compile(r"(?P<id>\d{4}\.\d{4,5})(?:v(?P<ver>\d+))?")

# Server arXiv menolak permintaan tanpa header yang lengkap, dan saat bebannya
# tinggi menjawab 406 (bukan 429). Keduanya ditangani di sini.
HEADERS = {
    "Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
}
THROTTLE_STATUSES = frozenset({403, 406, 429, 503})


def _query_terms(keywords: list[str]) -> list[str]:
    """Kata kunci untuk kueri arXiv, ditambah bentuk jamak untuk frasa berakhiran "language"."""
    terms: list[str] = []
    for kw in keywords:
        variants = [kw, kw + "s"] if kw.lower().endswith("language") else [kw]
        for v in variants:
            if v not in terms:
                terms.append(v)
    return terms


def build_query(topic: Topic, categories: list[str]) -> str:
    """Susun kueri arXiv: (kategori) AND (kata kunci topik)."""
    cats = " OR ".join(f"cat:{c}" for c in categories)
    terms = " OR ".join(
        f'abs:"{kw}"' if " " in kw or "-" in kw else f"abs:{kw}" for kw in _query_terms(topic.keywords)
    )
    return f"({cats}) AND ({terms})"


def query_url(search_query: str, max_results: int, start: int = 0) -> str:
    params = {
        "search_query": search_query,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return f"{API_URL}?{urllib.parse.urlencode(params)}"


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return " ".join(el.text.split())


def parse_feed(xml_bytes: bytes) -> list[dict]:
    """Ubah Atom feed arXiv menjadi daftar kamus makalah."""
    root = ET.fromstring(xml_bytes)
    papers = []
    for entry in root.findall("atom:entry", NS):
        raw_id = _text(entry.find("atom:id", NS))
        match = _ID_RE.search(raw_id)
        if not match:
            # Entri galat dari arXiv (misalnya kueri tidak valid) tidak punya ID makalah.
            continue
        pdf_url = ""
        for link in entry.findall("atom:link", NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
        primary = entry.find("arxiv:primary_category", NS)
        papers.append(
            {
                "id": match.group("id"),
                "source": "arxiv",
                "venue": "arXiv",
                "version": int(match.group("ver") or 1),
                "title": _text(entry.find("atom:title", NS)),
                "abstract": _text(entry.find("atom:summary", NS)),
                "authors": [_text(a.find("atom:name", NS)) for a in entry.findall("atom:author", NS)],
                "published": _text(entry.find("atom:published", NS)),
                "updated": _text(entry.find("atom:updated", NS)),
                "primary_category": primary.get("term", "") if primary is not None else "",
                "categories": [c.get("term", "") for c in entry.findall("atom:category", NS)],
                "comment": _text(entry.find("arxiv:comment", NS)),
                "journal_ref": _text(entry.find("arxiv:journal_ref", NS)),
                "abs_url": f"https://arxiv.org/abs/{match.group('id')}",
                "pdf_url": pdf_url or f"https://arxiv.org/pdf/{match.group('id')}",
            }
        )
    return papers


def _paper(pid: str, version: int, **fields) -> dict:
    return {
        "id": pid,
        "source": "arxiv",
        "venue": "arXiv",
        "version": version,
        "abs_url": f"https://arxiv.org/abs/{pid}",
        "pdf_url": fields.pop("pdf_url", "") or f"https://arxiv.org/pdf/{pid}",
        **fields,
    }


def _split_authors(value: str) -> list[str]:
    parts = re.split(r",\s*|\s+and\s+", value or "")
    return [p.strip() for p in parts if p.strip()]


def parse_rss(xml_bytes: bytes) -> list[dict]:
    """Ubah umpan RSS harian arXiv menjadi daftar makalah.

    Hanya makalah baru ("new") dan silang kategori ("cross") yang diambil.
    Makalah revisi ("replace") dilewati karena tanggal terbit aslinya tidak diketahui.
    """
    root = ET.fromstring(xml_bytes)
    papers = []
    for item in root.iter("item"):
        announce = _text(item.find("arxiv:announce_type", NS))
        if announce and announce not in ("new", "cross"):
            continue
        ref = _text(item.find("guid")) or _text(item.find("link"))
        match = _RSS_ID_RE.search(ref)
        if not match:
            continue
        description = _text(item.find("description"))
        abstract = description.split("Abstract:", 1)[1].strip() if "Abstract:" in description else description
        categories = [_text(c) for c in item.findall("category") if _text(c)]
        pub = _text(item.find("pubDate"))
        published = (
            parsedate_to_datetime(pub).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if pub else ""
        )
        if not published:
            continue
        papers.append(
            _paper(
                match.group("id"),
                int(match.group("ver") or 1),
                title=_text(item.find("title")),
                abstract=abstract,
                authors=_split_authors(_text(item.find("dc:creator", NS))),
                published=published,
                updated=published,
                primary_category=categories[0] if categories else "",
                categories=categories,
                comment="",
                journal_ref="",
            )
        )
    return papers


def fetch_rss(categories: list[str], log=print) -> list[dict]:
    url = RSS_URL.format(categories="+".join(categories))
    body = http.request(url, headers=HEADERS, timeout=60, retries=4, backoff=10,
                        retry_statuses=THROTTLE_STATUSES, log=log)
    return parse_rss(body)


def fetch_candidates(config: Config, log=print) -> dict[str, dict]:
    """Gabungkan dua sumber: umpan RSS harian dan kueri API per topik.

    RSS berada di server terpisah yang jarang dibatasi, jadi makalah hari ini
    tetap masuk walaupun API sedang menolak. API dipakai untuk mengisi makalah
    beberapa minggu terakhir. Jika API terus menolak, kueri topik berikutnya
    tidak dicoba lagi pada jalankan ini.
    """
    categories = config.arxiv.get("categories", ["cs.CL"])
    max_results = int(config.arxiv.get("max_results_per_topic", 100))
    delay = float(config.arxiv.get("request_delay_seconds", 3.5))
    retries = int(config.arxiv.get("api_retries", 5))
    backoff = float(config.arxiv.get("api_backoff_seconds", 15))
    found: dict[str, dict] = {}

    try:
        rss_papers = fetch_rss(categories, log=log)
        for p in rss_papers:
            found.setdefault(p["id"], p)
        log(f"  [arXiv RSS] {len(rss_papers)} makalah baru hari ini")
    except Exception as exc:
        log(f"  [arXiv RSS] gagal: {exc}")

    queried = [t for t in config.topics if t.query]
    for i, topic in enumerate(queried):
        time.sleep(delay)
        url = query_url(build_query(topic, categories), max_results)
        try:
            body = http.request(url, headers=HEADERS, timeout=60, retries=retries, backoff=backoff,
                                retry_statuses=THROTTLE_STATUSES, log=log)
            papers = parse_feed(body)
        except http.HttpError as exc:
            log(f"  [arXiv API] topik {topic.id} ditolak (HTTP {exc.status}); "
                f"{len(queried) - i - 1} topik lain dilewati pada jalankan ini")
            break
        except Exception as exc:
            log(f"  [arXiv API] topik {topic.id} gagal: {exc}")
            continue
        log(f"  [arXiv API] topik {topic.id}: {len(papers)} makalah")
        for p in papers:
            # Data API lebih lengkap (komentar penulis, tanggal terbit asli), jadi menimpa data RSS.
            found[p["id"]] = p
    return found
