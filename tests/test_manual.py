"""Pengujian makalah pilihan manual (config/manual.toml)."""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from lentera import build, manual, pipeline, relevance
from tests.helpers import CONFIG

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)

ARXIV_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2506.21563v2</id>
    <published>2025-06-10T00:00:00Z</published>
    <updated>2025-07-01T00:00:00Z</updated>
    <title>FormosanBench: Benchmarking Low-Resource Austronesian Languages</title>
    <summary>We benchmark LLMs on Formosan languages.</summary>
    <author><name>Kaiying Kevin Lin</name></author>
    <arxiv:primary_category term="cs.CL"/>
    <category term="cs.CL"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2603.15569v1</id>
    <published>2026-03-16T00:00:00Z</published>
    <updated>2026-03-16T00:00:00Z</updated>
    <title>Mamba-3: Improved Sequence Modeling using State Space Principles</title>
    <summary>A new state space model.</summary>
    <author><name>Albert Gu</name></author>
    <arxiv:primary_category term="cs.LG"/>
  </entry>
</feed>"""

ACL_XML = b"""<collection id="2025.acl">
  <volume id="long" ingest-date="2025-07-20">
    <meta><booktitle>Proceedings of ACL 2025</booktitle><venue>acl</venue></meta>
    <paper id="1377">
      <title>NusaAksara: A Multimodal and Multilingual Benchmark for Preserving Indonesian Indigenous Scripts</title>
      <author><first>A</first><last>B</last></author>
      <abstract>Indonesian scripts.</abstract>
      <doi>10.18653/v1/2025.acl-long.1377</doi>
      <url>2025.acl-long.1377</url>
    </paper>
    <paper id="1"><title>Other</title></paper>
  </volume>
