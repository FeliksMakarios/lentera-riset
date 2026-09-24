import copy
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from lentera import acl, fulltext, http, openalex, pipeline, signals
from tests.helpers import CONFIG

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class AclParseTest(unittest.TestCase):
    def setUp(self):
        self.papers = acl.parse_collection((FIXTURES / "acl_sample.xml").read_bytes(), date(2026, 6, 1))

    def test_only_recent_volumes(self):
        self.assertEqual([p["id"] for p in self.papers], ["acl:2026.sealp-1.1", "acl:2026.sealp-1.2"])

    def test_fields(self):
        p = self.papers[0]
        self.assertEqual(p["title"], "Dependency Parsing for Batak Toba")
        self.assertEqual(p["authors"], ["Rina Siregar", "Budi Nainggolan"])
        self.assertEqual(p["published"], "2026-09-10T00:00:00Z")
        self.assertEqual(p["venue"], "Proceedings of the Workshop on Southeast Asian Language Processing")
        self.assertEqual(p["abs_url"], "https://aclanthology.org/2026.sealp-1.1/")
        self.assertEqual(p["pdf_url"], "https://aclanthology.org/2026.sealp-1.1.pdf")
        self.assertEqual(p["doi"], "10.18653/v1/2026.sealp-1.1")
        self.assertEqual(p["source"], "acl")

    def test_external_url_without_pdf_has_no_pdf(self):
        self.assertEqual(self.papers[1]["pdf_url"], "")

    def test_old_style_collection_is_skipped(self):
        xml = b'<collection id="P19"><volume id="1" ingest-date="2026-09-01"><paper id="1"><title>x</title></paper></volume></collection>'
        self.assertEqual(acl.parse_collection(xml, date(2026, 1, 1)), [])


class AclFetchTest(unittest.TestCase):
    def fake_get_json(self, url, **kwargs):
        if "/commits?" in url:
            return [{"sha": "bbb"}, {"sha": "aaa"}]
        if url.endswith("/commits/bbb"):
            return {"files": [
                {"filename": "data/xml/2026.sealp.xml", "status": "modified"},
                {"filename": "python/acl_anthology/x.py", "status": "modified"},
            ]}
        if url.endswith("/commits/aaa"):
            return {"files": [
                {"filename": "data/xml/2026.sealp.xml", "status": "added"},
                {"filename": "data/xml/2020.gone.xml", "status": "removed"},
            ]}
        raise AssertionError(url)

    def test_fetch_uses_changed_files_and_updates_state(self):
        raw_urls = []

        def fake_request(url, **kwargs):
            raw_urls.append(url)
            return (FIXTURES / "acl_sample.xml").read_bytes()

        state = {}
        with mock.patch.object(http, "get_json", side_effect=self.fake_get_json), \
             mock.patch.object(http, "request", side_effect=fake_request):
            found = acl.fetch_candidates({"lookback_days": 120}, state, NOW, log=lambda *_: None)
        self.assertEqual(raw_urls, ["https://raw.githubusercontent.com/acl-org/acl-anthology/bbb/data/xml/2026.sealp.xml"])
        self.assertIn("acl:2026.sealp-1.1", found)
        self.assertEqual(state["commit"], "bbb")
        self.assertEqual(state["checked_at"], NOW.isoformat(timespec="seconds"))

    def test_since_uses_previous_check_with_overlap(self):
        seen = []

        def fake(url, **kwargs):
            seen.append(url)
            return []

        with mock.patch.object(http, "get_json", side_effect=fake):
            acl.fetch_candidates({"lookback_days": 120}, {"checked_at": "2026-09-20T00:00:00+00:00"}, NOW, log=lambda *_: None)
        self.assertIn("since=2026-09-18T00%3A00%3A00Z", seen[0])


WORK = {
    "id": "https://openalex.org/W123",
    "doi": "https://doi.org/10.1109/TASLP.2026.1234567",
    "display_name": "Speech Recognition for Endangered Languages of Papua",
    "publication_date": "2026-09-01",
    "created_date": "2026-09-05",
    "type": "article",
    "authorships": [{"author": {"display_name": "Maria Wanggai"}}, {"author": {"display_name": "Jon Doe"}}],
    "abstract_inverted_index": {"We": [0], "study": [1], "endangered": [2], "languages.": [3]},
    "primary_location": {
        "landing_page_url": "https://ieeexplore.ieee.org/document/1234567",
        "source": {
            "display_name": "IEEE/ACM Transactions on Audio, Speech, and Language Processing",
            "type": "journal",
            "host_organization_name": "Institute of Electrical and Electronics Engineers",
        },
    },
    "best_oa_location": None,
}


