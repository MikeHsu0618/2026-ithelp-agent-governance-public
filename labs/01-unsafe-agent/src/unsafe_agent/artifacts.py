import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ARTIFACT_MARKER = ".lab-01-artifacts"
MARKER_CONTENT = "lab-01\n"


class UnsafeCleanupError(RuntimeError):
    """Raised when cleanup cannot prove that its target belongs to Lab 01."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ArtifactStore:
    """Writes one run into an isolated directory under a marked artifact root."""

    def __init__(self, artifact_root: Path, run_id: str) -> None:
        if artifact_root.is_symlink():
            raise UnsafeCleanupError("artifact root must not be a symlink")

        self.artifact_root = artifact_root
        marker = artifact_root / ARTIFACT_MARKER
        if artifact_root.exists() and any(artifact_root.iterdir()) and not marker.is_file():
            raise UnsafeCleanupError("artifact root exists without the Lab 01 marker")

        artifact_root.mkdir(parents=True, exist_ok=True)
        if marker.exists() and marker.read_text(encoding="utf-8") != MARKER_CONTENT:
            raise UnsafeCleanupError("artifact marker content does not match Lab 01")
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

    def append_jsonl(self, filename: str, payload: dict[str, Any]) -> Path:
        path = self.run_dir / filename
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return path

    def record(self, event_type: str, trace_id: str, span_id: str, **fields: Any) -> None:
        self.append_jsonl(
            "events.jsonl",
            {
                "event_type": event_type,
                "timestamp": utc_now(),
                "trace_id": trace_id,
                "span_id": span_id,
                **fields,
            },
        )


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
        raise UnsafeCleanupError("refusing to clean artifacts without the Lab 01 marker")

    shutil.rmtree(resolved_target)
