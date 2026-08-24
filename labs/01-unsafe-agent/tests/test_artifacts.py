from pathlib import Path

import pytest

from unsafe_agent.artifacts import (
    ARTIFACT_MARKER,
    UnsafeCleanupError,
    cleanup_artifacts,
)


def test_cleanup_removes_marked_artifact_directory(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    (artifact_root / ARTIFACT_MARKER).write_text("lab-01\n", encoding="utf-8")
    (artifact_root / "evidence.json").write_text("{}\n", encoding="utf-8")

    cleanup_artifacts(tmp_path)

    assert not artifact_root.exists()


def test_cleanup_refuses_unmarked_directory(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    evidence = artifact_root / "keep-me.txt"
    evidence.write_text("not-created-by-lab-01\n", encoding="utf-8")

    with pytest.raises(UnsafeCleanupError, match="marker"):
        cleanup_artifacts(tmp_path)

    assert evidence.exists()


def test_cleanup_refuses_symlinked_artifact_directory(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    (external / ARTIFACT_MARKER).write_text("lab-01\n", encoding="utf-8")
    lab_root = tmp_path / "lab"
    lab_root.mkdir()
    (lab_root / "artifacts").symlink_to(external, target_is_directory=True)

    with pytest.raises(UnsafeCleanupError, match="symlink"):
        cleanup_artifacts(lab_root)

    assert external.exists()
