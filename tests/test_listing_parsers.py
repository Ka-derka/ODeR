from pathlib import Path
import unittest

from core.crawl import parse_listing


FIXTURES = Path(__file__).parent / "fixtures" / "listings"
BASE_URL = "https://files.example.test/media/"


class DirectoryListingParserTests(unittest.TestCase):
    def parse_fixture(self, name):
        html = (FIXTURES / name).read_text(encoding="utf-8")
        return parse_listing(BASE_URL, html)

    def assert_fixture(self, name, expected):
        entries = self.parse_fixture(name)
        actual = {(entry["name"], entry["is_dir"], entry["size"]) for entry in entries}
        self.assertEqual(actual, set(expected))
        self.assertEqual(len(entries), len(expected))
        for entry in entries:
            self.assertTrue(entry["url"].startswith(BASE_URL))
            self.assertNotIn("#", entry["url"])
            self.assertNotIn("?", entry["url"])

    def test_apache_listing(self):
        self.assert_fixture("apache.html", {
            ("Season 1/", True, None),
            ("Pilot Episode.mkv", False, "1.4G"),
            ("notes.txt", False, "812 B"),
        })

    def test_nginx_listing_with_single_quoted_links(self):
        self.assert_fixture("nginx.html", {
            ("Artwork/", True, None),
            ("soundtrack.flac", False, "612MB"),
        })

    def test_caddy_listing_with_unquoted_links(self):
        self.assert_fixture("caddy.html", {
            ("Extras", True, None),
            ("cover.webp", False, "2.7 MiB"),
        })

    def test_nested_markup_entities_and_unsafe_links(self):
        self.assert_fixture("simple.html", {
            ("Subtitles/", True, None),
            ("special & rare.srt", False, "48 KB"),
        })


if __name__ == "__main__":
    unittest.main()
