import base64
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

    def test_missing_section_fails(self):
        bad = copy.deepcopy(SUMMARY)
        del bad["sections"]["method"]
        with self.assertRaises(ValueError):
            summarize.validate(bad)

    def test_empty_language_fails(self):
        bad = copy.deepcopy(SUMMARY)
        bad["sections"]["results"]["id"] = "  "
        with self.assertRaises(ValueError):
            summarize.validate(bad)

    def test_output_has_version_and_all_sections(self):
        out = summarize.validate(copy.deepcopy(SUMMARY))
        self.assertEqual(out["version"], summarize.SUMMARY_VERSION)
        self.assertEqual(list(out["sections"]), [k for k, _, _ in summarize.SECTIONS])


class SummarizerTest(unittest.TestCase):
    def test_disabled_without_key(self):
        self.assertFalse(summarize.Summarizer(["m"], api_key="").enabled)

    def test_calls_gemini_with_key_header_and_schema(self):
        with mock.patch.object(http, "post_json", return_value=gemini_response(SUMMARY)) as post:
            result, model = summarize.Summarizer(["m1"], api_key="k").summarize(PAPER)
        self.assertEqual(model, "m1")
        self.assertEqual(result["tldr"]["id"], SUMMARY["tldr"]["id"])
        self.assertEqual(result["source"], "abstract")
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

        s = summarize.Summarizer(["gone", "ok"], api_key="k", log=lambda *_: None)
        with mock.patch.object(http, "post_json", side_effect=fake):
            _, model = s.summarize(PAPER)
        self.assertEqual(model, "ok")
        self.assertEqual(s.models, ["ok"])

    def run_with(self, models, responses):
        """Jalankan Summarizer dengan urutan respons palsu; kembalikan (hasil atau galat, summarizer, url)."""
        calls = []

        def fake(url, *args, **kwargs):
            calls.append(url)
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        s = summarize.Summarizer(models, api_key="k", log=lambda *_: None, sleep=lambda *_: None)
        with mock.patch.object(http, "post_json", side_effect=fake):
            try:
                out = s.summarize(PAPER)
            except Exception as exc:
                out = exc
        return out, s, calls

    def test_busy_model_falls_back_to_next(self):
        out, s, calls = self.run_with(["a", "b"], [http.HttpError(503, "u"), gemini_response(SUMMARY)])
        self.assertEqual(out[1], "b")
        self.assertEqual(s.models, ["a", "b"])  # model sibuk tidak dibuang

    def test_all_busy_raises_model_busy(self):
        with mock.patch.object(summarize, "list_flash_models", return_value=["a", "b"]):
            out, _, _ = self.run_with(["a", "b"], [http.HttpError(503, "u"), http.HttpError(503, "u")])
        self.assertIsInstance(out, summarize.ModelBusy)

    def test_all_busy_tries_discovered_backup_model(self):
        with mock.patch.object(summarize, "list_flash_models", return_value=["a", "gemini-9-flash"]):
            out, s, calls = self.run_with(["a"], [http.HttpError(503, "u"), gemini_response(SUMMARY)])
        self.assertEqual(out[1], "gemini-9-flash")
        self.assertEqual(s.models, ["a", "gemini-9-flash"])

    def test_discovery_happens_once_per_run(self):
        with mock.patch.object(summarize, "list_flash_models", return_value=["b"]) as lister:
            s = summarize.Summarizer(["a"], api_key="k", log=lambda *_: None, sleep=lambda *_: None)
            with mock.patch.object(http, "post_json", side_effect=http.HttpError(503, "u")):
                for _ in range(3):
                    with self.assertRaises(summarize.ModelBusy):
                        s.summarize(PAPER)
        self.assertEqual(lister.call_count, 1)

    def test_per_minute_limit_tries_next_model(self):
        out, s, _ = self.run_with(["a", "b"], [http.HttpError(429, "u", "GenerateRequestsPerMinute"), gemini_response(SUMMARY)])
        self.assertEqual(out[1], "b")
        self.assertEqual(s.models, ["a", "b"])

    def test_daily_quota_drops_model(self):
        out, s, _ = self.run_with(["a", "b"], [http.HttpError(429, "u", "GenerateRequestsPerDayPerProject"), gemini_response(SUMMARY)])
        self.assertEqual(out[1], "b")
        self.assertEqual(s.models, ["b"])

    def test_daily_quota_on_last_model_stops(self):
        with mock.patch.object(summarize, "list_flash_models", return_value=[]):
            out, _, _ = self.run_with(["a"], [http.HttpError(429, "u", "PerDay")])
        self.assertIsInstance(out, summarize.QuotaExceeded)

    def test_discovers_models_when_all_configured_are_gone(self):
        with mock.patch.object(summarize, "list_flash_models", return_value=["gemini-9-flash"]):
            out, s, calls = self.run_with(["gone"], [http.HttpError(404, "u"), gemini_response(SUMMARY)])
        self.assertEqual(out[1], "gemini-9-flash")
        self.assertIn("/models/gemini-9-flash:generateContent", calls[-1])


