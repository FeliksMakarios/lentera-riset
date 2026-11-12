"""Pengujian perbaikan tampilan dan SEO: nama bahasa, label venue, judul berhuruf kapital,
label bahasa yang dilipat, RSS, sitasi, meta mesin pencari, sitemap, 404, dan texts.json."""

import copy
import json
import re
import tempfile
import tomllib
import unittest
from pathlib import Path

from lentera import build, language_names, languages, pipeline
from lentera.config import ROOT
from tests.helpers import CONFIG, SUMMARY
from tests.test_pipeline_build import NOW, candidates


class LanguageNameTest(unittest.TestCase):
    def test_spellings_are_merged(self):
        for raw, name in [("Uighur", "Uyghur"), ("Farsi", "Persian"), ("isiZulu", "Zulu"),
                          ("Kiswahili", "Swahili"), ("Myanmar", "Burmese"), ("Mandarin Chinese", "Chinese"),
                          ("Modern Standard Arabic", "Arabic"), (" Bangla ", "Bengali"), ("Yoruba language", "Yoruba")]:
            self.assertEqual(language_names.canonical(raw), name, raw)

    def test_indonesian_display_names(self):
        self.assertEqual(language_names.indonesian("Spanish"), "Bahasa Spanyol")
        self.assertEqual(language_names.indonesian("Farsi"), "Bahasa Persia")
        self.assertEqual(language_names.indonesian("Yoruba"), "Bahasa Yoruba")

    def test_auto_pages_merge_spellings_and_use_indonesian_names(self):
        config = copy.deepcopy(CONFIG)
        config.search = {**CONFIG.search, "auto_language_min_papers": 2}
        papers = [
            {"id": "a", "title": "A", "abstract": "", "summary": {**SUMMARY, "languages_studied": ["Uyghur"]}},
            {"id": "b", "title": "B", "abstract": "", "summary": {**SUMMARY, "languages_studied": ["Uighur"]}},
        ]
        pages = languages.group_papers(config, papers)
        self.assertEqual(len(pages["x-uyghur"].papers), 2)
        self.assertEqual(pages["x-uyghur"].name_id, "Bahasa Uyghur")
        self.assertEqual(pages["x-uyghur"].name_en, "Uyghur")

    def test_studied_languages_use_indonesian_names(self):
        self.assertEqual(build.studied_names(CONFIG, ["Javanese", "Spanish", "Farsi", "Persian"]),
                         ["Bahasa Jawa", "Bahasa Spanyol", "Bahasa Persia"])

    def test_config_threshold_is_raised(self):
        self.assertGreaterEqual(int(CONFIG.search["auto_language_min_papers"]), 5)


class VenueAndTitleTest(unittest.TestCase):
    def venue(self, name, source="acl", published="2026-07-01"):
        return build.venue_short({"source": source, "venue": name, "published": published})

    def test_major_venues(self):
        self.assertEqual(self.venue("Proceedings of the Fifteenth Language Resources and Evaluation Conference"), "LREC 2026")
        self.assertEqual(self.venue("Findings of the Association for Computational Linguistics: EMNLP 2026"), "Findings EMNLP 2026")
        self.assertEqual(self.venue("Proceedings of the 64th Annual Meeting of the Association for Computational "
                                    "Linguistics (Volume 1: Long Papers)"), "ACL 2026 (Long)")
        self.assertEqual(self.venue("Proceedings of the Eleventh Conference on Machine Translation"), "WMT 2026")

    def test_workshop_acronym_in_brackets(self):
        self.assertEqual(self.venue("Proceedings of the Sixth Workshop on NLP for Indigenous Languages of the "
                                    "Americas (AmericasNLP)"), "AmericasNLP 2026")
        self.assertEqual(self.venue("Proceedings of the 6th Workshop on Multilingual Representation Learning "
                                    "(MRL 2026)"), "MRL 2026")
        self.assertEqual(self.venue("Proceedings of Resources for African Indigenous Languages (RAIL) 2026 @ LREC 2026"),
                         "RAIL 2026")

    def test_journals_and_arxiv(self):
        self.assertEqual(self.venue("Jurnal Buana Informatika", "openalex"), "Jurnal Buana Informatika")
        self.assertEqual(self.venue("International Journal on Information and Communication Technology (IJoICT)",
                                    "openalex"), "IJoICT")
        long = self.venue("Journal of Information Technology Software Engineering and Computer Science Research", "openalex")
        self.assertLessEqual(len(long), build.MAX_VENUE + 3)
        self.assertTrue(long.endswith("..."))
        self.assertEqual(build.venue_short({"source": "arxiv", "venue": "", "published": "2026-01-01"}), "arXiv")

    def test_all_caps_titles(self):
        paper = {"title": "DETEKSI SENTIMEN MULTIBAHASA: INDOBERT VS ROBERTA BERBASIS TERJEMAHAN NLLB-200",
                 "abstract": "Kami membandingkan IndoBERT dan RoBERTa dengan NLLB-200."}
        self.assertEqual(build.display_title(paper),
                         "Deteksi Sentimen Multibahasa: IndoBERT vs RoBERTa berbasis Terjemahan NLLB-200")
        kelas = {"title": "PRESTASI BELAJAR SISWA KELAS XI DI SMK MUHAMMADIYAH", "abstract": ""}
        self.assertEqual(build.display_title(kelas), "Prestasi Belajar Siswa Kelas XI di SMK Muhammadiyah")
        normal = {"title": "Low-Resource MT for Javanese", "abstract": ""}
        self.assertEqual(build.display_title(normal), "Low-Resource MT for Javanese")


