from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

ARTIFACT_MARKER = ".lab-04-artifacts"
MARKER_CONTENT = "lab-04\n"
PUBLIC_EVIDENCE_FILES = (
    "application-record.json",
    "governance-event.json",
    "operational-trace.json",
    "tool-receipt.json",
)


class CleanupError(RuntimeError):
    """Raised when cleanup cannot prove that a directory belongs to Lab 04."""


class ArtifactStore:
    def __init__(self, artifact_root: Path, run_id: str) -> None:
        if artifact_root.is_symlink():
            raise CleanupError("artifact root must not be a symlink")
        marker = artifact_root / ARTIFACT_MARKER
        if artifact_root.exists() and any(artifact_root.iterdir()) and not marker.is_file():
            raise CleanupError("artifact root exists without the Lab 04 marker")
        artifact_root.mkdir(parents=True, exist_ok=True)
        if marker.exists() and marker.read_text(encoding="utf-8") != MARKER_CONTENT:
            raise CleanupError("artifact marker content does not match Lab 04")
        marker.write_text(MARKER_CONTENT, encoding="utf-8")
        self.run_dir = artifact_root / run_id
        self.run_dir.mkdir()

    def write_json(self, filename: str, payload: dict[str, Any]) -> Path:
        path = self.run_dir / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path


def cleanup_artifacts(lab_root: Path) -> None:
    artifact_root = lab_root / "artifacts"
    if not artifact_root.exists() and not artifact_root.is_symlink():
        return
    if artifact_root.is_symlink():
        raise CleanupError("refusing to clean a symlinked artifact directory")
    if artifact_root.resolve().parent != lab_root.resolve():
        raise CleanupError("artifact directory resolved outside the Lab root")
    marker = artifact_root / ARTIFACT_MARKER
    if not marker.is_file() or marker.read_text(encoding="utf-8") != MARKER_CONTENT:
        raise CleanupError("refusing to clean artifacts without the Lab 04 marker")
    shutil.rmtree(artifact_root)


def package_public_evidence(*, artifact_dir: Path, backend_report: Path, destination: Path) -> None:
    """Copy one synthetic run into the publishable tree without local paths."""

    if destination.is_symlink():
        raise CleanupError("evidence destination must not be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    for filename in PUBLIC_EVIDENCE_FILES:
        shutil.copyfile(artifact_dir / filename, destination / filename)

    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest.pop("artifact_dir", None)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    shutil.copyfile(backend_report, destination / "backend-report.json")
