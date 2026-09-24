import unittest
from datetime import datetime, timezone

from lentera import rank, relevance
from tests.helpers import CONFIG

NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def paper(title, abstract, published="2026-09-18T00:00:00Z"):
    return {"title": title, "abstract": abstract, "published": published}


class RelevanceTest(unittest.TestCase):
    def test_indonesian_paper_is_relevant(self):
        r = relevance.score_paper(CONFIG, paper("Javanese NER", "We build a corpus for Javanese."))
        self.assertIn("indonesia", r["topics"])
        self.assertGreaterEqual(r["relevance"], CONFIG.ranking["min_relevance"])

    def test_generic_paper_is_not_relevant(self):
        r = relevance.score_paper(CONFIG, paper("Scaling vision transformers", "Image classification."))
        self.assertEqual(r["topics"], [])
        self.assertEqual(r["relevance"], 0)

    def test_multilingual_alone_is_below_threshold(self):
        r = relevance.score_paper(CONFIG, paper("A benchmark", "A multilingual benchmark."))
        self.assertLess(r["relevance"], CONFIG.ranking["min_relevance"])

    def test_hyphen_and_space_are_equivalent(self):
        r = relevance.score_paper(CONFIG, paper("x", "We target low resource settings."))
        self.assertIn("low-resource", r["topics"])

    def test_whole_word_only(self):
        # "Malaysia" tidak boleh cocok dengan kata kunci "Malay".
        r = relevance.score_paper(CONFIG, paper("x", "Tourism reviews from Malaysia."))
        self.assertNotIn("austronesia", r["topics"])

    def test_title_counts_more(self):
        in_title = relevance.score_paper(CONFIG, paper("Tagalog parsing", "A parser."))
        in_abstract = relevance.score_paper(CONFIG, paper("Parsing", "A parser for Tagalog."))
        self.assertGreater(in_title["relevance"], in_abstract["relevance"])

    def test_topic_score_is_capped(self):
        topic = CONFIG.topic("indonesia")
        text = "Javanese Sundanese Balinese Madurese Minangkabau Acehnese Buginese"
        _, score = relevance.topic_matches(topic, text, text)
        self.assertEqual(score, topic.weight * relevance.TOPIC_CAP_MULTIPLIER)


class RankTest(unittest.TestCase):
    def test_buzz_is_zero_without_signals(self):
        self.assertEqual(rank.buzz({}), 0)

    def test_buzz_increases_with_signals(self):
        low = rank.buzz({"hugging_face": {"upvotes": 1}})
        high = rank.buzz({"hugging_face": {"upvotes": 50}, "hacker_news": {"points": 100, "comments": 20}})
        self.assertGreater(high, low)

    def test_score_decays_with_age(self):
        fresh = {"relevance": 4, "signals": {}, "published": "2026-09-20T00:00:00Z"}
        old = {"relevance": 4, "signals": {}, "published": "2026-09-06T00:00:00Z"}
        self.assertAlmostEqual(rank.score(fresh, 14, NOW), 4)
        self.assertAlmostEqual(rank.score(old, 14, NOW), 2)


if __name__ == "__main__":
    unittest.main()
