"""Mengunduh PDF makalah untuk dibaca Gemini secara utuh.

Hanya PDF akses terbuka yang diambil: arXiv, ACL Anthology, dan tautan akses
terbuka dari OpenAlex. Jika gagal, ringkasan dibuat dari abstrak saja.
"""

from __future__ import annotations

import urllib.parse

from . import http

# Batas ukuran PDF. Permintaan Gemini dengan data sisipan dibatasi 20 MB,
# dan base64 menambah sekitar sepertiga ukuran.
DEFAULT_MAX_MB = 14


def pdf_url(paper: dict) -> str:
    """Alamat PDF yang aman dikirim. Beberapa jurnal memakai spasi di nama berkas
    ("/get/IJCSMT/VOL. 12 NO. 6 2026/..."), yang ditolak urllib jika tidak dikodekan."""
    url = (paper.get("pdf_url") or "").strip()
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=~")
    query = urllib.parse.quote(parts.query, safe="=&%:/?+,;@!$'()*~")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def fetch_pdf(paper: dict, max_mb: float = DEFAULT_MAX_MB, log=print) -> bytes | None:
    """Kembalikan isi PDF, atau None jika tidak tersedia, terlalu besar, atau bukan PDF."""
    url = pdf_url(paper)
    if not url:
        return None
    try:
        body = http.request(
            url,
            headers={"Accept": "application/pdf,*/*;q=0.8"},
            timeout=90,
            retries=2,
            backoff=5,
        )
    except Exception as exc:
        log(f"  [PDF] {paper['id']} gagal diunduh: {str(exc)[:120]}")
        return None
    if not body.startswith(b"%PDF"):
        log(f"  [PDF] {paper['id']} bukan berkas PDF, memakai abstrak")
        return None
    if len(body) > max_mb * 1024 * 1024:
        log(f"  [PDF] {paper['id']} terlalu besar ({len(body) / 1048576:.1f} MB), memakai abstrak")
        return None
    return body
