"""Alur pembaruan harian: ambil makalah, nilai relevansi, kumpulkan sinyal, ringkas."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone

from . import acl, arxiv, embeddings, fulltext, openalex, rank, relevance, signals, store
from .config import Config
from .summarize import SUMMARY_VERSION, ModelBusy, QuotaExceeded, Summarizer

# Kolom metadata dari sumber yang boleh ditimpa saat makalah diperbarui.
METADATA_FIELDS = (
    "version", "title", "abstract", "authors", "published", "updated",
    "primary_category", "categories", "comment", "journal_ref", "abs_url", "pdf_url",
    "venue", "doi",
)


def abstract_hash(paper: dict) -> str:
    return hashlib.sha1((paper["title"] + "\n" + paper["abstract"]).encode("utf-8")).hexdigest()[:12]


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


def merge_candidates(config: Config, papers: dict, candidates: dict, now: datetime) -> int:
    """Masukkan makalah baru yang relevan, perbarui metadata makalah lama. Kembalikan jumlah baru.

    Makalah yang sama dari sumber berbeda (misalnya versi arXiv dan versi ACL)
    dikenali dari judulnya. Makalah yang sudah ada dipertahankan, dan tautan dari
    sumber lain ditambahkan ke daftar `also`.
    """
    min_rel = float(config.ranking.get("min_relevance", 2.0))
    by_title = {title_key(p["title"]): pid for pid, p in papers.items() if p.get("title")}
    added = 0
    for pid, cand in candidates.items():
        if pid in papers:
            papers[pid].update({k: cand[k] for k in METADATA_FIELDS if k in cand})
            continue
        key = title_key(cand.get("title", ""))
        twin = by_title.get(key) if key else None
        if twin:
            existing = papers[twin]
            links = existing.setdefault("also", [])
            if not any(link["id"] == pid for link in links):
                links.append({
                    "id": pid,
                    "source": cand.get("source", "arxiv"),
                    "url": cand.get("abs_url", ""),
                    "venue": cand.get("venue", ""),
                })
            if not existing.get("pdf_url") and cand.get("pdf_url"):
                existing["pdf_url"] = cand["pdf_url"]
            continue
        if rank.age_days(cand, now) > config.lookback_days(cand.get("source", "arxiv")):
            continue
        rel = relevance.score_paper(config, cand)
        if rel["relevance"] < min_rel:
            continue
        papers[pid] = {**cand, **rel, "signals": {}, "summary": None, "first_seen": now.isoformat(timespec="seconds")}
        by_title[key] = pid
        added += 1
    return added


def rescore(config: Config, papers: dict, now: datetime) -> None:
    half_life = float(config.ranking.get("half_life_days", 14))
    for paper in papers.values():
        paper.update(relevance.score_paper(config, paper))
        paper["score"] = rank.score(paper, half_life, now)


def needs_summary(paper: dict) -> bool:
    summary = paper.get("summary")
    return (
        not summary
        or summary.get("version") != SUMMARY_VERSION
        or summary.get("source_hash") != abstract_hash(paper)
    )


def summarize_pending(
    config: Config, papers: dict, summarizer: Summarizer, log=print, pdf_fetcher=fulltext.fetch_pdf
) -> int:
    min_rel = float(config.ranking.get("min_relevance", 2.0))
    use_full_text = bool(config.summaries.get("use_full_text", True))
    max_pdf_mb = float(config.summaries.get("max_pdf_mb", fulltext.DEFAULT_MAX_MB))
    pending = [p for p in papers.values() if p["relevance"] >= min_rel and needs_summary(p)]
    pending.sort(key=lambda p: p.get("score", 0), reverse=True)
    limit = int(config.summaries.get("max_per_run", 25))
    delay = float(config.summaries.get("request_delay_seconds", 7))
    max_busy = int(config.summaries.get("max_busy_papers", 4))
    busy_wait = float(config.summaries.get("busy_wait_seconds", 60))
    done = 0
    busy_streak = 0
    for i, paper in enumerate(pending[:limit]):
        if i:
            time.sleep(delay)
        pdf = pdf_fetcher(paper, max_pdf_mb, log=log) if use_full_text else None
        try:
            result, model = summarizer.summarize(paper, pdf)
        except QuotaExceeded as exc:
            log(f"  [Gemini] berhenti: {exc}. Sisa makalah diringkas pada jalankan berikutnya")
            break
        except ModelBusy as exc:
            busy_streak += 1
            log(f"  [Gemini] {paper['id']} dilewati: {exc}")
            if busy_streak >= max_busy:
                log("  [Gemini] layanan sedang sibuk, sisa makalah diringkas pada jalankan berikutnya")
                break
            # Lonjakan permintaan biasanya reda dalam hitungan menit.
            time.sleep(busy_wait)
            continue
        except Exception as exc:
            log(f"  [Gemini] {paper['id']} gagal: {exc}")
            continue
        busy_streak = 0
        result.update(
            model=model,
            source_hash=abstract_hash(paper),
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        paper["summary"] = result
        done += 1
    full = sum(1 for p in pending[:limit] if (p.get("summary") or {}).get("source") == "full_text")
    log(f"  [Gemini] {done} ringkasan baru ({full} dari isi lengkap), {max(0, len(pending) - done)} masih menunggu")
    return done


def fetch_all(config: Config, papers: dict, sources_state: dict, now: datetime, log=print) -> None:
    """Ambil kandidat dari semua sumber yang aktif, berurutan arXiv, ACL, OpenAlex."""
    log("Mengambil makalah dari arXiv...")
    added = merge_candidates(config, papers, arxiv.fetch_candidates(config, log=log), now)
    log(f"  {added} makalah baru yang relevan dari arXiv")

    if config.acl.get("enabled", True):
        log("Mengambil makalah dari ACL Anthology...")
        try:
            cands = acl.fetch_candidates(config.acl, sources_state.setdefault("acl", {}), now, log=log)
            added = merge_candidates(config, papers, cands, now)
            log(f"  {added} makalah baru yang relevan dari ACL Anthology")
        except Exception as exc:
            log(f"  [ACL] gagal: {str(exc)[:200]}")

    if config.openalex.get("enabled", True):
        log("Mengambil makalah dari OpenAlex (jurnal dan konferensi)...")
        try:
            cands = openalex.fetch_candidates(config, sources_state.setdefault("openalex", {}), now, log=log)
            added = merge_candidates(config, papers, cands, now)
            log(f"  {added} makalah baru yang relevan dari OpenAlex")
        except Exception as exc:
            log(f"  [OpenAlex] gagal: {str(exc)[:200]}")
    log(f"  Total tersimpan: {len(papers)} makalah")


def update(config: Config, *, fetch=True, collect_signals=True, summaries=True, vectors=True, log=print) -> dict:
    data = store.load()
    papers = data["papers"]
    now = datetime.now(timezone.utc)

    if fetch:
        fetch_all(config, papers, data.setdefault("sources", {}), now, log=log)

    rescore(config, papers, now)

    if collect_signals:
        # Sinyal hanya diperbarui untuk makalah yang masih baru; untuk makalah lama
        # sinyalnya jarang berubah, sementara pencarian GitHub dibatasi 30 kali per menit.
        signal_days = float(config.signals.get("lookback_days", 30))
        recent = [
            p for p in papers.values()
            if p.get("relevance", 0) >= float(config.ranking.get("min_relevance", 2.0))
            and rank.age_days(p, now) <= min(signal_days, config.lookback_days(p.get("source", "arxiv")))
        ]
        log(f"Mengumpulkan sinyal popularitas untuk {len(recent)} makalah...")
        for pid, sig in signals.collect(recent, log=log).items():
            current = papers[pid].setdefault("signals", {})
            for source, value in sig.items():
                if value is None:
                    current.pop(source, None)
                else:
                    current[source] = value
        rescore(config, papers, now)

    if summaries:
        summarizer = Summarizer(config.summaries.get("models", ["gemini-flash-latest"]), log=log)
        if summarizer.enabled:
            log("Membuat ringkasan dwibahasa...")
            summarize_pending(config, papers, summarizer, log=log)
        else:
            log("GEMINI_API_KEY tidak diisi, langkah ringkasan dilewati")

    store.save(data)
    if vectors:
        embeddings.run(config, papers, log=log)
    return data
