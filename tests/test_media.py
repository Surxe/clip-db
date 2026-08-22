from clip_core import media


def test_master_merged_detection():
    assert media.is_master("clip123.mp4")
    assert not media.is_master("clip123_merged.mp4")
    assert not media.is_master("notes.txt")
    assert media.is_merged("clip123_merged.mp4")
    assert not media.is_merged("clip123.mp4")


def test_stem_and_merged_name():
    assert media.stem_of("clip123.mp4") == "clip123"
    assert media.stem_of("clip123_merged.mp4") == "clip123"  # both map to one asset id
    assert media.merged_name_for("clip123.mp4") == "clip123_merged.mp4"


def test_iter_masters_excludes_merged_and_nonmp4(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"")
    (tmp_path / "a_merged.mp4").write_bytes(b"")
    (tmp_path / "b.mp4").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("x")
    masters = [p.name for p in media.iter_masters(tmp_path)]
    assert masters == ["a.mp4", "b.mp4"]


def test_move_into_library_copies_then_removes(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    src = staging / "clip9.mp4"
    src.write_bytes(b"data")
    lib = tmp_path / "lib"

    dst = media.move_into_library(src, lib)

    assert dst == lib / "clip9.mp4"
    assert dst.read_bytes() == b"data"
    assert not src.exists()  # staging is cleared


def test_date_from_stem():
    assert media.date_from_stem("2026-07-30_22-03-03") == "2026-07-30"
    assert media.date_from_stem("2026-07-30 goblin combo") == "2026-07-30"
    assert media.date_from_stem("the goblin combo") is None


def test_file_mtime_date(tmp_path):
    import os
    from datetime import datetime
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"")
    ts = datetime(2026, 3, 14, 9, 0, 0).timestamp()
    os.utime(f, (ts, ts))
    assert media.file_mtime_date(f) == "2026-03-14"
    assert media.file_mtime_date(tmp_path / "nope.mp4") is None


def test_resolve_date_ladder(tmp_path):
    import os
    from datetime import datetime
    # no creation_time tag on an empty file -> mtime is the source
    f = tmp_path / "the goblin combo.mp4"
    f.write_bytes(b"")
    ts = datetime(2026, 5, 1, 12, 0, 0).timestamp()
    os.utime(f, (ts, ts))
    assert media.resolve_date(f, "the goblin combo") == "2026-05-01"
    # an explicit stem timestamp wins over mtime
    assert media.resolve_date(f, "2026-01-02_10-00-00 clip") == "2026-01-02"
