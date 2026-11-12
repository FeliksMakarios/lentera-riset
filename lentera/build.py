"""Pembangkit situs statis. Semua tautan bersifat relatif agar bisa dilayani dari subfolder GitHub Pages."""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlparse

from . import embeddings, fulltext, language_names, languages, relevance, store, tasks
from .config import ROOT, Config
from .rank import parse_date
from .summarize import SECTIONS

STATIC_DIR = ROOT / "static"
# Makalah disebut "Baru" jika pertama kali masuk dalam rentang ini sebelum pembaruan data terakhir.
NEW_WINDOW_HOURS = 30
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


def full_source(paper: dict) -> str:
    """Nama sumber lengkap: arXiv, ACL Anthology, atau nama lengkap jurnal/konferensi."""
    source = paper.get("source", "arxiv")
    if source == "arxiv":
        return "arXiv"
    return paper.get("venue") or SOURCE_LABELS.get(source, source)


# Nama venue yang panjang diganti singkatan yang lazim: (pola, singkatan). {y} = tahun.
VENUE_RULES = [
    (r"^Findings of the Association for Computational Linguistics:\s*(?P<name>.+)$", "Findings {name}"),
    (r"Annual Meeting of the Association for Computational Linguistics", "ACL {y}"),
    (r"Conference on Empirical Methods in Natural Language Processing", "EMNLP {y}"),
    (r"North American Chapter of the Association for Computational Linguistics", "NAACL {y}"),
    (r"European Chapter of the Association for Computational Linguistics", "EACL {y}"),
    (r"International Joint Conference on Natural Language Processing.*Asia-Pacific Chapter", "IJCNLP-AACL {y}"),
    (r"^Proceedings of the \w+ Language Resources and Evaluation Conference$", "LREC {y}"),
    (r"Joint International Conference on Computational Linguistics, Language Resources and Evaluation", "LREC-COLING {y}"),
    (r"^Proceedings of the \w+ International Conference on Computational Linguistics$", "COLING {y}"),
    (r"^Proceedings of the \w+ Conference on Machine Translation$", "WMT {y}"),
    (r"International Workshop on Semantic Evaluation", "SemEval {y}"),
    (r"Conference on Computational Natural Language Learning", "CoNLL {y}"),
    (r"European Association for Machine Translation", "EAMT {y}"),
    (r"^Transactions of the Association for Computational Linguistics", "TACL"),
    (r"^Computational Linguistics$", "Computational Linguistics"),
]
VENUE_PARTS = [
    ("Long Papers", "Long"), ("Short Papers", "Short"), ("System Demonstrations", "Demo"),
    ("Industry Track", "Industry"), ("Student Research Workshop", "SRW"), ("Tutorial", "Tutorial"),
]
VENUE_ACRONYM = re.compile(r"\((\*?[A-Za-z][\w\-*]*?)(?:\s+((?:19|20)\d{2}))?\)")
MAX_VENUE = 60


def venue_year(paper: dict) -> str:
    match = re.search(r"\b((?:19|20)\d{2})\b", paper.get("venue") or "")
    return match.group(1) if match else (paper.get("published") or "")[:4]


def venue_short(paper: dict) -> str:
    """Nama venue yang ringkas untuk kartu dan daftar, misalnya "LREC 2026" atau
    "Findings EMNLP 2026". Nama lengkapnya tetap tampil di halaman makalah."""
    venue = full_source(paper)
    if paper.get("source", "arxiv") == "arxiv" or not paper.get("venue"):
        return venue
    year = venue_year(paper)
    for pattern, template in VENUE_RULES:
        match = re.search(pattern, venue)
        if match:
            short = template.format(y=year, **match.groupdict()).strip()
            parts = [label for text, label in VENUE_PARTS if text in venue]
            return f"{short} ({parts[0]})" if parts else short
    # Singkatan di dalam kurung, misalnya "(AmericasNLP)", "(MRL 2026)", atau "(IJoICT)".
    # Prosiding diberi tahun; jurnal tidak.
    found = [m for m in VENUE_ACRONYM.finditer(venue) if re.search(r"[A-Z]", m.group(1))]
    if found:
        name, in_year = found[-1].group(1), found[-1].group(2)
        if not in_year and venue.startswith(("Proceedings", "The Proceedings")) \
                and not re.search(r"(?:19|20)\d{2}", name):
            in_year = year
        return " ".join(part for part in (name, in_year) if part)
    if len(venue) > MAX_VENUE:
        return venue[:MAX_VENUE].rsplit(" ", 1)[0].rstrip(",:;") + "..."
    return venue


def source_label(paper: dict) -> str:
    """Nama sumber untuk kartu dan daftar: arXiv, ACL Anthology, atau singkatan venue."""
    return venue_short(paper)


SMALL_WORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "of", "on", "or", "the",
    "to", "via", "vs", "with", "dan", "di", "ke", "dari", "untuk", "pada", "yang", "dengan", "dalam",
    "atau", "terhadap", "sebagai", "oleh", "bagi", "melalui", "menggunakan", "berbasis",
}


WORD = r"[\w][\w\-.'\u2019]*[\w]|[\w]"
ROMAN = re.compile(r"^(?=[IVXLC])M*(C[MD]|D?C{0,3})(X[CL]|L?X{0,3})(I[XV]|V?I{0,3})$")


