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
        return collect.candidate(
            "pixel", "Commons", f"https://commons.wikimedia.org/wiki/File:{slug}.png", title,
            author="Artist", image=f"https://upload.wikimedia.org/{slug}.png", license="CC0",
            work_type="pixel illustration", theme="pixel", discovery="adjacent",
            collection={"enabled": True, "verified": True, "name": "Reviewed",
                        "image_host": "upload.wikimedia.org", "priority": 90},
        )

    def run_with(self, day, *items):
        with patch.object(collect, "gather", return_value=items), \
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
        self.assertIn("commons.wikimedia.org/wiki/File:one.png", seen)
        self.assertIn("upload.wikimedia.org/one.png", seen)
        self.assertEqual(collect.read_json(self.directory / "index.json")["dates"], list(issues))

    def test_failed_or_repeated_run_preserves_last_issue(self):
        self.run_with(self.first, self.item("one"))
        previous = {path: path.read_bytes() for path in self.directory.rglob("*.json")}
        self.run_with(self.first, self.item("different"))
        self.run_with(self.second, self.item("one"), self.item("excluded", "AI-generated asset pack"))
        self.assertEqual(previous, {path: path.read_bytes() for path in self.directory.rglob("*.json")})

    def test_provider_urls_and_word_boundaries(self):
        self.assertEqual(collect.safe_url("https://artist.itch.io/item#notes", "itch.io", True),
                         "https://artist.itch.io/item")
        for url in ["https://itch.io.example.com/work", "https://itch.io@other.test", "http://itch.io/work"]:
            self.assertEqual(collect.safe_url(url, "itch.io", True), "")
        self.assertEqual(collect.matches("low_poly ambient ambiance", ["low-poly", "ambient", "amb"]),
                         ["low-poly", "ambient"])

    def test_game_store_screenshot_cannot_qualify_on_keywords(self):
        item = collect.candidate("pixel", "itch.io", "https://artist.itch.io/ordinary-game",
                                 "Ancient ruins and environmental storytelling")
        with patch.object(collect, "load_details"), patch.object(collect, "image_available", return_value=True):
            decisions = []
            self.assertEqual(collect.select([item], self.config, self.first, set(), decisions=decisions), [])
        self.assertIn("白名单", decisions[0]["reason"])
        self.assertFalse(decisions[0]["work_type_verified"])

    def test_metadata_gates_and_mirror_image(self):
        original = self.item("one", "Low-poly art and pixel lighting")
        mirror = self.item("mirror")
        mirror["image"] = original["image"] + "?utm_source=mirror"
        unlicensed = self.item("bad")
        unlicensed["license"] = "unverified"
        unknown = self.item("unknown")
        unknown["author"] = collect.UNKNOWN
        with patch.object(collect, "load_details"), patch.object(collect, "image_available", return_value=True), \
             patch.object(collect, "warn"):
            decisions = []
            results = collect.select([original, mirror, unlicensed, unknown], self.config, self.first,
                                     set(), decisions=decisions)
        self.assertEqual(results, [original])
        self.assertEqual(original["license_url"], collect.LICENSES["CC0"])
        self.assertEqual({row["status"] for row in decisions}, {"selected", "rejected"})
        self.assertIn("预览重复", next(row["reason"] for row in decisions if row["url"] == mirror["url"]))

    def test_diagnostics_simulate_same_day_without_writes(self):
        self.run_with(self.first, self.item("one"))
        previous = {path: path.read_bytes() for path in self.directory.rglob("*.json")}
        tracks = [collect.candidate("music", "OC ReMix", "https://ocremix.org/remix/OCR00000", "Track",
                                    work_type="music track", author="Musician", image="https://ocremix.org/art.jpg",
                                    collection={"name": "Music", "verified": True, "enabled": True,
                                                "image_host": "ocremix.org"})]
        with patch.object(collect, "gather", return_value=[self.item("one"), *tracks]), \
             patch.object(collect, "load_details"), patch.object(collect, "image_available", return_value=True):
            report = collect.run(self.config, self.directory, self.first, diagnostic=True, sources=[])
            collect.run(self.config, self.directory, self.second, sources=[])
        self.assertEqual(report["candidate_count"], 2)
        self.assertEqual(report["selected_visual"], 0)
        self.assertEqual(report["selected_music"], 1)
        self.assertFalse(report["would_publish_with_available_visuals"])
        self.assertEqual(previous, {path: path.read_bytes() for path in self.directory.rglob("*.json")})

    def test_allowed_commons_category_requires_expected_credit_and_license(self):
        source = {
            "access": "commons_collection", "page_host": "commons.wikimedia.org",
            "url": "https://commons.wikimedia.org/wiki/Category:Concept",
            "author_credits": ["Studio Artist"],
        }
        item = self.item("one")
        item.pop("author")
        item["collection"] = source
        fixture = b"""
        <div class="fullImageLink"><a href="https://upload.wikimedia.org/example.png">original</a></div>
        <a href="/wiki/Category:Concept">collection</a>
        <tr><td id="fileinfotpl&#95;aut">Author</td><td>Studio Artist</td></tr>
        <span class="licensetpl&#95;link">https://creativecommons.org/licenses/by-sa/2.0</span>
        """
        with patch.object(collect, "robots_allowed", return_value=True), \
             patch.object(collect, "download", return_value=fixture):
            collect.load_details(item)
        self.assertEqual(item["author"], "Studio Artist")
        self.assertEqual(item["license"], "CC BY-SA 2.0")
        self.assertEqual(item["image"], "https://upload.wikimedia.org/example.png")
        fixture = fixture.replace(b'/wiki/Category:Concept', b'/wiki/Category:Screenshots')
        with patch.object(collect, "robots_allowed", return_value=True), \
             patch.object(collect, "download", return_value=fixture), \
             self.assertRaisesRegex(ValueError, "制作档案"):
            collect.load_details(item)


if __name__ == "__main__":
    unittest.main()
