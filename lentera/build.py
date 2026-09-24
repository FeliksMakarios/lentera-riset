"""Pembangkit situs statis. Semua tautan bersifat relatif agar bisa dilayani dari subfolder GitHub Pages."""

from __future__ import annotations

import html
import re
import shutil
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from . import relevance, store
from .config import ROOT, Config
from .rank import parse_date
from .summarize import SECTIONS

STATIC_DIR = ROOT / "static"
MONTHS_ID = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

esc = html.escape


# ---------------------------------------------------------------------------
# Pembantu teks
# ---------------------------------------------------------------------------

def inline(text: str) -> str:
    """Escape HTML, lalu ubah *istilah* menjadi <em>istilah</em>."""
    return re.sub(r"\*([^*\n]+?)\*", r"<em>\1</em>", esc(text or ""))


def plain(text: str) -> str:
    """Escape HTML dan buang penanda *istilah* (untuk teks bahasa Inggris)."""
    return esc(re.sub(r"\*([^*\n]+?)\*", r"\1", text or ""))


def paragraphs(text: str, fmt=inline) -> str:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    return "".join(f"<p>{fmt(p)}</p>" for p in parts)


def date_id(value: str) -> str:
    d = parse_date(value)
    return f"{d.day} {MONTHS_ID[d.month - 1]} {d.year}"


def authors_short(authors: list[str], limit: int = 4) -> str:
    if len(authors) <= limit:
        return ", ".join(authors)
    return ", ".join(authors[:limit]) + f", dan {len(authors) - limit} lainnya"


def slug(paper_id: str) -> str:
    return re.sub(r"[/:]", "_", paper_id)


SOURCE_LABELS = {"arxiv": "arXiv", "acl": "ACL Anthology", "openalex": "DOI"}
DATA_SOURCES = {"arxiv": "arXiv", "acl": "ACL Anthology", "openalex": "OpenAlex"}


def source_label(paper: dict) -> str:
    """Nama sumber untuk ditampilkan: arXiv, ACL Anthology, atau nama jurnal/konferensi."""
    source = paper.get("source", "arxiv")
    if source == "arxiv":
        return "arXiv"
    return paper.get("venue") or SOURCE_LABELS.get(source, source)


def tldr_pair(summary: dict | None) -> tuple[str, str] | None:
    """(TL;DR Indonesia, TL;DR Inggris), mendukung format ringkasan lama dan baru."""
    if not summary:
        return None
    if isinstance(summary.get("tldr"), dict):
        return summary["tldr"]["id"], summary["tldr"]["en"]
    if isinstance(summary.get("id"), dict):
        return summary["id"].get("tldr", ""), summary["en"].get("tldr", "")
    return None


# ---------------------------------------------------------------------------
# Komponen
# ---------------------------------------------------------------------------

def page(title: str, body: str, *, root: str, config: Config, updated_at: str | None, description: str = "") -> str:
    site = config.site
    desc = description or site.get("tagline", "")
    updated = f"Data diperbarui {date_id(updated_at)}." if updated_at else ""
    return f"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="stylesheet" href="{root}assets/style.css">
<link rel="alternate" type="application/rss+xml" title="{esc(site.get('title', ''))}" href="{root}feed.xml">
</head>
<body>
<header class="site-header">
  <div class="wrap header-inner">
    <a class="brand" href="{root}index.html"><span class="brand-mark" aria-hidden="true"></span>{esc(site.get('title', 'Lentera Riset'))}</a>
    <nav><a href="{root}index.html">Makalah</a><a href="{root}tentang.html">Tentang</a><a href="{root}feed.xml">RSS</a></nav>
  </div>
</header>
<main class="wrap">
{body}
</main>
<footer class="site-footer">
  <div class="wrap">
    <p>{updated} Metadata makalah dari <a href="https://arxiv.org">arXiv</a>, <a href="https://aclanthology.org">ACL Anthology</a>, dan <a href="https://openalex.org">OpenAlex</a>. Thank you to arXiv for use of its open access interoperability.</p>
    <p>Ringkasan dibuat otomatis oleh model bahasa dan bisa keliru. Selalu periksa makalah aslinya. <a href="{esc(site.get('repo_url', '#'))}">Kode sumber</a>.</p>
  </div>
