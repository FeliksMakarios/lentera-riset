"""Pembangkit situs statis. Semua tautan bersifat relatif agar bisa dilayani dari subfolder GitHub Pages."""

from __future__ import annotations

import html
import json
import os
import re
import shutil
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from . import embeddings, languages, relevance, store, tasks
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

SEARCH_ICON = (
    '<svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>'
)
NAV = [("beranda", "index.html", "Beranda"), ("makalah", "makalah.html", "Makalah"),
       ("tentang", "tentang.html", "Tentang"), ("rss", "feed.xml", "RSS")]


def page(title: str, body: str, *, root: str, config: Config, updated_at: str | None, description: str = "",
         scripts: tuple[str, ...] = (), active: str = "", query: str = "", worker_url: str = "") -> str:
    site = config.site
    extra_scripts = "".join(f'\n<script src="{root}assets/{name}" defer></script>' for name in scripts)
    desc = description or site.get("tagline", "")
    updated = f"Data diperbarui {date_id(updated_at)}." if updated_at else ""
    current = ' aria-current="page"'
    nav = "".join(
        f'<a href="{root}{href}"{current if key == active else ""}>{label}</a>'
        for key, href, label in NAV
    )
    return f"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="stylesheet" href="{root}assets/style.css">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='12' fill='%23b45309'/%3E%3Ccircle cx='16' cy='14' r='5' fill='%23fde68a'/%3E%3C/svg%3E">
<link rel="alternate" type="application/rss+xml" title="{esc(site.get('title', ''))}" href="{root}feed.xml">
</head>
<body data-root="{root}" data-worker="{esc(worker_url)}">
<header class="site-header">
  <div class="wrap header-inner">
    <a class="brand" href="{root}index.html"><span class="brand-mark" aria-hidden="true"></span>{esc(site.get('title', 'Lentera Riset'))}</a>
    <form class="site-search" action="{root}cari.html" method="get" role="search">
      <label class="sr-only" for="site-q">Cari makalah berdasarkan makna</label>
      <input id="site-q" name="q" type="search" value="{esc(query)}" placeholder="Cari makalah berdasarkan makna..." autocomplete="off" required>
      <button type="submit" aria-label="Cari">{SEARCH_ICON}</button>
    </form>
    <nav aria-label="Menu utama">{nav}</nav>
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
<script src="{root}assets/app.js" defer></script>{extra_scripts}
</body>
</html>
"""


def filter_link(root: str, key: str, value: str) -> str:
    return f"{root}makalah.html?{key}={esc(value)}"


def topic_chips(config: Config, paper: dict, root: str = "") -> str:
    chips = []
    for tid in paper.get("topics", []):
        topic = config.topic(tid)
        if topic:
            chips.append(f'<a class="chip chip-{esc(tid)}" href="{filter_link(root, "topik", tid)}">{esc(topic.label_id)}</a>')
    return "".join(chips)


def language_chips(pages: dict, paper: dict, root: str = "") -> str:
    return "".join(
        f'<a class="chip chip-lang" href="{filter_link(root, "bahasa", lid)}">{esc(pages[lid].name_id)}</a>'
        for lid in paper.get("languages", []) if lid in pages
    )


def task_chips(config: Config, paper: dict, root: str = "") -> str:
    names = {t.id: t.name for t in config.tasks}
    return "".join(
        f'<a class="chip chip-task" href="{filter_link(root, "tugas", tid)}">{esc(names[tid])}</a>'
        for tid in paper.get("tasks", []) if tid in names
    )


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


def snippet(paper: dict, limit: int = 280) -> str:
    abstract = paper.get("abstract") or ""
    return abstract if len(abstract) <= limit else abstract[:limit].rsplit(" ", 1)[0] + "..."


def card(config: Config, paper: dict, root: str = "", rank: int | None = None) -> str:
    """Kartu makalah. Bentuknya sama dengan kartu yang dibuat assets/app.js."""
    pair = tldr_pair(paper.get("summary"))
    if pair:
        tldr = (
            f'<p class="tldr" lang="id">{inline(pair[0])}</p>'
            f'<p class="tldr tldr-en" lang="en">{plain(pair[1])}</p>'
        )
    else:
        tldr = f'<p class="tldr tldr-pending" lang="en">{esc(snippet(paper))}</p>'
    badge = f'<span class="rank" aria-label="Peringkat {rank}">{rank}</span>' if rank else ""
    return f"""<article class="card">
  <div class="card-meta">{badge}<time datetime="{esc(paper['published'])}">{date_id(paper['published'])}</time><span>{esc(source_label(paper))}</span>{topic_chips(config, paper, root)}</div>
  <h2><a href="{root}papers/{slug(paper['id'])}.html">{esc(paper['title'])}</a></h2>
  <p class="authors">{esc(authors_short(paper['authors']))}</p>
  {tldr}
  {signals_inline(paper)}
