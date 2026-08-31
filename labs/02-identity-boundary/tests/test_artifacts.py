from pathlib import Path

import pytest

from identity_boundary.artifacts import (
    ARTIFACT_MARKER,
    MARKER_CONTENT,
    ArtifactStore,
    UnsafeCleanupError,
    cleanup_artifacts,
)


def test_cleanup_removes_only_marked_lab_artifacts(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    (artifact_root / ARTIFACT_MARKER).write_text(MARKER_CONTENT, encoding="utf-8")
    (artifact_root / "evidence.json").write_text("{}\n", encoding="utf-8")

    cleanup_artifacts(tmp_path)

    assert not artifact_root.exists()


def test_cleanup_refuses_unmarked_artifact_directory(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    (artifact_root / "belongs-to-user.txt").write_text("keep me\n", encoding="utf-8")

    with pytest.raises(UnsafeCleanupError):
        cleanup_artifacts(tmp_path)

    assert artifact_root.is_dir()
    assert (artifact_root / "belongs-to-user.txt").is_file()


def test_cleanup_refuses_symlinked_artifact_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep-me.txt").write_text("keep me\n", encoding="utf-8")
    (tmp_path / "artifacts").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafeCleanupError):
        cleanup_artifacts(tmp_path)

    assert (outside / "keep-me.txt").is_file()


def test_artifact_store_refuses_symlinked_ownership_marker(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    outside_marker = tmp_path / "outside-marker.txt"
    outside_marker.write_text(MARKER_CONTENT, encoding="utf-8")
    (artifact_root / ARTIFACT_MARKER).symlink_to(outside_marker)

    with pytest.raises(UnsafeCleanupError):
        ArtifactStore(artifact_root, "run-001")

    assert outside_marker.read_text(encoding="utf-8") == MARKER_CONTENT