</footer>
<script src="{root}assets/app.js" defer></script>
</body>
</html>
"""


def topic_chips(config: Config, paper: dict) -> str:
    chips = []
    for tid in paper.get("topics", []):
        topic = config.topic(tid)
        if topic:
            chips.append(f'<span class="chip chip-{esc(tid)}">{esc(topic.label_id)}</span>')
    return "".join(chips)


def signal_items(paper: dict) -> list[tuple[str, str, str]]:
    """Daftar (label, nilai, url) untuk sinyal yang tersedia."""
    s = paper.get("signals") or {}
    items = []
    if hf := s.get("hugging_face"):
        items.append(("Hugging Face", f"{hf['upvotes']} suka", hf.get("url", "")))
    if hn := s.get("hacker_news"):
        items.append(("Hacker News", f"{hn['points']} poin, {hn['comments']} komentar", hn.get("url", "")))
    if gh := s.get("github"):
        items.append(("GitHub", f"{gh['stars']} bintang", gh.get("url", "")))
    if s2 := s.get("semantic_scholar"):
        if s2.get("citations"):
            items.append(("Sitasi", str(s2["citations"]), s2.get("url", "")))
    return items


def signals_inline(paper: dict) -> str:
    items = signal_items(paper)
    if not items:
        return ""
    spans = "".join(f"<span><b>{esc(label)}</b> {esc(value)}</span>" for label, value, _ in items)
    return f'<div class="signals">{spans}</div>'


def card(config: Config, paper: dict) -> str:
    summary = paper.get("summary")
    pair = tldr_pair(summary)
    if pair:
        tldr = (
            f'<p class="tldr" lang="id">{inline(pair[0])}</p>'
            f'<p class="tldr tldr-en" lang="en">{plain(pair[1])}</p>'
        )
    else:
        abstract = paper["abstract"]
        short = abstract if len(abstract) <= 280 else abstract[:280].rsplit(" ", 1)[0] + "..."
        tldr = f'<p class="tldr tldr-pending" lang="en">{esc(short)}</p>'
    search_blob = " ".join(
        [paper["title"], " ".join(paper["authors"]), paper["abstract"]]
        + (summary.get("languages_studied", []) if summary else [])
    ).lower()
    return f"""<article class="card" data-date="{esc(paper['published'])}" data-score="{paper.get('score', 0)}" data-topics="{esc(' '.join(paper.get('topics', [])))}" data-search="{esc(search_blob)}">
  <div class="card-meta"><time datetime="{esc(paper['published'])}">{date_id(paper['published'])}</time><span>{esc(source_label(paper))}</span>{topic_chips(config, paper)}</div>
  <h2><a href="papers/{slug(paper['id'])}.html">{esc(paper['title'])}</a></h2>
  <p class="authors">{esc(authors_short(paper['authors']))}</p>
  {tldr}
  {signals_inline(paper)}
</article>"""


def index_body(config: Config, papers: list[dict]) -> str:
    options = "".join(
        f'<option value="{esc(t.id)}">{esc(t.label_id)}</option>' for t in config.topics
    )
    cards = "\n".join(card(config, p) for p in papers)
    empty = "" if papers else '<p class="empty">Belum ada makalah. Data akan muncul setelah alur kerja harian berjalan.</p>'
    return f"""<section class="intro">
  <h1>{esc(config.site.get('title', 'Lentera Riset'))}</h1>
  <p>{esc(config.site.get('tagline', ''))}</p>
</section>
<section class="controls" aria-label="Pengaturan daftar">
  <div class="tabs" role="tablist">
    <button type="button" role="tab" class="tab" data-sort="score" aria-selected="true">Sedang ramai</button>
    <button type="button" role="tab" class="tab" data-sort="date" aria-selected="false">Terbaru</button>
  </div>
  <label class="field"><span class="sr-only">Topik</span>
    <select id="topic-filter"><option value="">Semua topik</option>{options}</select>
  </label>
  <label class="field grow"><span class="sr-only">Cari</span>
    <input id="search" type="search" placeholder="Cari judul, penulis, bahasa...">
  </label>