</article>"""


def home_body(config: Config, trending: list[dict], newest: list[dict], newest_total: int) -> str:
    per_page = int(config.site.get("newest_per_page", 7))
    trending_cards = "\n".join(card(config, p, rank=i) for i, p in enumerate(trending, 1))
    newest_cards = "\n".join(card(config, p) for p in newest[:per_page])
    pages = max(1, -(-newest_total // per_page))
    empty = '<p class="empty">Belum ada makalah. Data akan muncul setelah alur kerja harian berjalan.</p>'
    return f"""<section class="intro">
  <h1>{esc(config.site.get('title', 'Lentera Riset'))}</h1>
  <p>{esc(config.site.get('tagline', ''))}</p>
</section>
<div class="tabs" role="tablist" aria-label="Urutan makalah">
  <button type="button" role="tab" class="tab" id="tab-trending" aria-controls="panel-trending" aria-selected="true">Sedang ramai</button>
  <button type="button" role="tab" class="tab" id="tab-newest" aria-controls="panel-newest" aria-selected="false">Terbaru</button>
</div>
<section id="panel-trending" role="tabpanel" aria-labelledby="tab-trending">
  <p class="result-count">{len(trending)} makalah teramai saat ini, menurut relevansi, sinyal keramaian, dan kebaruan. Diperbarui setiap hari.</p>
  <div class="paper-list">{trending_cards or empty}</div>
</section>
<section id="panel-newest" role="tabpanel" aria-labelledby="tab-newest" hidden data-per-page="{per_page}">
  <p class="result-count" id="newest-count">{newest_total} makalah, dari yang terbaru.</p>
  <div class="paper-list" id="newest-list">{newest_cards or empty}</div>
  <nav class="pager" id="newest-pager" aria-label="Halaman" data-pages="{pages}"></nav>
</section>
<p class="more"><a class="button" href="makalah.html">Jelajahi semua makalah per tugas, topik, dan bahasa</a></p>"""


def catalog_body(config: Config, total: int) -> str:
    per_page = int(config.site.get("catalog_per_page", 20))
    return f"""<div class="catalog">
  <aside class="facets" aria-label="Saringan">
    <div class="facet-tabs" role="tablist">
      <button type="button" role="tab" class="facet-tab" data-facet="tugas" aria-selected="true">Tugas</button>
      <button type="button" role="tab" class="facet-tab" data-facet="topik" aria-selected="false">Topik</button>
      <button type="button" role="tab" class="facet-tab" data-facet="bahasa" aria-selected="false">Bahasa</button>
    </div>
    <label class="sr-only" for="facet-filter">Saring pilihan</label>
    <input id="facet-filter" class="facet-filter" type="search" placeholder="Saring tugas berdasarkan nama" autocomplete="off">
    <div id="facet-list" class="facet-list"></div>
  </aside>
  <section class="catalog-main">
    <div class="catalog-head">
      <h1>Makalah <span class="count" id="catalog-count">{total}</span></h1>
      <label class="sr-only" for="catalog-q">Saring judul atau penulis</label>
      <input id="catalog-q" class="catalog-q" type="search" placeholder="Saring judul atau penulis" autocomplete="off">
      <label class="sr-only" for="catalog-sort">Urutan</label>
      <select id="catalog-sort">
        <option value="ramai">Urut: sedang ramai</option>
        <option value="terbaru">Urut: terbaru</option>
        <option value="judul">Urut: judul</option>
      </select>
    </div>
    <div id="active-filters" class="active-filters"></div>
    <div id="catalog-list" class="row-list" data-per-page="{per_page}"><p class="note">Memuat daftar makalah...</p></div>
    <nav class="pager" id="catalog-pager" aria-label="Halaman"></nav>
    <noscript><p class="note">Halaman ini memerlukan JavaScript.</p></noscript>
  </section>
