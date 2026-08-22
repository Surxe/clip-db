from clip_core import index
from clip_core import query as q
from clip_core.schema import connect


def _seed():
    conn = connect(":memory:")
    index.upsert_clip(conn, index.Clip(stem="c1", master_path="/c1.mp4", game="valorant",
                                       tags=["clutch", "ace"]))
    index.upsert_clip(conn, index.Clip(stem="c2", master_path="/c2.mp4", game="valorant",
                                       tags=["fail", "funny"]))
    index.upsert_clip(conn, index.Clip(stem="c3", master_path="/c3.mp4", game="apex",
                                       tags=["clutch"]))
    return conn


def _seed_spaced():
    conn = connect(":memory:")
    index.upsert_clip(conn, index.Clip(stem="s1", master_path="/s1.mp4", game="war robots frontiers",
                                       tags=["movement tech", "fuel thief"]))
    index.upsert_clip(conn, index.Clip(stem="s2", master_path="/s2.mp4", game="war robots frontiers",
                                       tags=["clutch"]))
    return conn


def _stems(clips):
    return {c.stem for c in clips}


def test_bare_term_matches_tag_or_game():
    conn = _seed()
    assert _stems(q.query(conn, "clutch")) == {"c1", "c3"}
    assert _stems(q.query(conn, "valorant")) == {"c1", "c2"}


def test_and_or():
    conn = _seed()
    assert _stems(q.query(conn, "clutch AND valorant")) == {"c1"}
    assert _stems(q.query(conn, "fail OR ace")) == {"c1", "c2"}


def test_prefixed_terms():
    conn = _seed()
    assert _stems(q.query(conn, "game:apex")) == {"c3"}
    assert _stems(q.query(conn, "tag:funny")) == {"c2"}


def test_empty_returns_all():
    conn = _seed()
    assert _stems(q.query(conn, "")) == {"c1", "c2", "c3"}


def test_multiword_tag_bare_and_quoted():
    conn = _seed_spaced()
    # bare multi-word tag
    assert _stems(q.query(conn, "movement tech")) == {"s1"}
    # prefixed, quoted (the form the MCP client naturally tries)
    assert _stems(q.query(conn, 'tag:"movement tech"')) == {"s1"}
    # prefixed, bare
    assert _stems(q.query(conn, "tag:fuel thief")) == {"s1"}
    # fully-quoted bare phrase
    assert _stems(q.query(conn, '"fuel thief"')) == {"s1"}


def test_multiword_game_and_and():
    conn = _seed_spaced()
    assert _stems(q.query(conn, "game:war robots frontiers")) == {"s1", "s2"}
    assert _stems(q.query(conn, 'tag:"movement tech" AND clutch')) == set()
    assert _stems(q.query(conn, 'tag:"fuel thief" OR clutch')) == {"s1", "s2"}


def test_tag_substring_does_not_false_match():
    conn = connect(":memory:")
    index.upsert_clip(conn, index.Clip(stem="x", master_path="/x.mp4", tags=["ace"]))
    # "ac" must not match the tag "ace"
    assert _stems(q.query(conn, "tag:ac")) == set()