def display_title(paper: dict) -> str:
    """Judul yang seluruhnya huruf kapital (sering dari jurnal di OpenAlex) diubah menjadi
    huruf kapital di awal kata. Singkatan diambil dari bentuknya di abstrak (misalnya
    "IndoBERT" atau "NLLB-200"); judul lain dibiarkan apa adanya."""
    title = paper.get("title") or ""
    letters = [c for c in title if c.isalpha()]
    if len(letters) < 12 or any(c.islower() for c in letters):
        return title
    known: dict[str, str] = {}
    for word in re.findall(WORD, paper.get("abstract") or ""):
        if any(c.isupper() for c in word[1:]) or (word.isupper() and len(word) > 1):
            known.setdefault(word.lower(), word)

    def fix(match: re.Match) -> str:
        word = match.group(0)
        lower = word.lower()
        start = match.start() == 0 or title[:match.start()].rstrip().endswith((":", "?", "!", ".", "-"))
        if lower in known:
            return known[lower]
        if lower in SMALL_WORDS and not start:
            return lower
        if any(c.isdigit() for c in word) or ROMAN.match(word) or not re.search(r"[aeiouyAEIOUY]", word):
            return word
        return "-".join(part[:1].upper() + part[1:].lower() for part in word.split("-"))

    return re.sub(WORD, fix, title)


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
MENU_ICON = (
    '<svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round"><path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h16"/></svg>'
)
NAV = [("beranda", "index.html", "Beranda"), ("makalah", "makalah.html", "Makalah"),
       ("tentang", "tentang.html", "Tentang"), ("rss", "feed.xml", "RSS")]

# Dijalankan sebelum halaman digambar: menandai bahwa JavaScript aktif dan memasang
# bahasa ringkasan pilihan pembaca, supaya tidak ada kedipan bahasa yang salah.
HEAD_SCRIPT = (
    '<script>(function(d){d.classList.add("js");try{var l=localStorage.getItem("lentera:bahasa-ringkasan");'
    'if(l==="id"||l==="en")d.setAttribute("data-ringkasan",l)}catch(e){}})(document.documentElement)</script>'
)


def lang_switch(compact: bool = False) -> str:
    """Pilihan bahasa ringkasan dan TL;DR. Semua tombol di halaman saling terhubung (app.js)."""
    labels = ("ID", "EN") if compact else ("Indonesia", "English")
    cls = "lang-switch lang-switch-compact" if compact else "lang-switch"
    title = ' title="Bahasa ringkasan dan TL;DR"' if compact else ""
    return (f'<div class="{cls}" role="group" aria-label="Bahasa ringkasan"{title}>'
            f'<button type="button" data-set-lang="id" aria-pressed="true" lang="id">{labels[0]}</button>'
            f'<button type="button" data-set-lang="en" aria-pressed="false" lang="en">{labels[1]}</button></div>')


def site_base(config: Config) -> str:
    return (config.site.get("site_url") or "").rstrip("/")


def page(title: str, body: str, *, root: str, config: Config, updated_at: str | None, description: str = "",
         scripts: tuple[str, ...] = (), active: str = "", query: str = "", worker_url: str = "",
         wide: bool = False, path: str | None = None, og_type: str = "website", head_extra: str = "",
         search_open: bool = False) -> str:
    site = config.site
    extra_scripts = "".join(f'\n<script src="{root}assets/{name}" defer></script>' for name in scripts)
    desc = description or site.get("tagline", "")
    updated = f"Data diperbarui {date_id(updated_at)}." if updated_at else ""
    current = ' aria-current="page"'
    wrap = "wrap wrap-wide" if wide else "wrap"
    nav = "".join(
        f'<a href="{root}{href}"{current if key == active else ""}>{label}</a>'
        for key, href, label in NAV
    )
    base = site_base(config)
    meta = ""
    if base and path is not None:
        url = f"{base}/{path}" if path else f"{base}/"
        meta = (f'<link rel="canonical" href="{esc(url)}">\n'
                f'<meta property="og:url" content="{esc(url)}">\n')
    meta += (f'<meta property="og:site_name" content="{esc(site.get("title", "Lentera Riset"))}">\n'
             f'<meta property="og:title" content="{esc(title)}">\n'
             f'<meta property="og:description" content="{esc(desc)}">\n'
             f'<meta property="og:type" content="{og_type}">\n'
             '<meta property="og:locale" content="id_ID">\n'
             '<meta name="twitter:card" content="summary">\n'
             '<meta name="theme-color" content="#b45309">')
    header_cls = "site-header search-open" if search_open else "site-header"
    return f"""<!doctype html>
<html lang="id" data-ringkasan="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
{meta}
{HEAD_SCRIPT}
<link rel="stylesheet" href="{root}assets/style.css">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='12' fill='%23b45309'/%3E%3Ccircle cx='16' cy='14' r='5' fill='%23fde68a'/%3E%3C/svg%3E">
<link rel="alternate" type="application/rss+xml" title="{esc(site.get('title', ''))}" href="{root}feed.xml">{head_extra}
</head>
<body data-root="{root}" data-worker="{esc(worker_url)}">
<header class="{header_cls}" id="site-header">
  <div class="{wrap} header-inner">
    <a class="brand" href="{root}index.html"><span class="brand-mark" aria-hidden="true"></span>{esc(site.get('title', 'Lentera Riset'))}</a>
    <div class="header-tools">
      <button type="button" class="header-btn" id="search-toggle" aria-controls="site-search" aria-expanded="{'true' if search_open else 'false'}" aria-label="Buka pencarian">{SEARCH_ICON}</button>
      <button type="button" class="header-btn" id="menu-toggle" aria-controls="site-menu" aria-expanded="false" aria-label="Buka menu">{MENU_ICON}</button>
    </div>
    <form class="site-search" id="site-search" action="{root}cari.html" method="get" role="search">
      <label class="sr-only" for="site-q">Cari makalah berdasarkan makna</label>
      <input id="site-q" name="q" type="search" value="{esc(query)}" placeholder="Cari makalah berdasarkan makna..." autocomplete="off" required>
      <button type="submit" aria-label="Cari">{SEARCH_ICON}</button>
    </form>
    <div class="site-menu" id="site-menu">
      <nav aria-label="Menu utama">{nav}</nav>
      {lang_switch(compact=True)}
    </div>
  </div>
</header>
<main class="{wrap}" id="main">
{body}
</main>
<footer class="site-footer">
  <div class="{wrap}">
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


MAX_LANGUAGE_CHIPS = 10


def language_chips(pages: dict, paper: dict, root: str = "", limit: int | None = MAX_LANGUAGE_CHIPS) -> str:
    """Label bahasa yang dikaji. Makalah yang mengkaji ratusan bahasa hanya menampilkan
    beberapa label pertama; sisanya muncul lewat tombol "+N bahasa lainnya" (paper.js).
    Tanpa JavaScript semua label tampil."""
    ids = [lid for lid in paper.get("languages", []) if lid in pages]
    folded = limit is not None and len(ids) > limit + 2
    chips = []
    for i, lid in enumerate(ids):
        cls = "chip chip-lang chip-extra" if folded and i >= limit else "chip chip-lang"
        chips.append(f'<a class="{cls}" href="{filter_link(root, "bahasa", lid)}">{esc(pages[lid].name_id)}</a>')
    if folded:
        chips.insert(limit, f'<button type="button" class="chip chip-more-btn" id="chip-more" hidden>'
                            f'+{len(ids) - limit} bahasa lainnya</button>')
    return "".join(chips)


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


def source_span(paper: dict) -> str:
    """Nama sumber singkat; nama lengkapnya muncul saat kursor diarahkan."""
    short, full = source_label(paper), full_source(paper)
    title = f' title="{esc(full)}"' if full != short else ""
    return f'<span class="source"{title}>{esc(short)}</span>'


NEW_BADGE = '<span class="badge-new">Baru</span>'


def card(config: Config, paper: dict, root: str = "", rank: int | None = None) -> str:
    """Kartu makalah. Bentuknya sama dengan kartu yang dibuat assets/app.js."""
    pair = tldr_pair(paper.get("summary"))
    if pair:
        tldr = (
            f'<p class="tldr" lang="id" data-l="id">{inline(pair[0])}</p>'
            f'<p class="tldr tldr-en" lang="en" data-l="en">{plain(pair[1])}</p>'
        )
    else:
        tldr = f'<p class="tldr tldr-pending" lang="en">{esc(snippet(paper))}</p>'
    badge = f'<span class="rank" aria-label="Peringkat {rank}">{rank}</span>' if rank else ""
    new = NEW_BADGE if paper.get("_new") else ""
    return f"""<article class="card">
  <div class="card-meta">{badge}{new}<time datetime="{esc(paper['published'])}">{date_id(paper['published'])}</time>{source_span(paper)}{topic_chips(config, paper, root)}</div>
  <h2><a href="{root}papers/{slug(paper['id'])}.html">{esc(paper['title'])}</a></h2>
  <p class="authors">{esc(authors_short(paper['authors']))}</p>
  {tldr}
  {signals_inline(paper)}
