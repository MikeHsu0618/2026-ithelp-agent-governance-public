from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from incident_replay.cli import main


def _write_case(root: Path) -> Path:
    trace_id = "a" * 32
    files = {
        "manifest.json": json.dumps(
            {
                "run_id": "historical-run",
                "trace_id": trace_id,
                "policy_version": "day-01-open-v1",
            }
        )
        + "\n",
        "events.jsonl": "".join(
            json.dumps(item) + "\n"
            for item in (
                {
                    "event_type": "run.started",
                    "timestamp": "2026-08-17T00:00:00Z",
                    "trace_id": trace_id,
                    "span_id": "b" * 16,
                },
                {
                    "event_type": "model.tool_call",
                    "timestamp": "2026-08-17T00:00:01Z",
                    "trace_id": trace_id,
                    "span_id": "b" * 16,
                    "tool_name": "delete_demo_database",
                    "arguments": {"database": "payments-demo"},
                },
                {
                    "event_type": "policy.decision",
                    "timestamp": "2026-08-17T00:00:02Z",
                    "trace_id": trace_id,
                    "span_id": "b" * 16,
                    "tool_name": "delete_demo_database",
                    "decision": "ALLOW",
                },
                {
                    "event_type": "tool.executed",
                    "timestamp": "2026-08-17T00:00:03Z",
                    "trace_id": trace_id,
                    "span_id": "b" * 16,
                    "tool_name": "delete_demo_database",
                    "result": "CANARY_TRIGGERED",
                },
                {
                    "event_type": "run.completed",
                    "timestamp": "2026-08-17T00:00:04Z",
                    "trace_id": trace_id,
                    "span_id": "b" * 16,
                    "tool_name": "delete_demo_database",
                    "result": "CANARY_TRIGGERED",
                },
            )
        ),
        "canary.jsonl": json.dumps(
            {
                "timestamp": "2026-08-17T00:00:03Z",
                "trace_id": trace_id,
                "tool_name": "delete_demo_database",
                "database": "payments-demo",
                "result": "CANARY_TRIGGERED",
            }
        )
        + "\n",
    }
    root.mkdir(parents=True)
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    (root / "evidence-lock.json").write_text(
        json.dumps(
            {
                "case_id": "historical-case",
                "files": {
                    name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def test_historical_command_writes_validated_report(tmp_path: Path) -> None:
    output = tmp_path / "out" / "day01-replay.json"

    status = main(
        [
            "historical",
            "--case-dir",
            str(_write_case(tmp_path / "case")),
            "--target-tool",
            "delete_demo_database",
            "--output",
            str(output),
        ]
    )

    assert status == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["case_id"] == "historical-case"
    assert payload["identity"]["principal"]["status"] == "UNKNOWN"


def test_modern_command_selects_one_scenario_and_queries_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario_report = tmp_path / "scenario-report.json"
    scenario_report.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario": "normal-call",
                        "action_id": "act-normal-call-1234",
                        "trace_id": "b" * 32,
                        "expected_services": ["agentgateway", "agent-runtime"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "incident_replay.cli.query_modern_reference",
        lambda **kwargs: {
            **kwargs,
            "tempo": {"status": "OBSERVED", "complete": True},
            "loki": {"status": "OBSERVED", "matched_action": True},
            "prometheus": {"status": "OBSERVED"},
        },
    )
    output = tmp_path / "modern-reference.json"

    status = main(
        [
            "modern",
            "--scenario-report",
            str(scenario_report),
            "--scenario",
            "normal-call",
            "--output",
            str(output),
            "--attempts",
            "1",
        ]
    )

    assert status == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["action_id"] == "act-normal-call-1234"
    assert payload["trace_id"] == "b" * 32
    assert payload["expected_services"] == ["agentgateway", "agent-runtime"]


def test_modern_command_writes_partial_report_and_fails_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario_report = tmp_path / "scenario-report.json"
    scenario_report.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario": "normal-call",
                        "action_id": "act-normal-call-1234",
                        "trace_id": "b" * 32,
                        "expected_services": ["agentgateway"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "incident_replay.cli.query_modern_reference",
        lambda **_kwargs: {
            "tempo": {"status": "OBSERVED", "complete": False},
            "loki": {"status": "UNKNOWN", "matched_action": False},
            "prometheus": {"status": "UNKNOWN"},
        },
    )
    output = tmp_path / "modern-reference.json"

    status = main(
        [
            "modern",
            "--scenario-report",
            str(scenario_report),
            "--output",
            str(output),
            "--attempts",
            "1",
        ]
    )

    assert status == 1
    assert json.loads(output.read_text(encoding="utf-8"))["tempo"]["complete"] is False


def test_modern_command_rejects_missing_scenario(tmp_path: Path) -> None:
    scenario_report = tmp_path / "scenario-report.json"
    scenario_report.write_text(json.dumps({"scenarios": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="scenario not found"):
        main(
            [
                "modern",
                "--scenario-report",
                str(scenario_report),
                "--scenario",
                "normal-call",
                "--output",
                str(tmp_path / "out.json"),
            ]
        )


def test_modern_command_rejects_non_string_identifiers(tmp_path: Path) -> None:
    scenario_report = tmp_path / "scenario-report.json"
    scenario_report.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario": "normal-call",
                        "action_id": None,
                        "trace_id": "b" * 32,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="action_id or trace_id"):
        main(
            [
                "modern",
                "--scenario-report",
                str(scenario_report),
                "--output",
                str(tmp_path / "out.json"),
            ]
        )


@pytest.mark.parametrize(
    "expected_services",
    [[], ["agentgateway", "agentgateway"], [" agentgateway"]],
)
def test_modern_command_rejects_invalid_service_contract(
    tmp_path: Path,
    expected_services: list[str],
) -> None:
    scenario_report = tmp_path / "scenario-report.json"
    scenario_report.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario": "normal-call",
                        "action_id": "act-normal-call-1234",
                        "trace_id": "b" * 32,
                        "expected_services": expected_services,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected_services"):
        main(
            [
                "modern",
                "--scenario-report",
                str(scenario_report),
                "--output",
                str(tmp_path / "out.json"),
            ]
        )
