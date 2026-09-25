"""Pengujian tahap 2: vektor makna, halaman bahasa dan topik, serta pencarian."""

import base64
import copy
import json
import math
import re
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from lentera import build, embeddings, http, languages, pipeline
from lentera.config import ROOT
from tests.helpers import CONFIG, SUMMARY
from tests.test_pipeline_build import NOW, candidates


def paper(pid, title, abstract="", summary=None, relevance=5.0, score=1.0):
    return {
        "id": pid, "title": title, "abstract": abstract, "authors": ["A"],
        "published": "2026-09-01T00:00:00Z", "relevance": relevance, "score": score,
        "summary": summary, "topics": [],
    }


class VectorCodecTest(unittest.TestCase):
    def test_f16_roundtrip(self):
        v = embeddings.normalize([3.0, 4.0, 0.0])
        out = embeddings.decode_f16(embeddings.encode_f16(v))
        for a, b in zip(v, out):
            self.assertAlmostEqual(a, b, places=3)

    def test_i8_keeps_direction(self):
        v = embeddings.normalize([0.5, -0.25, 0.1, 0.0])
        import struct
        raw = base64.b64decode(embeddings.encode_i8(v))
        ints = struct.unpack(f"<{len(raw)}b", raw)
        self.assertEqual(ints[0], 127)
        self.assertEqual(ints[1], round(-0.25 / 0.5 * 127))
        cos = sum(a * b for a, b in zip(v, ints)) / math.sqrt(sum(i * i for i in ints))
        self.assertGreater(cos, 0.999)

    def test_similar_orders_by_cosine_and_skips_self(self):
        vecs = {
            "a": embeddings.normalize([1, 0, 0]),
            "b": embeddings.normalize([0.9, 0.1, 0]),
            "c": embeddings.normalize([0.6, 0.8, 0]),
            "d": embeddings.normalize([0, 0, 1]),
        }
        out = embeddings.similar(vecs, ["a", "b", "c", "d", "missing"], k=2, min_score=0.5)
        self.assertEqual([pid for pid, _ in out["a"]], ["b", "c"])
        self.assertEqual(out["d"], [])
        self.assertNotIn("missing", out)