</article>"""


def home_body(config: Config, trending: list[dict], newest: list[dict], newest_total: int,
              stats: dict | None = None) -> str:
    per_page = int(config.site.get("newest_per_page", 7))
    stats = stats or {}
    facts = []
    if stats.get("updated_at"):
        facts.append(f'Diperbarui <time datetime="{esc(stats["updated_at"])}">{date_id(stats["updated_at"])}</time>')
    if stats.get("new"):
        facts.append(f'<a href="index.html?tab=terbaru" id="new-link"><b>{stats["new"]} makalah baru</b></a>')
    facts.append(f"{newest_total} makalah")
    if stats.get("languages"):
        facts.append(f'{stats["languages"]} bahasa')
    facts.append("arXiv, ACL Anthology, dan OpenAlex")
    facts_html = '<p class="home-facts">' + '<span class="dot" aria-hidden="true"> · </span>'.join(facts) + "</p>"
    trending_cards = "\n".join(card(config, p, rank=i) for i, p in enumerate(trending, 1))
    newest_cards = "\n".join(card(config, p) for p in newest[:per_page])
    pages = max(1, -(-newest_total // per_page))
    empty = '<p class="empty">Belum ada makalah. Data akan muncul setelah alur kerja harian berjalan.</p>'
    return f"""<section class="intro">
  <h1>{esc(config.site.get('title', 'Lentera Riset'))}</h1>
  <p>{esc(config.site.get('tagline', ''))}</p>
  {facts_html}
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
  <aside class="facets" id="facets" aria-label="Saringan">
    <div class="facets-head">
      <h2>Saring makalah</h2>
      <button type="button" class="ask-icon-btn" id="facet-close" aria-label="Tutup saringan">{CLOSE_ICON}</button>
    </div>
    <div class="facet-tabs" role="tablist">
      <button type="button" role="tab" class="facet-tab" data-facet="tugas" aria-selected="true">Tugas</button>
      <button type="button" role="tab" class="facet-tab" data-facet="topik" aria-selected="false">Topik</button>
      <button type="button" role="tab" class="facet-tab" data-facet="bahasa" aria-selected="false">Bahasa</button>
    </div>
    <label class="sr-only" for="facet-filter">Saring pilihan</label>
    <input id="facet-filter" class="facet-filter" type="search" placeholder="Saring tugas berdasarkan nama" autocomplete="off">
    <div id="facet-list" class="facet-list"></div>
    <div class="facets-foot"><button type="button" class="button button-ask" id="facet-done">Tampilkan makalah</button></div>
  </aside>
  <section class="catalog-main">
    <div class="catalog-head">
      <h1>Makalah <span class="count" id="catalog-count">{total}</span></h1>
      <button type="button" class="button filter-toggle" id="facet-open" aria-controls="facets" aria-expanded="false">Saring<span class="filter-count" id="facet-count" hidden></span></button>
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
    for lang in ("id", "en"):
        fmt = inline if lang == "id" else plain
        text = paragraphs(summary[lang].get("summary", ""), fmt)
        cols.append(f'<div class="summary-col" lang="{lang}" data-l="{lang}">{text}</div>')
    return "".join(cols)


