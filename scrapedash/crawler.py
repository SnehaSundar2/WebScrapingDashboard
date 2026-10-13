"""Crawling: fetch the start page, extract items, follow "next page" links.

Safety limits: a maximum number of pages, only URLs inside the profile's
allowed domains, no page visited twice (loop protection). If a later page
fails, the items already collected are kept and the reason is reported.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin

from . import validators as v
from .dom import parse_html
from .exceptions import FetchError, RobotsDisallowedError, ValidationError
from .extract import extract_items

log = logging.getLogger("scrapedash")
MAX_PAGES = 50


@dataclass
class PageInfo:
    url: str
    status: int
    items: int
    from_cache: bool
    elapsed: float


@dataclass
class CrawlResult:
    profile: object
    start_url: str
    started: str
    finished: str = ""
    duration: float = 0.0
    pages: list = field(default_factory=list)
    items: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    duplicates: int = 0
    units: dict = field(default_factory=dict)
    stop_reason: str = ""

    @property
    def status(self):
        if not self.items:
            return "failed"
        return "partial" if self.errors else "complete"


def crawl(profile, fetcher, max_pages=5, start_url=None, on_page=None, clock=time.monotonic):
    """Scrape up to `max_pages` pages. `on_page(PageInfo)` is called after each page (for progress)."""
    max_pages = v.validate_int(max_pages, "Number of pages", 1, MAX_PAGES)
    url = v.validate_url(start_url or profile.start_url, profile.allowed_domains)
    result = CrawlResult(profile, url, datetime.now().isoformat(timespec="seconds"))
    began = clock()
    visited, seen_keys = set(), set()

    while url:
        if len(result.pages) >= max_pages:
            result.stop_reason = f"page limit reached ({max_pages})"
            break
        if url in visited:
            result.stop_reason = "the next-page link pointed back to a page already visited"
            result.warnings.append(f"Loop detected at {url}; stopped.")
            break
        visited.add(url)
        page_no = len(result.pages) + 1
        try:
            page = fetcher.get(url)
        except RobotsDisallowedError as exc:
            result.errors.append(str(exc))
            result.stop_reason = "robots.txt disallowed the next page"
            break
        except FetchError as exc:
            result.errors.append(f"Page {page_no}: {exc}")
            result.stop_reason = "a page could not be downloaded"
            break
        if not v.in_domains(v.host_of(page.url), profile.allowed_domains):
            result.errors.append(f"Page {page_no} redirected outside the allowed domains ({page.url}); ignored.")
            result.stop_reason = "redirected to another site"
            break

        dom = parse_html(page.text)
        items, warnings, units = extract_items(dom, profile, page.url, f"Page {page_no}")
        result.warnings.extend(warnings)
        for key, symbol in units.items():
            result.units.setdefault(key, symbol)
        for item in items:
            key = item.get(profile.key) if profile.key else None
            if key is not None and key in seen_keys:
                result.duplicates += 1
                continue
            if key is not None:
                seen_keys.add(key)
            result.items.append(item)
        info = PageInfo(page.url, page.status, len(items), page.from_cache, page.elapsed)
        result.pages.append(info)
        log.info("Scraped %s: %d items", page.url, len(items))
        if on_page:
            on_page(info)
        if not items and page_no == 1:
            result.errors.append(f"No items matched the selector '{profile.item}' on the first page. "
                                 "The site's layout may have changed, or the profile is wrong.")
            result.stop_reason = "no items found"
            break

        url = None
        if profile.next_page:
            link = dom.select_one(profile.next_page)
            href = link.get("href") if link is not None else None
            if href:
                candidate = urljoin(page.url, href)
                try:
                    url = v.validate_url(candidate, profile.allowed_domains)
                except ValidationError:
                    result.warnings.append(f"Next-page link {candidate} is outside the allowed domains; not followed.")
                    result.stop_reason = "next page is on another site"
        if url is None and not result.stop_reason:
            result.stop_reason = "last page reached"

    result.finished = datetime.now().isoformat(timespec="seconds")
    result.duration = round(clock() - began, 2)
    return result
