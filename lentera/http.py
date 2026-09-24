"""Pembantu HTTP kecil berbasis pustaka standar, dengan percobaan ulang sederhana."""

from __future__ import annotations

import gzip
import json
import random
import time
import urllib.error
import urllib.request

from . import __version__

USER_AGENT = f"lentera-riset/{__version__} (+https://github.com/FeliksMakarios/lentera-riset)"


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} untuk {url}: {body[:200]}")
        self.status = status
        self.url = url
        self.body = body


def _retry_after(headers) -> float | None:
    value = headers.get("Retry-After") if headers else None
    try:
        return float(value) if value else None
    except ValueError:
        return None


def request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
    retries: int = 3,
    backoff: float = 2.0,
    retry_statuses: frozenset[int] = frozenset(),
    log=None,
) -> bytes:
    """Kirim permintaan dan kembalikan isi respons (sudah didekompresi jika gzip).

    Percobaan ulang dilakukan untuk galat jaringan, status 5xx, dan status di
    `retry_statuses` (misalnya 406 atau 429 yang dipakai server untuk membatasi
    permintaan). Jeda naik dua kali lipat setiap percobaan, ditambah sedikit acak.
    Status 4xx lainnya langsung dilempar agar pemanggil yang memutuskan.
    """
    all_headers = {"User-Agent": USER_AGENT}
    all_headers.update(headers or {})
    last_error: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
        wait = backoff * (2**attempt)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code < 500 and exc.code not in retry_statuses:
                raise HttpError(exc.code, url, body) from exc
            last_error = HttpError(exc.code, url, body)
            wait = max(wait, _retry_after(exc.headers) or 0)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
        if attempt < retries - 1:
            wait += random.uniform(0, backoff)
            if log:
                log(f"    percobaan {attempt + 1} gagal ({last_error.__class__.__name__}"
                    f"{' ' + str(last_error.status) if isinstance(last_error, HttpError) else ''}),"
                    f" mencoba lagi dalam {wait:.0f} detik")
            time.sleep(wait)
    assert last_error is not None
    raise last_error


def get_json(url: str, **kwargs) -> object:
    return json.loads(request(url, **kwargs).decode("utf-8"))


def post_json(url: str, payload: object, headers: dict[str, str] | None = None, **kwargs) -> object:
    all_headers = {"Content-Type": "application/json"}
    all_headers.update(headers or {})
    body = json.dumps(payload).encode("utf-8")
    return json.loads(request(url, method="POST", data=body, headers=all_headers, **kwargs).decode("utf-8"))
