"""Shared fixtures: a fake clock, fetchers on the in-memory web, temporary databases."""

import tempfile
import unittest
from pathlib import Path

from scrapedash.fetcher import Fetcher
from scrapedash.sample_site import FakeWeb, build_sample_web
from scrapedash.storage import Database


class FakeClock:
    """clock() and sleep() that never really wait; every sleep is recorded."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


def make_fetcher(web=None, delay=1.5, **kwargs):
    clock = FakeClock()
    fetcher = Fetcher(opener=web if web is not None else build_sample_web(), delay=delay, sleep=clock.sleep,
                      clock=clock.clock, **kwargs)
    return fetcher, clock


def page_html(body, title="Test page", head=""):
    return f"<!doctype html><html lang='en'><head><title>{title}</title>{head}</head><body>{body}</body></html>"


class TempDirTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = Database(self.dir / "test.db")
        self.addCleanup(self.db.close)


__all__ = ["FakeClock", "FakeWeb", "make_fetcher", "page_html", "TempDirTest", "build_sample_web"]
