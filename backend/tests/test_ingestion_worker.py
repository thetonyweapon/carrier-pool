from pathlib import Path
from threading import Event

import pytest

from scripts.ingestion_worker import SOURCE_CONFIG, _validate_source_root, run_forever


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


def test_run_forever_polls_until_stopped(monkeypatch, tmp_path: Path) -> None:
    stop_event = Event()
    calls = []

    def poll(root: Path, worker_id: str) -> tuple[int, int]:
        calls.append((root, worker_id))
        stop_event.set()
        return 2, 1

    monkeypatch.setattr("scripts.ingestion_worker.run_once", poll)

    run_forever(tmp_path, "worker-a", 0.001, stop_event=stop_event)

    assert calls == [(tmp_path, "worker-a")]


def test_run_forever_continues_after_poll_failure(monkeypatch, tmp_path: Path) -> None:
    stop_event = Event()
    attempts = 0

    def poll(root: Path, worker_id: str) -> tuple[int, int]:
        nonlocal attempts
        del root, worker_id
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary failure")
        stop_event.set()
        return 0, 0

    monkeypatch.setattr("scripts.ingestion_worker.run_once", poll)

    run_forever(tmp_path, "worker-a", 0.001, stop_event=stop_event)

    assert attempts == 2


def test_run_forever_rejects_non_positive_interval(tmp_path: Path) -> None:
    for interval in (0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="greater than zero"):
            run_forever(tmp_path, "worker-a", interval)
