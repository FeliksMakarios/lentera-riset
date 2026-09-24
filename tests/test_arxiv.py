import unittest
import urllib.parse
from pathlib import Path

from lentera import arxiv
from tests.helpers import CONFIG

FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_sample.xml"


class ParseFeedTest(unittest.TestCase):
    def setUp(self):
        self.papers = arxiv.parse_feed(FIXTURE.read_bytes())

    def test_parses_all_entries(self):
        self.assertEqual([p["id"] for p in self.papers], ["2609.01234", "2609.05555", "2609.07777"])

    def test_fields(self):
        p = self.papers[0]
        self.assertEqual(p["version"], 2)
        self.assertEqual(p["title"], "Low-Resource Machine Translation for Javanese and Sundanese")
        self.assertEqual(p["authors"], ["Siti Rahma", "Budi Santoso"])
        self.assertEqual(p["primary_category"], "cs.CL")
        self.assertEqual(p["categories"], ["cs.CL", "cs.AI"])
        self.assertEqual(p["comment"], "Accepted at a workshop")
        self.assertEqual(p["abs_url"], "https://arxiv.org/abs/2609.01234")
        self.assertIn("2609.01234", p["pdf_url"])

    def test_missing_pdf_link_falls_back(self):
        self.assertEqual(self.papers[2]["pdf_url"], "https://arxiv.org/pdf/2609.07777")

    def test_error_entry_is_skipped(self):
        xml = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>http://arxiv.org/api/errors#incorrect_id_format</id><title>Error</title></entry></feed>"""
        self.assertEqual(arxiv.parse_feed(xml), [])


class QueryTest(unittest.TestCase):
    def test_build_query_quotes_phrases(self):
        topic = CONFIG.topic("low-resource")
        q = arxiv.build_query(topic, ["cs.CL", "cs.AI"])
        self.assertTrue(q.startswith("(cat:cs.CL OR cat:cs.AI) AND ("))
        self.assertIn('abs:"low-resource language"', q)
        self.assertIn('abs:"low-resource languages"', q)
        self.assertIn('abs:"endangered languages"', q)
        self.assertNotIn('abs:"low-resource ASRs"', q)

    def test_query_url(self):
        url = arxiv.query_url("cat:cs.CL", 50)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(params["search_query"], ["cat:cs.CL"])
        self.assertEqual(params["sortBy"], ["submittedDate"])
        self.assertEqual(params["max_results"], ["50"])


if __name__ == "__main__":
    unittest.main()
