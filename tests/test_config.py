from clip_core import config


def test_load_config_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIP_INTAKE_DIR", str(tmp_path / "intake"))
    monkeypatch.setenv("CLIP_LIBRARY_DIR", str(tmp_path / "lib"))
    monkeypatch.setenv("CLIP_INDEX_PATH", str(tmp_path / "idx.sqlite"))
    monkeypatch.setenv("CLIP_TAGS_PATH", str(tmp_path / "tags.json"))
    monkeypatch.setenv("CLIP_MODEL", "claude-test")

    cfg = config.load_config()

    assert cfg.intake_dir == tmp_path / "intake"
    assert cfg.library_dir == tmp_path / "lib"
    assert cfg.index_path == tmp_path / "idx.sqlite"
    assert cfg.model == "claude-test"


def test_relative_tags_path_resolves_against_repo_root(monkeypatch):
    monkeypatch.setenv("CLIP_TAGS_PATH", "tags.json")
    cfg = config.load_config()
    assert cfg.tags_path == config.REPO_ROOT / "tags.json"
    assert cfg.tags_path.is_absolute()
