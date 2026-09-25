"""Vektor makna (embedding) makalah untuk pencarian semantik dan daftar makalah serupa.

Vektor dibuat dengan model embedding Gemini (kuota gratis) dari judul dan abstrak,
lalu disimpan di data/embeddings.json sebagai float16 base64 supaya berkasnya kecil.
Pertanyaan pengunjung diubah menjadi vektor oleh Cloudflare Worker (folder worker/)
dengan model dan dimensi yang sama, jadi keduanya bisa dibandingkan langsung.
"""

from __future__ import annotations

import base64
import hashlib
import heapq
import json
import math
import operator
import os
import struct
import time
from pathlib import Path

from . import http
from .config import ROOT, Config

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
DEFAULT_STORE = ROOT / "data" / "embeddings.json"


class EmbeddingQuotaExceeded(Exception):
    """Kuota harian habis atau model tidak tersedia; sisa makalah menunggu jalankan berikutnya."""


# ---------------------------------------------------------------------------
# Penyandian vektor
# ---------------------------------------------------------------------------

def normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def encode_f16(values: list[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(values)}e", *values)).decode("ascii")


def decode_f16(text: str) -> list[float]:
    raw = base64.b64decode(text)
    return list(struct.unpack(f"<{len(raw) // 2}e", raw))


def encode_i8(values: list[float]) -> str:
    """Kuantisasi ke int8 untuk berkas indeks di situs. Skala tidak disimpan karena
    pencarian memakai kemiripan kosinus, yang tidak terpengaruh skala."""
    peak = max((abs(v) for v in values), default=0.0) or 1.0
    ints = [max(-127, min(127, round(v / peak * 127))) for v in values]
    return base64.b64encode(struct.pack(f"<{len(ints)}b", *ints)).decode("ascii")


def embed_text(paper: dict, max_chars: int) -> str:
    return f"{paper['title']}\n\n{paper.get('abstract') or ''}".strip()[:max_chars]


def text_hash(text: str, model: str, dimensions: int) -> str:
    return hashlib.sha1(f"{model}|{dimensions}|{text}".encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Penyimpanan
# ---------------------------------------------------------------------------

def load(path: Path = DEFAULT_STORE) -> dict:
    if not path.exists():
        return {"model": None, "dimensions": None, "vectors": {}}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("vectors", {})
    return data


def save(data: dict, path: Path = DEFAULT_STORE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=0, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)


def vectors_for(data: dict, config: Config) -> dict[str, list[float]]:
    """Vektor ternormalisasi per makalah, hanya jika model dan dimensinya sesuai konfigurasi."""
    settings = config.embeddings
    if data.get("model") != settings.get("model") or data.get("dimensions") != int(settings.get("dimensions", 256)):
        return {}
    return {pid: normalize(decode_f16(item["v"])) for pid, item in data.get("vectors", {}).items()}


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def call_batch(model: str, dimensions: int, api_key: str, texts: list[str]) -> list[list[float]]:
    payload = {
        "requests": [
            {
                "model": f"models/{model}",
                "content": {"parts": [{"text": t}]},
                "taskType": "RETRIEVAL_DOCUMENT",
                "outputDimensionality": dimensions,
            }
            for t in texts
        ]
    }
    data = http.post_json(
        API_URL.format(model=model), payload, headers={"x-goog-api-key": api_key}, timeout=120, retries=3, backoff=10
    )
    vectors = [e.get("values") or [] for e in data.get("embeddings", [])]
    if len(vectors) != len(texts) or any(len(v) != dimensions for v in vectors):
        raise ValueError(f"respons embedding tidak lengkap: {len(vectors)} vektor untuk {len(texts)} teks")
    return vectors


def update(config: Config, papers: dict, store: dict, *, api_key: str | None = None,
           log=print, sleep=time.sleep, call=call_batch) -> int:
    """Buat vektor untuk makalah relevan yang belum punya, lalu buang vektor makalah yang sudah dihapus.

    Kembalikan jumlah vektor baru.
    """
    settings = config.embeddings
    api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
    model = settings.get("model", "gemini-embedding-001")
    dims = int(settings.get("dimensions", 256))
    if store.get("model") != model or store.get("dimensions") != dims:
        # Model atau dimensi berubah: vektor lama tidak sebanding lagi.
        store.update(model=model, dimensions=dims, vectors={})
    vectors = store["vectors"]
    for pid in [pid for pid in vectors if pid not in papers]:
        del vectors[pid]
    if not api_key:
        log("  [Embedding] GEMINI_API_KEY tidak diisi, langkah ini dilewati")
        return 0

    min_rel = float(config.ranking.get("min_relevance", 2.0))
    max_chars = int(settings.get("max_chars", 1200))
    pending = []
    for paper in sorted(papers.values(), key=lambda p: p.get("score", 0), reverse=True):
        if paper.get("relevance", 0) < min_rel:
            continue
        text = embed_text(paper, max_chars)
        h = text_hash(text, model, dims)
        if vectors.get(paper["id"], {}).get("h") != h:
            pending.append((paper["id"], text, h))
    limit = int(settings.get("max_per_run", 400))
    batch_size = int(settings.get("batch_size", 25))
    delay = float(settings.get("request_delay_seconds", 20))
    todo = pending[:limit]
    done = 0
    for start in range(0, len(todo), batch_size):
        batch = todo[start:start + batch_size]
        if start:
            sleep(delay)
        for attempt in range(3):
            try:
                result = call(model, dims, api_key, [t for _, t, _ in batch])
                break
            except http.HttpError as exc:
                if exc.status == 429 and "PerDay" not in exc.body and attempt < 2:
                    log("  [Embedding] batas per menit, jeda 65 detik")
                    sleep(65)
                    continue
                if exc.status in (429, 404):
                    reason = "kuota harian habis" if exc.status == 429 else f"model {model} tidak tersedia"
                    log(f"  [Embedding] berhenti: {reason}")
                    raise EmbeddingQuotaExceeded(reason) from exc
                raise
        else:
            break
        for (pid, _, h), values in zip(batch, result):
            vectors[pid] = {"h": h, "v": encode_f16(normalize(values))}
            done += 1
    return done


def run(config: Config, papers: dict, path: Path = DEFAULT_STORE, log=print) -> None:
    if not config.embeddings.get("enabled", True):
        return
    store = load(path)
    log("Membuat vektor makna (embedding)...")
    try:
        done = update(config, papers, store, log=log)
    except EmbeddingQuotaExceeded:
        done = None
    except Exception as exc:
        log(f"  [Embedding] gagal: {str(exc)[:200]}")
        done = None
    save(store, path)
    total = len(store["vectors"])
    if done is not None:
        log(f"  [Embedding] {done} vektor baru, total {total}")
    else:
        log(f"  [Embedding] total {total} vektor tersimpan")


# ---------------------------------------------------------------------------
# Makalah serupa
# ---------------------------------------------------------------------------

def similar(vectors: dict[str, list[float]], ids: list[str], k: int = 5, min_score: float = 0.5) -> dict[str, list[tuple[str, float]]]:
    """Untuk setiap makalah di `ids`, k makalah lain dengan kemiripan kosinus tertinggi."""
    ids = [i for i in ids if i in vectors]
    rows = [vectors[i] for i in ids]
    scores: list[list[tuple[float, str]]] = [[] for _ in ids]
    # Setiap pasangan dihitung sekali; map(operator.mul) jauh lebih cepat daripada zip biasa.
    for i, va in enumerate(rows):
        for j in range(i + 1, len(rows)):
            s = sum(map(operator.mul, va, rows[j]))
            if s >= min_score:
                scores[i].append((s, ids[j]))
                scores[j].append((s, ids[i]))
    return {
        pid: [(other, s) for s, other in heapq.nlargest(k, scores[n])]
        for n, pid in enumerate(ids)
    }
