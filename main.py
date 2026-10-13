"""Entry point for the Web Scraping Dashboard.

Usage:
    python main.py                                    # interactive menu
    python main.py --profile books --pages 3 --html dashboards/books.html
    python main.py --profile-file sample_data/profiles/books_travel.json --csv exports/travel.csv
    python main.py --analyze https://quotes.toscrape.com/
    python main.py --demo                             # offline demo: no internet needed
"""

import argparse
import logging
import sys
from pathlib import Path

from scrapedash import analysis, dashboard, exporters, page_report, profiles
from scrapedash import validators as v
from scrapedash.crawler import MAX_PAGES, crawl
from scrapedash.exceptions import ScrapeError
from scrapedash.fetcher import Fetcher
from scrapedash.sample_site import build_sample_web
from scrapedash.storage import Database
from scrapedash.cli import ScraperCLI, Settings


def run_demo(db):
    """Scrape the offline sample site twice (it 'changes' in between) and build dashboards."""
    paths = []
    for version in (1, 2):
        result = crawl(profiles.builtin("books"), Fetcher(opener=build_sample_web(version), delay=0), MAX_PAGES)
        books_id = db.save_run(result, "offline sample")
        print(f"Sample bookshop v{version}: {len(result.items)} items from {len(result.pages)} pages (run #{books_id})")
    quotes = crawl(profiles.builtin("quotes"), Fetcher(opener=build_sample_web(), delay=0), MAX_PAGES)
    quotes_id = db.save_run(quotes, "offline sample")
    print(f"Sample quotes: {len(quotes.items)} items (run #{quotes_id})")
    new, old = db.get_run(books_id), db.get_run(books_id - 1)
    diff = analysis.compare(old, new)
    print(dashboard.render_comparison(old, new, diff))
    paths.append(dashboard.save_html(new, Path("dashboards") / f"demo_books_run_{new.id}.html", old, diff))
    paths.append(dashboard.save_html(db.get_run(quotes_id), Path("dashboards") / f"demo_quotes_run_{quotes_id}.html"))
    for p in paths:
        print(f"Dashboard saved: {p}")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):  # show £, ₹, █ and ✓ correctly on Windows consoles
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Web Scraping Dashboard — polite scraping with analysis")
    parser.add_argument("--profile", help=f"built-in profile: {', '.join(profiles.BUILTIN)}")
    parser.add_argument("--profile-file", metavar="JSON", help="custom profile file")
    parser.add_argument("--start-url", help="start page (must be inside the profile's domains)")
    parser.add_argument("--pages", default="5", help=f"maximum pages, 1-{MAX_PAGES} (default 5)")
    parser.add_argument("--delay", default="1.5", help="seconds between requests, 1-10 (default 1.5)")
    parser.add_argument("--html", metavar="PATH", help="save an HTML dashboard of the run")
    parser.add_argument("--csv", metavar="PATH", help="export the items as CSV")
    parser.add_argument("--json", metavar="PATH", help="export the items as JSON")
    parser.add_argument("--analyze", metavar="URL", help="analyse a single web page and exit")
    parser.add_argument("--offline", action="store_true", help="use the built-in sample site (no internet)")
    parser.add_argument("--demo", action="store_true", help="offline demo: two runs, a comparison and dashboards")
    parser.add_argument("--db", default="data/scraper.db", help="database file (default data/scraper.db)")
    args = parser.parse_args(argv)

    logging.basicConfig(filename="scrapedash.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        db = Database(args.db)
        if args.demo:
            run_demo(db)
            return 0
        delay = v.validate_float(args.delay, "Delay", 1, 10)
        fetcher = (Fetcher(opener=build_sample_web(), delay=0) if args.offline
                   else Fetcher(delay=delay, cache=db))
        if args.analyze:
            print(dashboard.render_page_report(page_report.analyse_page(fetcher.get(args.analyze))))
            return 0
        if args.profile or args.profile_file:
            profile = profiles.load_profile_file(args.profile_file) if args.profile_file else profiles.builtin(args.profile)
            pages = v.validate_int(args.pages, "Pages", 1, MAX_PAGES)
            result = crawl(profile, fetcher, pages, args.start_url,
                           on_page=lambda p: print(f"  ✓ {p.url} → {p.items} item(s)"))
            run_id = db.save_run(result, "offline sample" if args.offline else "live")
            run = db.get_run(run_id)
            print(dashboard.render_terminal(run))
            if args.html:
                path = v.validate_output_path(args.html, [".html", ".htm"])
                earlier = [r for r in db.list_runs(50, profile.name) if r["id"] < run_id and r["items"]]
                previous = db.get_run(earlier[0]["id"]) if earlier and profile.key else None
                dashboard.save_html(run, path, previous, analysis.compare(previous, run) if previous else None)
                print(f"Dashboard saved to {path}")
            if args.csv:
                print(f"CSV saved to {exporters.export_csv(run, v.validate_output_path(args.csv, ['.csv']))}")
            if args.json:
                print(f"JSON saved to {exporters.export_json(run, v.validate_output_path(args.json, ['.json']))}")
            return 0 if run.items else 1
        settings = Settings()
        settings.offline = args.offline
        settings.delay = delay
        ScraperCLI(db, settings).run()
        return 0
    except ScrapeError as exc:
        print(f"Error: {exc}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
