import copy
import json
import unittest
from unittest import mock

from lentera import http, summarize
from tests.helpers import SUMMARY

PAPER = {"title": "T", "abstract": "A", "comment": ""}


def gemini_response(obj):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]}


class ValidateTest(unittest.TestCase):
    def test_valid_summary_passes_and_strips_asterisks_in_glossary(self):
        out = summarize.validate(copy.deepcopy(SUMMARY))
        self.assertEqual(out["glossary"][0]["term"], "benchmark")

    def test_missing_language_fails(self):
        bad = copy.deepcopy(SUMMARY)
        del bad["id"]
        with self.assertRaises(ValueError):
            summarize.validate(bad)

    def test_empty_key_points_fails(self):
        bad = copy.deepcopy(SUMMARY)
        bad["en"]["key_points"] = []
        with self.assertRaises(ValueError):
            summarize.validate(bad)


class SummarizerTest(unittest.TestCase):
    def test_disabled_without_key(self):
        self.assertFalse(summarize.Summarizer(["m"], api_key="").enabled)

    def test_calls_gemini_with_key_header_and_schema(self):
        with mock.patch.object(http, "post_json", return_value=gemini_response(SUMMARY)) as post:
            result, model = summarize.Summarizer(["m1"], api_key="k").summarize(PAPER)
        self.assertEqual(model, "m1")
        self.assertEqual(result["id"]["tldr"], SUMMARY["id"]["tldr"])
        url, payload = post.call_args.args
        self.assertIn("/models/m1:generateContent", url)
        self.assertEqual(post.call_args.kwargs["headers"], {"x-goog-api-key": "k"})
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")

    def test_falls_back_to_next_model_on_404(self):
        responses = [http.HttpError(404, "u"), gemini_response(SUMMARY)]

        def fake(*args, **kwargs):
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        s = summarize.Summarizer(["gone", "ok"], api_key="k")
        with mock.patch.object(http, "post_json", side_effect=fake):
            _, model = s.summarize(PAPER)
        self.assertEqual(model, "ok")
        self.assertEqual(s.models, ["ok"])

    def test_quota_error(self):
        with mock.patch.object(http, "post_json", side_effect=http.HttpError(429, "u")):
            with self.assertRaises(summarize.QuotaExceeded):
                summarize.Summarizer(["m"], api_key="k").summarize(PAPER)


if __name__ == "__main__":
    unittest.main()
