from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import collect


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = collect.read_json(collect.ROOT / "scripts" / "preferences.json")
        self.first = date(2026, 11, 1)
        self.second = date(2026, 11, 2)

    def item(self, slug, title="Forgotten landscape"):
        return collect.candidate("pixel", "itch.io", f"https://artist.itch.io/{slug}", title,
                                 rank=0, author="Artist", image="https://img.itch.zone/preview.png")

    def run_with(self, day, *items):
        with patch.object(collect, "itch_candidates", return_value=items), \
             patch.object(collect, "museum_candidates", return_value=[]), \
             patch.object(collect, "music_candidates", return_value=[]), \
             patch.object(collect, "load_details"), \
             patch.object(collect, "image_available", return_value=True), \
             patch.object(collect, "warn"), patch.object(collect, "print_issue"):
            collect.run(self.config, self.directory, day)

    def test_history_and_deduplication(self):
        self.run_with(self.first, self.item("one"), self.item("one"))
        self.run_with(self.second, self.item("one"), self.item("two"))
        issues, seen = collect.history(self.directory)
        self.assertEqual(list(issues), ["2026-11-02", "2026-11-01"])
        self.assertEqual([len(issue["items"]) for issue in issues.values()], [1, 1])
        self.assertIn("artist.itch.io/one", seen)
        self.assertEqual(collect.read_json(self.directory / "index.json")["dates"], list(issues))

    def test_failed_or_repeated_run_preserves_last_issue(self):
        self.run_with(self.first, self.item("one"))
        previous = {path: path.read_bytes() for path in self.directory.rglob("*.json")}
        self.run_with(self.first, self.item("different"))
        with self.assertRaisesRegex(ValueError, "no new verified"):
            self.run_with(self.second, self.item("one"), self.item("excluded", "AI-generated asset pack"))
        self.assertEqual(previous, {path: path.read_bytes() for path in self.directory.rglob("*.json")})

    def test_provider_urls_and_word_boundaries(self):
        self.assertEqual(collect.safe_url("https://artist.itch.io/item#notes", "itch.io", True),
                         "https://artist.itch.io/item")
        for url in ["https://itch.io.example.com/work", "https://itch.io@other.test", "http://itch.io/work"]:
            self.assertEqual(collect.safe_url(url, "itch.io", True), "")
        self.assertEqual(collect.keyword_score("no ambient ambiance", {"ambient": 5, "amb": 9}), 5)


if __name__ == "__main__":
    unittest.main()