</section>
<p class="result-count" id="result-count" aria-live="polite">{len(papers)} makalah</p>
<section id="paper-list" class="paper-list">
{cards}
{empty}
</section>
<p class="empty" id="no-results" hidden>Tidak ada makalah yang cocok.</p>"""


def legacy_summary(summary: dict) -> str:
    """Ringkasan format lama (sebelum enam bagian), ditampilkan sampai dibuat ulang."""
    cols = []
    for lang, heading in (("id", "Bahasa Indonesia"), ("en", "English")):
        part = summary[lang]
        fmt = inline if lang == "id" else plain
        cols.append(f'''<div class="summary-col" lang="{lang}"><h3>{heading}</h3>{paragraphs(part.get("summary", ""), fmt)}</div>''')
    return f'<div class="compare">{"".join(cols)}</div>'


def structured_summary(summary: dict) -> str:
    """Enam bagian ringkasan; tiap bagian menampilkan versi Indonesia dan Inggris berdampingan."""
    blocks = []
    for key, title_id, title_en in SECTIONS:
        part = summary["sections"].get(key)
        if not part:
            continue
        blocks.append(f"""<section class="summary-section" id="{key}">
  <h3>{esc(title_id)} <span class="en-title" lang="en">{esc(title_en)}</span></h3>
  <div class="compare">
    <div class="summary-col" lang="id"><span class="col-label">Indonesia</span>{paragraphs(part['id'], inline)}</div>
    <div class="summary-col" lang="en"><span class="col-label">English</span>{paragraphs(part['en'], plain)}</div>
  </div>
</section>""")
    return "\n".join(blocks)


def links_for(paper: dict) -> list[tuple[str, str]]:
    source = paper.get("source", "arxiv")
    main_label = {"arxiv": "arXiv", "acl": "ACL Anthology"}.get(source, "DOI" if paper.get("doi") else "Halaman makalah")
    links = [(main_label, paper["abs_url"])]
    if paper.get("pdf_url"):
        links.append(("PDF", paper["pdf_url"]))
    for alt in paper.get("also", []):
        label = {"arxiv": "arXiv", "acl": "ACL Anthology"}.get(alt.get("source"), alt.get("venue") or "Versi lain")
        if alt.get("url"):
            links.append((label, alt["url"]))
    links += [(label, url) for label, _, url in signal_items(paper) if url]
    return links


def paper_body(config: Config, paper: dict) -> str:
    summary = paper.get("summary")
    link_html = "".join(
        f'<a class="button" href="{esc(url)}" rel="noopener">{esc(label)}</a>' for label, url in links_for(paper)
    )

    matched = paper.get("matched_keywords") or {}
    matched_html = "".join(
        f"<li><b>{esc(config.topic(tid).label_id if config.topic(tid) else tid)}</b>: {esc(', '.join(kws))}</li>"
        for tid, kws in matched.items()
    )

    pair = tldr_pair(summary)
    tldr_html = (
        f"""<div class="tldr-card">
    <span class="tldr-label">TL;DR</span>
    <p lang="id">{inline(pair[0])}</p>
    <p class="tldr-en" lang="en">{plain(pair[1])}</p>
  </div>"""
        if pair else ""
    )

    if summary:
        glossary = "".join(
            f"<dt>{esc(g['term'])}</dt><dd>{inline(g['explanation_id'])}</dd>" for g in summary.get("glossary", [])
        )
        glossary_html = f'<section class="glossary"><h2>Glosarium istilah</h2><dl>{glossary}</dl></section>' if glossary else ""
        langs = summary.get("languages_studied") or []
        langs_html = (
            '<p class="langs"><b>Bahasa yang dikaji:</b> ' + "".join(f'<span class="chip">{esc(l)}</span>' for l in langs) + "</p>"
            if langs else ""
        )
        if summary.get("source") == "full_text":
            basis = "dari isi lengkap makalah (PDF)"
        else:
            basis = "hanya dari judul dan abstrak, karena PDF akses terbuka tidak tersedia"
        body = structured_summary(summary) if "sections" in summary else legacy_summary(summary)
        summary_html = f"""<section class="summary">
  <h2>Ringkasan</h2>
  <p class="note">Dibuat otomatis oleh {esc(summary.get('model', 'model bahasa'))} {basis}. TL;DR di atas diringkas dari abstrak. Istilah bercetak miring sengaja dipertahankan dalam bahasa Inggris.</p>
  {langs_html}
  {body}
