"""Polite page downloading.

Rules this fetcher always follows:
  * robots.txt is checked before any page of a site is fetched (and cannot be switched off);
    a Crawl-delay in robots.txt is honoured
  * requests to the same site are spaced out by at least `delay` seconds
  * it identifies itself with an honest User-Agent
  * temporary failures (network errors, HTTP 5xx, HTTP 429) are retried with back-off,
    honouring Retry-After; permanent errors (404, 403 ...) are not retried
  * only HTML is accepted, and pages larger than `max_bytes` are refused
"""

import http.client
import logging
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .exceptions import FetchError, RobotsDisallowedError
from .validators import validate_url

log = logging.getLogger("scrapedash")

USER_AGENT = "WebScrapingDashboard/1.0 (educational internship project; polite: robots.txt + rate limit)"
HTML_TYPES = ("text/html", "application/xhtml+xml")
REASONS = {400: "bad request", 401: "login required", 403: "access denied", 404: "page not found",
           410: "page removed", 429: "too many requests", 500: "server error", 502: "bad gateway",
           503: "service unavailable", 504: "gateway timeout"}
MAX_RETRY_WAIT = 60.0


class HTTPStatusError(FetchError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


@dataclass
class Page:
    url: str              # final URL (after redirects)
    status: int
    content_type: str
    text: str
    elapsed: float        # seconds
    size: int             # bytes
    from_cache: bool = False


def decode_body(body, content_type):
    """Use the charset from the Content-Type header, then <meta charset>, then UTF-8."""
    charset = None
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    if m:
        charset = m.group(1)
    else:
        m = re.search(rb"""<meta[^>]+charset=["']?([\w-]+)""", body[:4096], re.I)
        if m:
            charset = m.group(1).decode("ascii", "ignore")
    try:
        return body.decode(charset or "utf-8", errors="replace")
    except LookupError:  # unknown charset name
        return body.decode("utf-8", errors="replace")


class Fetcher:
    def __init__(self, user_agent=USER_AGENT, timeout=10.0, delay=1.5, retries=2, backoff=2.0,
                 max_bytes=3_000_000, cache=None, cache_ttl=3600, opener=None,
                 sleep=time.sleep, clock=time.monotonic):
        self.user_agent = user_agent
        self.timeout = timeout
        self.delay = delay
        self.retries = retries
        self.backoff = backoff
        self.max_bytes = max_bytes
        self.cache = cache
        self.cache_ttl = cache_ttl
        self._open = opener or urllib.request.urlopen   # injectable: tests and offline mode
        self._sleep = sleep
        self._clock = clock
        self._robots = {}        # "https://host" -> RobotFileParser
        self._crawl_delay = {}   # "https://host" -> seconds
        self._last_request = {}  # host -> clock value
        self.requests_made = 0

    # ------------------------------------------------------------ public
    def get(self, url):
        """Fetch an HTML page (from the cache if fresh), after the robots.txt check."""
        url = validate_url(url)
        if self.cache is not None:
            cached = self.cache.get_page(url, self.cache_ttl)
            if cached is not None:
                return cached
        self.check_robots(url)
        page = self._download(url, html_only=True)
        if self.cache is not None:
            self.cache.put_page(url, page)
        return page

    def check_robots(self, url):
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        rules = self._robots.get(base) or self._load_robots(base)
        if not rules.can_fetch(self.user_agent, url):
            raise RobotsDisallowedError(f"{parts.netloc}'s robots.txt does not allow scraping "
                                        f"{parts.path or '/'} — this page was skipped.")

    # ------------------------------------------------------------ internals
    def _load_robots(self, base):
        rules = RobotFileParser(base + "/robots.txt")
        try:
            page = self._download(base + "/robots.txt", html_only=False)
            rules.parse(page.text.splitlines())
        except HTTPStatusError as exc:
            if exc.status in (401, 403):
                rules.disallow_all = True          # the site blocks robots completely
            elif 400 <= exc.status < 500:
                rules.allow_all = True             # no robots.txt: everything allowed (the standard's rule)
            else:
                raise FetchError(f"Could not read {base}/robots.txt (HTTP {exc.status}); "
                                 "not scraping until it can be checked. Try again later.") from exc
        delay = rules.crawl_delay(self.user_agent)
        self._crawl_delay[base] = float(delay) if delay else 0.0
        self._robots[base] = rules
        log.info("robots.txt for %s loaded (crawl-delay %s)", base, delay)
        return rules

    def _throttle(self, url):
        parts = urlsplit(url)
        host = parts.netloc
        wait_between = max(self.delay, self._crawl_delay.get(f"{parts.scheme}://{host}", 0.0))
        last = self._last_request.get(host)
        if last is not None:
            remaining = wait_between - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[host] = self._clock()

    def _retry_wait(self, attempt, headers=None):
        retry_after = headers.get("Retry-After") if headers is not None else None
        if retry_after and str(retry_after).strip().isdigit():
            return min(float(retry_after), MAX_RETRY_WAIT)
        return min(self.backoff * (2 ** attempt), MAX_RETRY_WAIT)

    def _download(self, url, html_only):
        host = urlsplit(url).netloc
        last_problem = "unknown error"
        for attempt in range(self.retries + 1):
            self._throttle(url)
            request = urllib.request.Request(url, headers={
                "User-Agent": self.user_agent, "Accept-Language": "en",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"})
            started = self._clock()
            try:
                with self._open(request, timeout=self.timeout) as response:
                    self.requests_made += 1
                    content_type = response.headers.get("Content-Type", "") or ""
                    if html_only and content_type.split(";")[0].strip().lower() not in HTML_TYPES:
                        raise FetchError(f"{url} is not a web page (Content-Type: {content_type or 'unknown'}).")
                    body = response.read(self.max_bytes + 1)
                    if len(body) > self.max_bytes:
                        raise FetchError(f"{url} is larger than {self.max_bytes // 1_000_000} MB; skipped.")
                    final_url = response.geturl() or url
                    status = getattr(response, "status", 200) or 200
                text = decode_body(body, content_type)
                return Page(final_url, status, content_type, text, self._clock() - started, len(body))
            except urllib.error.HTTPError as exc:
                self.requests_made += 1
                reason = REASONS.get(exc.code, "HTTP error")
                if (exc.code == 429 or exc.code >= 500) and attempt < self.retries:
                    wait = self._retry_wait(attempt, exc.headers)
                    log.warning("HTTP %s from %s, retrying in %.0fs", exc.code, host, wait)
                    self._sleep(wait)
                    continue
                raise HTTPStatusError(exc.code, f"{url} returned HTTP {exc.code} ({reason}).") from None
            except (urllib.error.URLError, http.client.HTTPException, socket.timeout, TimeoutError,
                    ConnectionError) as exc:
                last_problem = str(getattr(exc, "reason", exc)) or exc.__class__.__name__
                if attempt < self.retries:
                    wait = self._retry_wait(attempt)
                    log.warning("Network problem with %s (%s), retrying in %.0fs", host, last_problem, wait)
                    self._sleep(wait)
                    continue
        raise FetchError(f"Could not download {url}: {last_problem}. Check the internet connection, "
                         "or switch on offline mode to use the built-in sample site.")
