"""Sinyal popularitas dari layanan yang API-nya gratis.

Sumber: Hacker News (Algolia), Hugging Face Papers, Semantic Scholar, GitHub.
X (Twitter) tidak dipakai karena API-nya berbayar. Reddit belum dipakai karena
API-nya kini mewajibkan OAuth dan sering memblokir alamat IP layanan awan.
"""

from __future__ import annotations

import os
import time
import urllib.parse

from . import http


def hacker_news(arxiv_id: str) -> dict | None:
    q = urllib.parse.quote(f'"{arxiv_id}"')
    url = f"https://hn.algolia.com/api/v1/search?query={q}&restrictSearchableAttributes=url&tags=story"
    data = http.get_json(url)
    hits = [h for h in data.get("hits", []) if arxiv_id in (h.get("url") or "")]
    if not hits:
        return None
    top = max(hits, key=lambda h: h.get("points") or 0)
    return {
        "points": sum(h.get("points") or 0 for h in hits),
        "comments": sum(h.get("num_comments") or 0 for h in hits),
        "url": f"https://news.ycombinator.com/item?id={top['objectID']}",
    }


def hugging_face(arxiv_id: str) -> dict | None:
    try:
        data = http.get_json(f"https://huggingface.co/api/papers/{arxiv_id}")
    except http.HttpError as exc:
        if exc.status == 404:
            return None
        raise
    return {
        "upvotes": int(data.get("upvotes") or 0),
        "url": f"https://huggingface.co/papers/{arxiv_id}",
    }


def semantic_scholar_batch(arxiv_ids: list[str]) -> dict[str, dict]:
    """Ambil jumlah sitasi untuk banyak makalah sekaligus (maksimal 500 per panggilan)."""
    out: dict[str, dict] = {}
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/batch"
        "?fields=citationCount,influentialCitationCount,url"
    )
    for i in range(0, len(arxiv_ids), 500):
        chunk = arxiv_ids[i : i + 500]
        data = http.post_json(url, {"ids": [f"ARXIV:{a}" for a in chunk]}, timeout=60)
        for arxiv_id, item in zip(chunk, data):
            if item:
                out[arxiv_id] = {
                    "citations": int(item.get("citationCount") or 0),
                    "influential": int(item.get("influentialCitationCount") or 0),
                    "url": item.get("url") or "",
                }
    return out


def github_repos(arxiv_id: str) -> dict | None:
    """Cari repositori publik yang README-nya menyebut ID arXiv makalah."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    q = urllib.parse.quote(f'"{arxiv_id}" in:readme')
    data = http.get_json(
        f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=5",
        headers=headers,
    )
    items = data.get("items", [])
    if not items:
        return None
    top = items[0]
    return {
        "stars": sum(int(i.get("stargazers_count") or 0) for i in items),
        "repos": int(data.get("total_count") or len(items)),
        "url": top.get("html_url", ""),
        "name": top.get("full_name", ""),
    }


def collect(arxiv_ids: list[str], log=print) -> dict[str, dict]:
    """Kumpulkan semua sinyal. Kegagalan satu sumber hanya dicatat, tidak menghentikan proses."""
    results: dict[str, dict] = {a: {} for a in arxiv_ids}
    if not arxiv_ids:
        return results

    try:
        for a, v in semantic_scholar_batch(arxiv_ids).items():
            results[a]["semantic_scholar"] = v
    except Exception as exc:
        log(f"  [Semantic Scholar] gagal: {exc}")

    # GitHub Search mengizinkan 30 permintaan per menit dengan token, 10 tanpa token.
    gh_delay = 2.2 if os.environ.get("GITHUB_TOKEN") else 6.5
    sources = [
        ("hacker_news", hacker_news, 0.2),
        ("hugging_face", hugging_face, 0.3),
        ("github", github_repos, gh_delay),
    ]
    for name, fn, delay in sources:
        failures = 0
        for a in arxiv_ids:
            try:
                value = fn(a)
            except Exception as exc:
                failures += 1
                if failures >= 5:
                    log(f"  [{name}] terlalu banyak galat, sumber ini dilewati: {exc}")
                    break
                continue
            if value:
                results[a][name] = value
            time.sleep(delay)
        found = sum(1 for a in arxiv_ids if name in results[a])
        log(f"  [{name}] {found} dari {len(arxiv_ids)} makalah punya sinyal")
    return results
