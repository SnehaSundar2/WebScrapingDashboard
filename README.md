# Web Scraping Dashboard

A **polite web scraper with a built-in analytics dashboard**, written in pure Python. It
downloads web pages responsibly, parses the HTML with its own document tree and CSS-selector
engine, and extracts and cleans structured data using *scraper profiles*. Every run is stored in
SQLite, and the results become statistics, data-quality checks, run-to-run change reports and
dashboards, both in the terminal and as a self-contained HTML page.

Developed by **Sneha S** as a virtual internship project (Python Development, Skyrovix IT
Solutions) to demonstrate **Python modules, input validation, data processing and error
handling**. Only the Python standard library is used, so there is nothing to install.

---

## 1. Features

| Area | What it does |
|---|---|
| **Polite fetching** | Checks `robots.txt` first (always on) and honours `Crawl-delay`; waits between requests to the same site; honest User-Agent; retries temporary errors with back-off and `Retry-After`; HTML only; 3 MB page limit |
| **HTML parsing** | Forgiving document tree (repairs unclosed `<p>`/`<li>`, stray end tags, void elements) and a CSS-selector engine: tags, `#id`, `.class`, attributes (`=`, `~=`, `^=`, `$=`, `*=`), descendant, child (`>`), groups, `:first-child`, `:last-child`, `:nth-child(n)` |
| **Scraper profiles** | What to scrape, described as JSON: item selector, fields (selector + attribute + type), next-page link, allowed domains. Built-in: `books`, `quotes`; write your own |
| **Data cleaning** | Types: text, category, number, money (`£51.77` → 51.77), count (`22 available` → 22), rating (`star-rating Three` → 3), yes/no, absolute URL, list (tags) |
| **Crawling** | Follows "next page" within the allowed domains, page limit, loop protection, duplicate removal, keeps partial results when a later page fails |
| **Storage** | SQLite: every run, its items, pages and warnings; page cache to avoid re-downloading |
| **Analysis** | Statistics (min, max, mean, median, standard deviation), histograms with rounded bin edges, rating distributions, top values, word frequency, averages by group, data quality, insights in plain English |
| **Compare runs** | New, removed and changed items between two runs, e.g. price changes |
| **Dashboards** | Terminal dashboard, and an HTML dashboard with charts, tooltips, table views and dark mode |
| **Page analyser** | Any page: title, description, headings, word count, frequent words, links, images without alt text, issues, score |
| **Selector tester** | Try a CSS selector on a live page before writing a profile |
| **Export** | CSV (Excel-friendly, protected against formula injection) and JSON |
| **Offline mode** | A built-in sample bookshop and quotes site, so everything works without internet |

### Responsible scraping

- The built-in profiles target **books.toscrape.com** and **quotes.toscrape.com**, sandbox sites
  created specifically for scraping practice.
- `robots.txt` is always checked and cannot be switched off. Pages it disallows are skipped and
  reported.
- Requests to one site are spaced out: 1.5 s by default, and never less than 1 s in live mode.
  A longer `Crawl-delay` set by the site wins.
- The scraper identifies itself honestly, follows only links inside the profile's domains, and
  stops at a page limit.
- Before scraping any other site, read its terms of use, and **never collect personal data**.

---

## 2. Architecture

```
  main.py / cli.py ─► crawler.crawl(profile)
                          │
                          ├─► fetcher.Fetcher.get(url) ── robots.txt ─ rate limit ─ retries ─ cache (storage)
                          │        └─ urllib  (or sample_site.FakeWeb in offline mode and tests)
                          ├─► dom.parse_html(text) ─► Node tree ─► selectors.select(css)
                          ├─► extract.extract_items(dom, profile) ─► cleaned items + warnings
                          └─► next-page link ─► loop / domain / limit checks
                          ▼
                   storage.Database.save_run()  (SQLite)
                          ▼
         analysis (stats · histogram · quality · compare · insights)
                          ▼
         dashboard (terminal · HTML)   exporters (CSV · JSON)
```

| Module | Responsibility |
|---|---|
| `exceptions.py` | `ScrapeError` → `ValidationError` (`SelectorError`), `FetchError` (`RobotsDisallowedError`), `StorageError` |
| `validators.py` | URLs (http/https, real host, no credentials, allowed domains), numbers, selectors, field names, file names |
| `fetcher.py` | Polite downloading: robots.txt, rate limiting, retries, charset detection, size and type limits |
| `dom.py` | HTML → forgiving document tree |
| `selectors.py` | CSS selector parser and matcher |
| `profiles.py` | Profile format, validation, built-in profiles |
| `extract.py` | Field extraction and type conversion |
| `crawler.py` | Pagination, limits, loop and domain protection, duplicates |
| `storage.py` | SQLite runs, items, messages, pages and page cache |
| `analysis.py` | Statistics, histograms, quality, comparison, insights |
| `page_report.py` | Single-page analysis and the selector tester |
| `dashboard.py` | Terminal views and the HTML dashboard |
| `exporters.py` | CSV / JSON export |
| `sample_site.py` | Offline sample site and the in-memory `FakeWeb` used by tests |
| `cli.py` | Interactive menu |

---

## 3. How to run

Requires **Python 3.8 or newer**.

```bash
cd WebScrapingDashboard
python main.py --demo                       # offline demo: 2 runs, a comparison and 2 HTML dashboards
python main.py                              # interactive menu (live)
python main.py --offline                    # interactive menu using the sample site
python main.py --profile books --pages 3 --html dashboards/books.html --csv exports/books.csv
python main.py --profile-file sample_data/profiles/books_travel.json
python main.py --analyze https://quotes.toscrape.com/
```