class OpenAlexTest(unittest.TestCase):
    def test_rebuild_abstract(self):
        self.assertEqual(openalex.rebuild_abstract({"b": [1], "a": [0, 2]}), "a b a")
        self.assertEqual(openalex.rebuild_abstract(None), "")

    def test_to_paper(self):
        p = openalex.to_paper(WORK)
        self.assertEqual(p["id"], "doi:10.1109/taslp.2026.1234567")
        self.assertEqual(p["abstract"], "We study endangered languages.")
        self.assertEqual(p["venue"], "IEEE/ACM Transactions on Audio, Speech, and Language Processing")
        self.assertEqual(p["authors"], ["Maria Wanggai", "Jon Doe"])
        self.assertEqual(p["published"], "2026-09-01T00:00:00Z")
        self.assertEqual(p["abs_url"], "https://doi.org/10.1109/taslp.2026.1234567")
        self.assertEqual(p["pdf_url"], "")

    def test_preprints_are_skipped(self):
        arxiv_work = copy.deepcopy(WORK)
        arxiv_work["doi"] = "https://doi.org/10.48550/arXiv.2609.00001"
        self.assertIsNone(openalex.to_paper(arxiv_work))
        repo_work = copy.deepcopy(WORK)
        repo_work["primary_location"]["source"]["type"] = "repository"
        self.assertIsNone(openalex.to_paper(repo_work))

    def test_filter(self):
        f = openalex.build_filter(CONFIG.topic("low-resource"), "2026-09-01")
        self.assertIn('title_and_abstract.search:("low-resource language" OR ', f)
        self.assertIn("from_created_date:2026-09-01", f)
        self.assertIn("topics.field.id:17", f)

    def test_skipped_without_key(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(openalex.fetch_candidates(CONFIG, {}, NOW, log=lambda *_: None), {})

    def test_fetch_with_key_and_redacted_errors(self):
        logs = []
        calls = []

        def fake(url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise http.HttpError(403, url, "forbidden")
            return {"results": [WORK], "meta": {"next_cursor": None}}

        state = {}
        with mock.patch.dict("os.environ", {"OPENALEX_API_KEY": "secret-key"}), \
             mock.patch.object(http, "get_json", side_effect=fake), mock.patch("time.sleep"):
            found = openalex.fetch_candidates(CONFIG, state, NOW, log=logs.append)
        self.assertIn("doi:10.1109/taslp.2026.1234567", found)
        self.assertIn("api_key=secret-key", calls[0])
        self.assertFalse(any("secret-key" in line for line in logs))
        self.assertIn("checked_at", state)


class MergeTest(unittest.TestCase):
    def test_same_title_from_other_source_is_merged(self):
        papers = {}
        arxiv_version = {
            "id": "2609.00001", "source": "arxiv", "title": "Dependency Parsing for Batak Toba",
            "abstract": "A treebank for Batak Toba, a low-resource language.", "authors": [],
            "published": "2026-09-20T00:00:00Z", "abs_url": "https://arxiv.org/abs/2609.00001", "pdf_url": "",
        }
        pipeline.merge_candidates(CONFIG, papers, {"2609.00001": arxiv_version}, NOW)
        acl_papers = acl.parse_collection((FIXTURES / "acl_sample.xml").read_bytes(), date(2026, 6, 1))
        added = pipeline.merge_candidates(CONFIG, papers, {p["id"]: p for p in acl_papers}, NOW)
        self.assertEqual(added, 0)
        self.assertEqual(list(papers), ["2609.00001"])
        also = papers["2609.00001"]["also"]
        self.assertEqual(also[0]["source"], "acl")
        self.assertEqual(also[0]["url"], "https://aclanthology.org/2026.sealp-1.1/")
        self.assertEqual(papers["2609.00001"]["pdf_url"], "https://aclanthology.org/2026.sealp-1.1.pdf")

    def test_acl_lookback_is_separate_from_arxiv(self):
        papers = {}
        acl_papers = acl.parse_collection((FIXTURES / "acl_sample.xml").read_bytes(), date(2026, 1, 1))
        later = datetime(2026, 12, 1, tzinfo=timezone.utc)  # 82 hari setelah volume masuk
        added = pipeline.merge_candidates(CONFIG, papers, {p["id"]: p for p in acl_papers}, later)
        self.assertEqual(added, 1)  # ACL memakai lookback 120 hari, arXiv 60 hari


class SignalRefsTest(unittest.TestCase):
    def test_references_per_source(self):
        self.assertEqual(signals.references({"id": "2609.1", "source": "arxiv"})["semantic_scholar"], "ARXIV:2609.1")
        r = signals.references({"id": "acl:2026.sealp-1.1", "source": "acl", "anthology_id": "2026.sealp-1.1"})
        self.assertEqual(r["semantic_scholar"], "ACL:2026.sealp-1.1")
        self.assertIsNone(r["hugging_face"])
        r = signals.references({"id": "doi:10.1109/x", "source": "openalex", "doi": "10.1109/x"})
        self.assertEqual(r["semantic_scholar"], "DOI:10.1109/x")
        self.assertIsNone(r["hacker_news"])


class FullTextTest(unittest.TestCase):
    PAPER = {"id": "2609.1", "pdf_url": "https://arxiv.org/pdf/2609.1"}

    def test_returns_pdf_bytes(self):
        with mock.patch.object(http, "request", return_value=b"%PDF-1.7 content"):
            self.assertEqual(fulltext.fetch_pdf(self.PAPER, log=lambda *_: None), b"%PDF-1.7 content")

    def test_rejects_non_pdf_and_oversized(self):
        with mock.patch.object(http, "request", return_value=b"<html>captcha</html>"):
            self.assertIsNone(fulltext.fetch_pdf(self.PAPER, log=lambda *_: None))
        with mock.patch.object(http, "request", return_value=b"%PDF" + b"0" * 2_000_000):
            self.assertIsNone(fulltext.fetch_pdf(self.PAPER, max_mb=1, log=lambda *_: None))

    def test_no_url_or_download_error(self):
        self.assertIsNone(fulltext.fetch_pdf({"id": "x", "pdf_url": ""}, log=lambda *_: None))
        with mock.patch.object(http, "request", side_effect=http.HttpError(403, "u")):
            self.assertIsNone(fulltext.fetch_pdf(self.PAPER, log=lambda *_: None))


if __name__ == "__main__":
    unittest.main()