class EmbeddingUpdateTest(unittest.TestCase):
    def setUp(self):
        self.papers = {
            "p1": paper("p1", "Javanese MT", "abs one", score=3),
            "p2": paper("p2", "Sundanese ASR", "abs two", score=2),
            "p3": paper("p3", "Irrelevant", "abs", relevance=0.5),
        }
        self.calls = []
        self.sleeps = []

    def fake_call(self, model, dims, key, texts):
        self.calls.append(texts)
        return [[1.0] + [0.0] * (dims - 1) for _ in texts]

    def run_update(self, store, call=None, **kw):
        return embeddings.update(CONFIG, self.papers, store, api_key="k", log=lambda *_: None,
                                 sleep=self.sleeps.append, call=call or self.fake_call, **kw)

    def test_embeds_relevant_papers_in_score_order_and_skips_unchanged(self):
        store = {"vectors": {}}
        self.assertEqual(self.run_update(store), 2)
        self.assertEqual(self.calls[0][0].split("\n")[0], "Javanese MT")
        self.assertEqual(set(store["vectors"]), {"p1", "p2"})
        self.assertEqual(store["model"], CONFIG.embeddings["model"])
        self.assertEqual(self.run_update(store), 0)
        self.papers["p2"]["abstract"] = "changed"
        self.assertEqual(self.run_update(store), 1)

    def test_model_change_resets_vectors_and_removed_papers_are_pruned(self):
        store = {"model": "old", "dimensions": 256, "vectors": {"p1": {"h": "x", "v": ""}, "gone": {"h": "y", "v": ""}}}
        self.run_update(store)
        self.assertNotIn("gone", store["vectors"])
        self.assertEqual(store["model"], CONFIG.embeddings["model"])

    def test_per_minute_limit_waits_then_retries(self):
        attempts = []

        def flaky(model, dims, key, texts):
            attempts.append(1)
            if len(attempts) == 1:
                raise http.HttpError(429, "u", "RESOURCE_EXHAUSTED PerMinute")
            return self.fake_call(model, dims, key, texts)

        store = {"vectors": {}}
        self.assertEqual(self.run_update(store, call=flaky), 2)
        self.assertIn(65, self.sleeps)

    def test_daily_quota_keeps_finished_batches(self):
        batches = []

        def quota(model, dims, key, texts):
            batches.append(texts)
            if len(batches) > 1:
                raise http.HttpError(429, "u", "GenerateRequestsPerDay")
            return self.fake_call(model, dims, key, texts)

        config = copy.deepcopy(CONFIG)
        config.embeddings = {**CONFIG.embeddings, "batch_size": 1}
        store = {"vectors": {}}
        with self.assertRaises(embeddings.EmbeddingQuotaExceeded):
            embeddings.update(config, self.papers, store, api_key="k", log=lambda *_: None,
                              sleep=lambda _: None, call=quota)
        self.assertEqual(list(store["vectors"]), ["p1"])

    def test_without_key_nothing_is_called(self):
        store = {"vectors": {}}
        n = embeddings.update(CONFIG, self.papers, store, api_key="", log=lambda *_: None, call=self.fake_call)
        self.assertEqual(n, 0)
        self.assertEqual(self.calls, [])

    def test_vectors_for_requires_matching_model(self):
        v = embeddings.encode_f16(embeddings.normalize([1.0, 2.0]))
        good = {"model": CONFIG.embeddings["model"], "dimensions": CONFIG.embeddings["dimensions"], "vectors": {"a": {"h": "", "v": v}}}
        self.assertIn("a", embeddings.vectors_for(good, CONFIG))
        self.assertEqual(embeddings.vectors_for({**good, "model": "lain"}, CONFIG), {})


class WorkerConfigTest(unittest.TestCase):
    def test_worker_uses_same_model_and_dimensions_as_pipeline(self):
        with open(ROOT / "worker" / "wrangler.toml", "rb") as fh:
            wrangler = tomllib.load(fh)
        self.assertEqual(wrangler["vars"]["EMBED_MODEL"], CONFIG.embeddings["model"])
        self.assertEqual(int(wrangler["vars"]["EMBED_DIMENSIONS"]), int(CONFIG.embeddings["dimensions"]))
        origin = re.match(r"https://[^/]+", CONFIG.site["site_url"]).group(0)
        self.assertIn(origin, wrangler["vars"]["ALLOWED_ORIGINS"].split(","))


class LanguageTest(unittest.TestCase):
    def test_longer_names_win(self):
        found = languages.find(CONFIG, "A Papuan Malay and Malay corpus; Dayak Ngaju speech; Toba Batak MT")
        self.assertEqual(found, ["papuan-malay", "malay", "dayak-ngaju", "batak-toba"])
        self.assertNotIn("dayak", languages.find(CONFIG, "Dayak Ngaju only"))
        self.assertNotIn("batak", languages.find(CONFIG, "Batak Toba only"))

    def test_indonesian_names_and_hyphens(self):
        self.assertEqual(languages.find(CONFIG, "Analisis sentimen ulasan berbahasa Bahasa Jawa"), ["javanese"])
        self.assertIn("javanese", languages.find(CONFIG, "Javanese-Indonesian code-mixing"))
        self.assertIn("indonesian", languages.find(CONFIG, "Javanese-Indonesian code-mixing"))

    def test_sign_language_is_not_counted_as_indonesian(self):
        self.assertEqual(languages.find(CONFIG, "Indonesian Sign Language recognition"), ["indonesian-sign"])

    def test_summary_languages_are_mapped_or_become_auto_pages(self):
        summary = {**SUMMARY, "languages_studied": ["Javanese", "English", "Yoruba"]}
        papers = [
            paper("a", "A study", summary=summary),
            paper("b", "Another", summary={**SUMMARY, "languages_studied": ["Yoruba"]}),
            paper("c", "Third", summary={**SUMMARY, "languages_studied": ["Klingon"]}),
        ]
        pages = languages.group_papers(CONFIG, papers)
        self.assertIn("javanese", pages)
        self.assertIn("x-yoruba", pages)
        self.assertEqual(len(pages["x-yoruba"].papers), 2)
        self.assertNotIn("x-english", pages)
        self.assertNotIn("x-klingon", pages)
        self.assertEqual(papers[0]["languages"], ["javanese", "x-yoruba"])
        self.assertEqual(papers[2]["languages"], [])


