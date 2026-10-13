"""Web Scraping Dashboard.

A polite, modular web scraper with a dashboard: it fetches pages (respecting
robots.txt and rate limits), parses HTML with a small DOM and CSS-selector
engine built on the standard library, extracts and cleans structured data
using scraper profiles, stores every run in SQLite, and turns the results into
statistics, data-quality checks, change reports and HTML/terminal dashboards.
"""

import logging

__version__ = "1.0.0"

# Stay silent unless the application (main.py) configures logging.
logging.getLogger("scrapedash").addHandler(logging.NullHandler())
