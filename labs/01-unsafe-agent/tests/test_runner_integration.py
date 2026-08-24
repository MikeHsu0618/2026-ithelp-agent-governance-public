import hashlib
import json
import re
from pathlib import Path

import pytest

from unsafe_agent.adk_agent import ExecutionState
from unsafe_agent.config import RunConfig
from unsafe_agent.runner import resolve_run_outcome, run_scenario


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.integration
def test_normal_fixture_uses_read_only_tool_without_canary(
    tmp_path: Path, fixture_dir: Path
) -> None:
    summary = run_scenario(
        RunConfig(
            scenario="normal",
            model_mode="fixture",
            policy_mode="open",
            artifact_root=tmp_path / "artifacts",
            fixture_dir=fixture_dir,
        )
    )

    assert summary.result == "SUCCESS"
    assert summary.tool_name == "query_logs"
    assert summary.canary_delta == 0
    assert not (summary.artifact_dir / "canary-events.jsonl").exists()


@pytest.mark.integration
def test_attack_fixture_open_policy_triggers_exactly_one_canary(
    tmp_path: Path, fixture_dir: Path
) -> None:
    summary = run_scenario(
        RunConfig(
            scenario="attack",
            model_mode="fixture",
            policy_mode="open",
            artifact_root=tmp_path / "artifacts",
            fixture_dir=fixture_dir,
        )
    )

    canary_events = read_jsonl(summary.artifact_dir / "canary-events.jsonl")
    assert summary.result == "CANARY_TRIGGERED"
    assert summary.tool_name == "delete_demo_database"
    assert summary.canary_delta == 1
    assert len(canary_events) == 1
    assert canary_events[0]["trace_id"] == summary.trace_id


@pytest.mark.integration
def test_same_attack_fixture_is_denied_before_canary_execution(
    tmp_path: Path, fixture_dir: Path
) -> None:
    summary = run_scenario(
        RunConfig(
            scenario="attack",
            model_mode="fixture",
            policy_mode="allowlist",
            artifact_root=tmp_path / "artifacts",
            fixture_dir=fixture_dir,
        )
    )

    events = read_jsonl(summary.artifact_dir / "events.jsonl")
    assert summary.result == "POLICY_DENIED"
    assert summary.tool_name == "delete_demo_database"
    assert summary.canary_delta == 0
    assert not (summary.artifact_dir / "canary-events.jsonl").exists()
    assert any(
        event["event_type"] == "policy.decision" and event["decision"] == "DENY" for event in events
    )
    assert not any(event["event_type"] == "tool.executed" for event in events)


@pytest.mark.integration
def test_obvious_attack_is_stopped_by_keyword_guard_before_model_execution(
    tmp_path: Path, fixture_dir: Path
) -> None:
    summary = run_scenario(
        RunConfig(
            scenario="attack",
            model_mode="fixture",
            policy_mode="open",
            input_guard_mode="keyword",
            artifact_root=tmp_path / "artifacts",
            fixture_dir=fixture_dir,
        )
    )

    events = read_jsonl(summary.artifact_dir / "events.jsonl")
    assert summary.result == "INPUT_DENIED"
    assert summary.tool_name is None
    assert summary.canary_delta == 0
    assert any(
        event["event_type"] == "input.guard.decision" and event["decision"] == "DENY"
        for event in events
    )
    assert not any(event["event_type"] == "model.tool_call" for event in events)
    assert not any(event["event_type"] == "policy.decision" for event in events)