</section>
{glossary_html}"""
        abstract_html = f'<details class="abstract"><summary>Abstrak asli</summary><p lang="en">{esc(paper["abstract"])}</p></details>'
    else:
        summary_html = '<p class="note">Ringkasan dwibahasa belum tersedia untuk makalah ini. Berikut abstrak aslinya.</p>'
        abstract_html = f'<section class="abstract-open"><h2>Abstrak</h2><p lang="en">{esc(paper["abstract"] or "Abstrak tidak tersedia.")}</p></section>'

    extra = ""
    if paper.get("comment"):
        extra += f"<li><b>Catatan penulis:</b> {esc(paper['comment'])}</li>"
    if paper.get("journal_ref"):
        extra += f"<li><b>Terbit di:</b> {esc(paper['journal_ref'])}</li>"
    extra += f"<li><b>Sumber data:</b> {esc(DATA_SOURCES.get(paper.get('source', 'arxiv'), 'arXiv'))}</li>"

    meta = [date_id(paper["published"]), source_label(paper)]
    if paper.get("source", "arxiv") == "arxiv" and paper.get("categories"):
        meta.append(", ".join(paper["categories"]))
    return f"""<p class="back"><a href="../index.html">&larr; Semua makalah</a></p>
<article class="paper">
  <div class="card-meta">{"".join(f"<span>{esc(m)}</span>" for m in meta)}</div>
  <h1 lang="en">{esc(paper['title'])}</h1>
  <p class="authors">{esc(', '.join(paper['authors']))}</p>
  {tldr_html}
  <div class="topic-row">{topic_chips(config, paper)}</div>
  <div class="links">{link_html}</div>
  {summary_html}
  {abstract_html}
  <section class="details">
    <h2>Mengapa makalah ini muncul</h2>
    <ul>{matched_html}{extra}</ul>
  </section>
</article>"""


def about_body(config: Config) -> str:
    topics = "".join(
        f"<li><b>{esc(t.label_id)}</b> ({esc(t.label_en)}): {esc(', '.join(t.keywords[:12]))}{', dan lainnya' if len(t.keywords) > 12 else ''}</li>"
        for t in config.topics
    )
    cats = ", ".join(config.arxiv.get("categories", []))
    return f"""<article class="prose">
<h1>Tentang {esc(config.site.get('title', 'Lentera Riset'))}</h1>
<p>{esc(config.site.get('tagline', ''))} Situs ini terinspirasi oleh Emergent Mind, tetapi berfokus pada bahasa berdaya sumber rendah, bahasa daerah Indonesia, dan bahasa Austronesia lainnya.</p>

<h2>Cara kerja</h2>
<ol>
<li>Setiap hari, sistem mencari makalah baru dari tiga sumber: arXiv (kategori {esc(cats)}), ACL Anthology (volume prosiding yang baru masuk), dan OpenAlex (jurnal serta konferensi lain, misalnya IEEE). Makalah yang sama dari beberapa sumber digabung menjadi satu.</li>
<li>Setiap makalah diberi <b>skor relevansi</b> berdasarkan kata kunci yang muncul di judul dan abstraknya. Kata kunci di judul bernilai dua kali lipat.</li>
<li>Sistem mengumpulkan <b>sinyal keramaian</b> dari Hugging Face Papers, Hacker News, GitHub, dan jumlah sitasi dari Semantic Scholar.</li>
<li>Skor akhir adalah relevansi ditambah keramaian, lalu berkurang separuh setiap {esc(str(config.ranking.get('half_life_days', 14)))} hari supaya makalah baru tidak tenggelam.</li>
<li>Gemini membaca isi lengkap makalah (PDF akses terbuka) dan menyusun ringkasan dalam bahasa Inggris dan Indonesia dengan enam bagian: latar belakang masalah, penelitian terkait, kontribusi dan kebaruan, metode, hasil dan pembahasan, serta penelitian selanjutnya. TL;DR dua kalimat diringkas dari abstrak. Istilah teknis yang lazim tetap ditulis dalam bahasa Inggris dan dicetak miring, disertai glosarium.</li>
</ol>

<h2>Topik yang dipantau</h2>
<ul>{topics}</ul>

<h2>Keterbatasan</h2>
<ul>
<li>Jika PDF akses terbuka tidak tersedia (misalnya makalah jurnal berbayar), ringkasan dibuat dari abstrak saja. Halaman makalah menyebutkan dasar ringkasannya.</li>
<li>Model bahasa bisa keliru. Periksa makalah aslinya sebelum mengutip.</li>
<li>Makalah tentang bahasa berdaya sumber rendah jarang ramai di media sosial, sehingga peringkat lebih banyak ditentukan oleh relevansi dan kebaruan.</li>
<li>Sinyal dari X (Twitter) dan Reddit belum dipakai karena API-nya berbayar atau mewajibkan otorisasi khusus.</li>
</ul>