</div>"""


def search_body(config: Config) -> str:
    topic_options = "".join(f'<option value="{esc(t.id)}">{esc(t.label_id)}</option>' for t in config.topics)
    return f"""<section class="search-head">
  <h1 id="search-title">Cari makalah</h1>
  <p class="note">Pencarian berdasarkan makna: pertanyaan dalam bahasa Indonesia atau Inggris dicocokkan dengan makalah yang maknanya paling dekat, walaupun kata-katanya berbeda.</p>
</section>
<form class="filter-bar" id="search-filters" aria-label="Saringan hasil">
  <label class="field"><span class="field-label">Rentang waktu</span>
    <select id="filter-waktu" name="waktu">
      <option value="">Kapan saja</option>
      <option value="7">7 hari terakhir</option>
      <option value="30">30 hari terakhir</option>
      <option value="90">3 bulan terakhir</option>
      <option value="365">1 tahun terakhir</option>
    </select>
  </label>
  <label class="field"><span class="field-label">Topik</span>
    <select id="filter-topik" name="topik"><option value="">Semua topik</option>{topic_options}</select>
  </label>
  <label class="field"><span class="field-label">Bahasa</span>
    <select id="filter-bahasa" name="bahasa"><option value="">Semua bahasa</option></select>
  </label>
</form>
<p class="result-count" id="search-status" aria-live="polite"></p>
<section id="search-results" class="paper-list"></section>
<noscript><p class="note">Halaman pencarian memerlukan JavaScript.</p></noscript>"""


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


def similar_html(items: list[dict]) -> str:
    if not items:
        return ""
    rows = "".join(
        f"""<li><a href="{slug(p['id'])}.html">{esc(p['title'])}</a>
  <span class="note">{date_id(p['published'])}, {esc(source_label(p))}</span></li>"""
        for p in items
    )
    return f"""<section class="similar">
    <h2>Makalah serupa</h2>
    <p class="note">Dipilih berdasarkan kedekatan makna judul dan abstrak.</p>
    <ul>{rows}</ul>
  </section>"""


def paper_body(config: Config, paper: dict, lang_pages: dict | None = None, similar: list[dict] | None = None) -> str:
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
    return f"""<p class="back"><a href="../makalah.html">&larr; Semua makalah</a></p>
<article class="paper">
  <div class="card-meta">{"".join(f"<span>{esc(m)}</span>" for m in meta)}</div>
  <h1 lang="en">{esc(paper['title'])}</h1>
  <p class="authors">{esc(', '.join(paper['authors']))}</p>
  {tldr_html}
  <div class="topic-row">{topic_chips(config, paper, "../")}{language_chips(lang_pages or {}, paper, "../")}{task_chips(config, paper, "../")}</div>
  <div class="links">{link_html}</div>
  {summary_html}
  {abstract_html}
  {similar_html(similar or [])}
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
<p>{esc(config.site.get('tagline', ''))} Situs ini berfokus pada bahasa berdaya sumber rendah, bahasa daerah Indonesia, dan bahasa Austronesia lainnya.</p>
<p>Situs ini terinspirasi oleh tiga layanan: <a href="https://www.semanticscholar.org">Semantic Scholar</a> (TL;DR dan pencarian makalah), <a href="https://huggingface.co">Hugging Face</a> (penjelajahan per tugas dan bahasa), dan <a href="https://www.emergentmind.com">Emergent Mind</a> (makalah yang sedang ramai beserta ringkasannya).</p>