| Option | Purpose |
|---|---|
| `--profile NAME` / `--profile-file JSON` | Scrape with a built-in or custom profile, then exit |
| `--start-url URL` | Start somewhere else, e.g. a category page (must be inside the profile's domains) |
| `--pages N` | Maximum pages, 1–50 (default 5) |
| `--delay S` | Seconds between requests, 1–10 (default 1.5) |
| `--html`, `--csv`, `--json` | Save a dashboard / export the items |
| `--analyze URL` | Page report for one page |
| `--offline` | Use the built-in sample site |
| `--db FILE` | Database file (default `data/scraper.db`) |

### Typical menu session

1. **1. Scrape with a built-in profile:** choose `books`, press Enter for the start page, and
   choose 5 pages. Progress shows each page as it is fetched.
2. The terminal dashboard appears; answer **Y** to save the HTML dashboard and open it in a
   browser.
3. Later, scrape again and use **7. Compare two runs** to see what changed. In offline mode, set
   *sample version* to 2 in **10. Settings** to simulate a changed website.
4. **3. Analyse a single web page** and **4. Test a CSS selector** help when writing your own
   profile.
5. **9. Export** to CSV or JSON. **8. Run history** lists and deletes runs.

### Writing a profile

```json
{
  "name": "books-travel",
  "start_url": "https://books.toscrape.com/catalogue/category/books/travel_2/index.html",
  "allowed_domains": ["books.toscrape.com"],
  "item": "article.product_pod",
  "next_page": "li.next > a",
  "key": "url", "label": "title",
  "fields": {
    "title":  {"select": "h3 > a", "attr": "title", "type": "text", "required": true},
    "price":  {"select": "p.price_color", "type": "money", "required": true},
    "rating": {"select": "p.star-rating", "attr": "class", "type": "rating"},
    "url":    {"select": "h3 > a", "attr": "href", "type": "url", "required": true}
  }
}
```

`sample_data/profiles/broken_profile_example.json` is deliberately invalid, so you can see the
validation messages.

---

## 4. Key concepts demonstrated

**Python modules.** Fifteen focused modules. The fetcher, parser, extractor, storage and analysis
know nothing about each other's internals. The fetcher's network function can be swapped, so
offline mode and the tests use the same code path as live scraping.

**Input validation.**
- **URLs:** only http/https, a real host name, no embedded passwords, and only inside the
  profile's allowed domains.
- **CSS selectors:** parsed and rejected with the exact position of the problem, e.g.
  "Unexpected '!' at position 4".
- **Profiles:** every setting is checked before any request is made, including field names,
  types, selectors, the domain of the start URL, and that the key field is required.
- **Numbers and files:** delays, page limits, timeouts and output file names all have ranges or
  rules.

**Data processing.**
- An HTML tree builder and a right-to-left CSS selector matcher, written from scratch.
- Type conversion and cleaning (money, ratings, counts).
- Statistics, histograms with "nice" bin edges, frequency analysis and averages by group.
- Data-quality scoring, and comparing two runs item by item using the key field.

**Error handling.**
- Temporary errors (network, HTTP 5xx, HTTP 429) are retried with back-off. Permanent errors
  (HTTP 404, 403) are reported immediately.
- A broken field doesn't stop the page, and a broken page doesn't stop the run: partial results
  are kept with clear warnings.
- Pages blocked by robots.txt, redirects to other sites and pagination loops are all detected.
- A damaged database gives a clear message, and the file is released.
- SQL is always parameterised, scraped text is HTML-escaped in dashboards, only http(s) links
  become clickable, and CSV cells that look like spreadsheet formulas are neutralised.

---

## 5. Testing

```bash
cd WebScrapingDashboard
python -m unittest discover -s tests -t . -v
```

Result: **43 tests, all passing**. They need no internet. The in-memory `FakeWeb` serves pages,
simulates HTTP errors, redirects and `Retry-After`, and records every request. A fake clock lets
the rate-limit and retry tests run instantly.

| Test file | Tests | Covers |
|---|---|---|
| `test_dom_selectors.py` | 7 | Repairing messy HTML, entities, hidden script text, every selector feature, invalid selectors with positions |
| `test_fetcher.py` | 11 | URL rules, robots.txt (missing, disallow, 403, 500), Crawl-delay, per-site rate limit, User-Agent, retries with back-off and Retry-After, no retry on 404, network failure, non-HTML and oversized pages, charsets, cache |
| `test_profiles_crawler.py` | 10 | Built-in and example profiles, 9 kinds of invalid profile, JSON errors with line numbers, converters, extraction warnings, full crawls, page limit, loops, foreign links, duplicates, partial failure, empty pages, robots-blocked page, foreign redirect |
| `test_storage_analysis.py` | 8 | Exact types after storage, history and delete, cache expiry, damaged database, statistics, histograms, quality, insights, averages by group, comparing runs |
| `test_outputs_cli.py` | 7 | CSV/JSON export and formula-injection guard, page report issues, selector tester, terminal and HTML dashboards, HTML escaping and blocked `javascript:` links, full menu sessions including compare and export, friendly errors |

**Live verification.** During development the real practice sites were scraped successfully:
- books.toscrape.com: 2 pages, 40 books, then the Travel category with 11 books.
- quotes.toscrape.com: 2 pages, 20 quotes.
- A page report of the quotes home page.

These runs made one robots.txt request per site, and each request waited the polite delay.
