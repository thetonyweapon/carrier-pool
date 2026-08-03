from pathlib import Path

import pytest

from scripts.ingestion_worker import SOURCE_CONFIG, _validate_source_root


def _source_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    for directory_name, _, _, _ in SOURCE_CONFIG:
        (root / directory_name).mkdir()
    return root


def test_source_root_requires_all_configured_directories(tmp_path: Path) -> None:
    root = _source_root(tmp_path)

    assert _validate_source_root(root) == root.resolve()


def test_source_root_rejects_missing_directory(tmp_path: Path) -> None:
    root = _source_root(tmp_path)
    (root / SOURCE_CONFIG[0][0]).rmdir()

    with pytest.raises(ValueError, match="missing"):
        _validate_source_root(root)


def test_source_root_rejects_symlinked_directory(tmp_path: Path) -> None:
    root = _source_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    directory = root / SOURCE_CONFIG[0][0]
    directory.rmdir()
    directory.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="missing"):
        _validate_source_root(root)
