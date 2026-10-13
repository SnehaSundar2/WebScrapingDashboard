"""Custom exception hierarchy.

Every deliberate error derives from ScrapeError so the CLI can catch a single
base class and show a friendly message instead of a traceback.
"""


class ScrapeError(Exception):
    """Base class for all scraper errors."""


class ValidationError(ScrapeError):
    """User input or a scraper profile is invalid."""


class SelectorError(ValidationError):
    """A CSS selector could not be parsed."""


class FetchError(ScrapeError):
    """A page could not be downloaded (network problem, HTTP error, not HTML ...)."""


class RobotsDisallowedError(FetchError):
    """The site's robots.txt does not allow this page to be fetched."""


class StorageError(ScrapeError):
    """The database or an export file cannot be read or written."""
