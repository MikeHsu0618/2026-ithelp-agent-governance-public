import json
import re
from pathlib import Path

from identity_boundary.oauth_flow_demo import run_oauth_flow_demo

JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def test_oauth_flow_demo_matches_all_expected_results(tmp_path: Path) -> None:
    summary = run_oauth_flow_demo(tmp_path / "artifacts")

    assert summary.matched == summary.total == 9
    assert {
        result.case_id: (result.flow, result.decision, result.code) for result in summary.results
    } == {
        "pkce_human_success": ("PKCE", "ISSUE", "TOKEN_ISSUED"),
        "pkce_callback_mismatch": ("PKCE", "DENY", "REDIRECT_URI_MISMATCH"),
        "pkce_invalid_scope": ("PKCE", "DENY", "INVALID_SCOPE"),
        "pkce_unregistered_client": ("PKCE", "DENY", "CLIENT_NOT_REGISTERED"),
        "client_credentials_success": ("CLIENT_CREDENTIALS", "ISSUE", "TOKEN_ISSUED"),
        "client_credentials_public_client": (
            "CLIENT_CREDENTIALS",
            "DENY",
            "UNAUTHORIZED_CLIENT",
        ),
        "token_exchange_success": ("TOKEN_EXCHANGE", "ISSUE", "TOKEN_ISSUED"),
        "token_exchange_invalid_target": (
            "TOKEN_EXCHANGE",
            "DENY",
            "INVALID_TARGET",
        ),
        "token_exchange_wrong_subject_audience": (
            "TOKEN_EXCHANGE",
            "DENY",
            "SUBJECT_TOKEN_INVALID",
        ),
    }


def test_successful_flows_keep_principal_semantics_separate(tmp_path: Path) -> None:
    summary = run_oauth_flow_demo(tmp_path / "artifacts")
    by_case = {result.case_id: result for result in summary.results}

    assert by_case["pkce_human_success"].subject == "user/sre-oncaller"
    assert by_case["pkce_human_success"].actor == "user/sre-oncaller"
    assert by_case["client_credentials_success"].subject == "client/sre-scheduler"
    assert by_case["client_credentials_success"].actor == "client/sre-scheduler"
    assert by_case["token_exchange_success"].subject == "user/sre-oncaller"
    assert by_case["token_exchange_success"].actor == "client/sre-investigator-runtime"


def test_oauth_evidence_contains_safe_fingerprints_but_no_credentials(tmp_path: Path) -> None:
    summary = run_oauth_flow_demo(tmp_path / "artifacts")
    manifest = json.loads((summary.run_dir / "manifest.json").read_text(encoding="utf-8"))
    credentials = json.loads(
        (summary.run_dir / "credential-fingerprints.json").read_text(encoding="utf-8")
    )

    assert manifest["slice"] == "day-11-oauth-flows"
    assert manifest["raw_credentials_persisted"] is False
    assert manifest["authorization_codes_persisted"] is False
    assert manifest["pkce_verifiers_persisted"] is False
    assert manifest["client_secrets_persisted"] is False
    assert credentials["raw_credentials_persisted"] is False
    assert all(
        value.startswith("sha256:")
        for key, value in credentials.items()
        if key != "raw_credentials_persisted"
    )

    all_evidence = "\n".join(
        path.read_text(encoding="utf-8") for path in summary.run_dir.rglob("*") if path.is_file()
    )
    assert not JWT_PATTERN.search(all_evidence)
    assert "PRIVATE KEY" not in all_evidence
    assert '"code_verifier":' not in all_evidence
    assert '"client_secret":' not in all_evidence
