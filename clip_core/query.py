"""Query expression parser: 'clutch AND valorant', 'game:apex', 'tag:funny'.

A bare term matches either a tag or the game. Prefixes narrow it: game:, date:, tag:.
Tags may contain spaces (e.g. `movement tech`, `fuel thief`): write them bare
(`movement tech`) or quoted (`tag:"movement tech"`) — both work, and quoting also
protects a literal AND/OR inside a phrase. AND/OR combine terms left-to-right
(no parentheses yet).
"""
from __future__ import annotations

import re
import sqlite3

from .index import _row_to_clip
from .tags import normalize

# A piece is a run of non-space/non-quote chars and/or whole quoted spans, so a
# quoted phrase keeps its internal spaces (`tag:"movement tech"` is one piece)
# while unquoted spaces separate pieces. Pieces are then regrouped into terms
# around the AND/OR operators.
_PIECE = re.compile(r"""(?:[^\s"']|"[^"]*"|'[^']*')+""")
_OPS = {"AND", "OR"}


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _bare_sql(t: str) -> tuple[str, list]:
    # bare term: match a tag OR the game
    return ("((',' || tags || ',') LIKE ? OR LOWER(game) = ?)", [f"%,{t},%", t])


def _term_sql(term: str) -> tuple[str, list]:
    term = term.strip()
    # A fully-quoted term is a bare phrase; the quotes protect any ':' inside it.
    if len(term) >= 2 and term[0] == term[-1] and term[0] in "\"'":
        return _bare_sql(normalize(term[1:-1]))
    if ":" in term:
        field, _, val = term.partition(":")
        field = field.strip().lower()
        val = normalize(_unquote(val))
        if field == "tag":
            return ("(',' || tags || ',') LIKE ?", [f"%,{val},%"])
        if field in ("game", "date"):
            return (f"LOWER({field}) = ?", [val])
    return _bare_sql(normalize(_unquote(term)))


def _split_terms(expr: str) -> tuple[list[str], list[str]]:
    """Split into terms and the AND/OR operators between them (quote-aware).

    Consecutive non-operator pieces join with a single space, so a bare
    multi-word tag stays one term. Empty terms (stray/leading/trailing ops) are
    dropped along with the operator that would have joined them.
    """
    terms: list[str] = []
    ops: list[str] = []
    cur: list[str] = []
    pending_op: str | None = None

    def flush() -> None:
        nonlocal cur
        term = " ".join(cur).strip()
        cur = []
        if not term:
            return
        terms.append(term)
        if pending_op is not None and len(terms) >= 2:
            ops.append(pending_op)

    for piece in _PIECE.findall(expr):
        if piece.upper() in _OPS:
            flush()
            pending_op = piece.upper()
        else:
            cur.append(piece)
    flush()
    return terms, ops


def build_where(expr: str) -> tuple[str, list]:
    expr = (expr or "").strip()
    if not expr:
        return ("1=1", [])
    terms, ops = _split_terms(expr)
    if not terms:
        return ("1=1", [])
    sql, params = _term_sql(terms[0])
    for op, term in zip(ops, terms[1:]):
        clause, clause_params = _term_sql(term)
        sql += f" {op} {clause}"
        params += clause_params
    return (sql, params)


def query(conn: sqlite3.Connection, expr: str):
    where, params = build_where(expr)
    rows = conn.execute(f"SELECT * FROM clips WHERE {where} ORDER BY stem", params).fetchall()
    return [_row_to_clip(r) for r in rows]
