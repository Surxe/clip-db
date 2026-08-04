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
