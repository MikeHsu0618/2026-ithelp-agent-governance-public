import json
from pathlib import Path

import pytest

from traceability_lab.artifacts import CleanupError, cleanup_artifacts
from traceability_lab.runner import run_action


def test_run_persists_correlated_records_and_a_noop_receipt(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"

    summary = run_action(artifact_root=artifact_root, otlp_endpoint=None)

    run_dir = Path(summary.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    application = json.loads((run_dir / "application-record.json").read_text())
    trace = json.loads((run_dir / "operational-trace.json").read_text())
    governance = json.loads((run_dir / "governance-event.json").read_text())
    receipt = json.loads((run_dir / "tool-receipt.json").read_text())

    assert manifest["action_id"] == application["action_id"] == governance["action_id"]
    assert manifest["trace_id"] == trace["trace_id"] == governance["correlation"]["trace_id"]
    assert [span["name"] for span in trace["spans"]] == [
        "invoke_agent sre-investigation-agent",
        "execute_tool delete_demo_database",
    ]
    assert receipt["side_effects"] == 0
    assert receipt["status"] == "CANARY_TRIGGERED"
    assert summary.export_mode == "local-only"


def test_artifacts_do_not_persist_prompt_token_or_email(tmp_path: Path) -> None:
    summary = run_action(artifact_root=tmp_path / "artifacts", otlp_endpoint=None)
    content = "\n".join(
        path.read_text() for path in Path(summary.artifact_dir).iterdir() if path.is_file()
    ).casefold()

    assert "raw_prompt" not in content
    assert "bearer " not in content
    assert "@example" not in content


def test_cleanup_requires_the_lab_marker(tmp_path: Path) -> None:
    lab_root = tmp_path / "lab"
    artifact_root = lab_root / "artifacts"
    artifact_root.mkdir(parents=True)
    (artifact_root / "keep.txt").write_text("user data\n")

    with pytest.raises(CleanupError, match="marker"):
        cleanup_artifacts(lab_root)

    assert (artifact_root / "keep.txt").exists()


def test_artifact_root_rejects_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "real-artifacts"
    target.mkdir()
    link = tmp_path / "artifacts-link"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(CleanupError, match="symlink"):
        run_action(artifact_root=link, otlp_endpoint=None)


def test_cleanup_removes_only_a_marked_artifact_directory(tmp_path: Path) -> None:
    lab_root = tmp_path / "lab"
    run_action(artifact_root=lab_root / "artifacts", otlp_endpoint=None)

    cleanup_artifacts(lab_root)

    assert not (lab_root / "artifacts").exists()
