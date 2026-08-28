"""Tests for semantic retrieval (clip_core.embed).

These exercise a real frozen sentence-transformers model, so the first run downloads it
(~90 MB) and loads torch. If the optional deps aren't installed, the whole module is
skipped rather than failing -- semantic search is an add-on to the core pipeline.
"""
import pytest

pytest.importorskip("sentence_transformers")
pytest.importorskip("sqlite_vec")

from clip_core import embed, index  # noqa: E402
from clip_core.schema import connect  # noqa: E402


def _clip(stem, description, tags):
    return index.Clip(stem=stem, master_path=f"/lib/{stem}.mp4", description=description, tags=tags)


def test_embedding_text_combines_description_and_tags():
    c = _clip("a", "1v4 retake for the round", ["clutch", "valorant"])
    assert embed.embedding_text(c) == "1v4 retake for the round. Tags: clutch, valorant"


def test_embedding_text_handles_missing_pieces():
    assert embed.embedding_text(_clip("a", None, ["clutch"])) == "Tags: clutch"
    assert embed.embedding_text(_clip("a", "just a description", [])) == "just a description"
    assert embed.embedding_text(_clip("a", None, [])) == ""


def test_embed_text_is_normalized_and_right_shape():
    vec = embed.embed_text("clutch 1v4 comeback")
    assert len(vec) == embed._dim()
    norm = sum(x * x for x in vec) ** 0.5
    assert norm == pytest.approx(1.0, abs=1e-3)  # normalize_embeddings=True -> unit vector


def _seed(conn):
    embed.ensure_vec_table(conn)
    clips = [
        _clip("clutch1", "1v4 retake, insane comeback to win the round", ["clutch", "ace"]),
        _clip("recipe1", "how to bake sourdough bread at home", ["cooking"]),
        _clip("scenery1", "a calm timelapse of clouds over the mountains", ["nature"]),
    ]
    for c in clips:
        index.upsert_clip(conn, c)
        embed.index_clip(conn, c)


def test_semantic_search_ranks_by_meaning_not_words():
    """A query sharing NO words with the clip still retrieves it by meaning."""
    conn = connect(":memory:")
    _seed(conn)
    hits = embed.semantic_search(conn, "that crazy clutch play", k=3)
    stems = [stem for stem, _ in hits]
    assert stems[0] == "clutch1"  # the gaming-clutch clip, not the recipe or the timelapse
    # scores are descending in [0, 1]
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)


def test_semantic_search_respects_k():
    conn = connect(":memory:")
    _seed(conn)
    assert len(embed.semantic_search(conn, "gaming highlight", k=1)) == 1
    assert len(embed.semantic_search(conn, "gaming highlight", k=2)) == 2


def test_index_clip_is_idempotent_upsert():
    conn = connect(":memory:")
    embed.ensure_vec_table(conn)
    c = _clip("x", "a clutch play", ["clutch"])
    embed.index_clip(conn, c)
    embed.index_clip(conn, c)  # re-embedding must not duplicate the row
    assert conn.execute("SELECT COUNT(*) FROM vec_clips WHERE stem='x'").fetchone()[0] == 1
    embed.remove_clip(conn, "x")
    assert not embed.has_vector(conn, "x")
