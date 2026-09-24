import gzip
import io
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

from lentera import arxiv, http
from tests.helpers import CONFIG

FIXTURES = Path(__file__).parent / "fixtures"


class RssTest(unittest.TestCase):
    def setUp(self):
        self.papers = arxiv.parse_rss((FIXTURES / "arxiv_rss_sample.xml").read_bytes())

    def test_skips_replacements(self):
        self.assertEqual([p["id"] for p in self.papers], ["2609.11111", "2609.22222"])

    def test_fields(self):
        p = self.papers[0]
        self.assertEqual(p["title"], "Sentiment Analysis for Minangkabau and Acehnese Tweets")
        self.assertTrue(p["abstract"].startswith("We build a sentiment corpus"))
        self.assertNotIn("Announce Type", p["abstract"])
        self.assertEqual(p["authors"], ["Putri Ayu", "Rahmat Hidayat", "Dewi Lestari"])
        self.assertEqual(p["published"], "2026-09-23T04:00:00Z")
        self.assertEqual(p["categories"], ["cs.CL", "cs.AI"])
        self.assertEqual(p["abs_url"], "https://arxiv.org/abs/2609.11111")

    def test_version(self):
        self.assertEqual(self.papers[1]["version"], 2)


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, headers: dict | None = None):
        super().__init__(body)
        self.headers = Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "err", Message(), io.BytesIO(b""))


class HttpTest(unittest.TestCase):
    def test_gzip_is_decompressed(self):
        resp = FakeResponse(gzip.compress(b"hello"), {"Content-Encoding": "gzip"})
        with mock.patch("urllib.request.urlopen", return_value=resp):
            self.assertEqual(http.request("https://x"), b"hello")

    def test_throttle_status_is_retried(self):
        responses = [http_error(406), FakeResponse(b"ok")]

        def fake(*args, **kwargs):
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with mock.patch("urllib.request.urlopen", side_effect=fake), mock.patch("time.sleep") as sleep:
            self.assertEqual(http.request("https://x", retry_statuses=frozenset({406})), b"ok")
        self.assertEqual(sleep.call_count, 1)

    def test_other_4xx_is_not_retried(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(406)), mock.patch("time.sleep") as sleep:
            with self.assertRaises(http.HttpError) as ctx:
                http.request("https://x")
        self.assertEqual(ctx.exception.status, 406)
        sleep.assert_not_called()

    def test_gives_up_after_retries_without_final_sleep(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(406)), mock.patch("time.sleep") as sleep:
            with self.assertRaises(http.HttpError):
                http.request("https://x", retries=3, retry_statuses=frozenset({406}))
        self.assertEqual(sleep.call_count, 2)


class FetchCandidatesTest(unittest.TestCase):
    def test_rss_papers_survive_api_rejection(self):
        rss = (FIXTURES / "arxiv_rss_sample.xml").read_bytes()
        calls = []

        def fake_request(url, **kwargs):
            calls.append(url)
            self.assertIn("Accept", kwargs["headers"])
            if url.startswith("https://rss.arxiv.org/"):
                return rss
            raise http.HttpError(406, url)

        with mock.patch.object(http, "request", side_effect=fake_request), mock.patch("time.sleep"):
            found = arxiv.fetch_candidates(CONFIG, log=lambda *_: None)
        self.assertEqual(sorted(found), ["2609.11111", "2609.22222"])
        # Satu permintaan RSS, lalu API berhenti setelah topik pertama ditolak.
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].startswith("https://rss.arxiv.org/rss/cs.CL+cs.AI"))

    def test_api_results_override_rss(self):
        rss = (FIXTURES / "arxiv_rss_sample.xml").read_bytes()
        api = (FIXTURES / "arxiv_sample.xml").read_bytes()

        def fake_request(url, **kwargs):
            return rss if url.startswith("https://rss.arxiv.org/") else api

        with mock.patch.object(http, "request", side_effect=fake_request), mock.patch("time.sleep"):
            found = arxiv.fetch_candidates(CONFIG, log=lambda *_: None)
        self.assertIn("2609.01234", found)
        self.assertIn("2609.11111", found)
        self.assertEqual(found["2609.01234"]["comment"], "Accepted at a workshop")


if __name__ == "__main__":
    unittest.main()


class SignalsTest(unittest.TestCase):
    def test_aggregator_repos_are_ignored(self):
        from lentera import signals

        data = {"total_count": 3, "items": [
            {"full_name": "Tavish9/awesome-daily-AI-arxiv", "description": "", "stargazers_count": 120, "html_url": "a"},
            {"full_name": "someone/agent-arXiv-daily", "description": "", "stargazers_count": 10, "html_url": "b"},
            {"full_name": "lab/nusa-mt", "description": "Official code for the paper", "stargazers_count": 7, "html_url": "c"},
        ]}
        with mock.patch.object(http, "get_json", return_value=data):
            out = signals.github_repos("2609.00001")
        self.assertEqual(out["stars"], 7)
        self.assertEqual(out["repos"], 1)
        self.assertEqual(out["name"], "lab/nusa-mt")

    def test_only_aggregators_means_no_signal(self):
        from lentera import signals

        data = {"items": [{"full_name": "x/awesome-papers", "description": "", "stargazers_count": 99}]}
        with mock.patch.object(http, "get_json", return_value=data):
            self.assertIsNone(signals.github_repos("2609.00001"))
