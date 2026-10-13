import copy
import json
from decimal import Decimal
from pathlib import Path

from scrapedash import extract, profiles
from scrapedash.crawler import crawl
from scrapedash.dom import parse_html
from scrapedash.exceptions import ValidationError
from scrapedash.sample_site import build_sample_web
from tests.helpers import FakeWeb, TempDirTest, make_fetcher, page_html

SAMPLES = Path(__file__).parent.parent / "sample_data" / "profiles"


class TestProfiles(TempDirTest):
    def test_builtin_and_example_profiles_are_valid(self):
        for name in profiles.BUILTIN:
            self.assertEqual(profiles.builtin(name).name, name)
        travel = profiles.load_profile_file(SAMPLES / "books_travel.json")
        self.assertIn("travel", travel.start_url)
        with self.assertRaises(ValidationError):
            profiles.builtin("amazon")

    def test_invalid_profiles_are_explained(self):
        base = profiles.BUILTIN["books"]
        mutations = {
            "missing 'item'": lambda d: d.pop("item"),
            "selector": lambda d: d.update(item="article..pod"),
            "type must be one of": lambda d: d["fields"]["price"].update(type="currency"),
            "outside this profile's allowed domains": lambda d: d.update(start_url="https://example.com/"),
            "must be marked": lambda d: d["fields"]["url"].update(required=False),
            "unknown setting": lambda d: d.update(colour="blue"),
            "Field name": lambda d: d["fields"].update({"Bad Name": {"select": "p"}}),
            "at least one field": lambda d: d.update(fields={}),
            "unknown option": lambda d: d["fields"]["title"].update(css="h3"),
        }
        for hint, mutate in mutations.items():
            data = copy.deepcopy(base)
            mutate(data)
            with self.assertRaises(ValidationError, msg=hint) as ctx:
                profiles.load_profile(data)
            self.assertIn(hint, str(ctx.exception))

    def test_profile_files(self):
        with self.assertRaises(ValidationError):
            profiles.load_profile_file(SAMPLES / "broken_profile_example.json")
        bad = self.dir / "bad.json"
        bad.write_text('{"name": "x",\n "fields": }', encoding="utf-8")
        with self.assertRaises(ValidationError) as ctx:
            profiles.load_profile_file(bad)
        self.assertIn("line 2", str(ctx.exception))
        with self.assertRaises(ValidationError):
            profiles.load_profile_file(self.dir / "missing.json")


class TestExtraction(TempDirTest):
    def test_converters(self):
        self.assertEqual(extract.to_money("£51.77"), (Decimal("51.77"), "£"))
        self.assertEqual(extract.to_money("Price: ₹1,299"), (Decimal("1299"), "₹"))
        self.assertEqual(extract.to_money("USD 12.50"), (Decimal("12.50"), "USD"))
        self.assertEqual(extract.to_rating("star-rating Three"), 3)
        self.assertEqual(extract.to_rating("4 out of 5"), 4)
        self.assertEqual(extract.to_rating("Rated 4.5/5"), Decimal("4.5"))
        self.assertEqual(extract.to_count("In stock (22 available)"), 22)
        self.assertTrue(extract.to_bool(" In stock ", "in stock"))
        self.assertFalse(extract.to_bool("Out of stock", "in stock"))
        self.assertEqual(extract.to_url("../page-2.html", "https://x.example.com/a/b/c.html"),
                         "https://x.example.com/a/page-2.html")
        for call, raw in [(extract.to_money, "free"), (extract.to_money, "£-5.00"), (extract.to_rating, "7/10"),
                          (extract.to_count, "many"), (lambda r: extract.to_url(r, "https://x.example.com/"), "javascript:alert(1)")]:
            with self.assertRaises(ValueError, msg=raw):
                call(raw)

    def test_items_from_sample_page(self):
        profile = profiles.builtin("books")
        web = build_sample_web()
        page2 = web.routes["https://books.toscrape.com/catalogue/page-2.html"][0]["body"].decode("utf-8")
        items, warnings, units = extract.extract_items(parse_html(page2), profile,
                                                       "https://books.toscrape.com/catalogue/page-2.html", "Page 2")
        self.assertEqual(len(items), 19)   # one book without a price is skipped
        self.assertEqual(units, {"price": "£"})
        self.assertTrue(any("skipped: required field(s) price missing" in w for w in warnings))
        self.assertTrue(any("'rating' could not be read" in w for w in warnings))
        book = items[0]
        self.assertIsInstance(book["price"], Decimal)
        self.assertTrue(book["url"].startswith("https://books.toscrape.com/catalogue/"))
        self.assertIn(book["rating"], range(1, 6))


