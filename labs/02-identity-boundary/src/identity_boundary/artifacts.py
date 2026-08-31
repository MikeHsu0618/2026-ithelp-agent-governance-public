"""Safe, isolated evidence storage for Lab 02."""

import json
import shutil
from pathlib import Path
from typing import Any

ARTIFACT_MARKER = ".lab-02-artifacts"
MARKER_CONTENT = "lab-02\n"


class UnsafeCleanupError(RuntimeError):
    """Raised when artifact ownership cannot be proven."""


class ArtifactStore:
    """Write one run under a marked Lab 02 artifact root."""

    def __init__(self, artifact_root: Path, run_id: str) -> None:
        if artifact_root.is_symlink():
            raise UnsafeCleanupError("artifact root must not be a symlink")

        marker = artifact_root / ARTIFACT_MARKER
        if marker.is_symlink():
            raise UnsafeCleanupError("artifact ownership marker must not be a symlink")
        if artifact_root.exists() and any(artifact_root.iterdir()) and not marker.is_file():
            raise UnsafeCleanupError("artifact root exists without the Lab 02 marker")

        artifact_root.mkdir(parents=True, exist_ok=True)
        if marker.exists() and marker.read_text(encoding="utf-8") != MARKER_CONTENT:
            raise UnsafeCleanupError("artifact marker content does not match Lab 02")
        marker.write_text(MARKER_CONTENT, encoding="utf-8")

        self.artifact_root = artifact_root
        self.run_dir = artifact_root / run_id
        self.run_dir.mkdir()

    def write_json(self, relative_path: str, payload: dict[str, Any]) -> Path:
        path = self._safe_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def append_jsonl(self, relative_path: str, payload: dict[str, Any]) -> Path:
        path = self._safe_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return path

    def _safe_path(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("artifact path must stay inside the run directory")
        return self.run_dir / candidate


def cleanup_artifacts(lab_root: Path) -> None:
    """Remove only a real, marked ``<lab_root>/artifacts`` directory."""

    artifact_root = lab_root / "artifacts"
    if not artifact_root.exists() and not artifact_root.is_symlink():
        return
    if artifact_root.is_symlink():
        raise UnsafeCleanupError("refusing to clean a symlinked artifact directory")

    expected_parent = lab_root.resolve()
    resolved_target = artifact_root.resolve()
    if resolved_target.parent != expected_parent:
        raise UnsafeCleanupError("artifact directory resolved outside the Lab root")

    marker = artifact_root / ARTIFACT_MARKER
    if not marker.is_file() or marker.read_text(encoding="utf-8") != MARKER_CONTENT:
        raise UnsafeCleanupError("refusing to clean artifacts without the Lab 02 marker")

    shutil.rmtree(resolved_target)