<h2>Cara kerja</h2>
<ol>
<li>Setiap hari, sistem mencari makalah baru dari tiga sumber: arXiv (kategori {esc(cats)}), ACL Anthology (volume prosiding yang baru masuk), dan OpenAlex (jurnal serta konferensi lain, misalnya IEEE). Makalah yang sama dari beberapa sumber digabung menjadi satu.</li>
<li>Setiap makalah diberi <b>skor relevansi</b> berdasarkan kata kunci yang muncul di judul dan abstraknya. Kata kunci di judul bernilai dua kali lipat.</li>
<li>Sistem mengumpulkan <b>sinyal keramaian</b> dari Hugging Face Papers, Hacker News, GitHub, dan jumlah sitasi dari Semantic Scholar.</li>
<li>Skor akhir adalah relevansi ditambah keramaian, lalu berkurang separuh setiap {esc(str(config.ranking.get('half_life_days', 14)))} hari supaya makalah baru tidak tenggelam.</li>
<li>Gemini membaca isi lengkap makalah (PDF akses terbuka) dan menyusun ringkasan dalam bahasa Inggris dan Indonesia dengan enam bagian: latar belakang masalah, penelitian terkait, kontribusi dan kebaruan, metode, hasil dan pembahasan, serta penelitian selanjutnya. TL;DR dua kalimat diringkas dari abstrak. Istilah teknis yang lazim tetap ditulis dalam bahasa Inggris dan dicetak miring, disertai glosarium.</li>
</ol>

<h2>Mencari dan menjelajah</h2>
<ul>
<li><b>Beranda</b> menampilkan {esc(str(config.site.get('trending_count', 10)))} makalah yang sedang ramai dan daftar makalah terbaru. Keduanya diperbarui setiap hari.</li>
<li><b>Kolom pencarian</b> di bagian atas setiap halaman mencari berdasarkan makna. Judul dan abstrak setiap makalah diubah menjadi vektor makna dengan model embedding Gemini, begitu pula pertanyaan Anda, lalu makalah diurutkan menurut kemiripan kosinus. Hasilnya bisa disaring menurut rentang waktu, topik, dan bahasa.</li>
<li><b>Makalah</b> menampilkan seluruh koleksi dengan saringan tugas (misalnya terjemahan mesin atau pengenalan ucapan), topik, dan bahasa yang dikaji.</li>
<li><b>Makalah serupa</b> di setiap halaman makalah dipilih berdasarkan kedekatan makna judul dan abstrak.</li>
</ul>

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

def relevant_papers(config: Config, papers: dict) -> list[dict]:
    """Semua makalah yang relevan, diurutkan menurut skor (paling ramai lebih dulu).

    Relevansi dihitung ulang dengan konfigurasi saat ini, jadi perubahan kata kunci
    langsung berlaku tanpa menunggu pembaruan data berikutnya.
    """
    for paper in papers.values():
        paper.update(relevance.score_paper(config, paper))
    min_rel = float(config.ranking.get("min_relevance", 2.0))
    relevant = [p for p in papers.values() if p.get("relevance", 0) >= min_rel]
    return sorted(relevant, key=lambda p: p.get("score", 0), reverse=True)


def newest_first(papers: list[dict]) -> list[dict]:
    return sorted(papers, key=lambda p: (p["published"], p.get("score", 0)), reverse=True)


def strip_marks(text: str) -> str:
    return re.sub(r"\*([^*\n]+?)\*", r"\1", text or "")


