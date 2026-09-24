import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from lentera import arxiv, build, pipeline
from lentera.summarize import QuotaExceeded
from tests.helpers import CONFIG, SUMMARY

FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_sample.xml"
NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def candidates():
    return {p["id"]: p for p in arxiv.parse_feed(FIXTURE.read_bytes())}


class FakeSummarizer:
    def __init__(self, fail_after=None):
        self.calls = 0
        self.fail_after = fail_after

    def summarize(self, paper):
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise QuotaExceeded("habis")
        self.calls += 1
        return copy.deepcopy(SUMMARY), "fake-model"


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.papers = {}
        pipeline.merge_candidates(CONFIG, self.papers, candidates(), NOW)
        pipeline.rescore(CONFIG, self.papers, NOW)

    def test_only_relevant_papers_are_kept(self):
        self.assertEqual(list(self.papers), ["2609.01234"])

    def test_old_papers_are_skipped(self):
        later = datetime(2027, 1, 1, tzinfo=timezone.utc)
        papers = {}
        self.assertEqual(pipeline.merge_candidates(CONFIG, papers, candidates(), later), 0)

    def test_existing_paper_keeps_summary_and_updates_metadata(self):
        self.papers["2609.01234"]["summary"] = {"x": 1}
        cand = candidates()
        cand["2609.01234"]["version"] = 3
        pipeline.merge_candidates(CONFIG, self.papers, cand, NOW)
        self.assertEqual(self.papers["2609.01234"]["version"], 3)
        self.assertEqual(self.papers["2609.01234"]["summary"], {"x": 1})

    def test_summaries_are_added_with_source_hash(self):
        with mock.patch("time.sleep"):
            done = pipeline.summarize_pending(CONFIG, self.papers, FakeSummarizer(), log=lambda *_: None)
        self.assertEqual(done, 1)
        s = self.papers["2609.01234"]["summary"]
        self.assertEqual(s["model"], "fake-model")
        self.assertEqual(s["source_hash"], pipeline.abstract_hash(self.papers["2609.01234"]))

        # Jalankan lagi: tidak ada yang perlu diringkas.
        with mock.patch("time.sleep"):
            self.assertEqual(pipeline.summarize_pending(CONFIG, self.papers, FakeSummarizer(), log=lambda *_: None), 0)

    def test_changed_abstract_triggers_resummary(self):
        with mock.patch("time.sleep"):
            pipeline.summarize_pending(CONFIG, self.papers, FakeSummarizer(), log=lambda *_: None)
            self.papers["2609.01234"]["abstract"] += " Revised."
            self.assertEqual(pipeline.summarize_pending(CONFIG, self.papers, FakeSummarizer(), log=lambda *_: None), 1)

    def test_quota_stops_gracefully(self):
        with mock.patch("time.sleep"):
            done = pipeline.summarize_pending(CONFIG, self.papers, FakeSummarizer(fail_after=0), log=lambda *_: None)
        self.assertEqual(done, 0)
        self.assertIsNone(self.papers["2609.01234"]["summary"])


