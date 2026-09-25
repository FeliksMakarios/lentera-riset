"""Sinyal popularitas dari layanan yang API-nya gratis.

Sumber: Hacker News (Algolia), Hugging Face Papers, Semantic Scholar, GitHub.
X (Twitter) tidak dipakai karena API-nya berbayar. Reddit belum dipakai karena
API-nya kini mewajibkan OAuth dan sering memblokir alamat IP layanan awan.
"""

from __future__ import annotations

import os
import re
import time
import urllib.parse

from . import http


def hacker_news(ref: str) -> dict | None:
    """Cari cerita Hacker News yang URL-nya memuat `ref` (ID arXiv atau ID ACL Anthology)."""
    q = urllib.parse.quote(f'"{ref}"')
    url = f"https://hn.algolia.com/api/v1/search?query={q}&restrictSearchableAttributes=url&tags=story"
    data = http.get_json(url)
    hits = [h for h in data.get("hits", []) if ref in (h.get("url") or "")]
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


def semantic_scholar_batch(refs: dict[str, str]) -> dict[str, dict]:
    """Ambil jumlah sitasi untuk banyak makalah sekaligus (maksimal 500 per panggilan).

    `refs` memetakan ID makalah ke ID Semantic Scholar, misalnya "ARXIV:2409.12345",
    "ACL:2026.acl-long.1", atau "DOI:10.1109/...".
    """
    out: dict[str, dict] = {}
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/batch"
        "?fields=citationCount,influentialCitationCount,url"
    )
    # Kunci API gratis (opsional) memberi jatah permintaan sendiri, sehingga jarang
    # ditolak (429) seperti saat memakai jatah bersama tanpa kunci.
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    headers = {"x-api-key": key} if key else None
    items = list(refs.items())
    for i in range(0, len(items), 500):
        chunk = items[i : i + 500]
        data = http.post_json(url, {"ids": [s2 for _, s2 in chunk]}, headers=headers, timeout=60)
        for (pid, _), item in zip(chunk, data):
            if item:
                out[pid] = {
                    "citations": int(item.get("citationCount") or 0),
                    "influential": int(item.get("influentialCitationCount") or 0),
                    "url": item.get("url") or "",
                }
    return out


# Repositori pengumpul makalah (daftar harian, "awesome list") menyebut banyak ID
# arXiv sekaligus, jadi bintangnya bukan sinyal untuk makalah tertentu.
_AGGREGATOR_RE = re.compile(
    r"arxiv|awesome|daily|weekly|digest|papers|reading[-_ ]?list|paper[-_ ]?list|feed|tracker|curated",
    re.IGNORECASE,
)


def is_aggregator(repo: dict) -> bool:
    text = f"{repo.get('full_name', '')} {repo.get('description') or ''}"
    return bool(_AGGREGATOR_RE.search(text))


def github_repos(ref: str) -> dict | None:
    """Cari repositori kode yang README-nya menyebut ID makalah (tanpa repositori pengumpul)."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    q = urllib.parse.quote(f'"{ref}" in:readme')
    data = http.get_json(
        f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=10",
        headers=headers,
    )
    items = [i for i in data.get("items", []) if not is_aggregator(i)]
    if not items:
        return None
    top = items[0]
    return {
        "stars": sum(int(i.get("stargazers_count") or 0) for i in items),
        "repos": len(items),
        "url": top.get("html_url", ""),
        "name": top.get("full_name", ""),
    }


def references(paper: dict) -> dict[str, str | None]:
    """Pengenal makalah untuk tiap layanan sinyal. None berarti layanan itu dilewati."""
    source = paper.get("source", "arxiv")
    if source == "arxiv":
        pid = paper["id"]
        return {"semantic_scholar": f"ARXIV:{pid}", "hacker_news": pid, "hugging_face": pid, "github": pid}
    if source == "acl":
        aid = paper.get("anthology_id") or paper["id"].removeprefix("acl:")
        return {"semantic_scholar": f"ACL:{aid}", "hacker_news": aid, "hugging_face": None, "github": aid}
    doi = paper.get("doi")
    return {
        "semantic_scholar": f"DOI:{doi}" if doi else None,
        "hacker_news": None,
        "hugging_face": None,
        "github": doi or None,
    }


def collect(papers: list[dict], log=print) -> dict[str, dict]:
    """Kumpulkan semua sinyal. Kegagalan satu sumber hanya dicatat, tidak menghentikan proses."""
    results: dict[str, dict] = {p["id"]: {} for p in papers}
    if not papers:
        return results
    refs = {p["id"]: references(p) for p in papers}

    s2_refs = {pid: r["semantic_scholar"] for pid, r in refs.items() if r["semantic_scholar"]}
    try:
        for pid, v in semantic_scholar_batch(s2_refs).items():
            results[pid]["semantic_scholar"] = v
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
        targets = [(pid, r[name]) for pid, r in refs.items() if r[name]]
        failures = 0
        for pid, ref in targets:
            try:
                value = fn(ref)
            except Exception as exc:
                failures += 1
                if failures >= 5:
                    log(f"  [{name}] terlalu banyak galat, sumber ini dilewati: {exc}")
                    break
                continue
            # None berarti sumber berhasil dihubungi tetapi tidak ada sinyal,
            # sehingga sinyal lama (jika ada) ikut dihapus saat digabung.
            results[pid][name] = value
            time.sleep(delay)
        found = sum(1 for pid, _ in targets if results[pid].get(name))
        log(f"  [{name}] {found} dari {len(targets)} makalah punya sinyal")
    return results