</collection>"""


def work(title, doi, source_type="repository"):
    return {
        "id": "https://openalex.org/W1",
        "doi": f"https://doi.org/{doi}",
        "display_name": title,
        "publication_date": "2026-03-01",
        "authorships": [{"author": {"display_name": "Hokky Situngkir"}}],
        "abstract_inverted_index": {"Batak": [0], "model": [1]},
        "primary_location": {"source": {"type": source_type, "display_name": "SSRN"}},
        "best_oa_location": {},
    }


class LoadTest(unittest.TestCase):
    def write(self, text):
        path = Path(tempfile.mkdtemp()) / "manual.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_entries_need_a_valid_identifier(self):
        with self.assertRaises(ValueError):
            manual.load(self.write('[[papers]]\nnote = "tanpa ID"\n'))
        with self.assertRaises(ValueError):
            manual.load(self.write('[[papers]]\narxiv = "https://arxiv.org/abs/2506.21563"\n'))
        with self.assertRaises(ValueError):
            manual.load(self.write('[[papers]]\nacl = "../rahasia"\n'))
        self.assertEqual(manual.load(Path("/tidak/ada.toml")), [])

    def test_repository_list_is_valid_and_has_no_duplicates(self):
        entries = manual.load()
        self.assertGreaterEqual(len(entries), 36)
        keys = [manual.expected_id(e) or e["title"] for e in entries]
        self.assertEqual(len(keys), len(set(keys)))


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.papers = {
            "2609.18310": {"id": "2609.18310", "title": "SEA-LION-v4.8: A Technical Report", "relevance": 3.75},
            "2601.00001": {
                "id": "2601.00001", "title": "Engram Memory for TOBA LM", "relevance": 5.0,
                "also": [{"id": "acl:2026.acl-long.24", "source": "acl", "url": "", "venue": ""}],
            },
        }

    def fake_request(self, url, **kwargs):
        if "export.arxiv.org" in url:
            self.assertIn("id_list=2506.21563%2C2603.15569", url)
            return ARXIV_FEED
        if url.endswith("data/xml/2025.acl.xml"):
            return ACL_XML
        raise AssertionError(f"alamat tak terduga {url}")

    def fake_page(self, url, sleep=None):
        if "/doi:10.2139/ssrn.6400298" in url:
            return work("TOBA-LM Paper on SSRN", "10.2139/ssrn.6400298")
        if "search=" in url:
            return {"results": [work("Batak Toba Language-Indonesian Machine Translation", "10.1/bt", "journal")]}
        raise AssertionError(f"alamat tak terduga {url}")

    def run_fetch(self, entries):
        logs = []
        with mock.patch("lentera.http.request", side_effect=self.fake_request), \
                mock.patch("lentera.openalex.get_page", side_effect=self.fake_page):
            added = manual.fetch(CONFIG, self.papers, NOW, entries=entries, log=logs.append)
        return added, logs

    def test_marks_existing_and_adds_missing(self):
        entries = [
            {"arxiv": "2609.18310"},
            {"acl": "2026.acl-long.24"},
            {"arxiv": "2506.21563"},
            {"arxiv": "2603.15569"},
            {"acl": "2025.acl-long.1377"},
            {"doi": "10.2139/ssrn.6400298"},
            {"title": "Batak Toba Language–Indonesian Machine Translation"},
        ]
        added, logs = self.run_fetch(entries)
        self.assertEqual(added, 5)
        self.assertTrue(self.papers["2609.18310"]["manual"])
        # Sudah ada sebagai tautan `also` makalah lain.
        self.assertTrue(self.papers["2601.00001"]["manual"])
        self.assertNotIn("acl:2026.acl-long.24", self.papers)

        formosan = self.papers["2506.21563"]
        self.assertTrue(formosan["manual"])
        self.assertEqual(formosan["source"], "arxiv")
        self.assertEqual(formosan["pdf_url"], "https://arxiv.org/pdf/2506.21563")
        self.assertIsNone(formosan["summary"])
        self.assertIn("relevance", formosan)
        # Makalah di luar topik tetap masuk karena dipilih manual.
        self.assertEqual(self.papers["2603.15569"]["relevance"], 0)
        self.assertTrue(relevance.is_relevant(CONFIG, self.papers["2603.15569"]))

        nusa = self.papers["acl:2025.acl-long.1377"]
        self.assertEqual(nusa["pdf_url"], "https://aclanthology.org/2025.acl-long.1377.pdf")
        self.assertEqual(nusa["doi"], "10.18653/v1/2025.acl-long.1377")

        ssrn = self.papers["doi:10.2139/ssrn.6400298"]
        self.assertEqual(ssrn["abs_url"], "https://doi.org/10.2139/ssrn.6400298")
        self.assertEqual(ssrn["abstract"], "Batak model")
        self.assertIn("doi:10.1/bt", self.papers)

    def test_second_run_fetches_nothing(self):
        entries = [{"arxiv": "2506.21563"}, {"arxiv": "2603.15569"}]
        self.run_fetch(entries)
        with mock.patch("lentera.http.request", side_effect=AssertionError("tidak boleh dipanggil")):
            added = manual.fetch(CONFIG, self.papers, NOW, entries=entries, log=lambda *_: None)
        self.assertEqual(added, 0)

    def test_arxiv_failure_falls_back_to_openalex(self):
        def page(url, sleep=None):
            self.assertIn("/doi:10.48550/arxiv.2506.21563", url)
            return work("FormosanBench", "10.48550/arxiv.2506.21563")
        with mock.patch("lentera.http.request", side_effect=manual.http.HttpError(406, "u")), \
                mock.patch("lentera.openalex.get_page", side_effect=page):
            added = manual.fetch(CONFIG, self.papers, NOW, entries=[{"arxiv": "2506.21563"}], log=lambda *_: None)
        self.assertEqual(added, 1)
        paper = self.papers["2506.21563"]
        self.assertEqual((paper["source"], paper["abs_url"]), ("arxiv", "https://arxiv.org/abs/2506.21563"))

    def test_not_found_is_logged_and_skipped(self):
        def page(url, sleep=None):
            return {"results": [work("Judul lain sama sekali", "10.1/x")]}
        with mock.patch("lentera.openalex.get_page", side_effect=page):
            logs = []
            added = manual.fetch(CONFIG, self.papers, NOW, entries=[{"title": "Judul yang dicari"}], log=logs.append)
        self.assertEqual(added, 0)
        self.assertTrue(any("tidak ditemukan" in line for line in logs))

    def test_same_title_from_other_source_becomes_link(self):
        self.papers["x"] = {"id": "x", "title": "FormosanBench: Benchmarking Low-Resource Austronesian Languages"}
        with mock.patch("lentera.http.request", side_effect=self.fake_request):
            added = manual.fetch(CONFIG, self.papers, NOW,
                                 entries=[{"arxiv": "2506.21563"}, {"arxiv": "2603.15569"}], log=lambda *_: None)
        self.assertEqual(added, 1)
        self.assertTrue(self.papers["x"]["manual"])
        self.assertEqual(self.papers["x"]["also"][0]["id"], "2506.21563")


class ManualOnSiteTest(unittest.TestCase):
    def paper(self, pid, relevance_score, manual_flag=False, score=1.0):
        return {
            "id": pid, "title": f"Paper {pid}", "abstract": "Abstract.", "authors": ["A"],
            "published": "2025-01-01T00:00:00Z", "relevance": relevance_score, "score": score,
            "summary": None, "topics": [], "source": "arxiv", "abs_url": "", "pdf_url": "",
            **({"manual": True} if manual_flag else {}),
        }

    def test_manual_paper_is_built_and_summarized_first(self):
        papers = {
            "2501.00001": self.paper("2501.00001", 0.0, manual_flag=True, score=0.0),
            "2501.00002": self.paper("2501.00002", 0.0),
        }
        out = Path(tempfile.mkdtemp()) / "site"
        with mock.patch("lentera.relevance.score_paper", return_value={"relevance": 0.0, "topics": [], "matched_keywords": {}}):
            build.build_site(CONFIG, out, {"updated_at": None, "papers": copy.deepcopy(papers)}, vectors={})
        ids = [p["id"] for p in json.loads((out / "catalog.json").read_text())["papers"]]
        self.assertEqual(ids, ["2501.00001"])
        html = (out / "papers/2501.00001.html").read_text()
        self.assertIn("Pilihan pengelola", html)

        papers["2501.00003"] = self.paper("2501.00003", 9.0, score=50.0)
        order = []

        class Summarizer:
            def summarize(self, paper, pdf):
                order.append(paper["id"])
                return {"source": "abstract"}, "m"

        config = copy.deepcopy(CONFIG)
        config.summaries = {**CONFIG.summaries, "request_delay_seconds": 0}
        pipeline.summarize_pending(config, papers, Summarizer(), log=lambda *_: None, pdf_fetcher=lambda *a, **k: None)
        self.assertEqual(order, ["2501.00001", "2501.00003"])


if __name__ == "__main__":
    unittest.main()