class BuildTest(unittest.TestCase):
    def build(self, with_summary: bool):
        papers = {}
        pipeline.merge_candidates(CONFIG, papers, candidates(), NOW)
        pipeline.rescore(CONFIG, papers, NOW)
        p = papers["2609.01234"]
        p["signals"] = {"hugging_face": {"upvotes": 7, "url": "https://huggingface.co/papers/2609.01234"}}
        if with_summary:
            p["summary"] = {**copy.deepcopy(SUMMARY), "model": "fake-model"}
            p["summary"]["glossary"][0]["term"] = "benchmark"
        tmp = Path(tempfile.mkdtemp())
        build.build_site(CONFIG, tmp / "site", {"updated_at": "2026-09-20T00:00:00+00:00", "papers": papers})
        return tmp / "site"

    def test_builds_all_pages(self):
        out = self.build(with_summary=True)
        for rel in ["index.html", "tentang.html", "feed.xml", "assets/style.css", "assets/app.js",
                    "papers/2609.01234.html", ".nojekyll"]:
            self.assertTrue((out / rel).exists(), rel)
        self.assertFalse((out / "papers/2609.05555.html").exists())

    def test_paper_page_shows_both_languages_and_italic_terms(self):
        html = (self.build(with_summary=True) / "papers/2609.01234.html").read_text()
        self.assertIn('lang="id"', html)
        self.assertIn('lang="en"', html)
        self.assertIn("<em>low-resource</em>", html)
        self.assertIn("Glosarium istilah", html)
        self.assertIn("Javanese", html)
        self.assertIn("https://huggingface.co/papers/2609.01234", html)
        self.assertIn('href="../assets/style.css"', html)

    def test_page_without_summary_shows_abstract(self):
        html = (self.build(with_summary=False) / "papers/2609.01234.html").read_text()
        self.assertIn("belum tersedia", html)
        self.assertIn("NusaX as a benchmark", html)

    def test_index_escapes_html(self):
        papers = {}
        pipeline.merge_candidates(CONFIG, papers, candidates(), NOW)
        papers["2609.01234"]["title"] = "<script>alert(1)</script> Javanese"
        tmp = Path(tempfile.mkdtemp())
        build.build_site(CONFIG, tmp / "s", {"updated_at": None, "papers": papers})
        html = (tmp / "s" / "index.html").read_text()
        self.assertNotIn("<script>alert(1)", html)

    def test_inline_markup(self):
        self.assertEqual(build.inline("a *b* <c>"), "a <em>b</em> &lt;c&gt;")

    def test_date_in_indonesian(self):
        self.assertEqual(build.date_id("2026-09-18T10:00:00Z"), "18 September 2026")




class SignalMergeTest(unittest.TestCase):
    def test_empty_signal_clears_stale_value(self):
        papers = {}
        pipeline.merge_candidates(CONFIG, papers, candidates(), NOW)
        papers["2609.01234"]["signals"] = {"github": {"stars": 120}, "hugging_face": {"upvotes": 3}}
        fresh = {"2609.01234": {"github": None, "hugging_face": {"upvotes": 5}}}
        with mock.patch("lentera.signals.collect", return_value=fresh), \
             mock.patch("lentera.store.load", return_value={"papers": papers}), \
             mock.patch("lentera.store.save"), \
             mock.patch("lentera.pipeline.datetime") as dt:
            dt.now.return_value = NOW
            pipeline.update(CONFIG, fetch=False, summaries=False, log=lambda *_: None)
        self.assertEqual(papers["2609.01234"]["signals"], {"hugging_face": {"upvotes": 5}})


class MarkupTest(unittest.TestCase):
    def test_plain_strips_marks_and_escapes(self):
        self.assertEqual(build.plain("a *large language model* <b>"), "a large language model &lt;b&gt;")

    def test_english_column_has_no_italics_but_indonesian_does(self):
        summary = copy.deepcopy(SUMMARY)
        summary["en"]["summary"] = "Uses *large language models*."
        html = build.summary_column(summary, "en", "English")
        self.assertNotIn("<em>", html)
        self.assertIn("Uses large language models.", html)
        self.assertIn("<em>low-resource</em>", build.summary_column(summary, "id", "Bahasa Indonesia"))

    def test_glossary_explanation_renders_italics(self):
        papers = {}
        pipeline.merge_candidates(CONFIG, papers, candidates(), NOW)
        p = papers["2609.01234"]
        p["summary"] = {**copy.deepcopy(SUMMARY), "model": "m"}
        p["summary"]["glossary"] = [{"term": "fertility", "explanation_id": "Jumlah token per kata dari *tokenizer*."}]
        html = build.paper_body(CONFIG, p)
        self.assertIn("dari <em>tokenizer</em>.", html)
        self.assertNotIn("*tokenizer*", html)


if __name__ == "__main__":
    unittest.main()
