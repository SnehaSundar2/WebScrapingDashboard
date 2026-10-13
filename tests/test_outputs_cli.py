"""Exports, page report, dashboards and end-to-end menu sessions."""

import csv
import io
import json
from contextlib import redirect_stdout
from decimal import Decimal
from unittest.mock import patch

from scrapedash import dashboard, exporters, page_report, profiles
from scrapedash.cli import ScraperCLI, Settings
from scrapedash.crawler import crawl
from scrapedash.exceptions import StorageError
from scrapedash.fetcher import Page
from scrapedash.sample_site import build_sample_web
from scrapedash.storage import Run
from tests.helpers import TempDirTest, make_fetcher, page_html


def offline_run(db, name="books", version=1):
    result = crawl(profiles.builtin(name), make_fetcher(build_sample_web(version), delay=1)[0], 10)
    return db.get_run(db.save_run(result, "offline sample"))


class TestExports(TempDirTest):
    def test_csv_and_json(self):
        run = offline_run(self.db)
        run.items[0]["title"] = "=HYPERLINK(\"https://evil.example\")"   # spreadsheet formula injection attempt
        path = exporters.export_csv(run, self.dir / "out" / "books.csv")
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 59)
        self.assertTrue(rows[0]["title"].startswith("'="))
        self.assertIn(rows[0]["in_stock"], ("yes", "no"))
        doc = json.loads(exporters.export_json(run, self.dir / "books.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["run"]["items"], 59)
        self.assertIsInstance(doc["items"][1]["price"], str)                 # exact decimal, not float
        with self.assertRaises(StorageError):
            exporters.export_csv(run, path)                                   # never overwrite silently


class TestPageReport(TempDirTest):
    def test_report_finds_issues(self):
        html = page_html('<h1>Shop</h1><h1>Again</h1><p>Few words here.</p><img src="a.png">'
                         '<a href="/about">About</a><a href="https://other.example.org/" rel="nofollow">Out</a>'
                         '<a href="mailto:a@b.example">Mail</a><a href="#top">Top</a>',
                         title="A" * 70)
        page = Page("https://shop.example.com/", 200, "text/html", html, 0.25, len(html))
        r = page_report.analyse_page(page)
        self.assertEqual((r["h1_count"], r["internal_links"], r["external_links"], r["nofollow_links"],
                          r["other_links"], r["images_missing_alt"]), (2, 1, 1, 1, 1, 1))
        joined = " ".join(r["issues"])
        for hint in ("title is 70 characters", "No meta description", "2 <h1>", "no alt text", "thin content"):
            self.assertIn(hint, joined)
        self.assertLess(r["score"], 50)
        count, preview = page_report.test_selector(page, "a[href]")
        self.assertEqual((count, preview[0]["text"]), (4, "About"))


class TestDashboards(TempDirTest):
    def test_terminal_and_html(self):
        run = offline_run(self.db)
        text = dashboard.render_terminal(run)
        for part in ("INSIGHTS", "DATA QUALITY", "FIELDS", "TOP 5 BY PRICE", "PROBLEMS"):
            self.assertIn(part, text)
        page = dashboard.render_html(run)
        self.assertEqual(page.count("<details class=\"tv\">"), 3)            # every chart has a table view
        self.assertIn('rel="noopener noreferrer nofollow"', page)
        self.assertIn("prefers-color-scheme:dark", page)

    def test_html_escapes_scraped_content(self):
        run = offline_run(self.db, "quotes")
        run.items[0]["text"] = '<script>alert("x")</script>'
        run.items[0]["author_url"] = "javascript:alert(1)"
        page = dashboard.render_html(run)
        self.assertNotIn('<script>alert', page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn('href="javascript:', page)

    def test_comparison_text(self):
        old, new = offline_run(self.db, version=1), offline_run(self.db, version=2)
        from scrapedash import analysis
        text = dashboard.render_comparison(old, new, analysis.compare(old, new))
        self.assertIn("3 new · 2 removed", text)
        self.assertIn("price:", text)


def run_cli(cli, inputs):
    out = io.StringIO()
    with patch("builtins.input", side_effect=inputs), redirect_stdout(out):
        cli.run()
    return out.getvalue()


class TestCLI(TempDirTest):
    def make_cli(self):
        settings = Settings()
        settings.offline = True
        settings.out_dir = self.dir / "dash"
        return ScraperCLI(self.db, settings)

    def test_scrape_change_compare_export_session(self):
        cli = self.make_cli()
        out = run_cli(cli, [
            "1", "1", "", "5", "n",                                   # books, default start, 5 pages, no HTML
            "10", "", "", "", "", "", "", "2", "n",                   # settings: offline sample version 2
            "1", "books", "", "", "y", "",                            # scrape again, save HTML (default name)
            "7", "", "",                                              # compare latest with previous
            "8", "",                                                  # history
            "9", "", "csv", str(self.dir / "export.csv"),             # export latest run
            "0"])
        self.assertIn("Saved as run #1: 59 item(s) from 3 page(s)", out)
        self.assertIn("Saved as run #2: 60 item(s) from 4 page(s)", out)
        self.assertIn("includes changes since run #1", out)
        self.assertIn("3 new · 2 removed", out)
        self.assertIn("Exported 60 item(s)", out)
        html = (self.dir / "dash" / "run_2_books.html").read_text(encoding="utf-8")
        self.assertIn("Changes since run #1", html)
        self.assertTrue((self.dir / "export.csv").exists())

    def test_tools_and_friendly_errors(self):
        out = run_cli(self.make_cli(), [
            "42",                                                     # invalid option
            "1", "amazon",                                            # unknown profile
            "3", "not a url",                                         # invalid address
            "3", "https://quotes.toscrape.com/",                      # page report (offline sample)
            "4", "https://quotes.toscrape.com/", "div.quote small.author",   # selector tester
            "4", "https://quotes.toscrape.com/", "div!",              # bad selector
            "5", "99",                                                # no runs yet
            "2", "missing.json",                                      # profile file not found
            "0"])
        self.assertIn("Invalid option", out)
        self.assertIn("Unknown profile 'amazon'", out)
        self.assertIn("cannot contain spaces", out)
        self.assertIn("PAGE REPORT", out)
        self.assertIn("matched 10 element(s)", out)
        self.assertIn("Unexpected '!' at position 4", out)
        self.assertIn("No runs saved yet", out)
        self.assertIn("Profile file not found", out)
