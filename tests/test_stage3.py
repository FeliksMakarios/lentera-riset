"""Pengujian tahap 3: tanya jawab tentang makalah."""

import copy
import json
import re
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from lentera import build, pipeline
from lentera.config import ROOT
from tests.helpers import CONFIG, SUMMARY
from tests.test_pipeline_build import NOW, candidates

WORKER = "https://w.example.workers.dev"


class AskBuildTest(unittest.TestCase):
    def setUp(self):
        papers = {}
        pipeline.merge_candidates(CONFIG, papers, candidates(), NOW)
        pipeline.rescore(CONFIG, papers, NOW)
        main = papers["2609.01234"]
        main["summary"] = {**copy.deepcopy(SUMMARY), "model": "fake-model"}
        main["pdf_url"] = "https://example.org/get/VOL 12/makalah.pdf"
        self.papers = papers
        self.data = {"updated_at": None, "papers": papers}

    def build(self, worker_url=""):
        out = Path(tempfile.mkdtemp()) / "site"
        with mock.patch.dict("os.environ", {"LENTERA_WORKER_URL": worker_url}):
            build.build_site(CONFIG, out, copy.deepcopy(self.data), vectors={})
        return out

    def test_context_file_for_worker(self):
        out = self.build()
        data = json.loads((out / "qa/2609.01234.json").read_text())
        self.assertEqual(data["id"], "2609.01234")
        self.assertEqual(data["title"], self.papers["2609.01234"]["title"])
        self.assertEqual(data["venue"], "arXiv")
        self.assertRegex(data["published"], r"^\d{4}-\d{2}-\d{2}$")
        # Alamat PDF sudah dikodekan, sama seperti yang diunduh saat meringkas.
        self.assertEqual(data["pdf_url"], "https://example.org/get/VOL%2012/makalah.pdf")
        self.assertIn("TL;DR: ", data["summary"])
        self.assertIn("Background: ", data["summary"])
        # Semua makalah relevan punya berkas konteks.
        pages = {p.stem for p in (out / "papers").glob("*.html")}
        self.assertEqual({p.stem for p in (out / "qa").glob("*.json")}, pages)

    def test_ask_box_only_when_worker_is_configured(self):
        html = (self.build() / "papers/2609.01234.html").read_text()
        self.assertNotIn('id="tanya"', html)
        self.assertNotIn("ask.js", html)

        html = (self.build(WORKER) / "papers/2609.01234.html").read_text()
        self.assertIn('<section class="ask" id="tanya" data-paper="2609.01234">', html)
        self.assertIn(f'data-worker="{WORKER}"', html)
        self.assertIn('src="../assets/ask.js"', html)
        self.assertIn('href="#tanya">Tanya makalah ini</a>', html)
        self.assertIn("dari isi lengkap makalah (PDF akses terbuka)", html)
        self.assertEqual(html.count('class="ask-chip"'), len(build.ASK_SUGGESTIONS))

    def test_ask_box_without_pdf_says_so(self):
        paper = copy.deepcopy(self.papers["2609.01234"])
        paper["pdf_url"] = ""
        html = build.paper_body(CONFIG, paper, ask=True)
        self.assertIn("hanya dari abstrak dan ringkasan", html)

    def test_no_em_dash_in_ask_ui(self):
        html = build.ask_html(self.papers["2609.01234"])
        script = (ROOT / "static/ask.js").read_text()
        for text in (html, script):
            self.assertNotIn("—", text)

    def test_legacy_summary_text(self):
        legacy = {"en": {"summary": "Old summary."}, "id": {"summary": "Lama."}, "languages_studied": ["Javanese"]}
        self.assertEqual(build.summary_text(legacy), "Old summary.\n\nLanguages studied: Javanese")
        self.assertEqual(build.summary_text(None), "")


class AskWorkerConfigTest(unittest.TestCase):
    def test_worker_reads_context_from_this_site(self):
        with open(ROOT / "worker" / "wrangler.toml", "rb") as fh:
            wrangler = tomllib.load(fh)
        site = CONFIG.site["site_url"].rstrip("/") + "/"
        self.assertEqual(wrangler["vars"]["SITE_URL"], site)
        self.assertIn("ASK_LIMITER", [r["name"] for r in wrangler["ratelimits"]])
        ids = {r["namespace_id"] for r in wrangler["ratelimits"]}
        self.assertEqual(len(ids), len(wrangler["ratelimits"]))

    def test_worker_accepts_every_page_name(self):
        pattern = re.search(r"const PAPER_ID = /(.+)/;", (ROOT / "worker/src/ask.js").read_text()).group(1)
        for pid in ("2609.01234v2", "acl:2025.acl-long.12", "openalex:W4400000000", "hep-th/9901001"):
            self.assertRegex(build.slug(pid), pattern)


if __name__ == "__main__":
    unittest.main()