def catalog_data(config: Config, papers: list[dict], lang_pages: dict) -> dict:
    """Metadata ringkas semua makalah, untuk halaman Makalah, Beranda, dan pencarian."""
    task_counts: dict[str, int] = {}
    for p in papers:
        for tid in p.get("tasks", []):
            task_counts[tid] = task_counts.get(tid, 0) + 1
    items = []
    for p in papers:
        pair = tldr_pair(p.get("summary"))
        items.append({
            "id": p["id"],
            "url": f"papers/{slug(p['id'])}.html",
            "title": p["title"],
            "authors": authors_short(p["authors"], 3),
            "date": p["published"][:10],
            "date_label": date_id(p["published"]),
            "source": source_label(p),
            "topics": p.get("topics", []),
            "languages": p.get("languages", []),
            "tasks": p.get("tasks", []),
            # TL;DR Indonesia tetap memakai penanda *istilah*; app.js mengubahnya menjadi huruf miring.
            "tldr": pair[0] if pair else "",
            "tldr_en": strip_marks(pair[1]) if pair else "",
            "snippet": "" if pair else snippet(p),
            "score": p.get("score", 0),
        })
    return {
        "topics": {t.id: t.label_id for t in config.topics},
        "task_groups": config.task_groups,
        "tasks": {
            t.id: {"name": t.name, "group": t.group, "count": task_counts.get(t.id, 0)}
            for t in config.tasks if task_counts.get(t.id)
        },
        "language_groups": config.language_groups,
        "languages": {
            lid: {"name": pg.name_id, "group": pg.group, "count": len(pg.papers)}
            for lid, pg in sorted(lang_pages.items(), key=lambda x: (-len(x[1].papers), x[1].name_id))
        },
        "papers": items,
    }


def search_index(config: Config, papers: list[dict], vectors: dict[str, list[float]]) -> dict:
    """Vektor int8 setiap makalah untuk pencarian semantik di peramban."""
    return {
        "model": config.embeddings.get("model"),
        "dimensions": int(config.embeddings.get("dimensions", 256)),
        "vectors": {p["id"]: embeddings.encode_i8(vectors[p["id"]]) for p in papers if p["id"] in vectors},
    }


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def build_site(config: Config, out: Path, data: dict | None = None, vectors: dict | None = None) -> None:
    data = data if data is not None else store.load()
    if vectors is None:
        vectors = embeddings.vectors_for(embeddings.load(), config)
    updated_at = data.get("updated_at")
    relevant = relevant_papers(config, data["papers"])
    for paper in relevant:
        paper["tasks"] = tasks.detect(config, paper)
    lang_pages = languages.group_papers(config, relevant)
    trending = relevant[: int(config.site.get("trending_count", 10))]
    newest = newest_first(relevant)
    by_id = {p["id"]: p for p in relevant}
    k = int(config.search.get("similar_papers", 5))
    similar = embeddings.similar(vectors, list(by_id), k=k) if k else {}
    worker_url = (os.environ.get("LENTERA_WORKER_URL") or config.search.get("worker_url") or "").strip().rstrip("/")

    if out.exists():
        shutil.rmtree(out)
    (out / "papers").mkdir(parents=True)
    shutil.copytree(STATIC_DIR, out / "assets")

    title = config.site.get("title", "Lentera Riset")

    def write(path: str, page_title: str, body: str, root: str, **kwargs) -> None:
        (out / path).write_text(
            page(page_title, body, root=root, config=config, updated_at=updated_at, **kwargs), encoding="utf-8"
        )

    write("index.html", title, home_body(config, trending, newest, len(newest)), "", active="beranda")
    write("makalah.html", f"Makalah | {title}", catalog_body(config, len(relevant)), "",
          active="makalah", scripts=("catalog.js",))
    write("cari.html", f"Cari | {title}", search_body(config), "", scripts=("search.js",), worker_url=worker_url)
    write("tentang.html", f"Tentang | {title}", about_body(config), "", active="tentang")

    for paper in relevant:
        pair = tldr_pair(paper.get("summary"))
        desc = pair[0] if pair else paper["abstract"][:200]
        near = [by_id[pid] for pid, _ in similar.get(paper["id"], [])]
        write(f"papers/{slug(paper['id'])}.html", f"{paper['title']} | {title}",
              paper_body(config, paper, lang_pages, near), "../", description=desc.replace("*", ""))

    write_json(out / "catalog.json", catalog_data(config, relevant, lang_pages))
    write_json(out / "search-index.json", search_index(config, relevant, vectors))
    (out / "feed.xml").write_text(feed(config, newest[:50], updated_at), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    with_vectors = sum(1 for p in relevant if p["id"] in vectors)
    print(
        f"Situs dibangun di {out} ({len(relevant)} makalah, {len(trending)} sedang ramai, "
        f"{len(lang_pages)} bahasa, {with_vectors} makalah bervektor)"
    )
