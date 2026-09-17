from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from incident_replay.contract import ContractError, validate_replay_report
from incident_replay.evidence import load_case
from incident_replay.historical import reconstruct_action


def _case(tmp_path: Path) -> Path:
    trace_id = "d" * 32
    manifest = {"run_id": "case-1", "trace_id": trace_id, "policy_version": "v1"}
    events = [
        {
            "event_type": "model.tool_call",
            "timestamp": "2026-09-17T00:00:00Z",
            "trace_id": trace_id,
            "span_id": "e" * 16,
            "tool_name": "delete_demo_database",
            "arguments": {"database": "payments-demo"},
        },
        {
            "event_type": "policy.decision",
            "timestamp": "2026-09-17T00:00:01Z",
            "trace_id": trace_id,
            "span_id": "e" * 16,
            "tool_name": "delete_demo_database",
            "decision": "DENY",
            "policy_version": "v1",
        },
        {
            "event_type": "run.completed",
            "timestamp": "2026-09-17T00:00:02Z",
            "trace_id": trace_id,
            "span_id": "e" * 16,
            "tool_name": "delete_demo_database",
            "result": "POLICY_DENIED",
        },
    ]
    files = {
        "manifest.json": json.dumps(manifest) + "\n",
        "events.jsonl": "".join(json.dumps(item) + "\n" for item in events),
        "canary.jsonl": "",
    }
    tmp_path.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    lock = {
        "case_id": "schema-case",
        "files": {
            name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in files
        },
    }
    (tmp_path / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")
    return tmp_path


def test_reconstructed_report_matches_schema(tmp_path: Path) -> None:
    report = reconstruct_action(load_case(_case(tmp_path)), target_tool="delete_demo_database")

    validate_replay_report(report)


def test_schema_rejects_status_outside_evidence_taxonomy(tmp_path: Path) -> None:
    report = reconstruct_action(load_case(_case(tmp_path)), target_tool="delete_demo_database")
    report["identity"]["principal"]["status"] = "ASSERTED"

    with pytest.raises(ContractError, match="ASSERTED"):
        validate_replay_report(report)


def test_schema_rejects_unknown_field_with_invented_value(tmp_path: Path) -> None:
    report = reconstruct_action(load_case(_case(tmp_path)), target_tool="delete_demo_database")
    report["identity"]["principal"]["value"] = "sre-oncaller"

    with pytest.raises(ContractError, match="identity/principal/value"):
        validate_replay_report(report)


def test_schema_rejects_observed_field_without_source(tmp_path: Path) -> None:
    report = reconstruct_action(load_case(_case(tmp_path)), target_tool="delete_demo_database")
    report["target"]["tool"]["sources"] = []

    with pytest.raises(ContractError, match="target/tool/sources"):
        validate_replay_report(report)


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("identifiers", "trace_id"),
        ("policy", "decision"),
        ("result", "status"),
    ],
)
def test_schema_rejects_missing_required_nested_field(
    tmp_path: Path,
    section: str,
    field: str,
) -> None:
    report = reconstruct_action(load_case(_case(tmp_path)), target_tool="delete_demo_database")
    del report[section][field]

    with pytest.raises(ContractError, match=section):
        validate_replay_report(report)


def test_schema_rejects_malformed_observed_trace_id(tmp_path: Path) -> None:
    report = reconstruct_action(load_case(_case(tmp_path)), target_tool="delete_demo_database")
    report["identifiers"]["trace_id"]["value"] = "not-a-trace-id"

    with pytest.raises(ContractError, match="identifiers/trace_id/value"):
        validate_replay_report(report)


def test_schema_rejects_malformed_observed_span_id(tmp_path: Path) -> None:
    report = reconstruct_action(load_case(_case(tmp_path)), target_tool="delete_demo_database")
    report["identifiers"]["span_id"]["value"] = "not-a-span-id"

    with pytest.raises(ContractError, match="identifiers/span_id/value"):
        validate_replay_report(report)


def test_schema_rejects_unknown_policy_decision_value(tmp_path: Path) -> None:
    report = reconstruct_action(load_case(_case(tmp_path)), target_tool="delete_demo_database")
    report["policy"]["decision"]["value"] = "MAYBE"

    with pytest.raises(ContractError, match="policy/decision/value"):
        validate_replay_report(report)