class PaperPageTest(unittest.TestCase):
    def setUp(self):
        papers = {}
        pipeline.merge_candidates(CONFIG, papers, candidates(), NOW)
        self.paper = papers["2609.01234"]
        self.paper["summary"] = {**copy.deepcopy(SUMMARY), "model": "m", "source": "full_text"}

    def test_many_languages_are_folded(self):
        pages = {f"l{i}": languages.LanguagePage(f"l{i}", f"Bahasa {i}", f"L{i}", "other") for i in range(40)}
        self.paper["languages"] = list(pages)
        html = build.language_chips(pages, self.paper)
        self.assertEqual(html.count('class="chip chip-lang"'), build.MAX_LANGUAGE_CHIPS)
        self.assertEqual(html.count("chip-extra"), 40 - build.MAX_LANGUAGE_CHIPS)
        self.assertIn(f"+{40 - build.MAX_LANGUAGE_CHIPS} bahasa lainnya", html)
        # Sedikit bahasa: semua tampil tanpa tombol.
        self.paper["languages"] = ["l1", "l2"]
        self.assertNotIn("chip-more", build.language_chips(pages, self.paper))

    def test_citations(self):
        apa = build.apa_citation(self.paper)
        self.assertTrue(apa.startswith("Rahma, S., & Santoso, B. (2026). Low-Resource Machine Translation"))
        self.assertIn("arXiv preprint arXiv:2609.01234", apa)
        bib = build.bibtex(self.paper)
        self.assertTrue(bib.startswith("@misc{rahma2026low,"))
        self.assertIn("author = {Siti Rahma and Budi Santoso}", bib)
        self.assertIn("eprint = {2609.01234}", bib)
        acl = {**self.paper, "source": "acl", "venue": "Proceedings of the Fifteenth Language Resources and Evaluation Conference",
               "doi": "10.1/x", "id": "acl:2026.lrec-1.1"}
        self.assertIn("@inproceedings{", build.bibtex(acl))
        self.assertIn("booktitle = {Proceedings of the Fifteenth Language Resources", build.bibtex(acl))
        self.assertTrue(build.apa_citation(acl).endswith("https://doi.org/10.1/x"))

    def test_paper_page_has_cite_box_and_copy_link(self):
        html = build.paper_body(CONFIG, self.paper)
        self.assertIn('<details class="cite" id="kutip">', html)
        self.assertIn('href="#kutip" id="cite-jump">Kutip</a>', html)
        self.assertIn('id="copy-link" hidden>Salin tautan</button>', html)

    def test_citation_meta_and_json_ld(self):
        meta = build.citation_meta(self.paper, "https://contoh.org/papers/2609.01234.html")
        self.assertIn('<meta name="citation_title" content="Low-Resource Machine Translation', meta)
        self.assertEqual(meta.count('name="citation_author"'), 2)
        self.assertIn('<meta name="citation_arxiv_id" content="2609.01234">', meta)
        ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', meta).group(1))
        self.assertEqual(ld["@type"], "ScholarlyArticle")
        self.assertEqual(ld["url"], "https://contoh.org/papers/2609.01234.html")
        evil = {**self.paper, "abstract": "</script><script>alert(1)</script>"}
        self.assertNotIn("</script><script>", build.citation_meta(evil, ""))


class SiteOutputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        papers = {}
        pipeline.merge_candidates(CONFIG, papers, candidates(), NOW)
        pipeline.rescore(CONFIG, papers, NOW)
        main = papers["2609.01234"]
        main["summary"] = {**copy.deepcopy(SUMMARY), "model": "m"}
        main["first_seen"] = "2026-09-19T23:30:00+00:00"
        cls.out = Path(tempfile.mkdtemp()) / "site"
        build.build_site(CONFIG, cls.out, {"updated_at": "2026-09-20T00:00:00+00:00", "papers": papers}, vectors={})

    def read(self, name):
        return (self.out / name).read_text()

    def test_feed_has_no_markers_and_uses_page_links_as_guid(self):
        feed = self.read("feed.xml")
        self.assertNotIn("*low-resource*", feed)
        self.assertIn("low-resource", feed)
        self.assertNotIn("arxiv:2609", feed)
        base = CONFIG.site["site_url"].rstrip("/")
        self.assertIn(f'<guid isPermaLink="true">{base}/papers/2609.01234.html</guid>', feed)

    def test_head_has_canonical_and_open_graph(self):
        base = CONFIG.site["site_url"].rstrip("/")
        paper = self.read("papers/2609.01234.html")
        self.assertIn(f'<link rel="canonical" href="{base}/papers/2609.01234.html">', paper)
        self.assertIn('<meta property="og:type" content="article">', paper)
        self.assertIn('name="citation_title"', paper)
        self.assertIn(f'<link rel="canonical" href="{base}/">', self.read("index.html"))
        self.assertNotIn('rel="canonical"', self.read("cari.html"))

    def test_sitemap_and_404(self):
        base = CONFIG.site["site_url"].rstrip("/")
        sitemap = self.read("sitemap.xml")
        self.assertIn(f"<loc>{base}/papers/2609.01234.html</loc>", sitemap)
        self.assertNotIn("cari.html", sitemap)
        page404 = self.read("404.html")
        self.assertIn("Halaman tidak ditemukan", page404)
        self.assertIn('href="/lentera-riset/assets/style.css"', page404)
        self.assertIn('href="/lentera-riset/makalah.html"', page404)

    def test_new_badge_and_home_facts(self):
        home = self.read("index.html")
        self.assertIn('class="badge-new">Baru</span>', home)
        self.assertIn("1 makalah baru", home)
        self.assertIn('class="home-facts"', home)
        catalog = json.loads(self.read("catalog.json"))
        item = next(p for p in catalog["papers"] if p["id"] == "2609.01234")
        self.assertEqual(item.get("new"), 1)

    def test_global_language_switch_and_card_languages(self):
        home = self.read("index.html")
        self.assertIn('<html lang="id" data-ringkasan="id">', home)
        self.assertIn('lentera:bahasa-ringkasan', home)
        self.assertIn('class="lang-switch lang-switch-compact"', home)
        self.assertIn('<p class="tldr" lang="id" data-l="id">', home)
        self.assertIn('<p class="tldr tldr-en" lang="en" data-l="en">', home)

    def test_catalog_is_small_and_texts_are_separate(self):
        catalog = json.loads(self.read("catalog.json"))
        item = catalog["papers"][0]
        for gone in ("url", "date_label", "tldr", "tldr_en", "snippet"):
            self.assertNotIn(gone, item)
        texts = json.loads(self.read("texts.json"))
        self.assertEqual(set(texts), {p["id"] for p in catalog["papers"]})

    def test_mobile_filter_button_on_catalog(self):
        html = self.read("makalah.html")
        self.assertIn('id="facet-open" aria-controls="facets"', html)
        self.assertIn('<aside class="facets" id="facets"', html)


class ScheduleTest(unittest.TestCase):
    def test_cron_avoids_the_top_of_the_hour(self):
        workflow = (ROOT / ".github/workflows/update.yml").read_text()
        minute = re.search(r'cron: "(\d+) ', workflow).group(1)
        self.assertNotEqual(minute, "0")

    def test_worker_has_daily_limits(self):
        wrangler = tomllib.loads((ROOT / "worker/wrangler.toml").read_text())
        self.assertGreater(int(wrangler["vars"]["ASK_DAILY_LIMIT"]), 0)
        self.assertGreater(int(wrangler["vars"]["EMBED_DAILY_LIMIT"]), 0)
        self.assertEqual(wrangler["durable_objects"]["bindings"][0]["class_name"], "UsageCounter")
        self.assertIn("UsageCounter", wrangler["migrations"][0]["new_sqlite_classes"])


if __name__ == "__main__":
    unittest.main()
