"""Exporting a run's items to CSV (for Excel) or JSON."""

import csv
import json
from decimal import Decimal
from pathlib import Path

from .exceptions import StorageError


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _safe_cell(text):
    """Stop spreadsheet formula injection: a scraped value like '=HYPERLINK(...)' must stay plain text."""
    return "'" + text if text[:1] in ("=", "+", "-", "@") and not _is_number(text) else text


def _is_number(text):
    try:
        Decimal(text)
        return True
    except ArithmeticError:
        return False
    except ValueError:
        return False


def export_csv(run, path, overwrite=False):
    path = Path(path)
    if path.exists() and not overwrite:
        raise StorageError(f"{path} already exists. Choose another name.")
    columns = list(run.profile.fields)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:   # BOM so Excel shows £ and ₹ correctly
            writer = csv.writer(fh)
            writer.writerow(columns)
            for item in run.items:
                writer.writerow([_safe_cell(_cell(item.get(c))) for c in columns])
    except OSError as exc:
        raise StorageError(f"Could not write {path}: {exc.strerror or exc}") from exc
    return path


def export_json(run, path, overwrite=False):
    path = Path(path)
    if path.exists() and not overwrite:
        raise StorageError(f"{path} already exists. Choose another name.")
    document = {
        "run": {"id": run.id, "profile": run.profile.name, "start_url": run.start_url, "mode": run.mode,
                "started": run.started, "finished": run.finished, "status": run.status,
                "pages": len(run.pages), "items": len(run.items), "units": run.units},
        "items": run.items,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2,
                                   default=lambda v: str(v) if isinstance(v, Decimal) else repr(v)), encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"Could not write {path}: {exc.strerror or exc}") from exc
    return path
