from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from incident_replay.evidence import EvidenceIntegrityError, load_case
from incident_replay.historical import reconstruct_action


def _write_case(root: Path, *, decision: str = "ALLOW", executed: bool = True) -> Path:
    trace_id = "a281375fdcb5516c8983eada8ff11c9b"
    manifest = {
        "run_id": "live-attack-open-3938d659",
        "trace_id": trace_id,
        "runtime": "google-adk-python",
        "model_name": "gemini-2.5-flash",
        "policy_version": "day-01-open-v1",
    }
    events: list[dict[str, Any]] = [
        {
            "event_type": "run.started",
            "timestamp": "2026-08-17T03:24:43Z",
            "trace_id": trace_id,
            "span_id": "6ecb4fbf03f379f3",
        },
        {
            "event_type": "model.tool_call",
            "timestamp": "2026-08-17T03:24:46Z",
            "trace_id": trace_id,
            "span_id": "6ecb4fbf03f379f3",
            "tool_name": "delete_demo_database",
            "arguments": {"database": "payments-demo", "ticket": "INC-DEMO-001"},
        },
        {
            "event_type": "policy.decision",
            "timestamp": "2026-08-17T03:24:46.5Z",
            "trace_id": trace_id,
            "span_id": "6ecb4fbf03f379f3",
            "tool_name": "delete_demo_database",
            "decision": decision,
            "policy_version": "day-01-open-v1",
            "reason": "open_policy" if decision == "ALLOW" else "tool_not_allowlisted",
            "tool_arguments": {
                "database": "payments-demo",
                "ticket": "INC-DEMO-001",
            },
        },
    ]
    if executed:
        events.append(
            {
                "event_type": "tool.executed",
                "timestamp": "2026-08-17T03:24:47Z",
                "trace_id": trace_id,
                "span_id": "6ecb4fbf03f379f3",
                "tool_name": "delete_demo_database",
                "resource": "payments-demo",
                "result": "CANARY_TRIGGERED",
            }
        )
    events.append(
        {
            "event_type": "run.completed",
            "timestamp": "2026-08-17T03:24:51Z",
            "trace_id": trace_id,
            "span_id": "6ecb4fbf03f379f3",
            "tool_name": "delete_demo_database",
            "result": "CANARY_TRIGGERED" if executed else "POLICY_DENIED",
            "canary_delta": 1 if executed else 0,
        }
    )
    canary: list[dict[str, Any]] = []
    if executed:
        canary.append(
            {
                "timestamp": "2026-08-17T03:24:46.7Z",
                "trace_id": trace_id,
                "tool_name": "delete_demo_database",
                "database": "payments-demo",
                "result": "CANARY_TRIGGERED",
            }
        )

    root.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    (root / "events.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in events), encoding="utf-8"
    )
    (root / "canary.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in canary), encoding="utf-8"
    )
    lock = {
        "case_id": "day01-canary" if executed else "day03-policy-denied",
        "files": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("manifest.json", "events.jsonl", "canary.jsonl")
        },
    }
    (root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")
    return root


def test_replay_keeps_observed_and_unknown_fields_separate(tmp_path: Path) -> None:
    case = load_case(_write_case(tmp_path / "day01"))

    report = reconstruct_action(case, target_tool="delete_demo_database")

    assert report["record_kind"] == "RECONSTRUCTED_GOVERNANCE_EVENT"
    assert report["identifiers"]["trace_id"]["status"] == "OBSERVED"
    assert report["identifiers"]["action_id"]["status"] == "UNKNOWN"
    assert report["identity"]["principal"]["status"] == "UNKNOWN"
    assert report["identity"]["workload"]["status"] == "UNKNOWN"
    assert report["agent"]["artifact_digest"]["status"] == "UNKNOWN"
    assert report["credential_reference"]["status"] == "UNKNOWN"
    assert report["target"]["tool"]["value"] == "delete_demo_database"
    assert report["target"]["tool"]["status"] == "OBSERVED"
    assert report["policy"]["decision"]["value"] == "ALLOW"
    assert report["result"]["status"]["value"] == "CANARY_TRIGGERED"
    assert report["result"]["effect_receipt"]["status"] == "OBSERVED"
    assert report["backend_presence"]["tempo"]["status"] == "UNKNOWN"
    assert report["integrity"]["repository_lock"]["status"] == "VERIFIED"
    assert report["integrity"]["original_tamper_evidence"]["status"] == "UNKNOWN"
    assert [item["event_type"] for item in report["timeline"]] == [
        "run.started",
        "model.tool_call",
        "policy.decision",
        "tool.executed",
        "run.completed",
    ]


def test_denied_tool_has_not_applicable_execution_not_a_fake_receipt(tmp_path: Path) -> None:
    case = load_case(_write_case(tmp_path / "day03", decision="DENY", executed=False))

    report = reconstruct_action(case, target_tool="delete_demo_database")

    assert report["policy"]["decision"]["value"] == "DENY"
    assert report["result"]["status"]["value"] == "POLICY_DENIED"
    assert report["result"]["effect_receipt"]["status"] == "NOT_APPLICABLE"
    assert report["result"]["effect_receipt"]["value"] is None


def test_lock_mismatch_is_rejected(tmp_path: Path) -> None:
    case_root = _write_case(tmp_path / "day01")
    (case_root / "events.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(EvidenceIntegrityError, match="events.jsonl"):
        load_case(case_root)


def test_mixed_trace_ids_are_rejected(tmp_path: Path) -> None:
    case_root = _write_case(tmp_path / "day01")
    events = (case_root / "events.jsonl").read_text(encoding="utf-8")
    events += json.dumps({"event_type": "rogue", "trace_id": "f" * 32}) + "\n"
    (case_root / "events.jsonl").write_text(events, encoding="utf-8")
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["files"]["events.jsonl"] = hashlib.sha256(
        (case_root / "events.jsonl").read_bytes()
    ).hexdigest()
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")

    case = load_case(case_root)
    with pytest.raises(ValueError, match="multiple trace IDs"):
        reconstruct_action(case, target_tool="delete_demo_database")


def test_target_action_result_does_not_inherit_another_tool_run_summary(tmp_path: Path) -> None:
    case_root = _write_case(tmp_path / "day01")
    trace_id = "a281375fdcb5516c8983eada8ff11c9b"
    events = json.loads((case_root / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert events["event_type"] == "run.completed"
    existing = (case_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    existing[-1:-1] = [
        json.dumps(
            {
                "event_type": "model.tool_call",
                "timestamp": "2026-08-17T03:24:48Z",
                "trace_id": trace_id,
                "span_id": "b" * 16,
                "tool_name": "query_metrics",
                "arguments": {"query": "up"},
            }
        ),
        json.dumps(
            {
                "event_type": "policy.decision",
                "timestamp": "2026-08-17T03:24:49Z",
                "trace_id": trace_id,
                "span_id": "b" * 16,
                "tool_name": "query_metrics",
                "decision": "ALLOW",
            }
        ),
        json.dumps(
            {
                "event_type": "tool.executed",
                "timestamp": "2026-08-17T03:24:50Z",
                "trace_id": trace_id,
                "span_id": "b" * 16,
                "tool_name": "query_metrics",
                "result": "SUCCESS",
            }
        ),
    ]
    (case_root / "events.jsonl").write_text("\n".join(existing) + "\n", encoding="utf-8")
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["files"]["events.jsonl"] = hashlib.sha256(
        (case_root / "events.jsonl").read_bytes()
    ).hexdigest()
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")

    report = reconstruct_action(load_case(case_root), target_tool="query_metrics")

    assert report["result"]["status"]["value"] == "SUCCESS"
    assert report["result"]["status"]["sources"] == ["events.jsonl:tool.executed"]


def test_repeated_same_tool_calls_are_rejected_as_ambiguous(tmp_path: Path) -> None:
    case_root = _write_case(tmp_path / "day01")
    records = (case_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    duplicate = json.loads(records[1])
    duplicate["timestamp"] = "2026-08-17T03:24:47.5Z"
    records.insert(-1, json.dumps(duplicate))
    (case_root / "events.jsonl").write_text("\n".join(records) + "\n", encoding="utf-8")
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["files"]["events.jsonl"] = hashlib.sha256(
        (case_root / "events.jsonl").read_bytes()
    ).hexdigest()
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ambiguous"):
        reconstruct_action(load_case(case_root), target_tool="delete_demo_database")


def test_denied_action_with_execution_evidence_is_rejected(tmp_path: Path) -> None:
    case = load_case(_write_case(tmp_path / "contradictory", decision="DENY", executed=True))

    with pytest.raises(ValueError, match="DENY.*execution"):
        reconstruct_action(case, target_tool="delete_demo_database")


def test_action_events_with_different_spans_are_rejected(tmp_path: Path) -> None:
    case_root = _write_case(tmp_path / "mixed-action")
    records = [
        json.loads(line)
        for line in (case_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for record in records:
        if record.get("event_type") in {"policy.decision", "run.completed"}:
            record["span_id"] = "c" * 16
    (case_root / "events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["files"]["events.jsonl"] = hashlib.sha256(
        (case_root / "events.jsonl").read_bytes()
    ).hexdigest()
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="span"):
        reconstruct_action(load_case(case_root), target_tool="delete_demo_database")


def test_denied_action_with_positive_completion_is_rejected(tmp_path: Path) -> None:
    case_root = _write_case(tmp_path / "contradictory-result", decision="DENY", executed=False)
    records = [
        json.loads(line)
        for line in (case_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    records[-1]["result"] = "CANARY_TRIGGERED"
    records[-1]["canary_delta"] = 1
    (case_root / "events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["files"]["events.jsonl"] = hashlib.sha256(
        (case_root / "events.jsonl").read_bytes()
    ).hexdigest()
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="DENY.*completion"):
        reconstruct_action(load_case(case_root), target_tool="delete_demo_database")


def test_action_events_out_of_order_are_rejected(tmp_path: Path) -> None:
    case_root = _write_case(tmp_path / "out-of-order")
    records = [
        json.loads(line)
        for line in (case_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    records[2]["timestamp"] = "2026-08-17T03:24:45Z"
    (case_root / "events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["files"]["events.jsonl"] = hashlib.sha256(
        (case_root / "events.jsonl").read_bytes()
    ).hexdigest()
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="order"):
        reconstruct_action(load_case(case_root), target_tool="delete_demo_database")


def test_policy_resource_must_match_the_requested_and_executed_resource(
    tmp_path: Path,
) -> None:
    case_root = _write_case(tmp_path / "policy-resource-mismatch")
    records = [
        json.loads(line)
        for line in (case_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    records[2]["tool_arguments"]["database"] = "another-demo"
    (case_root / "events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["files"]["events.jsonl"] = hashlib.sha256(
        (case_root / "events.jsonl").read_bytes()
    ).hexdigest()
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="resources"):
        reconstruct_action(load_case(case_root), target_tool="delete_demo_database")


def test_execution_and_completion_results_must_agree(tmp_path: Path) -> None:
    case_root = _write_case(tmp_path / "outcome-mismatch")
    records = [
        json.loads(line)
        for line in (case_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    records[-1]["result"] = "FAILURE"
    records[-1]["canary_delta"] = 0
    (case_root / "events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["files"]["events.jsonl"] = hashlib.sha256(
        (case_root / "events.jsonl").read_bytes()
    ).hexdigest()
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="results"):
        reconstruct_action(load_case(case_root), target_tool="delete_demo_database")


def test_completion_supplies_result_when_execution_did_not_record_one(
    tmp_path: Path,
) -> None:
    case_root = _write_case(tmp_path / "completion-result")
    records = [
        json.loads(line)
        for line in (case_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    del records[3]["result"]
    (case_root / "events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["files"]["events.jsonl"] = hashlib.sha256(
        (case_root / "events.jsonl").read_bytes()
    ).hexdigest()
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")

    report = reconstruct_action(load_case(case_root), target_tool="delete_demo_database")

    assert report["result"]["status"]["value"] == "CANARY_TRIGGERED"
    assert report["result"]["status"]["sources"] == ["events.jsonl:run.completed"]


def test_non_otel_span_id_is_rejected(tmp_path: Path) -> None:
    case_root = _write_case(tmp_path / "invalid-span")
    records = [
        json.loads(line)
        for line in (case_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for record in records:
        record["span_id"] = "not-otel-span"
    (case_root / "events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["files"]["events.jsonl"] = hashlib.sha256(
        (case_root / "events.jsonl").read_bytes()
    ).hexdigest()
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="span_id"):
        reconstruct_action(load_case(case_root), target_tool="delete_demo_database")


def test_unknown_target_tool_is_rejected(tmp_path: Path) -> None:
    case = load_case(_write_case(tmp_path / "unknown-tool"))

    with pytest.raises(ValueError, match="no events for target Tool"):
        reconstruct_action(case, target_tool="no_such_tool")


def test_policy_and_completion_can_supply_partial_target_evidence(tmp_path: Path) -> None:
    case_root = _write_case(tmp_path / "partial-deny", decision="DENY", executed=False)
    records = [
        json.loads(line)
        for line in (case_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    records = [record for record in records if record["event_type"] != "model.tool_call"]
    (case_root / "events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["files"]["events.jsonl"] = hashlib.sha256(
        (case_root / "events.jsonl").read_bytes()
    ).hexdigest()
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")

    report = reconstruct_action(load_case(case_root), target_tool="delete_demo_database")

    assert report["identifiers"]["span_id"]["value"] == "6ecb4fbf03f379f3"
    assert report["identifiers"]["span_id"]["sources"] == ["events.jsonl:policy.decision"]
    assert report["target"]["tool"]["status"] == "OBSERVED"
    assert report["target"]["resource"]["value"] == "payments-demo"
    assert report["target"]["resource"]["sources"] == ["events.jsonl:policy.decision"]


@pytest.mark.parametrize("missing_field", ["timestamp", "result", "database"])
def test_incomplete_canary_receipt_is_rejected(
    tmp_path: Path,
    missing_field: str,
) -> None:
    case_root = _write_case(tmp_path / f"bad-canary-{missing_field}")
    canary = json.loads((case_root / "canary.jsonl").read_text(encoding="utf-8"))
    del canary[missing_field]
    (case_root / "canary.jsonl").write_text(json.dumps(canary) + "\n", encoding="utf-8")
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["files"]["canary.jsonl"] = hashlib.sha256(
        (case_root / "canary.jsonl").read_bytes()
    ).hexdigest()
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="canary"):
        reconstruct_action(load_case(case_root), target_tool="delete_demo_database")


def test_missing_case_or_trace_identifier_is_rejected(tmp_path: Path) -> None:
    case_root = _write_case(tmp_path / "missing-id")
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["case_id"] = None
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")
    with pytest.raises(EvidenceIntegrityError, match="case_id"):
        load_case(case_root)

    case_root = _write_case(tmp_path / "missing-trace")
    manifest = json.loads((case_root / "manifest.json").read_text(encoding="utf-8"))
    manifest["trace_id"] = None
    (case_root / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    lock = json.loads((case_root / "evidence-lock.json").read_text(encoding="utf-8"))
    lock["files"]["manifest.json"] = hashlib.sha256(
        (case_root / "manifest.json").read_bytes()
    ).hexdigest()
    (case_root / "evidence-lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="trace_id"):
        reconstruct_action(load_case(case_root), target_tool="delete_demo_database")


def test_symlinked_evidence_file_is_rejected(tmp_path: Path) -> None:
    case_root = _write_case(tmp_path / "day01")
    outside = tmp_path / "outside-events.jsonl"
    outside.write_bytes((case_root / "events.jsonl").read_bytes())
    (case_root / "events.jsonl").unlink()
    (case_root / "events.jsonl").symlink_to(outside)

    with pytest.raises(EvidenceIntegrityError, match="symlink"):
        load_case(case_root)
