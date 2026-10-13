"""Interactive menu-driven command-line interface.

All ScrapeError subclasses are caught here and shown as friendly messages;
unexpected errors are logged and the menu keeps running.
"""

import logging
from pathlib import Path

from . import analysis, dashboard, exporters, page_report, profiles
from . import validators as v
from .crawler import MAX_PAGES, crawl
from .exceptions import ScrapeError, ValidationError
from .fetcher import Fetcher
from .sample_site import build_sample_web

log = logging.getLogger("scrapedash")

MENU = """
==================== WEB SCRAPING DASHBOARD ====================
 SCRAPE                               ANALYSE
  1. Scrape with a built-in profile    5. View a run's dashboard
  2. Scrape with a profile file        6. Save an HTML dashboard
  3. Analyse a single web page         7. Compare two runs
  4. Test a CSS selector on a page     8. Run history
 DATA & SETTINGS
  9. Export a run (CSV / JSON)        10. Settings
  0. Exit
================================================================"""


def ask(prompt):
    return input(f"  {prompt}: ").strip()


def confirm(prompt, default=False):
    answer = ask(f"{prompt} [{'Y/n' if default else 'y/N'}]").lower()
    return default if not answer else answer in {"y", "yes"}


class Settings:
    def __init__(self):
        self.delay = 1.5          # seconds between requests to the same site (live mode)
        self.max_pages = 5
        self.timeout = 10.0
        self.use_cache = True
        self.cache_minutes = 60
        self.offline = False
        self.sample_version = 1   # offline sample site: 1 = original, 2 = some prices/stock changed
        self.out_dir = Path("dashboards")

    def summary(self):
        mode = f"OFFLINE sample site v{self.sample_version}" if self.offline else "LIVE"
        cache = f"cache {self.cache_minutes} min" if self.use_cache and not self.offline else "no cache"
        return f"{mode} · {self.delay:g}s delay · max {self.max_pages} pages · timeout {self.timeout:g}s · {cache}"