class TestCrawler(TempDirTest):
    def test_full_sample_crawl(self):
        f, _ = make_fetcher(delay=1)
        result = crawl(profiles.builtin("books"), f, max_pages=10)
        self.assertEqual((len(result.pages), len(result.items), result.status), (3, 59, "complete"))
        self.assertEqual(result.stop_reason, "last page reached")
        limited = crawl(profiles.builtin("books"), make_fetcher(delay=1)[0], max_pages=2)
        self.assertEqual((len(limited.items), limited.stop_reason), (39, "page limit reached (2)"))  # page 2 skips 1
        quotes = crawl(profiles.builtin("quotes"), make_fetcher(delay=1)[0], max_pages=10)
        self.assertEqual(len(quotes.items), 18)
        self.assertEqual(quotes.items[0]["tags"], ["learning", "habits", "life"])

    def custom(self, pages):
        web = FakeWeb()
        for url, body in pages.items():
            web.add(url, body)
        data = {"name": "test", "start_url": "https://site.example.com/1", "allowed_domains": ["site.example.com"],
                "item": "li.item", "next_page": "a.next", "key": "name",
                "fields": {"name": {"type": "text", "required": True}}}
        return profiles.load_profile(data), make_fetcher(web, delay=1)[0], web

    def test_loops_foreign_links_duplicates_and_failures(self):
        item = lambda *names: "".join(f'<li class="item">{n}</li>' for n in names)
        profile, f, _ = self.custom({"https://site.example.com/1": page_html(item("a") + '<a class="next" href="/1">n</a>')})
        r = crawl(profile, f, 5)
        self.assertIn("Loop detected", r.warnings[0])
        profile, f, _ = self.custom({"https://site.example.com/1":
                                     page_html(item("a") + '<a class="next" href="https://evil.example.org/2">n</a>')})
        r = crawl(profile, f, 5)
        self.assertIn("not followed", r.warnings[0])
        profile, f, _ = self.custom({"https://site.example.com/1": page_html(item("a", "b") + '<a class="next" href="2">n</a>'),
                                     "https://site.example.com/2": page_html(item("b", "c"))})
        r = crawl(profile, f, 5)
        self.assertEqual(([i["name"] for i in r.items], r.duplicates), (["a", "b", "c"], 1))
        profile, f, web = self.custom({"https://site.example.com/1": page_html(item("a") + '<a class="next" href="2">n</a>')})
        web.add("https://site.example.com/2", status=500)
        r = crawl(profile, f, 5)
        self.assertEqual((r.status, len(r.items)), ("partial", 1))
        self.assertIn("HTTP 500", r.errors[0])

    def test_no_items_and_robots_and_bad_start(self):
        profile, f, _ = self.custom({"https://site.example.com/1": page_html("<p>redesigned page</p>")})
        r = crawl(profile, f, 5)
        self.assertEqual(r.status, "failed")
        self.assertIn("No items matched", r.errors[0])
        web = build_sample_web()
        web.add("https://books.toscrape.com/robots.txt", "User-agent: *\nDisallow: /catalogue/page-2.html",
                content_type="text/plain")
        r = crawl(profiles.builtin("books"), make_fetcher(web, delay=1)[0], 5)
        self.assertEqual((len(r.items), r.stop_reason), (20, "robots.txt disallowed the next page"))
        with self.assertRaises(ValidationError):
            crawl(profiles.builtin("books"), f, 5, start_url="https://quotes.toscrape.com/")
        with self.assertRaises(ValidationError):
            crawl(profiles.builtin("books"), f, 51)

    def test_redirect_outside_domain_is_rejected(self):
        web = build_sample_web()
        web.routes["https://books.toscrape.com/"][0]["final_url"] = "https://elsewhere.example.org/"
        r = crawl(profiles.builtin("books"), make_fetcher(web, delay=1)[0], 3)
        self.assertEqual(r.status, "failed")
        self.assertIn("redirected outside", r.errors[0])

    def test_profile_json_round_trip(self):
        data = json.loads(json.dumps(profiles.BUILTIN["quotes"]))
        self.assertEqual(list(profiles.load_profile(data).fields), ["text", "author", "tags", "author_url"])
