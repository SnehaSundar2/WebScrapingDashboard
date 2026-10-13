import urllib.error

from scrapedash import validators as v
from scrapedash.exceptions import FetchError, RobotsDisallowedError, ValidationError
from scrapedash.fetcher import USER_AGENT, decode_body
from tests.helpers import FakeWeb, TempDirTest, make_fetcher, page_html

SITE = "https://shop.example.com"


def web_with(pages=None, robots=None, robots_status=200):
    web = FakeWeb()
    if robots is not None:
        web.add(f"{SITE}/robots.txt", robots, status=robots_status, content_type="text/plain")
    for url, body in (pages or {}).items():
        web.add(url, body)
    return web


class TestValidation(TempDirTest):
    def test_url_rules(self):
        self.assertEqual(v.validate_url("Books.ToScrape.com/catalogue#top"), "https://books.toscrape.com/catalogue")
        self.assertEqual(v.validate_url("http://127.0.0.1:8000/x"), "http://127.0.0.1:8000/x")
        for bad in ["", "not a site", "ftp://example.com/f", "https://user:pw@example.com/", "https://example",
                    "https://example.com:99999/", "https://" + "a" * 2000 + ".com"]:
            with self.assertRaises(ValidationError, msg=bad):
                v.validate_url(bad)
        with self.assertRaises(ValidationError):
            v.validate_url("https://evil.example.org/", ["example.com"])
        self.assertTrue(v.in_domains("shop.example.com", ["example.com"]))
        self.assertFalse(v.in_domains("notexample.com", ["example.com"]))


class TestRobots(TempDirTest):
    def test_missing_robots_txt_allows_everything(self):
        f, _ = make_fetcher(web_with({f"{SITE}/": page_html("hi")}))  # robots.txt -> 404
        self.assertEqual(f.get(f"{SITE}/").status, 200)

    def test_disallowed_path_is_refused_and_crawl_delay_honoured(self):
        web = web_with({f"{SITE}/a": page_html("a"), f"{SITE}/b": page_html("b")},
                       robots="User-agent: *\nDisallow: /private/\nCrawl-delay: 4\n")
        f, clock = make_fetcher(web, delay=1.5)
        with self.assertRaises(RobotsDisallowedError):
            f.get(f"{SITE}/private/data")
        f.get(f"{SITE}/a")
        f.get(f"{SITE}/b")
        self.assertTrue(all(s >= 4 for s in clock.sleeps), clock.sleeps)   # Crawl-delay beats our 1.5 s
        self.assertNotIn(f"{SITE}/private/data", [u for u, _ in web.requests])

    def test_robots_403_blocks_and_500_stops(self):
        f, _ = make_fetcher(web_with({f"{SITE}/": page_html("x")}, robots="no", robots_status=403))
        with self.assertRaises(RobotsDisallowedError):
            f.get(f"{SITE}/")
        f, _ = make_fetcher(web_with({f"{SITE}/": page_html("x")}, robots="err", robots_status=500), retries=0)
        with self.assertRaises(FetchError) as ctx:
            f.get(f"{SITE}/")
        self.assertIn("robots.txt", str(ctx.exception))


class TestPoliteDownloading(TempDirTest):
    def test_rate_limit_per_site_and_user_agent(self):
        web = web_with({f"{SITE}/1": page_html("1"), f"{SITE}/2": page_html("2")})
        web.add("https://other.example.org/", page_html("o"))
        f, clock = make_fetcher(web, delay=2)
        f.get(f"{SITE}/1")
        f.get(f"{SITE}/2")
        f.get("https://other.example.org/")
        # shop: robots -> /1 -> /2 (2 waits); other site: robots -> / (1 wait); switching sites adds no wait
        self.assertEqual(clock.sleeps.count(2.0), 3)
        self.assertTrue(all(agent == USER_AGENT for _, agent in web.requests))

    def test_retries_temporary_errors_with_backoff_and_retry_after(self):
        web = web_with()
        web.add(f"{SITE}/", status=503).add(f"{SITE}/", status=429, headers={"Retry-After": "7"})
        web.add(f"{SITE}/", page_html("finally"))
        f, clock = make_fetcher(web, delay=1, retries=2, backoff=2)
        self.assertIn("finally", f.get(f"{SITE}/").text)
        self.assertIn(2.0, clock.sleeps)   # back-off after 503
        self.assertIn(7.0, clock.sleeps)   # Retry-After after 429

    def test_permanent_errors_are_not_retried(self):
        web = web_with()
        web.add(f"{SITE}/gone", status=404)
        f, _ = make_fetcher(web, retries=3)
        with self.assertRaises(FetchError) as ctx:
            f.get(f"{SITE}/gone")
        self.assertIn("HTTP 404 (page not found)", str(ctx.exception))
        self.assertEqual([u for u, _ in web.requests].count(f"{SITE}/gone"), 1)

    def test_network_failure_after_retries(self):
        web = web_with()
        web.add(f"{SITE}/", error=urllib.error.URLError("no route to host"))
        f, clock = make_fetcher(web, retries=2)
        with self.assertRaises(FetchError) as ctx:
            f.get(f"{SITE}/")
        self.assertIn("offline mode", str(ctx.exception))
        self.assertEqual(len([s for s in clock.sleeps if s > 1.5]), 2)  # two back-off waits

    def test_only_reasonable_html_is_accepted(self):
        web = web_with()
        web.add(f"{SITE}/file.pdf", b"%PDF", content_type="application/pdf")
        web.add(f"{SITE}/big", "x" * 5000)
        f, _ = make_fetcher(web, max_bytes=1000)
        with self.assertRaises(FetchError) as ctx:
            f.get(f"{SITE}/file.pdf")
        self.assertIn("not a web page", str(ctx.exception))
        with self.assertRaises(FetchError) as ctx:
            f.get(f"{SITE}/big")
        self.assertIn("larger than", str(ctx.exception))

    def test_character_sets(self):
        self.assertEqual(decode_body("café".encode("latin-1"), "text/html; charset=ISO-8859-1"), "café")
        self.assertIn("café", decode_body('<meta charset="windows-1252">café'.encode("cp1252"), "text/html"))
        self.assertIn("café", decode_body("café".encode("utf-8"), "text/html; charset=nonsense"))

    def test_cache_avoids_repeat_downloads(self):
        web = web_with({f"{SITE}/": page_html("cached page")})
        f, _ = make_fetcher(web, cache=self.db, cache_ttl=600)
        first, second = f.get(f"{SITE}/"), f.get(f"{SITE}/")
        self.assertFalse(first.from_cache)
        self.assertTrue(second.from_cache)
        self.assertEqual([u for u, _ in web.requests].count(f"{SITE}/"), 1)
        self.assertIsNone(self.db.get_page(f"{SITE}/", max_age=-1))  # expired entries are ignored
