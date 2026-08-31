import json
import re
from pathlib import Path

from identity_boundary.passthrough_demo import run_passthrough_demo

JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def test_passthrough_demo_matches_all_expected_results(tmp_path: Path) -> None:
    summary = run_passthrough_demo(tmp_path / "artifacts")

    assert summary.matched == summary.total == 7
    assert {
        result.case_id: (result.decision, result.code, result.attribution)
        for result in summary.results
    } == {
        "user_to_entry_resource": ("ALLOW", "ALLOW", "TOKEN_SUBJECT_AT_ENTRY"),
        "passthrough_to_tool_strict": ("DENY", "AUDIENCE_MISMATCH", "NOT_EVALUATED"),
        "passthrough_shared_audience": (
            "ALLOW",
            "ALLOW",
            "COLLAPSED_TO_TOKEN_SUBJECT",
        ),
        "audience_bound_downstream": ("ALLOW", "ALLOW", "FULL_CHAIN"),
        "downstream_token_replay_entry": (
            "DENY",
            "AUDIENCE_MISMATCH",
            "NOT_EVALUATED",
        ),
        "missing_delegation_context": (
            "DENY",
            "DELEGATION_CONTEXT_REQUIRED",
            "NOT_EVALUATED",
        ),
        "mismatched_delegation_context": (
            "DENY",
            "DELEGATION_CONTEXT_MISMATCH",
            "NOT_EVALUATED",
        ),
    }


def test_same_human_token_is_visible_across_passthrough_hops(tmp_path: Path) -> None:
    summary = run_passthrough_demo(tmp_path / "artifacts")
    events = _read_jsonl(summary.run_dir / "events.jsonl")
    by_case = {event["case_id"]: event for event in events}

    entry_fingerprint = by_case["user_to_entry_resource"]["credential_fingerprint"]
    assert by_case["passthrough_to_tool_strict"]["credential_fingerprint"] == entry_fingerprint
    assert by_case["passthrough_shared_audience"]["credential_fingerprint"] == entry_fingerprint
    assert by_case["passthrough_shared_audience"]["token_subject"] == "user/sre-oncaller"
    assert by_case["passthrough_shared_audience"]["executing_agent"] == "UNKNOWN"
    assert by_case["passthrough_shared_audience"]["workload_principal"] == "UNKNOWN"


def test_audience_bound_token_preserves_full_chain_and_cannot_be_replayed_at_entry(
    tmp_path: Path,
) -> None:
    summary = run_passthrough_demo(tmp_path / "artifacts")
    events = _read_jsonl(summary.run_dir / "events.jsonl")
    by_case = {event["case_id"]: event for event in events}

    downstream = by_case["audience_bound_downstream"]
    replay = by_case["downstream_token_replay_entry"]
    entry = by_case["user_to_entry_resource"]

    assert downstream["human_principal"] == "user/sre-oncaller"
    assert downstream["token_subject"] == "client/sre-investigator-runtime"
    assert downstream["executing_agent"] == "agent/sre-investigator@v1"
    assert downstream["workload_principal"] == "k8s://lab/identity-boundary/sa/sre-agent"
    assert downstream["credential_fingerprint"] != entry["credential_fingerprint"]
    assert replay["credential_fingerprint"] == downstream["credential_fingerprint"]
    assert replay["code"] == "AUDIENCE_MISMATCH"
    assert replay["token_subject"] == "UNVERIFIED"


def test_passthrough_evidence_contains_fingerprints_but_no_raw_credentials(tmp_path: Path) -> None:
    summary = run_passthrough_demo(tmp_path / "artifacts")

    manifest = json.loads((summary.run_dir / "manifest.json").read_text(encoding="utf-8"))
    fingerprints = json.loads(
        (summary.run_dir / "token-fingerprints.json").read_text(encoding="utf-8")
    )
    assert manifest["slice"] == "day-10-token-passthrough"
    assert manifest["raw_credentials_persisted"] is False
    assert manifest["same_user_token_reused_across_hops"] is True
    assert fingerprints["user_access_token"].startswith("sha256:")
    assert fingerprints["downstream_access_token"].startswith("sha256:")
    assert fingerprints["user_access_token"] != fingerprints["downstream_access_token"]

    all_evidence = "\n".join(
        path.read_text(encoding="utf-8") for path in summary.run_dir.rglob("*") if path.is_file()
    )
    assert not JWT_PATTERN.search(all_evidence)
    assert "PRIVATE KEY" not in all_evidence


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