def first_sentence(text: str, limit: int = 220) -> str:
    """Kalimat pertama sebuah bagian, untuk cuplikan saat bagian itu tertutup."""
    flat = " ".join((text or "").split())
    match = re.match(r"(.+?[.!?])(\s|$)", flat)
    sentence = match.group(1) if match else flat
    if len(sentence) > limit:
        sentence = sentence[:limit].rsplit(" ", 1)[0] + "..."
    return sentence


ASK_SECTION_ICON = (
    '<svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6'
    'A8 8 0 1 1 21 12Z"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.3 2.4c-.5.2-.8.6-.8 1.1v.5"/><path d="M12 16.5h.01"/></svg>'
)


def structured_summary(summary: dict, ask: bool = False) -> str:
    """Enam bagian ringkasan yang bisa dibuka dan ditutup. Versi Indonesia dan Inggris sama-sama
    ada di halaman; static/paper.js menampilkan salah satunya sesuai pilihan pembaca."""
    blocks = []
    for key, title_id, title_en in SECTIONS:
        part = summary["sections"].get(key)
        if not part:
            continue
        ask_button = (
            f'<button type="button" class="ask-section" data-section-id="{esc(title_id)}" '
            f'data-section-en="{esc(title_en)}" aria-label="Tanyakan bagian {esc(title_id)}" '
            f'title="Tanyakan bagian ini">{ASK_SECTION_ICON}</button>'
            if ask else ""
        )
        blocks.append(f"""<div class="summary-section" id="{key}">
  <details>
    <summary>
      <span class="sec-title"><span data-l="id">{esc(title_id)}</span><span data-l="en" lang="en">{esc(title_en)}</span></span>
      <span class="sec-snippet" data-l="id">{inline(first_sentence(part['id']))}</span>
      <span class="sec-snippet" data-l="en" lang="en">{plain(first_sentence(part['en']))}</span>
    </summary>
    <div class="sec-body">
      <div class="summary-text" lang="id" data-l="id">{paragraphs(part['id'], inline)}</div>
      <div class="summary-text" lang="en" data-l="en">{paragraphs(part['en'], plain)}</div>
    </div>
  </details>
  {ask_button}
</div>""")
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


