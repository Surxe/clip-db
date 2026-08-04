"""Query expression parser: 'clutch AND valorant', 'game:apex', 'tag:funny'.

A bare term matches either a tag or the game. Prefixes narrow it: game:, date:, tag:.
AND/OR are combined left-to-right (no parentheses yet).
"""
from __future__ import annotations

import re
import sqlite3

from .index import _row_to_clip
from .tags import normalize

_SPLIT = re.compile(r"\s+(AND|OR)\s+", re.IGNORECASE)


def _term_sql(term: str) -> tuple[str, list]:
    term = term.strip()
    if ":" in term:
        field, _, val = term.partition(":")
        field = field.strip().lower()
        val = normalize(val)
        if field == "tag":
            return ("(',' || tags || ',') LIKE ?", [f"%,{val},%"])
        if field in ("game", "date"):
            return (f"LOWER({field}) = ?", [val])
    # bare term: match a tag OR the game
    t = normalize(term)
    return ("((',' || tags || ',') LIKE ? OR LOWER(game) = ?)", [f"%,{t},%", t])


def build_where(expr: str) -> tuple[str, list]:
    expr = (expr or "").strip()
    if not expr:
        return ("1=1", [])
    parts = _SPLIT.split(expr)
    sql, params = _term_sql(parts[0])
    i = 1
    while i < len(parts):
        op = parts[i].upper()
        clause, clause_params = _term_sql(parts[i + 1])
        sql += f" {op} {clause}"
        params += clause_params
        i += 2
    return (sql, params)


def query(conn: sqlite3.Connection, expr: str):
    where, params = build_where(expr)
    rows = conn.execute(f"SELECT * FROM clips WHERE {where} ORDER BY stem", params).fetchall()
    return [_row_to_clip(r) for r in rows]
