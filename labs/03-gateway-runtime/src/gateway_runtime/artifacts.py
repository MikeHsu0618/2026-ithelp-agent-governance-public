"""Safe, ownership-marked evidence storage for Lab 03."""

import json
import shutil
from pathlib import Path
from typing import Any

ARTIFACT_MARKER = ".lab-03-artifacts"
MARKER_CONTENT = "lab-03\n"


class UnsafeCleanupError(RuntimeError):
    """Raised when an artifact directory cannot be proven to belong to this Lab."""


class ArtifactStore:
    """Write one run under a marked Lab 03 artifact root."""

    def __init__(self, artifact_root: Path, run_id: str) -> None:
        run_path = Path(run_id)
        if run_path.is_absolute() or len(run_path.parts) != 1 or run_id in {"", ".", ".."}:
            raise ValueError("run ID must be one directory name inside the artifact root")
        if artifact_root.is_symlink():
            raise UnsafeCleanupError("artifact root must not be a symlink")
        marker = artifact_root / ARTIFACT_MARKER
        if marker.is_symlink():
            raise UnsafeCleanupError("artifact marker must not be a symlink")
        if artifact_root.exists() and any(artifact_root.iterdir()) and not marker.is_file():
            raise UnsafeCleanupError("artifact root exists without the Lab 03 marker")

        artifact_root.mkdir(parents=True, exist_ok=True)
        if marker.exists() and marker.read_text(encoding="utf-8") != MARKER_CONTENT:
            raise UnsafeCleanupError("artifact marker content does not match Lab 03")
        marker.write_text(MARKER_CONTENT, encoding="utf-8")
        self.artifact_root = artifact_root
        self.run_dir = artifact_root / run_path
        self.run_dir.mkdir()

    def write_json(self, relative_path: str, payload: dict[str, Any]) -> Path:
        path = self._safe_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def write_text(self, relative_path: str, content: str) -> Path:
        path = self._safe_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _safe_path(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("artifact path must stay inside the run directory")
        return self.run_dir / candidate


def cleanup_artifacts(lab_root: Path) -> None:
    """Remove only a marked ``<lab_root>/artifacts`` directory."""

    artifact_root = lab_root / "artifacts"
    if not artifact_root.exists() and not artifact_root.is_symlink():
        return
    if artifact_root.is_symlink():
        raise UnsafeCleanupError("refusing to clean a symlinked artifact directory")
    if artifact_root.resolve().parent != lab_root.resolve():
        raise UnsafeCleanupError("artifact directory resolved outside the Lab root")
    marker = artifact_root / ARTIFACT_MARKER
    if not marker.is_file() or marker.read_text(encoding="utf-8") != MARKER_CONTENT:
        raise UnsafeCleanupError("refusing to clean artifacts without the Lab 03 marker")
    shutil.rmtree(artifact_root.resolve())


def assert_values_absent(run_dir: Path, values: set[str]) -> None:
    """Fail when ephemeral credentials or other sensitive values reach evidence files."""

    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.rglob("*") if path.is_file()
    )
    leaked = [value for value in values if value in serialized]
    if leaked:
        raise RuntimeError("sensitive values were found in the evidence directory")