def icon(paths: str, size: int = 18) -> str:
    return (f'<svg aria-hidden="true" viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" '
            f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')


# Kartu saran pertanyaan di panel tanya jawab: (ikon, pertanyaan).
ASK_SUGGESTIONS = [
    (icon('<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>'
          '<path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>'),
     "Data apa yang dipakai dan seberapa besar?"),
    (icon('<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18Z"/>'),
     "Bahasa apa saja yang dicakup dan bagaimana hasilnya per bahasa?"),
    (icon('<path d="M12 3 2 20h20L12 3Z"/><path d="M12 10v4"/><path d="M12 17h.01"/>'),
     "Apa keterbatasan utama penelitian ini?"),
    (icon('<path d="M9 6h11"/><path d="M9 12h11"/><path d="M9 18h11"/><path d="m3 6 1 1 2-2"/>'
          '<path d="m3 12 1 1 2-2"/><path d="m3 18 1 1 2-2"/>'),
     "Bagaimana cara mereproduksi eksperimennya?"),
]
CLOSE_ICON = icon('<path d="M6 6l12 12"/><path d="M18 6 6 18"/>')
SEND_ICON = icon('<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>')
ASK_ICON = icon('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z"/>'
                '<path d="M8.5 11h.01"/><path d="M12 11h.01"/><path d="M15.5 11h.01"/>', 22)


def ask_html(paper: dict) -> str:
    """Panel tanya jawab di sisi kanan halaman makalah (di ponsel menjadi panel dari bawah).
    Pertanyaan dikirim static/ask.js ke POST /ask di Worker."""
    if paper.get("pdf_url"):
        basis = "dari isi lengkap makalah (PDF akses terbuka)"
    else:
        basis = "hanya dari abstrak dan ringkasan, karena PDF akses terbuka tidak tersedia"
    cards = "".join(
        f'<button type="button" class="ask-card"><span class="ask-card-icon">{svg}</span>'
        f'<span class="ask-card-text">{esc(q)}</span></button>'
        for svg, q in ASK_SUGGESTIONS
    )
    return f"""<aside class="ask-panel" id="tanya" data-paper="{esc(slug(paper['id']))}" aria-labelledby="ask-title">
    <div class="ask-resize" id="ask-resize" role="separator" aria-orientation="vertical" tabindex="0"
      aria-label="Ubah lebar panel tanya jawab" title="Geser untuk mengubah lebar panel, klik ganda untuk lebar bawaan"></div>
    <div class="ask-head">
      <h2 id="ask-title">Tanya makalah ini</h2>
      <button type="button" class="link-button" id="ask-clear" hidden>Hapus percakapan</button>
      <button type="button" class="ask-icon-btn" id="ask-close" aria-label="Tutup panel tanya jawab" title="Tutup panel">{CLOSE_ICON}</button>
    </div>
    <div class="ask-scroll" id="ask-scroll">
      <p class="note">Jawaban disusun oleh Gemini {basis}. Jawaban bisa keliru, jadi periksa kembali makalah aslinya. Pilih teks di halaman untuk mengutipnya dalam pertanyaan.</p>
      <div class="ask-cards" id="ask-suggest">{cards}</div>
      <div class="ask-log" id="ask-log" aria-live="polite"></div>
    </div>
    <form class="ask-form" id="ask-form">
      <div class="ask-quote" id="ask-quote" hidden>
        <span class="ask-quote-text" id="ask-quote-text"></span>
        <button type="button" class="ask-icon-btn" id="ask-quote-remove" aria-label="Hapus kutipan" title="Hapus kutipan">{CLOSE_ICON}</button>
      </div>
      <div class="ask-input">
        <label class="sr-only" for="ask-q">Pertanyaan tentang makalah ini</label>
        <textarea id="ask-q" rows="2" maxlength="500" placeholder="Tanyakan tentang makalah ini, atau pilih teks di halaman untuk dikutip..."></textarea>
        <button type="submit" class="ask-send" id="ask-send" aria-label="Kirim pertanyaan" title="Kirim (Enter)">{SEND_ICON}</button>
      </div>
    </form>
  </aside>"""


def ask_launcher() -> str:
    """Tombol mengambang untuk membuka panel tanya jawab, plus tombol kutip saat teks dipilih."""
    return f"""<button type="button" class="ask-fab" id="ask-open" aria-controls="tanya" aria-expanded="false">{ASK_ICON}<span>Tanya makalah</span></button>
<button type="button" class="quote-pop" id="quote-pop" hidden>Tanyakan ini</button>"""



# ---------------------------------------------------------------------------
# Sitasi: BibTeX, APA, dan meta untuk pengelola pustaka (Zotero, Google Scholar)
# ---------------------------------------------------------------------------

def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def split_name(name: str) -> tuple[str, list[str]]:
    """(nama belakang, nama depan) dari "Tyler A. Chang". Nama satu kata tidak punya nama depan."""
    parts = name.replace(",", " ").split()
    if len(parts) <= 1:
        return name.strip(), []
    return parts[-1], parts[:-1]


def apa_author(name: str) -> str:
    last, given = split_name(name)
    initials = " ".join(f"{p[0]}." for p in given if p[:1].isalpha())
    return f"{last}, {initials}" if initials else last


def apa_citation(paper: dict) -> str:
    """Sitasi gaya APA 7: penulis (maksimal 20), tahun, judul, venue, dan tautan."""
    authors = [apa_author(a) for a in paper.get("authors", [])]
    if len(authors) > 20:
        names = ", ".join(authors[:19]) + ", ... " + authors[-1]
    elif len(authors) > 1:
        names = ", ".join(authors[:-1]) + ", & " + authors[-1]
    else:
        names = authors[0] if authors else "Anonim"
    year = (paper.get("published") or "")[:4] or "t.t."
    title = paper["title"].rstrip(".")
    venue = full_source(paper)
    if paper.get("source", "arxiv") == "arxiv":
        venue = f"arXiv preprint arXiv:{paper['id']}"
    link = f"https://doi.org/{paper['doi']}" if paper.get("doi") else paper.get("abs_url", "")
    return f"{names} ({year}). {title}. {venue}. {link}".strip()


def bib_escape(text: str) -> str:
    return re.sub(r"([&%$#_])", r"\\\1", text or "")


def bibtex(paper: dict) -> str:
    authors = paper.get("authors", [])
    last = re.sub(r"[^a-z]", "", ascii_fold(split_name(authors[0])[0]).lower()) if authors else "anon"
    year = (paper.get("published") or "")[:4]
    words = [w for w in re.findall(r"[a-z0-9]+", ascii_fold(paper["title"]).lower()) if w not in SMALL_WORDS]
    key = f"{last or 'anon'}{year}{words[0] if words else ''}"
    fields = [("title", "{" + bib_escape(paper["title"]) + "}"),
              ("author", " and ".join(bib_escape(a) for a in authors)), ("year", year)]
    source = paper.get("source", "arxiv")
    if source == "arxiv":
        kind = "misc"
        fields += [("eprint", paper["id"]), ("archivePrefix", "arXiv")]
        if paper.get("primary_category"):
            fields.append(("primaryClass", paper["primary_category"]))
    elif source == "acl" or full_source(paper).startswith(("Proceedings", "Findings", "The Proceedings")):
        kind = "inproceedings"
        fields.append(("booktitle", bib_escape(full_source(paper))))
    else:
        kind = "article"
        fields.append(("journal", bib_escape(full_source(paper))))
    if paper.get("doi"):
        fields.append(("doi", paper["doi"]))
    fields.append(("url", paper.get("abs_url", "")))
    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields if value)
    return f"@{kind}{{{key},\n{body}\n}}"


def citation_meta(paper: dict, url: str) -> str:
    """Meta citation_* (dibaca Zotero dan pengelola pustaka lain) dan JSON-LD ScholarlyArticle."""
    tags = [("citation_title", paper["title"])]
    tags += [("citation_author", a) for a in paper.get("authors", [])]
    tags.append(("citation_publication_date", (paper.get("published") or "")[:10].replace("-", "/")))
    source = paper.get("source", "arxiv")
    if source == "arxiv":
        tags.append(("citation_arxiv_id", paper["id"]))
    elif full_source(paper).startswith(("Proceedings", "Findings", "The Proceedings")):
        tags.append(("citation_conference_title", full_source(paper)))
    else:
        tags.append(("citation_journal_title", full_source(paper)))
    if paper.get("doi"):
        tags.append(("citation_doi", paper["doi"]))
    if paper.get("pdf_url"):
        tags.append(("citation_pdf_url", paper["pdf_url"]))
    tags.append(("citation_abstract_html_url", paper.get("abs_url", "")))
    meta = "".join(f'\n<meta name="{name}" content="{esc(value)}">' for name, value in tags if value)
    ld = {
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle",
        "headline": paper["title"][:250],
        "name": paper["title"],
        "author": [{"@type": "Person", "name": a} for a in paper.get("authors", [])[:50]],
        "datePublished": (paper.get("published") or "")[:10],
        "inLanguage": "en",
        "isPartOf": {"@type": "Periodical" if source == "openalex" else "PublicationIssue", "name": full_source(paper)},
        "abstract": paper.get("abstract") or "",
        "url": url or paper.get("abs_url", ""),
        "sameAs": [u for u in (paper.get("abs_url"), f"https://doi.org/{paper['doi']}" if paper.get("doi") else None) if u],
    }
    pair = tldr_pair(paper.get("summary"))
    if pair:
        ld["description"] = strip_marks(pair[1])
    data = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    return f'{meta}\n<script type="application/ld+json">{data}</script>'


COPY_ICON = ('<svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
             'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/>'
             '<path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>')


