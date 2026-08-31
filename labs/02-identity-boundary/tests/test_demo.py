import json
import re
from pathlib import Path

from identity_boundary.demo import run_demo

EXPECTED_CASES = {
    "valid_access": (True, "ALLOW"),
    "wrong_issuer": (False, "ISSUER_MISMATCH"),
    "wrong_audience": (False, "AUDIENCE_MISMATCH"),
    "expired_access": (False, "TOKEN_EXPIRED"),
    "missing_scope": (False, "SCOPE_MISSING"),
    "access_missing_team": (False, "CLAIM_MISSING"),
    "id_token_has_team": (False, "TOKEN_TYPE_INVALID"),
}


def test_demo_matches_all_positive_and_negative_expectations(tmp_path: Path) -> None:
    summary = run_demo(tmp_path / "artifacts")

    assert summary.matched == summary.total == len(EXPECTED_CASES)
    assert {result.case_id: (result.allowed, result.code) for result in summary.results} == (
        EXPECTED_CASES
    )


def test_demo_writes_the_evidence_contract_without_bearer_tokens(tmp_path: Path) -> None:
    summary = run_demo(tmp_path / "artifacts")
    run_dir = summary.run_dir

    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "summary.json").is_file()
    assert (run_dir / "events.jsonl").is_file()
    assert (run_dir / "jwks.json").is_file()
    for case_id in EXPECTED_CASES:
        assert (run_dir / "tokens" / "decoded" / f"{case_id}.json").is_file()
        assert (run_dir / "expected" / f"{case_id}.json").is_file()

    persisted = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.rglob("*") if path.is_file()
    )
    compact_jwt = re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
    assert compact_jwt.search(persisted) is None
    assert "BEGIN PRIVATE KEY" not in persisted
    assert "BEGIN RSA PRIVATE KEY" not in persisted

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["encoded_tokens_persisted"] is False
    assert manifest["private_key_persisted"] is False
    assert manifest["fixture_hash"].startswith("sha256:")


def test_events_keep_decision_codes_but_not_claim_values(tmp_path: Path) -> None:
    summary = run_demo(tmp_path / "artifacts")
    events = [
        json.loads(line)
        for line in (summary.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert len(events) == len(EXPECTED_CASES)
    assert {event["decision_code"] for event in events} >= {
        "ALLOW",
        "AUDIENCE_MISMATCH",
        "CLAIM_MISSING",
    }
    assert all("token" not in event for event in events)
    assert all("claims" not in event for event in events)