class ScraperCLI:
    def __init__(self, db, settings=None):
        self.db = db
        self.settings = settings or Settings()
        self._fetcher = None
        self.actions = {
            "1": self.scrape_builtin, "2": self.scrape_file, "3": self.analyse_page, "4": self.test_selector,
            "5": self.view_run, "6": self.save_dashboard, "7": self.compare_runs, "8": self.history,
            "9": self.export_run, "10": self.change_settings,
        }

    @property
    def mode(self):
        return "offline sample" if self.settings.offline else "live"

    def fetcher(self):
        """One fetcher per session, so robots.txt rules and rate limits carry over between scrapes."""
        if self._fetcher is None:
            s = self.settings
            if s.offline:
                self._fetcher = Fetcher(opener=build_sample_web(s.sample_version), delay=0, timeout=s.timeout)
            else:
                self._fetcher = Fetcher(delay=s.delay, timeout=s.timeout, cache=self.db if s.use_cache else None,
                                        cache_ttl=s.cache_minutes * 60)
        return self._fetcher

    def run(self):
        while True:
            print(MENU)
            print(f"  Settings: {self.settings.summary()}")
            choice = ask("Choose an option")
            if choice == "0":
                print("  Goodbye!")
                return
            action = self.actions.get(choice)
            if action is None:
                print("  ! Invalid option, please enter a number from the menu.")
                continue
            try:
                action()
            except ScrapeError as exc:
                log.warning("%s failed: %s", action.__name__, exc)
                print(f"  ! Error: {exc}")
            except (KeyboardInterrupt, EOFError):
                print("\n  Cancelled.")
            except Exception:  # safety net; the full traceback goes to the log file
                log.exception("Unexpected error in %s", action.__name__)
                print("  ! An unexpected error occurred. See scrapedash.log for details.")

    # ---------------------------------------------------------- scraping
    def scrape_builtin(self):
        names = list(profiles.BUILTIN)
        for i, name in enumerate(names, 1):
            print(f"   {i}. {name:8} {profiles.BUILTIN[name]['description']}")
        choice = ask(f"Profile [1-{len(names)} or name]")
        name = names[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(names) else choice
        self.scrape(profiles.builtin(name))

    def scrape_file(self):
        print("  A profile is a JSON file describing what to scrape; see sample_data/profiles/ for examples.")
        self.scrape(profiles.load_profile_file(ask("Profile file")))

    def scrape(self, profile, start_url=None, pages=None):
        s = self.settings
        start_url = start_url if start_url is not None else (ask(f"Start page [{profile.start_url}]") or None)
        pages = pages if pages is not None else v.validate_int(ask(f"Maximum pages [{s.max_pages}]") or s.max_pages,
                                                               "Maximum pages", 1, MAX_PAGES)
        if start_url:
            start_url = v.validate_url(start_url, profile.allowed_domains)
        print(f"\n  Scraping {profile.name} ({self.mode}) — robots.txt checked first"
              + ("" if s.offline else f", {s.delay:g}s between requests") + " …")

        def progress(page):
            cached = " (from cache)" if page.from_cache else ""
            print(f"   ✓ {page.url}  →  {page.items} item(s){cached}")

        result = crawl(profile, self.fetcher(), pages, start_url, on_page=progress)
        run_id = self.db.save_run(result, self.mode)
        log.info("Saved run #%d: %s, %d items", run_id, profile.name, len(result.items))
        for error in result.errors:
            print(f"   ✖ {error}")
        print(f"  Saved as run #{run_id}: {len(result.items)} item(s) from {len(result.pages)} page(s), "
              f"{result.status} ({result.stop_reason}).")
        if not result.items:
            return run_id
        run = self.db.get_run(run_id)
        print(dashboard.render_terminal(run))
        if confirm("Save an HTML dashboard for this run?", default=True):
            self._write_dashboard(run)
        return run_id

    def analyse_page(self):
        page = self.fetcher().get(ask("Web page address"))
        print(dashboard.render_page_report(page_report.analyse_page(page)))

    def test_selector(self):
        page = self.fetcher().get(ask("Web page address"))
        selector = v.validate_selector(ask("CSS selector (e.g. article.product_pod h3 > a)"))
        count, preview = page_report.test_selector(page, selector)
        print(f"  '{selector}' matched {count} element(s) on {page.url}")
        for i, m in enumerate(preview, 1):
            attrs = " ".join(f'{k}="{val}"' for k, val in m["attrs"].items())
            print(f"   {i}. <{m['tag']}{' ' + attrs if attrs else ''}>  {m['text'] or '(no text)'}")
        if count > len(preview):
            print(f"   … and {count - len(preview)} more")

    # ---------------------------------------------------------- runs
    def _pick_run(self, prompt="Run number"):
        runs = self.db.list_runs(5)
        if not runs:
            raise ValidationError("No runs saved yet. Scrape something first (option 1).")
        hint = ", ".join(f"#{r['id']} {r['profile']}" for r in runs)
        return self.db.get_run(ask(f"{prompt} [{runs[0]['id']}] (recent: {hint})") or runs[0]["id"])

    def view_run(self):
        print(dashboard.render_terminal(self._pick_run()))

    def _previous_run(self, run):
        earlier = [r for r in self.db.list_runs(50, run.profile.name) if r["id"] < run.id and r["items"]]
        return self.db.get_run(earlier[0]["id"]) if earlier else None

    def _write_dashboard(self, run, path=None):
        default = self.settings.out_dir / f"run_{run.id}_{run.profile.name}.html"
        path = v.validate_output_path(path or ask(f"File name [{default}]") or default, [".html", ".htm"])
        previous = self._previous_run(run) if run.profile.key else None
        diff = analysis.compare(previous, run) if previous else None
        dashboard.save_html(run, path, previous, diff)
        extra = f" (includes changes since run #{previous.id})" if previous else ""
        print(f"  Dashboard saved to {path}{extra} — open it in your web browser.")
        return path

    def save_dashboard(self):
        self._write_dashboard(self._pick_run())

    def compare_runs(self):
        new = self._pick_run("Newer run")
        old_default = self._previous_run(new)
        answer = ask(f"Older run to compare with [{old_default.id if old_default else '—'}]")
        if not answer and old_default is None:
            raise ValidationError(f"There is no earlier run of '{new.profile.name}' to compare with.")
        old = self.db.get_run(answer) if answer else old_default
        if old.profile.name != new.profile.name:
            raise ValidationError(f"Run #{old.id} used '{old.profile.name}' and run #{new.id} used "
                                  f"'{new.profile.name}'; only runs of the same profile can be compared.")
        if old.id == new.id:
            raise ValidationError("Choose two different runs.")
        try:
            diff = analysis.compare(old, new)
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
        print(dashboard.render_comparison(old, new, diff))

    def history(self):
        runs = self.db.list_runs(25)
        if not runs:
            print("  No runs saved yet.")
            return
        rows = [{"run": f"#{r['id']}", "profile": r["profile"], "mode": r["mode"], "started": r["started"].replace("T", " "),
                 "status": r["status"], "pages": r["pages"], "items": r["items"]} for r in runs]
        print(dashboard.format_table(rows, ["run", "profile", "mode", "started", "status", "pages", "items"],
                                     right={"pages", "items"}))
        answer = ask("Delete a run? (run number, or Enter to keep all)")
        if answer:
            run = self.db.get_run(answer)
            if confirm(f"Delete run #{run.id} ({run.profile.name}, {len(run.items)} items) permanently?"):
                print(f"  Deleted run #{self.db.delete_run(run.id)}.")

    def export_run(self):
        run = self._pick_run()
        fmt = (ask("Format csv/json [csv]") or "csv").lower().lstrip(".")
        if fmt not in ("csv", "json"):
            raise ValidationError("Format must be csv or json.")
        default = Path("exports") / f"run_{run.id}_{run.profile.name}.{fmt}"
        path = v.validate_output_path(ask(f"File name [{default}]") or default, [f".{fmt}"])
        (exporters.export_csv if fmt == "csv" else exporters.export_json)(run, path)
        print(f"  Exported {len(run.items)} item(s) to {path}.")

    # ---------------------------------------------------------- settings
    def change_settings(self):
        s = self.settings
        print("  Press Enter to keep the current value.")
        delay = ask(f"Seconds between requests, 1-10 [{s.delay:g}]")
        pages = ask(f"Default maximum pages, 1-{MAX_PAGES} [{s.max_pages}]")
        timeout = ask(f"Timeout in seconds, 3-60 [{s.timeout:g}]")
        cache = ask(f"Use the page cache? y/n [{'y' if s.use_cache else 'n'}]")
        minutes = ask(f"Keep cached pages for how many minutes, 1-1440 [{s.cache_minutes}]")
        offline = ask(f"Offline mode (built-in sample site)? y/n [{'y' if s.offline else 'n'}]")
        version = ask(f"Offline sample version 1/2 [{s.sample_version}]")
        new = {   # validate everything before changing anything
            "delay": v.validate_float(delay, "Delay", 1, 10) if delay else s.delay,
            "max_pages": v.validate_int(pages, "Maximum pages", 1, MAX_PAGES) if pages else s.max_pages,
            "timeout": v.validate_float(timeout, "Timeout", 3, 60) if timeout else s.timeout,
            "use_cache": cache.lower().startswith("y") if cache else s.use_cache,
            "cache_minutes": v.validate_int(minutes, "Cache minutes", 1, 1440) if minutes else s.cache_minutes,
            "offline": offline.lower().startswith("y") if offline else s.offline,
            "sample_version": v.validate_int(version, "Sample version", 1, 2) if version else s.sample_version,
        }
        for key, value in new.items():
            setattr(s, key, value)
        self._fetcher = None  # rebuilt with the new settings
        if confirm(f"Clear the page cache ({self.db.cache_size()} page(s))?"):
            print(f"  Removed {self.db.clear_cache()} cached page(s).")
        print(f"  Settings: {s.summary()}")
