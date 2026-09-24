"""Pembantu HTTP kecil berbasis pustaka standar, dengan percobaan ulang sederhana."""

from __future__ import annotations

import json
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


def request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
    retries: int = 3,
    backoff: float = 2.0,
) -> bytes:
    """Kirim permintaan dan kembalikan isi respons.

    Percobaan ulang hanya dilakukan untuk galat jaringan dan status 5xx.
    Status 4xx (termasuk 429) langsung dilempar agar pemanggil yang memutuskan.
    """
    all_headers = {"User-Agent": USER_AGENT}
    all_headers.update(headers or {})
    last_error: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code < 500:
                raise HttpError(exc.code, url, body) from exc
            last_error = HttpError(exc.code, url, body)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
        time.sleep(backoff * (2**attempt))
    assert last_error is not None
    raise last_error


def get_json(url: str, **kwargs) -> object:
    return json.loads(request(url, **kwargs).decode("utf-8"))


def post_json(url: str, payload: object, headers: dict[str, str] | None = None, **kwargs) -> object:
    all_headers = {"Content-Type": "application/json"}
    all_headers.update(headers or {})
    body = json.dumps(payload).encode("utf-8")
    return json.loads(request(url, method="POST", data=body, headers=all_headers, **kwargs).decode("utf-8"))