class ListModelsTest(unittest.TestCase):
    def test_filters_and_orders_flash_models(self):
        data = {"models": [
            {"name": "models/gemini-3-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-flash-latest", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3-flash-image", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3-pro", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-flash", "supportedGenerationMethods": ["embedContent"]},
        ]}
        with mock.patch.object(http, "get_json", return_value=data):
            names = summarize.list_flash_models("k")
        self.assertEqual(names, ["gemini-flash-latest", "gemini-3-flash", "gemini-2.5-flash", "gemini-3-flash-lite"])




class StripMarksTest(unittest.TestCase):
    def test_validate_strips_asterisks_from_english_only(self):
        s = copy.deepcopy(SUMMARY)
        s["tldr"]["en"] = "About *low-resource* MT."
        out = summarize.validate(s)
        self.assertEqual(out["tldr"]["en"], "About low-resource MT.")
        self.assertEqual(out["sections"]["method"]["en"], "Method with fine-tuning.")
        self.assertIn("*low-resource*", out["tldr"]["id"])
        self.assertIn("*fine-tuning*", out["sections"]["method"]["id"])


class PdfRequestTest(unittest.TestCase):
    def test_pdf_is_sent_inline_before_prompt(self):
        payload = summarize.build_request(PAPER, b"%PDF-1.7 fake")
        parts = payload["contents"][0]["parts"]
        self.assertEqual(parts[0]["inlineData"]["mimeType"], "application/pdf")
        self.assertEqual(base64.b64decode(parts[0]["inlineData"]["data"]), b"%PDF-1.7 fake")
        self.assertIn("full paper is attached", parts[1]["text"])

    def test_without_pdf_uses_abstract_note(self):
        parts = summarize.build_request(PAPER, None)["contents"][0]["parts"]
        self.assertEqual(len(parts), 1)
        self.assertIn("Only the title, abstract", parts[0]["text"])

    def test_source_is_full_text_when_pdf_accepted(self):
        s = summarize.Summarizer(["m"], api_key="k", log=lambda *_: None)
        with mock.patch.object(http, "post_json", return_value=gemini_response(SUMMARY)):
            result, _ = s.summarize(PAPER, b"%PDF")
        self.assertEqual(result["source"], "full_text")

    def test_rejected_pdf_falls_back_to_abstract(self):
        calls = []

        def fake(url, payload, **kwargs):
            calls.append(payload)
            if len(calls) == 1:
                raise http.HttpError(400, url, "The document has no pages.")
            return gemini_response(SUMMARY)

        s = summarize.Summarizer(["m"], api_key="k", log=lambda *_: None)
        with mock.patch.object(http, "post_json", side_effect=fake):
            result, _ = s.summarize(PAPER, b"%PDF")
        self.assertEqual(result["source"], "abstract")
        self.assertEqual(len(calls[1]["contents"][0]["parts"]), 1)


if __name__ == "__main__":
    unittest.main()
