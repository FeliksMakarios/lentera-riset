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
            acl.fetch_candidates({"lookback_days": 120},
                                 {"checked_at": "2026-09-20T00:00:00+00:00", "version": acl.STATE_VERSION},
                                 NOW, log=lambda *_: None)
        self.assertIn("since=2026-09-18T00%3A00%3A00Z", seen[0])

    def test_old_state_version_rescans_full_lookback(self):
        seen = []

        def fake(url, **kwargs):
            seen.append(url)
            return []

        with mock.patch.object(http, "get_json", side_effect=fake):
            acl.fetch_candidates({"lookback_days": 120}, {"checked_at": "2026-09-20T00:00:00+00:00"}, NOW, log=lambda *_: None)
        self.assertIn("since=2026-05-27T00%3A00%3A00Z", seen[0])

    def test_old_style_and_old_year_files_are_skipped_and_newest_first(self):
        files = ["data/xml/W19.xml", "data/xml/P19.xml", "data/xml/2019.acl.xml",
                 "data/xml/2025.emnlp.xml", "data/xml/2026.acl.xml", "data/xml/2026.wildre.xml"]
        raw = []

        def fake_request(url, **kwargs):
            raw.append(url.rsplit("/", 1)[-1])
            return b'<collection id="2026.x"></collection>'

        state = {}
        with mock.patch.object(acl, "changed_xml_files", return_value=(files, "h")), \
             mock.patch.object(http, "request", side_effect=fake_request):
            acl.fetch_candidates({"lookback_days": 120, "max_files_per_run": 2}, state, NOW, log=lambda *_: None)
        self.assertEqual(raw, ["2026.wildre.xml", "2026.acl.xml"])
        self.assertEqual(state["version"], acl.STATE_VERSION)

    def test_collection_year(self):
        self.assertEqual(acl.collection_year("data/xml/2026.acl.xml"), 2026)
        self.assertEqual(acl.collection_year("data/xml/P19.xml"), 0)


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
        self.assertIn("from_publication_date:2026-09-01", f)
        self.assertNotIn("from_created_date", f)
        self.assertIn("primary_topic.field.id:17", f)

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


class NlpContextTest(unittest.TestCase):
    def paper(self, title, abstract, source="openalex"):
        return {"id": "x", "source": source, "title": title, "abstract": abstract}

    def test_non_nlp_openalex_paper_scores_zero(self):
        from lentera import relevance
        p = self.paper("Media flashcard untuk kosakata Bahasa Indonesia",
                       "Pembelajaran Bahasa Indonesia di sekolah dasar, low-resource language setting.")
        self.assertFalse(relevance.has_nlp_context(CONFIG, p))
        self.assertEqual(relevance.score_paper(CONFIG, p)["relevance"], 0)

    def test_strong_term_passes(self):
        from lentera import relevance
        p = self.paper("Hate speech detection in Javanese", "We fine-tune IndoBERT on a new Javanese corpus.")
        self.assertTrue(relevance.has_nlp_context(CONFIG, p))
        self.assertGreater(relevance.score_paper(CONFIG, p)["relevance"], 0)

    def test_two_weak_terms_pass_one_does_not(self):
        from lentera import relevance
        one = self.paper("Malay idioms", "A corpus study of Malay idioms.")
        two = self.paper("Malay idioms", "We release a corpus and annotation guidelines for Malay.")
        self.assertFalse(relevance.has_nlp_context(CONFIG, one))
        self.assertTrue(relevance.has_nlp_context(CONFIG, two))

    def test_other_sources_are_not_filtered(self):
        from lentera import relevance
        p = self.paper("Covert reciprocals in Indonesian", "A syntax study.", source="acl")
        self.assertTrue(relevance.has_nlp_context(CONFIG, p))


class OpenAlex429Test(unittest.TestCase):
    def test_short_retry_after_is_retried(self):
        calls = []

        def fake(url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise http.HttpError(429, url, '{"message": "busy"}', {"Retry-After": "5"})
            return {"results": []}

        sleeps = []
        with mock.patch.object(http, "get_json", side_effect=fake):
            self.assertEqual(openalex.get_page("u", sleep=sleeps.append), {"results": []})
        self.assertEqual(sleeps, [6.0])

    def test_long_or_missing_retry_after_stops(self):
        err = http.HttpError(429, "u", '{"message": "Daily credits exhausted"}',
                             {"Retry-After": "33710", "X-RateLimit-Remaining": "0"})
        with mock.patch.object(http, "get_json", side_effect=err):
            with self.assertRaises(openalex.QuotaExhausted) as ctx:
                openalex.get_page("u", sleep=lambda *_: None)
        self.assertIn("Daily credits exhausted", str(ctx.exception))
        self.assertIn("x-ratelimit-remaining=0", str(ctx.exception))

    def test_quota_exhausted_stops_all_topics_and_hides_key(self):
        calls = []
        logs = []

        def fake(url, **kwargs):
            calls.append(url)
            if "/rate-limit" in url:
                return {"api_key": "secret-key", "credits_remaining": 0}
            raise http.HttpError(429, url, '{"message": "Anonymous search is rate-limited, use a free API key"}')

        with mock.patch.dict("os.environ", {"OPENALEX_API_KEY": "secret-key"}), \
             mock.patch.object(http, "get_json", side_effect=fake), mock.patch("time.sleep"):
            found = openalex.fetch_candidates(CONFIG, {}, NOW, log=logs.append)
        self.assertEqual(found, {})
        self.assertEqual(sum(1 for u in calls if "/works?" in u), 1)
        self.assertTrue(any("Anonymous search" in line for line in logs))
        self.assertTrue(any("credits_remaining" in line for line in logs))
        self.assertFalse(any("secret-key" in line for line in logs))


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

    def test_url_with_spaces_is_encoded(self):
        paper = {"id": "x", "pdf_url": "https://j.example/get/IJCSMT/VOL. 12 NO. 6 2026/Machine Translation 73-85.pdf"}
        self.assertEqual(
            fulltext.pdf_url(paper),
            "https://j.example/get/IJCSMT/VOL.%2012%20NO.%206%202026/Machine%20Translation%2073-85.pdf",
        )
        # Alamat yang sudah dikodekan atau memakai kueri tidak berubah.
        for url in ["https://aclanthology.org/2026.lrec-1.129.pdf",
                    "https://j.example/a%20b.pdf",
                    "https://j.example/download?id=12&file=a.pdf"]:
            self.assertEqual(fulltext.pdf_url({"pdf_url": url}), url)

    def test_no_url_or_download_error(self):
        self.assertIsNone(fulltext.fetch_pdf({"id": "x", "pdf_url": ""}, log=lambda *_: None))
        with mock.patch.object(http, "request", side_effect=http.HttpError(403, "u")):
            self.assertIsNone(fulltext.fetch_pdf(self.PAPER, log=lambda *_: None))


if __name__ == "__main__":
    unittest.main()