def cite_html(paper: dict) -> str:
    return f"""<details class="cite" id="kutip">
    <summary>Kutip makalah ini</summary>
    <div class="cite-body">
      <div class="cite-block">
        <div class="cite-head"><h3>APA</h3><button type="button" class="link-button copy-btn" data-copy="cite-apa" hidden>{COPY_ICON}Salin</button></div>
        <p class="cite-text" id="cite-apa" lang="en">{esc(apa_citation(paper))}</p>
      </div>
      <div class="cite-block">
        <div class="cite-head"><h3>BibTeX</h3><button type="button" class="link-button copy-btn" data-copy="cite-bib" hidden>{COPY_ICON}Salin</button></div>
        <pre class="cite-text" id="cite-bib" lang="en">{esc(bibtex(paper))}</pre>
      </div>
    </div>
  </details>"""


def studied_names(config: Config, names: list[str]) -> list[str]:
    """Nama berbahasa Indonesia untuk daftar bahasa yang dikaji menurut Gemini: nama dari
    config/topics.toml jika bahasanya terdaftar ("Javanese" -> "Bahasa Jawa"), selain itu
    dari lentera/language_names.py ("Spanish" -> "Bahasa Spanyol"). Nama ganda dibuang."""
    by_id = {lang.id: lang.name_id for lang in config.languages}
    out: list[str] = []
    for name in names:
        ids = languages.find(config, name)
        label = by_id[ids[0]] if ids else language_names.indonesian(name)
        if label not in out:
            out.append(label)
    return out


def paper_body(config: Config, paper: dict, lang_pages: dict | None = None, similar: list[dict] | None = None,
               ask: bool = False) -> str:
    summary = paper.get("summary")
    link_html = "".join(
        f'<a class="button" href="{esc(url)}" rel="noopener">{esc(label)}</a>' for label, url in links_for(paper)
    )
    if ask:
        link_html = '<a class="button button-ask" href="#tanya" id="ask-jump">Tanya makalah ini</a>' + link_html
    link_html += ('<a class="button" href="#kutip" id="cite-jump">Kutip</a>'
                  '<button type="button" class="button" id="copy-link" hidden>Salin tautan</button>')

    matched = paper.get("matched_keywords") or {}
    matched_html = "".join(
        f"<li><b>{esc(config.topic(tid).label_id if config.topic(tid) else tid)}</b>: {esc(', '.join(kws))}</li>"
        for tid, kws in matched.items()
    )

    pair = tldr_pair(summary)
    tldr_html = (
        f"""<div class="tldr-card">
    <span class="tldr-label">TL;DR</span>
    <p lang="id" data-l="id">{inline(pair[0])}</p>
    <p class="tldr-en" lang="en" data-l="en">{plain(pair[1])}</p>
  </div>"""
        if pair else ""
    )

    if summary:
        glossary = "".join(
            f"<dt>{esc(g['term'])}</dt><dd>{inline(g['explanation_id'])}</dd>" for g in summary.get("glossary", [])
        )
        glossary_html = f'<section class="glossary"><h2>Glosarium istilah</h2><dl>{glossary}</dl></section>' if glossary else ""
        langs = studied_names(config, summary.get("languages_studied") or [])
        shown = langs if len(langs) <= MAX_LANGUAGE_CHIPS + 2 else langs[:MAX_LANGUAGE_CHIPS]
        more = f'<span class="note">dan {len(langs) - len(shown)} bahasa lainnya</span>' if len(shown) < len(langs) else ""
        langs_html = (
            '<p class="langs"><b>Bahasa yang dikaji:</b> ' + "".join(f'<span class="chip">{esc(l)}</span>' for l in shown) + more + "</p>"
            if langs else ""
        )
        if summary.get("source") == "full_text":
            basis = "dari isi lengkap makalah (PDF)"
        else:
            basis = "hanya dari judul dan abstrak, karena PDF akses terbuka tidak tersedia"
        if "sections" in summary:
            body = structured_summary(summary, ask)
            tools = '<div class="summary-tools"><button type="button" class="link-button" id="sum-all" hidden>Buka semua bagian</button></div>'
        else:
            body, tools = legacy_summary(summary), ""
        summary_html = f"""<section class="summary">
  <h2>Ringkasan</h2>
  <p class="note">Dibuat otomatis oleh {esc(summary.get('model', 'model bahasa'))} {basis}. TL;DR di atas diringkas dari abstrak. Istilah bercetak miring sengaja dipertahankan dalam bahasa Inggris.</p>
  {langs_html}
  {tools}
  {body}
</section>
{glossary_html}"""
        abstract_html = f'<details class="abstract"><summary>Abstrak asli</summary><p lang="en">{esc(paper["abstract"])}</p></details>'
    else:
        summary_html = '<p class="note">Ringkasan dwibahasa belum tersedia untuk makalah ini. Berikut abstrak aslinya.</p>'
        abstract_html = f'<section class="abstract-open"><h2>Abstrak</h2><p lang="en">{esc(paper["abstract"] or "Abstrak tidak tersedia.")}</p></section>'

    extra = ""
    if paper.get("manual"):
        extra += "<li><b>Pilihan pengelola:</b> ditambahkan secara manual ke koleksi (config/manual.toml).</li>"
    if paper.get("comment"):
        extra += f"<li><b>Catatan penulis:</b> {esc(paper['comment'])}</li>"
    if paper.get("journal_ref"):
        extra += f"<li><b>Terbit di:</b> {esc(paper['journal_ref'])}</li>"
    extra += f"<li><b>Sumber data:</b> {esc(DATA_SOURCES.get(paper.get('source', 'arxiv'), 'arXiv'))}</li>"

    meta = [esc(date_id(paper["published"])), source_span(paper)]
    if paper.get("source", "arxiv") == "arxiv" and paper.get("categories"):
        meta.append(esc(", ".join(paper["categories"])))
    if paper.get("source", "arxiv") != "arxiv" and full_source(paper) != source_label(paper):
        extra = f"<li><b>Venue:</b> {esc(full_source(paper))}</li>" + extra
    new = NEW_BADGE if paper.get("_new") else ""
    article = f"""<article class="paper">
  <div class="paper-top">
    <div class="card-meta">{new}{"".join(m if m.startswith("<") else f"<span>{m}</span>" for m in meta)}</div>
    {lang_switch() if summary else ""}
  </div>
  <h1 lang="en">{esc(paper['title'])}</h1>
  <p class="authors">{esc(', '.join(paper['authors']))}</p>
  {tldr_html}
  <div class="topic-row">{topic_chips(config, paper, "../")}{language_chips(lang_pages or {}, paper, "../")}{task_chips(config, paper, "../")}</div>
  <div class="links">{link_html}</div>
  {cite_html(paper)}
  {summary_html}
  {abstract_html}
  {similar_html(similar or [])}
  <section class="details">
    <h2>Mengapa makalah ini muncul</h2>
    <ul>{matched_html}{extra}</ul>
  </section>
</article>"""
    back = '<p class="back"><a href="../makalah.html">&larr; Semua makalah</a></p>'
    if not ask:
        return f"{back}\n{article}"
    return f"""{back}
<div class="paper-layout" id="paper-layout" data-ask="open">
{article}
{ask_html(paper)}
</div>
{ask_launcher()}"""


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
<li><b>Tanya makalah ini</b> di setiap halaman makalah menjawab pertanyaan Anda tentang makalah itu. Gemini membaca isi lengkap makalah (PDF akses terbuka), atau abstrak dan ringkasan jika PDF tidak tersedia, dan diminta menjawab hanya dari isi makalah.</li>
</ul>