<h2>Sumber data</h2>
<p>Metadata makalah diambil dari <a href="https://info.arxiv.org/help/api/index.html">arXiv API</a>, data terbuka <a href="https://github.com/acl-org/acl-anthology">ACL Anthology</a> (CC BY 4.0), dan <a href="https://openalex.org">OpenAlex</a> (CC0). Thank you to arXiv for use of its open access interoperability. Situs ini tidak berafiliasi dengan arXiv, ACL, maupun OpenAlex. Hak cipta setiap makalah tetap milik penulisnya.</p>
</article>"""


def feed(config: Config, papers: list[dict], updated_at: str | None) -> str:
    site = config.site
    base = site.get("site_url", "").rstrip("/")
    items = []
    for p in sorted(papers, key=lambda p: p["published"], reverse=True)[:50]:
        link = f"{base}/papers/{slug(p['id'])}.html" if base else p["abs_url"]
        pair = tldr_pair(p.get("summary"))
        desc = pair[0] if pair else p["abstract"][:400]
        items.append(
            f"<item><title>{esc(p['title'])}</title><link>{esc(link)}</link>"
            f"<guid isPermaLink=\"false\">arxiv:{esc(p['id'])}</guid>"
            f"<pubDate>{format_datetime(parse_date(p['published']))}</pubDate>"
            f"<description>{esc(desc)}</description></item>"
        )
    built = format_datetime(parse_date(updated_at) if updated_at else datetime.now(timezone.utc))
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<title>{esc(site.get('title', 'Lentera Riset'))}</title>
<link>{esc(base or site.get('repo_url', ''))}</link>
<description>{esc(site.get('tagline', ''))}</description>
<language>id</language>
<lastBuildDate>{built}</lastBuildDate>
{''.join(items)}
</channel></rss>
"""


# ---------------------------------------------------------------------------
# Pembangunan
# ---------------------------------------------------------------------------

def select_papers(config: Config, papers: dict) -> list[dict]:
    """Makalah yang tampil: relevan, maksimal N terbaru, diurutkan menurut skor.

    Relevansi dihitung ulang dengan konfigurasi saat ini, jadi perubahan kata kunci
    langsung berlaku tanpa menunggu pembaruan data berikutnya.
    """
    for paper in papers.values():
        paper.update(relevance.score_paper(config, paper))
    min_rel = float(config.ranking.get("min_relevance", 2.0))
    limit = int(config.site.get("max_papers_on_index", 300))
    relevant = [p for p in papers.values() if p.get("relevance", 0) >= min_rel]
    newest = sorted(relevant, key=lambda p: p["published"], reverse=True)[:limit]
    return sorted(newest, key=lambda p: p.get("score", 0), reverse=True)


def build_site(config: Config, out: Path, data: dict | None = None) -> None:
    data = data if data is not None else store.load()
    updated_at = data.get("updated_at")
    papers = select_papers(config, data["papers"])

    if out.exists():
        shutil.rmtree(out)
    (out / "papers").mkdir(parents=True)
    shutil.copytree(STATIC_DIR, out / "assets")

    title = config.site.get("title", "Lentera Riset")
    (out / "index.html").write_text(
        page(title, index_body(config, papers), root="", config=config, updated_at=updated_at), encoding="utf-8"
    )
    (out / "tentang.html").write_text(
        page(f"Tentang | {title}", about_body(config), root="", config=config, updated_at=updated_at), encoding="utf-8"
    )
    for paper in papers:
        pair = tldr_pair(paper.get("summary"))
        desc = pair[0] if pair else paper["abstract"][:200]
        (out / "papers" / f"{slug(paper['id'])}.html").write_text(
            page(f"{paper['title']} | {title}", paper_body(config, paper), root="../",
                 config=config, updated_at=updated_at, description=desc.replace("*", "")),
            encoding="utf-8",
        )
    (out / "feed.xml").write_text(feed(config, papers, updated_at), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Situs dibangun di {out} ({len(papers)} makalah)")