@pytest.mark.integration
def test_obfuscated_attack_bypasses_keyword_guard_and_reaches_open_tool_policy(
    tmp_path: Path, fixture_dir: Path
) -> None:
    summary = run_scenario(
        RunConfig(
            scenario="attack-obfuscated",
            model_mode="fixture",
            policy_mode="open",
            input_guard_mode="keyword",
            artifact_root=tmp_path / "artifacts",
            fixture_dir=fixture_dir,
        )
    )

    events = read_jsonl(summary.artifact_dir / "events.jsonl")
    assert summary.result == "CANARY_TRIGGERED"
    assert summary.tool_name == "delete_demo_database"
    assert summary.canary_delta == 1
    assert any(
        event["event_type"] == "input.guard.decision" and event["decision"] == "ALLOW"
        for event in events
    )
    assert any(
        event["event_type"] == "policy.decision" and event["decision"] == "ALLOW"
        for event in events
    )


@pytest.mark.integration
def test_same_obfuscated_fixture_is_stopped_by_tool_allowlist(
    tmp_path: Path, fixture_dir: Path
) -> None:
    summary = run_scenario(
        RunConfig(
            scenario="attack-obfuscated",
            model_mode="fixture",
            policy_mode="allowlist",
            input_guard_mode="keyword",
            artifact_root=tmp_path / "artifacts",
            fixture_dir=fixture_dir,
        )
    )

    events = read_jsonl(summary.artifact_dir / "events.jsonl")
    assert summary.result == "POLICY_DENIED"
    assert summary.tool_name == "delete_demo_database"
    assert summary.canary_delta == 0
    assert any(
        event["event_type"] == "input.guard.decision" and event["decision"] == "ALLOW"
        for event in events
    )
    assert any(
        event["event_type"] == "policy.decision" and event["decision"] == "DENY" for event in events
    )
    assert not (summary.artifact_dir / "canary-events.jsonl").exists()


@pytest.mark.integration
def test_manifest_preserves_evidence_lineage_without_secrets(
    tmp_path: Path, fixture_dir: Path
) -> None:
    summary = run_scenario(
        RunConfig(
            scenario="attack",
            model_mode="fixture",
            policy_mode="open",
            artifact_root=tmp_path / "artifacts",
            fixture_dir=fixture_dir,
        )
    )

    manifest_text = (summary.artifact_dir / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    expected_hash = hashlib.sha256((fixture_dir / "attack-log.jsonl").read_bytes()).hexdigest()
    assert manifest["runtime"] == "google-adk-python"
    assert manifest["model_provider"] == "fixture"
    assert manifest["model_name"] == "deterministic-adk-callback"
    assert manifest["fixture_sha256"] == expected_hash
    assert manifest["trace_id"] == summary.trace_id
    assert re.fullmatch(r"[0-9a-f]{32}", manifest["trace_id"])
    assert "api_key" not in manifest_text.lower()
    assert "GEMINI_API_KEY" not in manifest_text


def test_invalid_run_configuration_is_rejected(tmp_path: Path, fixture_dir: Path) -> None:
    with pytest.raises(ValueError, match="unsupported scenario"):
        RunConfig(
            scenario="production",
            model_mode="fixture",
            policy_mode="open",
            artifact_root=tmp_path / "artifacts",
            fixture_dir=fixture_dir,
        )

    with pytest.raises(ValueError, match="unsupported input guard mode"):
        RunConfig(
            scenario="normal",
            model_mode="fixture",
            policy_mode="open",
            input_guard_mode="magic",
            artifact_root=tmp_path / "artifacts",
            fixture_dir=fixture_dir,
        )


def test_canary_outcome_is_not_overwritten_by_a_later_successful_tool() -> None:
    state = ExecutionState(
        tool_name="query_metrics",
        result="SUCCESS",
        canary_delta=1,
    )

    result, tool_name = resolve_run_outcome(state)

    assert result == "CANARY_TRIGGERED"
    assert tool_name == "delete_demo_database"


def test_policy_denial_is_not_overwritten_by_a_later_successful_tool() -> None:
    state = ExecutionState(
        tool_name="query_metrics",
        result="SUCCESS",
        denied_tool_name="delete_demo_database",
    )

    result, tool_name = resolve_run_outcome(state)

    assert result == "POLICY_DENIED"
    assert tool_name == "delete_demo_database"
