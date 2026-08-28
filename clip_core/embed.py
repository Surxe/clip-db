"""Semantic retrieval: embed clips and search them by meaning (the R in RAG).

Each clip's ``description + tags`` is embedded with a local, FROZEN sentence-transformers
model (no fine-tuning -- the semantic knowledge is baked in from the model's own
pretraining; we only run inference). Vectors live in a ``sqlite-vec`` ``vec0`` virtual
table beside the existing ``clips`` table, keyed by stem, and a natural-language query is
embedded the same way and matched by cosine top-k. This complements -- does not replace --
the exact controlled-vocabulary search in ``query.py``.

The embedding model is PINNED (``cfg.embed_model``). Vectors are only comparable when
produced by the same model, so changing it invalidates every stored vector; the model name
is recorded in ``vec_meta`` so a mismatch is detectable and a re-embed can be forced.

The sqlite-vec extension is loaded only on the connections that need it (this module,
the backfill script, the MCP search tool) -- ``schema.connect()` stays extension-free so
the tagger and eval paths don't pay for it.
"""
from __future__ import annotations

import sqlite3

import sqlite_vec

from . import index
from .config import load_config

# Lazily-loaded singletons so importing this module (and code paths that never embed) stay
# cheap: the model is only pulled/loaded on the first real embedding call.
_model = None
_model_name: str | None = None


def _model_id() -> str:
    return load_config().embed_model


def _get_model():
    """Load the SentenceTransformer once. First call may download the model (~90 MB)."""
    global _model, _model_name
    name = _model_id()
    if _model is None or _model_name != name:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(name)
        _model_name = name
    return _model


def _dim() -> int:
    model = _get_model()
    # Renamed in sentence-transformers 6.0; fall back to the old name on older installs.
    getter = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    return getter()


def embedding_text(clip: index.Clip) -> str:
    """The text we embed for a clip: free-text description plus its tags.

    Tags carry the controlled-vocabulary/jargon signal the free-text description may lack,
    so a query like 'insane comeback' can reach a clip tagged `clutch`.
    """
    desc = (clip.description or "").strip()
    tags = ", ".join(clip.tags)
    if desc and tags:
        return f"{desc}. Tags: {tags}"
    if desc:
        return desc
    if tags:
        return f"Tags: {tags}"
    return ""


def embed_text(text: str) -> list[float]:
    """Embed a single string into a unit-normalized vector (so cosine == dot product)."""
    vec = _get_model().encode(text, normalize_embeddings=True)
    return [float(x) for x in vec]


# --- vector store (sqlite-vec) ------------------------------------------------------------

def load_vec(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension onto a connection. Safe to call more than once."""
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def ensure_vec_table(conn: sqlite3.Connection) -> None:
    """Load the extension and create the vector table + metadata row if missing.

    ``vec_clips`` is a vec0 virtual table keyed by clip stem with a cosine-distance
    embedding column. ``vec_meta`` records the embedding model + dimension so a later
    model change is detectable (see the backfill script's re-embed guard).
    """
    load_vec(conn)
    dim = _dim()
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_clips USING vec0("
        f"  stem TEXT PRIMARY KEY,"
        f"  embedding float[{dim}] distance_metric=cosine"
        f")"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS vec_meta (model TEXT, dim INTEGER)")
    if conn.execute("SELECT COUNT(*) FROM vec_meta").fetchone()[0] == 0:
        conn.execute("INSERT INTO vec_meta(model, dim) VALUES (?, ?)", (_model_id(), dim))
    conn.commit()


def stored_model(conn: sqlite3.Connection) -> str | None:
    """The embedding model recorded in the index, or None if not yet initialized."""
    row = conn.execute("SELECT model FROM vec_meta LIMIT 1").fetchone()
    return row[0] if row else None


def set_stored_model(conn: sqlite3.Connection) -> None:
    """Stamp the current config model/dim into vec_meta (after a full re-embed)."""
    conn.execute("DELETE FROM vec_meta")
    conn.execute("INSERT INTO vec_meta(model, dim) VALUES (?, ?)", (_model_id(), _dim()))
    conn.commit()


def has_vector(conn: sqlite3.Connection, stem: str) -> bool:
    return conn.execute("SELECT 1 FROM vec_clips WHERE stem = ?", (stem,)).fetchone() is not None


def index_clip(conn: sqlite3.Connection, clip: index.Clip) -> None:
    """Upsert one clip's vector (delete-then-insert, so re-embedding is idempotent)."""
    vec = sqlite_vec.serialize_float32(embed_text(embedding_text(clip)))
    conn.execute("DELETE FROM vec_clips WHERE stem = ?", (clip.stem,))
    conn.execute("INSERT INTO vec_clips(stem, embedding) VALUES (?, ?)", (clip.stem, vec))
    conn.commit()


def remove_clip(conn: sqlite3.Connection, stem: str) -> None:
    """Drop a clip's vector (keeps the index consistent with index.delete_clip)."""
    conn.execute("DELETE FROM vec_clips WHERE stem = ?", (stem,))
    conn.commit()


def semantic_search(conn: sqlite3.Connection, query: str, k: int) -> list[tuple[str, float]]:
    """Embed the query and return the cosine top-k (stem, score) pairs, best first.

    ``score`` is ``1 - cosine_distance`` in ``[0, 1]`` for normalized vectors: 1.0 is
    identical meaning, ~0 is unrelated.
    """
    qvec = sqlite_vec.serialize_float32(embed_text(query))
    rows = conn.execute(
        "SELECT stem, distance FROM vec_clips "
        "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (qvec, k),
    ).fetchall()
    return [(stem, 1.0 - float(distance)) for stem, distance in rows]
