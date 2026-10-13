"""Input validation helpers.

Each function returns a cleaned value or raises ValidationError with a
message that can be shown directly to the user.
"""

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .exceptions import ValidationError
from .selectors import parse_selector

HOST_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")
FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,29}$")
MAX_URL_LENGTH = 2000


def validate_url(value, allowed_domains=None):
    """Return a normalised http(s) URL; optionally it must belong to one of `allowed_domains`."""
    text = str(value or "").strip()
    if not text:
        raise ValidationError("Web address cannot be empty.")
    if len(text) > MAX_URL_LENGTH:
        raise ValidationError(f"Web address is too long (max {MAX_URL_LENGTH} characters).")
    if any(c.isspace() for c in text):
        raise ValidationError("Web address cannot contain spaces.")
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", text):
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValidationError("Only http:// and https:// web addresses can be scraped.")
    if parts.username or parts.password:
        raise ValidationError("Remove the username/password from the web address.")
    host = (parts.hostname or "").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        if host != "localhost" and (len(labels) < 2 or not all(HOST_LABEL.match(l) for l in labels)
                                    or not re.fullmatch(r"[a-z]{2,63}", labels[-1])):
            raise ValidationError(f"'{value}' is not a valid web address (e.g. https://books.toscrape.com/).")
    try:
        parts.port
    except ValueError:
        raise ValidationError("The port number in the web address is not valid.") from None
    if allowed_domains and not in_domains(host, allowed_domains):
        raise ValidationError(f"{host} is outside this profile's allowed domains ({', '.join(allowed_domains)}).")
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))  # drop #fragment


def host_of(url):
    return (urlsplit(url).hostname or "").lower()


def in_domains(host, domains):
    """True if host is one of the domains or a subdomain of one."""
    host = host.lower()
    return any(host == d or host.endswith("." + d) for d in (d.lower().lstrip(".") for d in domains))


def validate_selector(value, field="Selector"):
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{field} cannot be empty.")
    parse_selector(text)  # raises SelectorError (a ValidationError) with the position of the problem
    return text


def validate_int(value, field, low, high):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a whole number.") from None
    if not low <= number <= high:
        raise ValidationError(f"{field} must be between {low} and {high}.")
    return number


def validate_float(value, field, low, high):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a number.") from None
    if number != number or not low <= number <= high:
        raise ValidationError(f"{field} must be between {low:g} and {high:g}.")
    return number


def validate_field_name(value):
    name = str(value or "").strip()
    if not FIELD_NAME.match(name):
        raise ValidationError(f"Field name '{value}' must start with a lowercase letter and use only "
                              "lowercase letters, digits and _ (max 30 characters).")
    return name


def validate_output_path(value, extensions):
    text = str(value or "").strip().strip('"')
    if not text:
        raise ValidationError("File name cannot be empty.")
    path = Path(text)
    if any(c in '<>:"|?*' for c in path.name):
        raise ValidationError(f"File name '{path.name}' contains characters that are not allowed.")
    if not path.suffix:
        path = path.with_suffix(extensions[0])
    if path.suffix.lower() not in extensions:
        raise ValidationError(f"File type must be one of: {', '.join(extensions)}.")
    return path
