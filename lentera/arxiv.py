"""Mengambil dan mengurai makalah dari arXiv API.

Thank you to arXiv for use of its open access interoperability.
"""

from __future__ import annotations

import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from . import http
from .config import Config, Topic

API_URL = "https://export.arxiv.org/api/query"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_ID_RE = re.compile(r"arxiv\.org/abs/(?P<id>.+?)(?:v(?P<ver>\d+))?$")


def build_query(topic: Topic, categories: list[str]) -> str:
    """Susun kueri arXiv: (kategori) AND (kata kunci topik)."""
    cats = " OR ".join(f"cat:{c}" for c in categories)
    terms = " OR ".join(f'abs:"{kw}"' if " " in kw or "-" in kw else f"abs:{kw}" for kw in topic.keywords)
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


def fetch_candidates(config: Config, log=print) -> dict[str, dict]:
    """Jalankan satu kueri per topik (yang `query = true`) dan gabungkan hasilnya."""
    categories = config.arxiv.get("categories", ["cs.CL"])
    max_results = int(config.arxiv.get("max_results_per_topic", 100))
    delay = float(config.arxiv.get("request_delay_seconds", 3.5))
    found: dict[str, dict] = {}
    queried = [t for t in config.topics if t.query]
    for i, topic in enumerate(queried):
        if i:
            time.sleep(delay)
        url = query_url(build_query(topic, categories), max_results)
        try:
            papers = parse_feed(http.request(url, timeout=60))
        except Exception as exc:  # satu topik gagal tidak boleh menghentikan semuanya
            log(f"  [arXiv] topik {topic.id} gagal: {exc}")
            continue
        log(f"  [arXiv] topik {topic.id}: {len(papers)} makalah")
        for p in papers:
            found.setdefault(p["id"], p)
    return found
