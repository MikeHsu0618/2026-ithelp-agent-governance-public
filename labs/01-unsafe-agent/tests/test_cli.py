import json
import logging
import sys
from pathlib import Path

import pytest

from unsafe_agent import cli
from unsafe_agent.artifacts import ARTIFACT_MARKER
from unsafe_agent.runner import LabRunError


class FakeSummary:
    def to_json_dict(self) -> dict[str, object]:
        return {"result": "CANARY_TRIGGERED", "trace_id": "a" * 32}


def test_run_command_prints_machine_readable_summary(
    monkeypatch, capsys, tmp_path: Path, fixture_dir: Path
) -> None:
    observed = {}

    def fake_run_scenario(config):
        observed["config"] = config
        return FakeSummary()

    monkeypatch.setattr(cli, "run_scenario", fake_run_scenario)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "unsafe-agent",
            "run",
            "--scenario",
            "attack",
            "--model",
            "fixture",
            "--policy",
            "open",
            "--fixture-dir",
            str(fixture_dir),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["result"] == "CANARY_TRIGGERED"
    assert observed["config"].scenario == "attack"


def test_clean_command_removes_only_marked_lab_artifacts(monkeypatch, tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    (artifact_root / ARTIFACT_MARKER).write_text("lab-01\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["unsafe-agent", "clean", "--lab-root", str(tmp_path)],
    )

    cli.main()

    assert not artifact_root.exists()


def test_replay_command_prints_timeline(monkeypatch, capsys, tmp_path: Path) -> None:
    trace_id = "a" * 32
    monkeypatch.setattr(
        cli,
        "replay_trace",
        lambda artifact_root, observed_trace_id: [
            {"event_type": "run.started", "trace_id": observed_trace_id}
        ],
        raising=False,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "unsafe-agent",
            "replay",
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--trace-id",
            trace_id,
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output[0]["trace_id"] == trace_id


def test_run_command_reports_redacted_failure(
    monkeypatch, capsys, tmp_path: Path, fixture_dir: Path
) -> None:
    artifact_dir = tmp_path / "artifacts" / "failed-run"
    provider_logger = logging.getLogger("unsafe-agent-test-provider")
    provider_logger.handlers.clear()
    provider_logger.propagate = False
    provider_logger.setLevel(logging.ERROR)
    provider_logger.addHandler(logging.StreamHandler(sys.stderr))

    def fail_without_raw_provider_payload(config):
        provider_logger.error("private provider payload projects/SYNTHETIC_ID")
        raise LabRunError("API_KEY_SERVICE_BLOCKED", artifact_dir, "b" * 32)

    monkeypatch.setattr(cli, "run_scenario", fail_without_raw_provider_payload)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "unsafe-agent",
            "run",
            "--scenario",
            "attack",
            "--model",
            "live",
            "--policy",
            "open",
            "--fixture-dir",
            str(fixture_dir),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    captured_error = capsys.readouterr().err
    error = json.loads(captured_error)
    assert exc_info.value.code == 2
    assert error["error_code"] == "API_KEY_SERVICE_BLOCKED"
    assert "provider payload" not in captured_error
    assert "SYNTHETIC_ID" not in captured_error
