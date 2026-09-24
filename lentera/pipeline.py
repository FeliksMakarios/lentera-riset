"""Alur pembaruan harian: ambil makalah, nilai relevansi, kumpulkan sinyal, ringkas."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

from . import arxiv, rank, relevance, signals, store
from .config import Config
from .summarize import ModelUnavailable, QuotaExceeded, Summarizer

# Kolom metadata dari arXiv yang boleh ditimpa saat makalah diperbarui.
ARXIV_FIELDS = (
    "version", "title", "abstract", "authors", "published", "updated",
    "primary_category", "categories", "comment", "journal_ref", "abs_url", "pdf_url",
)


def abstract_hash(paper: dict) -> str:
    return hashlib.sha1((paper["title"] + "\n" + paper["abstract"]).encode("utf-8")).hexdigest()[:12]


def merge_candidates(config: Config, papers: dict, candidates: dict, now: datetime) -> int:
    """Masukkan makalah baru yang relevan, perbarui metadata makalah lama. Kembalikan jumlah baru."""
    lookback = float(config.arxiv.get("lookback_days", 60))
    min_rel = float(config.ranking.get("min_relevance", 2.0))
    added = 0
    for pid, cand in candidates.items():
        if pid in papers:
            papers[pid].update({k: cand[k] for k in ARXIV_FIELDS})
            continue
        if rank.age_days(cand, now) > lookback:
            continue
        rel = relevance.score_paper(config, cand)
        if rel["relevance"] < min_rel:
            continue
        papers[pid] = {**cand, **rel, "signals": {}, "summary": None, "first_seen": now.isoformat(timespec="seconds")}
        added += 1
    return added


def rescore(config: Config, papers: dict, now: datetime) -> None:
    half_life = float(config.ranking.get("half_life_days", 14))
    for paper in papers.values():
        paper.update(relevance.score_paper(config, paper))
        paper["score"] = rank.score(paper, half_life, now)


def summarize_pending(config: Config, papers: dict, summarizer: Summarizer, log=print) -> int:
    min_rel = float(config.ranking.get("min_relevance", 2.0))
    pending = [
        p for p in papers.values()
        if p["relevance"] >= min_rel
        and (not p.get("summary") or p["summary"].get("source_hash") != abstract_hash(p))
    ]
    pending.sort(key=lambda p: p.get("score", 0), reverse=True)
    limit = int(config.summaries.get("max_per_run", 25))
    delay = float(config.summaries.get("request_delay_seconds", 7))
    done = 0
    for paper in pending[:limit]:
        if done:
            time.sleep(delay)
        try:
            result, model = summarizer.summarize(paper)
        except QuotaExceeded:
            log("  [Gemini] kuota habis, sisa makalah diringkas pada jalankan berikutnya")
            break
        except ModelUnavailable as exc:
            log(f"  [Gemini] {exc}")
            break
        except Exception as exc:
            log(f"  [Gemini] {paper['id']} gagal: {exc}")
            continue
        result.update(
            model=model,
            source_hash=abstract_hash(paper),
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        paper["summary"] = result
        done += 1
    log(f"  [Gemini] {done} ringkasan baru, {max(0, len(pending) - done)} masih menunggu")
    return done


def update(config: Config, *, fetch=True, collect_signals=True, summaries=True, log=print) -> dict:
    data = store.load()
    papers = data["papers"]
    now = datetime.now(timezone.utc)

    if fetch:
        log("Mengambil makalah dari arXiv...")
        added = merge_candidates(config, papers, arxiv.fetch_candidates(config, log=log), now)
        log(f"  {added} makalah baru yang relevan, total {len(papers)}")

    rescore(config, papers, now)

    if collect_signals:
        lookback = float(config.arxiv.get("lookback_days", 60))
        recent = [pid for pid, p in papers.items() if rank.age_days(p, now) <= lookback]
        log(f"Mengumpulkan sinyal popularitas untuk {len(recent)} makalah...")
        for pid, sig in signals.collect(recent, log=log).items():
            papers[pid].setdefault("signals", {}).update(sig)
        rescore(config, papers, now)

    if summaries:
        summarizer = Summarizer(config.summaries.get("models", ["gemini-2.5-flash"]))
        if summarizer.enabled:
            log("Membuat ringkasan dwibahasa...")
            summarize_pending(config, papers, summarizer, log=log)
        else:
            log("GEMINI_API_KEY tidak diisi, langkah ringkasan dilewati")

    store.save(data)
    return data
