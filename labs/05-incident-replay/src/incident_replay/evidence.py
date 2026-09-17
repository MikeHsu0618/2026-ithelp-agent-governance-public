from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class EvidenceIntegrityError(ValueError):
    """Raised when a locked evidence file no longer matches its digest."""


@dataclass(frozen=True, slots=True)
class EvidenceCase:
    case_id: str
    root: Path
    manifest: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    canary_events: tuple[dict[str, Any], ...]
    locked_files: dict[str, str]


def _safe_child(root: Path, relative_name: str) -> Path:
    relative = Path(relative_name)
    if relative.is_absolute() or len(relative.parts) != 1 or relative_name in {"", ".", ".."}:
        raise EvidenceIntegrityError(f"unsafe evidence path: {relative_name}")
    return root / relative


def _read_json_lines(name: str, content: bytes) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(content.decode("utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        payload = json.loads(raw_line)
        if not isinstance(payload, dict):
            raise EvidenceIntegrityError(f"{name}:{line_number} is not a JSON object")
        records.append(payload)
    return tuple(records)


def load_case(root: Path) -> EvidenceCase:
    lock_path = root / "evidence-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    raw_case_id = lock.get("case_id")
    case_id = raw_case_id.strip() if isinstance(raw_case_id, str) else ""
    locked_files = lock.get("files")
    if not case_id or not isinstance(locked_files, dict) or not locked_files:
        raise EvidenceIntegrityError("evidence lock requires case_id and files")

    verified: dict[str, str] = {}
    verified_content: dict[str, bytes] = {}
    for relative_name, expected_digest in locked_files.items():
        path = _safe_child(root, str(relative_name))
        if path.is_symlink():
            raise EvidenceIntegrityError(f"evidence file must not be a symlink: {relative_name}")
        if not path.is_file():
            raise EvidenceIntegrityError(f"missing evidence file: {relative_name}")
        content = path.read_bytes()
        observed_digest = hashlib.sha256(content).hexdigest()
        if observed_digest != expected_digest:
            raise EvidenceIntegrityError(
                f"evidence digest mismatch for {relative_name}: "
                f"expected {expected_digest}, observed {observed_digest}"
            )
        verified[str(relative_name)] = observed_digest
        verified_content[str(relative_name)] = content

    required = {"manifest.json", "events.jsonl", "canary.jsonl"}
    missing = sorted(required - set(verified))
    if missing:
        raise EvidenceIntegrityError(f"evidence lock is missing required files: {missing}")

    manifest = json.loads(verified_content["manifest.json"])
    if not isinstance(manifest, dict):
        raise EvidenceIntegrityError("manifest.json is not a JSON object")
    return EvidenceCase(
        case_id=case_id,
        root=root,
        manifest=manifest,
        events=_read_json_lines("events.jsonl", verified_content["events.jsonl"]),
        canary_events=_read_json_lines("canary.jsonl", verified_content["canary.jsonl"]),
        locked_files=verified,
    )