<h2>Topik yang dipantau</h2>
<ul>{topics}</ul>

<h2>Keterbatasan</h2>
<ul>
<li>Jika PDF akses terbuka tidak tersedia (misalnya makalah jurnal berbayar), ringkasan dibuat dari abstrak saja. Halaman makalah menyebutkan dasar ringkasannya.</li>
<li>Model bahasa bisa keliru, baik di ringkasan maupun di jawaban tanya jawab. Periksa makalah aslinya sebelum mengutip.</li>
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
        desc = strip_marks(pair[0]) if pair else (p.get("abstract") or "")[:400]
        guid = (f"<guid isPermaLink=\"true\">{esc(link)}</guid>" if base
                else f"<guid isPermaLink=\"false\">{esc(p['id'])}</guid>")
        items.append(
            f"<item><title>{esc(p['title'])}</title><link>{esc(link)}</link>{guid}"
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
    relevant = [p for p in papers.values() if relevance.is_relevant(config, p)]
    return sorted(relevant, key=lambda p: p.get("score", 0), reverse=True)


def newest_first(papers: list[dict]) -> list[dict]:
    return sorted(papers, key=lambda p: (p["published"], p.get("score", 0)), reverse=True)


def strip_marks(text: str) -> str:
    return re.sub(r"\*([^*\n]+?)\*", r"\1", text or "")


def catalog_data(config: Config, papers: list[dict], lang_pages: dict) -> dict:
    """Metadata ringkas semua makalah, untuk halaman Makalah, Beranda, dan pencarian.

    Teks TL;DR dan cuplikan abstrak ada di texts.json (lihat texts_data), karena halaman
    Makalah tidak memerlukannya. Alamat halaman dan tanggal berbahasa Indonesia dibuat
    ulang oleh app.js dari `id` dan `date`."""
    task_counts: dict[str, int] = {}
    for p in papers:
        for tid in p.get("tasks", []):
            task_counts[tid] = task_counts.get(tid, 0) + 1
    items = []
    for p in papers:
        item = {
            "id": p["id"],
            "title": p["title"],
            "authors": authors_short(p["authors"], 3),
            "date": p["published"][:10],
            "source": source_label(p),
            "topics": p.get("topics", []),
            "languages": p.get("languages", []),
            "tasks": p.get("tasks", []),
            "score": round(p.get("score", 0), 3),
        }
        if p.get("_new"):
            item["new"] = 1
        items.append(item)
    return {
        "topics": {t.id: t.label_id for t in config.topics},
        "task_groups": config.task_groups,
        "tasks": {
            t.id: {"name": t.name, "group": t.group, "count": task_counts.get(t.id, 0)}
            for t in config.tasks if task_counts.get(t.id)
        },
        "language_groups": config.language_groups,
        "languages": {
            lid: {"name": pg.name_id, "en": pg.name_en, "group": pg.group, "count": len(pg.papers)}
            for lid, pg in sorted(lang_pages.items(), key=lambda x: (-len(x[1].papers), x[1].name_id))
        },
        "papers": items,
    }


def texts_data(papers: list[dict]) -> dict:
    """TL;DR dua bahasa (atau cuplikan abstrak jika belum diringkas) per makalah, untuk kartu
    di tab Terbaru dan hasil pencarian. TL;DR Indonesia tetap memakai penanda *istilah*;
    app.js mengubahnya menjadi huruf miring."""
    out = {}
    for p in papers:
        pair = tldr_pair(p.get("summary"))
        out[p["id"]] = [pair[0], strip_marks(pair[1])] if pair else [snippet(p)]
    return out


def sitemap(config: Config, papers: list[dict], updated_at: str | None) -> str:
    base = site_base(config)
    today = (updated_at or datetime.now(timezone.utc).isoformat())[:10]
    urls = [(f"{base}/", today), (f"{base}/makalah.html", today), (f"{base}/tentang.html", today)]
    for p in papers:
        changed = (p.get("summary") or {}).get("created") or p.get("updated") or p.get("published") or today
        urls.append((f"{base}/papers/{slug(p['id'])}.html", str(changed)[:10]))
    rows = "".join(f"<url><loc>{esc(loc)}</loc><lastmod>{mod}</lastmod></url>\n" for loc, mod in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{rows}</urlset>\n')


def not_found_body(config: Config, root: str) -> str:
    return f"""<article class="prose not-found">
<h1>Halaman tidak ditemukan</h1>
<p>Halaman yang Anda cari tidak ada atau sudah dipindahkan. Makalah yang tidak lagi relevan dengan topik Lentera Riset juga bisa hilang dari koleksi.</p>
<p>Coba cari makalahnya lewat kolom pencarian di atas, atau buka <a href="{root}index.html">Beranda</a> dan <a href="{root}makalah.html">daftar semua makalah</a>.</p>
</article>"""


def search_index(config: Config, papers: list[dict], vectors: dict[str, list[float]]) -> dict:
    """Vektor int8 setiap makalah untuk pencarian semantik di peramban."""
    return {
        "model": config.embeddings.get("model"),
        "dimensions": int(config.embeddings.get("dimensions", 256)),
        "vectors": {p["id"]: embeddings.encode_i8(vectors[p["id"]]) for p in papers if p["id"] in vectors},
    }


def summary_text(summary: dict | None) -> str:
    """Ringkasan versi Inggris sebagai teks biasa, untuk konteks tanya jawab."""
    if not summary:
        return ""
    if "sections" in summary:
        parts = [f"TL;DR: {summary['tldr']['en']}"] + [
            f"{title_en}: {summary['sections'][key]['en']}"
            for key, _, title_en in SECTIONS
            if summary["sections"].get(key)
        ]
    else:
        parts = [(summary.get("en") or {}).get("summary", "")]
    if summary.get("languages_studied"):
        parts.append("Languages studied: " + ", ".join(summary["languages_studied"]))
    return "\n\n".join(p for p in parts if p.strip())


def qa_data(paper: dict) -> dict:
    """Keterangan satu makalah yang dibaca Worker untuk POST /ask (qa/<id>.json)."""
    return {
        "id": paper["id"],
        "title": paper["title"],
        "authors": paper.get("authors", []),
        "published": (paper.get("published") or "")[:10],
        "venue": full_source(paper),
        "abstract": paper.get("abstract") or "",
        "summary": summary_text(paper.get("summary")),
        "pdf_url": fulltext.pdf_url(paper),
    }


def as_utc(value: str) -> datetime:
    moment = parse_date(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def build_site(config: Config, out: Path, data: dict | None = None, vectors: dict | None = None) -> None:
    data = data if data is not None else store.load()
    if vectors is None:
        vectors = embeddings.vectors_for(embeddings.load(), config)
    updated_at = data.get("updated_at")
    relevant = relevant_papers(config, data["papers"])
    new_since = as_utc(updated_at) - timedelta(hours=NEW_WINDOW_HOURS) if updated_at else None
    for paper in relevant:
        paper["tasks"] = tasks.detect(config, paper)
        paper["title"] = display_title(paper)
        seen = paper.get("first_seen")
        paper["_new"] = bool(new_since and seen and as_utc(seen) >= new_since)
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
    (out / "qa").mkdir()
    shutil.copytree(STATIC_DIR, out / "assets")

    title = config.site.get("title", "Lentera Riset")

    def write(dest: str, page_title: str, body: str, root: str, **kwargs) -> None:
        (out / dest).write_text(
            page(page_title, body, root=root, config=config, updated_at=updated_at, **kwargs), encoding="utf-8"
        )

    stats = {"updated_at": updated_at, "new": sum(1 for p in relevant if p["_new"]), "languages": len(lang_pages)}
    write("index.html", title, home_body(config, trending, newest, len(newest), stats), "", active="beranda", path="")
    write("makalah.html", f"Makalah | {title}", catalog_body(config, len(relevant)), "",
          active="makalah", scripts=("catalog.js",), path="makalah.html")
    write("cari.html", f"Cari | {title}", search_body(config), "", scripts=("search.js",), worker_url=worker_url,
          path=None, search_open=True)
    write("tentang.html", f"Tentang | {title}", about_body(config), "", active="tentang", path="tentang.html")
    # Halaman 404 dilayani GitHub Pages dari alamat mana pun di bawah situs, jadi tautannya absolut.
    base_path = urlparse(site_base(config)).path.rstrip("/") + "/"
    write("404.html", f"Halaman tidak ditemukan | {title}", not_found_body(config, base_path), base_path, path=None)

    for paper in relevant:
        pair = tldr_pair(paper.get("summary"))
        desc = pair[0] if pair else paper["abstract"][:200]
        near = [by_id[pid] for pid, _ in similar.get(paper["id"], [])]
        ask = bool(worker_url)
        path = f"papers/{slug(paper['id'])}.html"
        url = f"{site_base(config)}/{path}" if site_base(config) else ""
        write(path, f"{paper['title']} | {title}",
              paper_body(config, paper, lang_pages, near, ask=ask), "../", description=strip_marks(desc),
              scripts=("paper.js", "ask.js") if ask else ("paper.js",), worker_url=worker_url, wide=ask,
              path=path, og_type="article", head_extra=citation_meta(paper, url))
        write_json(out / "qa" / f"{slug(paper['id'])}.json", qa_data(paper))

    write_json(out / "catalog.json", catalog_data(config, relevant, lang_pages))
    write_json(out / "texts.json", texts_data(relevant))
    if site_base(config):
        (out / "sitemap.xml").write_text(sitemap(config, relevant, updated_at), encoding="utf-8")
    write_json(out / "search-index.json", search_index(config, relevant, vectors))
    (out / "feed.xml").write_text(feed(config, newest[:50], updated_at), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    with_vectors = sum(1 for p in relevant if p["id"] in vectors)
    print(
        f"Situs dibangun di {out} ({len(relevant)} makalah, {len(trending)} sedang ramai, "
        f"{len(lang_pages)} bahasa, {with_vectors} makalah bervektor)"
    )
