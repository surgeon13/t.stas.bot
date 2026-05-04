"""Parse Travian map.sql into structured village rows.

The file is a sequence of MySQL INSERT statements, e.g.:

    INSERT INTO `x_world` VALUES (1,-100,100,3,1,'My City',5,'Player',2,'Alliance',500);
    INSERT INTO `x_world` VALUES (2,...),(3,...),(4,...);

Column count varies slightly across Travian versions. We parse each tuple
into a list of typed values and map the well-known columns by position,
keeping any extras in `extra`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterator

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VillageRow:
    village_id: int
    x: int
    y: int
    tribe_id: int
    vid: int                  # secondary village id (same as village_id on most servers)
    village_name: str
    player_id: int
    player_name: str
    alliance_id: int
    alliance_name: str
    population: int | None = None
    region: str | None = None
    extra: tuple = field(default_factory=tuple)


# Standard Travian x_world column order (positional).
_KNOWN_COLUMNS = (
    "village_id",
    "x",
    "y",
    "tribe_id",
    "vid",
    "village_name",
    "player_id",
    "player_name",
    "alliance_id",
    "alliance_name",
    "population",
    "region",
)


_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+`?x_world`?\s+VALUES\s*",
    re.IGNORECASE,
)


def _decode_text(content: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _iter_value_tuples(text: str) -> Iterator[str]:
    """Yield raw tuple bodies (text between matching parens) from VALUES lists.

    Handles quoted strings with backslash escapes and commas/parens inside them.
    """
    pos = 0
    n = len(text)
    while True:
        m = _INSERT_RE.search(text, pos)
        if not m:
            return
        i = m.end()
        # Walk through one or more (...)[, (...)]* until ';' is reached.
        while i < n:
            # Skip whitespace and commas between tuples.
            while i < n and text[i] in " \t\r\n,":
                i += 1
            if i >= n or text[i] == ";":
                break
            if text[i] != "(":
                break
            # Capture body inside this paren group.
            i += 1
            start = i
            in_string = False
            quote = ""
            while i < n:
                c = text[i]
                if in_string:
                    if c == "\\" and i + 1 < n:
                        i += 2
                        continue
                    if c == quote:
                        in_string = False
                    i += 1
                    continue
                if c == "'" or c == '"':
                    in_string = True
                    quote = c
                    i += 1
                    continue
                if c == ")":
                    yield text[start:i]
                    i += 1
                    break
                i += 1
            else:
                # Unterminated tuple — stop processing this insert.
                return
        pos = max(i, m.end() + 1)


def _split_values(body: str) -> list[str]:
    """Split a tuple body on commas while respecting quoted strings."""
    parts: list[str] = []
    cur: list[str] = []
    in_string = False
    quote = ""
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if in_string:
            cur.append(c)
            if c == "\\" and i + 1 < n:
                cur.append(body[i + 1])
                i += 2
                continue
            if c == quote:
                in_string = False
            i += 1
            continue
        if c == "'" or c == '"':
            in_string = True
            quote = c
            cur.append(c)
            i += 1
            continue
        if c == ",":
            parts.append("".join(cur).strip())
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    if cur:
        parts.append("".join(cur).strip())
    return parts


def _coerce(raw: str) -> int | float | str | None:
    s = raw.strip()
    if not s:
        return None
    if s.upper() == "NULL":
        return None
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        inner = s[1:-1]
        return (
            inner.replace("\\\\", "\\")
            .replace("\\'", "'")
            .replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
            .replace("\\0", "")
        )
    try:
        if "." in s or "e" in s or "E" in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def _row_from_values(values: list[object]) -> VillageRow | None:
    if len(values) < 10:
        return None

    def as_int(v: object, default: int = 0) -> int:
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return default
        return default

    def as_str(v: object) -> str:
        return "" if v is None else str(v)

    extras: tuple = ()
    pop_raw: object = None
    region_raw: object = None
    if len(values) >= 11:
        pop_raw = values[10]
    if len(values) >= 12:
        region_raw = values[11]
    if len(values) > 12:
        extras = tuple(values[12:])

    return VillageRow(
        village_id=as_int(values[0]),
        x=as_int(values[1]),
        y=as_int(values[2]),
        tribe_id=as_int(values[3]),
        vid=as_int(values[4]),
        village_name=as_str(values[5]),
        player_id=as_int(values[6]),
        player_name=as_str(values[7]),
        alliance_id=as_int(values[8]),
        alliance_name=as_str(values[9]),
        population=None if pop_raw is None else as_int(pop_raw),
        region=None if region_raw is None else as_str(region_raw),
        extra=extras,
    )


def parse_map_sql(content: bytes | str) -> list[VillageRow]:
    """Parse a map.sql file body into a list of VillageRow."""
    text = _decode_text(content) if isinstance(content, bytes) else content

    rows: list[VillageRow] = []
    skipped = 0
    for body in _iter_value_tuples(text):
        parts = _split_values(body)
        values = [_coerce(p) for p in parts]
        row = _row_from_values(values)
        if row is None:
            skipped += 1
            continue
        rows.append(row)

    if skipped:
        log.warning("Skipped %d malformed tuples", skipped)
    log.info("Parsed %d village rows", len(rows))
    return rows
