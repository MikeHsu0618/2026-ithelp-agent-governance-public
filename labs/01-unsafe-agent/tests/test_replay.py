from pathlib import Path

import pytest

from unsafe_agent.config import RunConfig
from unsafe_agent.replay import TraceNotFoundError, replay_trace
from unsafe_agent.runner import run_scenario


def test_replay_returns_ordered_governance_timeline(tmp_path: Path, fixture_dir: Path) -> None:
    summary = run_scenario(
        RunConfig(
            scenario="attack",
            model_mode="fixture",
            policy_mode="open",
            artifact_root=tmp_path / "artifacts",
            fixture_dir=fixture_dir,
        )
    )

    timeline = replay_trace(tmp_path / "artifacts", summary.trace_id)

    assert [event["event_type"] for event in timeline] == [
        "run.started",
        "model.tool_call",
        "policy.decision",
        "tool.executed",
        "model.final_response",
        "run.completed",
    ]
    assert all(event["trace_id"] == summary.trace_id for event in timeline)


def test_replay_rejects_unknown_trace_id(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    with pytest.raises(TraceNotFoundError, match="trace ID was not found"):
        replay_trace(artifact_root, "0" * 32)