class Stage2BuildTest(unittest.TestCase):
    def setUp(self):
        papers = {}
        pipeline.merge_candidates(CONFIG, papers, candidates(), NOW)
        pipeline.rescore(CONFIG, papers, NOW)
        main = papers["2609.01234"]
        main["summary"] = {**copy.deepcopy(SUMMARY), "model": "fake-model"}
        twin = copy.deepcopy(main)
        twin.update(id="2609.09999", title="Balinese and Javanese speech recognition", summary=None)
        papers[twin["id"]] = twin
        self.papers = papers
        vecs = {
            "2609.01234": embeddings.normalize([1.0, 0.1] + [0.0] * 254),
            "2609.09999": embeddings.normalize([0.9, 0.2] + [0.0] * 254),
        }
        self.out = Path(tempfile.mkdtemp()) / "site"
        build.build_site(CONFIG, self.out, {"updated_at": "2026-09-20T00:00:00+00:00", "papers": papers}, vectors=vecs)

    def test_similar_papers_are_linked(self):
        html = (self.out / "papers/2609.01234.html").read_text()
        self.assertIn("Makalah serupa", html)
        self.assertIn('href="2609.09999.html"', html)

    def test_paper_page_links_topics_and_languages(self):
        html = (self.out / "papers/2609.01234.html").read_text()
        self.assertIn('href="../topik/indonesia.html"', html)
        self.assertIn('href="../bahasa/javanese.html"', html)

    def test_language_pages(self):
        index = (self.out / "bahasa/index.html").read_text()
        self.assertIn("Bahasa Jawa", index)
        self.assertIn('href="balinese.html"', index)
        jav = (self.out / "bahasa/javanese.html").read_text()
        self.assertEqual(jav.count('class="card"'), 2)
        self.assertIn('href="../papers/2609.01234.html"', jav)
        self.assertNotIn('id="topic-filter"', (self.out / "topik/indonesia.html").read_text())

    def test_search_index_has_vectors_and_metadata(self):
        data = json.loads((self.out / "search-index.json").read_text())
        self.assertEqual(data["model"], CONFIG.embeddings["model"])
        self.assertEqual(data["dimensions"], 256)
        item = next(p for p in data["papers"] if p["id"] == "2609.01234")
        self.assertEqual(item["url"], "papers/2609.01234.html")
        self.assertIn("javanese", item["languages"])
        self.assertNotIn("*", item["tldr"])
        self.assertEqual(len(base64.b64decode(item["v"])), 256)
        self.assertIn("javanese", data["languages"])

    def test_search_page_carries_worker_url(self):
        html = (self.out / "cari.html").read_text()
        self.assertIn('data-worker=""', html)
        self.assertIn('src="assets/search.js"', html)
        env_out = Path(tempfile.mkdtemp()) / "site"
        with mock.patch.dict("os.environ", {"LENTERA_WORKER_URL": "https://w.example.workers.dev/"}):
            build.build_site(CONFIG, env_out, {"updated_at": None, "papers": self.papers}, vectors={})
        self.assertIn('data-worker="https://w.example.workers.dev"', (env_out / "cari.html").read_text())
