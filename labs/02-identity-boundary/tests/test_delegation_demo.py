import json
import re
from pathlib import Path

from identity_boundary.delegation_demo import run_delegation_demo

JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def test_delegation_demo_matches_all_expected_results(tmp_path: Path) -> None:
    summary = run_delegation_demo(tmp_path / "artifacts")

    assert summary.matched == summary.total == 7
    assert {result.case_id: result.code for result in summary.results} == {
        "human_delegated": "ACCEPT",
        "scheduled_service": "ACCEPT",
        "a2a_unknown_workload": "ACCEPT",
        "missing_workload_slot": "REQUIRED_FIELD_MISSING",
        "human_null": "NULL_NOT_ALLOWED",
        "duplicate_agent_sequence": "AGENT_SEQUENCE_INVALID",
        "actor_only": "REQUIRED_FIELD_MISSING",
    }


def test_delegation_demo_writes_queryable_safe_evidence(tmp_path: Path) -> None:
    summary = run_delegation_demo(tmp_path / "artifacts")

    manifest = json.loads((summary.run_dir / "manifest.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (summary.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    accepted = json.loads(
        (summary.run_dir / "contexts" / "human_delegated.json").read_text(encoding="utf-8")
    )

    assert manifest["slice"] == "day-09-delegation-context"
    assert manifest["raw_credentials_persisted"] is False
    assert len(events) == 7
    assert events[0]["human_state"] == "PRESENT"
    assert events[0]["service_state"] == "NOT_APPLICABLE"
    assert events[0]["agent_chain"] == ["agent/sre-copilot@v1", "agent/sre-investigator@v1"]
    assert events[0]["workload_state"] == "PRESENT"
    assert accepted["actor_chain"]["service"] == {
        "state": "NOT_APPLICABLE",
        "reason": "human delegated flow has no separate service actor",
    }
    assert accepted["credential"]["client_id"] == "sre-console"
    assert accepted["credential"]["fingerprint"].startswith("sha256:")

    all_evidence = "\n".join(
        path.read_text(encoding="utf-8") for path in summary.run_dir.rglob("*") if path.is_file()
    )
    assert not JWT_PATTERN.search(all_evidence)
    assert "PRIVATE KEY" not in all_evidence
