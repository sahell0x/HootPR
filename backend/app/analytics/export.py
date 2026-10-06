"""CSV / JSON export rendering (spec §10.5 "Data export")."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

# Spreadsheet apps execute cells starting with these as formulas (CSV injection, OWASP).
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _plain(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, list | tuple):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    return v


def safe_cell(v: Any) -> str:
    """A CSV cell that no spreadsheet will evaluate as a formula."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float | Decimal) and not isinstance(v, bool):
        return str(v)  # numbers (incl. negative credit deltas) stay numeric
    plain = _plain(v)
    text = json.dumps(plain) if isinstance(plain, list | dict) else str(plain)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def to_csv(columns: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for row in rows:
        w.writerow([safe_cell(row.get(c)) for c in columns])
    return buf.getvalue()


def to_json(rows: Iterable[Mapping[str, Any]]) -> str:
    return json.dumps([_plain(dict(r)) for r in rows], ensure_ascii=False)
