from decimal import Decimal

from scrapedash import analysis, profiles
from scrapedash.crawler import crawl
from scrapedash.exceptions import StorageError, ValidationError
from scrapedash.fetcher import Page
from scrapedash.sample_site import build_sample_web
from scrapedash.storage import Database
from tests.helpers import TempDirTest, make_fetcher


class RunsMixin:
    def scrape(self, name="books", version=1, pages=10):
        result = crawl(profiles.builtin(name), make_fetcher(build_sample_web(version), delay=1)[0], pages)
        return self.db.get_run(self.db.save_run(result, "offline sample"))


class TestStorage(RunsMixin, TempDirTest):
    def test_run_round_trip_keeps_exact_types(self):
        run = self.scrape()
        self.assertEqual((run.id, len(run.items), len(run.pages)), (1, 59, 3))
        self.assertIsInstance(run.items[0]["price"], Decimal)
        self.assertIsInstance(run.items[0]["in_stock"], bool)
        self.assertEqual(run.units, {"price": "£"})
        self.assertEqual(len(run.warnings), 2)
        self.assertEqual(run.profile.name, "books")

    def test_history_delete_and_missing(self):
        self.scrape()
        self.scrape("quotes")
        self.assertEqual([r["profile"] for r in self.db.list_runs()], ["quotes", "books"])
        self.assertEqual(self.db.latest_run_ids("books"), [1])
        self.assertEqual(self.db.delete_run(1), 1)
        with self.assertRaises(ValidationError):
            self.db.get_run(1)
        with self.assertRaises(ValidationError):
            self.db.get_run("abc")

    def test_page_cache_expiry(self):
        now = [100.0]
        db = Database(self.dir / "cache.db", clock=lambda: now[0])
        db.put_page("https://x.example.com/", Page("https://x.example.com/", 200, "text/html", "<p>hi</p>", 0.1, 9))
        self.assertTrue(db.get_page("https://x.example.com/", 60).from_cache)
        now[0] += 120
        self.assertIsNone(db.get_page("https://x.example.com/", 60))
        self.assertEqual((db.cache_size(), db.clear_cache(), db.cache_size()), (1, 1, 0))
        db.close()

    def test_damaged_database_file(self):
        bad = self.dir / "bad.db"
        bad.write_bytes(b"this is not a sqlite database" * 100)
        with self.assertRaises(StorageError):
            Database(bad)


class TestAnalysis(RunsMixin, TempDirTest):
    def test_numeric_stats_and_nice_histogram(self):
        st = analysis.numeric_stats([Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40")])
        self.assertEqual((st["mean"], st["median"], st["min"], st["max"]), (Decimal("25.00"), Decimal("25.00"), 10, 40))
        self.assertEqual(analysis.histogram([11, 19, 25, 58]),
                         [(10, 20, 2), (20, 30, 1), (30, 40, 0), (40, 50, 0), (50, 60, 1)])  # step rounded to 10
        self.assertEqual(sum(c for *_, c in analysis.histogram([Decimal(x) for x in range(1, 101)])), 100)
        self.assertEqual(analysis.histogram([5, 5]), [(5, 5, 2)])
        self.assertIsNone(analysis.numeric_stats([]))

    def test_summaries_quality_and_insights(self):
        run = self.scrape()
        s = analysis.summarize(run)
        self.assertEqual(sum(c for _, c in s["rating"]["distribution"]), 58)   # one rating unreadable
        self.assertEqual(s["in_stock"]["true"] + s["in_stock"]["false"], 59)
        q = analysis.quality(run)
        self.assertEqual(q["skipped"], 1)
        self.assertLess(q["completeness"], 100)
        lines = analysis.insights(run, s)
        self.assertTrue(any(l.startswith("Average price £") for l in lines))
        self.assertTrue(any("could not be converted" in l for l in lines))
        quotes = self.scrape("quotes")
        top_author = analysis.summarize(quotes)["author"]["top"][0]
        self.assertEqual(top_author, ("Vikram Nair", 5))
        self.assertTrue(any("Most common tags: life (6)" in l for l in analysis.insights(quotes)))

    def test_group_means_and_top_items(self):
        run = self.scrape()
        rows = analysis.group_means(run.items, "rating", "price")
        self.assertEqual([r[0] for r in rows], [1, 2, 3, 4, 5])
        top = analysis.top_items(run, "price", 3)
        self.assertGreaterEqual(top[0]["price"], top[1]["price"])

    def test_compare_two_runs(self):
        old, new = self.scrape(version=1), self.scrape(version=2)
        diff = analysis.compare(old, new)
        self.assertEqual((len(diff["added"]), len(diff["removed"])), (3, 2))
        fields = [c["field"] for c in diff["changed"]]
        self.assertEqual((fields.count("price"), fields.count("in_stock")), (8, 1))
        self.assertEqual(diff["numeric"]["price"]["up"] + diff["numeric"]["price"]["down"], 8)
        self.assertEqual(analysis.compare(old, old)["changed"], [])
