"""Pengujian tata letak halaman makalah: ringkasan yang bisa dibuka-tutup, pilihan bahasa,
dan ikon "Tanyakan bagian ini"."""

import copy
import unittest

from lentera import build, pipeline
from tests.helpers import CONFIG, SUMMARY
from tests.test_pipeline_build import NOW, candidates


class SummaryLayoutTest(unittest.TestCase):
    def setUp(self):
        papers = {}
        pipeline.merge_candidates(CONFIG, papers, candidates(), NOW)
        self.paper = papers["2609.01234"]
        self.paper["summary"] = {**copy.deepcopy(SUMMARY), "model": "m", "source": "full_text"}

    def test_sections_start_closed_with_snippet_in_both_languages(self):
        html = build.paper_body(CONFIG, self.paper)
        self.assertEqual(html.count('<div class="summary-section"'), len(build.SECTIONS))
        self.assertEqual(html.count("<details>"), len(build.SECTIONS))
        self.assertNotIn("<details open", html)
        self.assertIn('<span class="sec-snippet" data-l="id">Paragraf latar belakang dengan <em>benchmark</em> NusaX.</span>', html)
        self.assertIn('<span class="sec-snippet" data-l="en" lang="en">Background paragraph.</span>', html)
        self.assertIn('id="sum-all" hidden>Buka semua bagian</button>', html)

    def test_language_switch_defaults_to_indonesian(self):
        html = build.paper_body(CONFIG, self.paper)
        self.assertIn('<article class="paper" data-summary-lang="id">', html)
        self.assertIn('data-set-lang="id" aria-pressed="true"', html)
        self.assertIn('data-set-lang="en" aria-pressed="false"', html)
        # TL;DR ikut pilihan bahasa yang sama.
        self.assertIn('<p lang="id" data-l="id">', html)
        self.assertIn('<p class="tldr-en" lang="en" data-l="en">', html)

    def test_no_language_switch_without_summary(self):
        self.paper["summary"] = None
        html = build.paper_body(CONFIG, self.paper)
        self.assertNotIn("lang-switch", html)
        self.assertIn("belum tersedia", html)

    def test_ask_section_buttons_only_with_ask(self):
        self.assertNotIn('class="ask-section"', build.paper_body(CONFIG, self.paper))
        html = build.paper_body(CONFIG, self.paper, ask=True)
        self.assertEqual(html.count('class="ask-section"'), len(build.SECTIONS))
        self.assertIn('data-section-id="Metode" data-section-en="Method"', html)
        # Tombol ada di luar <summary>, supaya klik ikon tidak ikut membuka bagian.
        method = html.split('id="method">')[1].split('</div>\n<div class="summary-section"')[0]
        self.assertLess(method.index("</details>"), method.index('class="ask-section"'))

    def test_legacy_summary_uses_language_switch_too(self):
        self.paper["summary"] = {
            "id": {"summary": "Ringkasan lama.", "tldr": "TL;DR."},
            "en": {"summary": "Old summary.", "tldr": "TL;DR."},
            "model": "m",
        }
        html = build.paper_body(CONFIG, self.paper)
        self.assertIn('<div class="summary-col" lang="id" data-l="id"><p>Ringkasan lama.</p></div>', html)
        self.assertIn('<div class="summary-col" lang="en" data-l="en"><p>Old summary.</p></div>', html)
        self.assertNotIn('id="sum-all"', html)


class FirstSentenceTest(unittest.TestCase):
    def test_takes_first_sentence(self):
        self.assertEqual(build.first_sentence("Satu dua. Tiga empat."), "Satu dua.")
        self.assertEqual(build.first_sentence("Tanpa titik"), "Tanpa titik")
        self.assertEqual(build.first_sentence("  Baris\npertama.\n\nKedua."), "Baris pertama.")

    def test_decimal_point_is_not_a_sentence_end(self):
        self.assertEqual(build.first_sentence("Skor naik 3.5 poin pada NusaX. Lalu turun."), "Skor naik 3.5 poin pada NusaX.")

    def test_long_sentence_is_cut_at_a_word(self):
        text = "kata " * 100
        out = build.first_sentence(text, limit=40)
        self.assertTrue(out.endswith("..."))
        self.assertLessEqual(len(out), 43)
        self.assertNotIn("ka...", out)


if __name__ == "__main__":
    unittest.main()
