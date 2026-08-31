import json
import re
from pathlib import Path

from identity_boundary.cognito_demo import run_cognito_demo

JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def test_cognito_demo_matches_human_and_m2m_contract_cases(tmp_path: Path) -> None:
    summary = run_cognito_demo(tmp_path / "artifacts")

    assert summary.matched == summary.total == 9
    assert {
        result.case_id: (result.path, result.decision, result.code) for result in summary.results
    } == {
        "human_pkce_success": ("HUMAN", "ALLOW", "POLICY_ALLOWED"),
        "human_callback_mismatch": ("HUMAN", "DENY", "REDIRECT_URI_MISMATCH"),
        "human_scope_invalid": ("HUMAN", "DENY", "INVALID_SCOPE"),
        "human_missing_policy_claim": ("HUMAN", "DENY", "CLAIM_MISSING"),
        "m2m_client_credentials_success": ("M2M", "ALLOW", "POLICY_ALLOWED"),
        "m2m_public_client": ("M2M", "DENY", "UNAUTHORIZED_CLIENT"),
        "m2m_wrong_secret": ("M2M", "DENY", "INVALID_CLIENT"),
        "m2m_openid_scope": ("M2M", "DENY", "INVALID_SCOPE"),
        "m2m_resource_binding": ("M2M", "DENY", "RESOURCE_BINDING_UNSUPPORTED"),
    }


def test_successful_paths_keep_audit_principals_separate(tmp_path: Path) -> None:
    summary = run_cognito_demo(tmp_path / "artifacts")
    by_case = {result.case_id: result for result in summary.results}

    assert by_case["human_pkce_success"].subject == "user/sre-oncaller"
    assert by_case["human_pkce_success"].actor == "user/sre-oncaller"
    assert by_case["human_pkce_success"].audience == "https://observability.lab.example/mcp"
    assert by_case["m2m_client_credentials_success"].subject == "NOT_APPLICABLE"
    assert by_case["m2m_client_credentials_success"].actor == "client/sre-scheduler"
    assert by_case["m2m_client_credentials_success"].audience == "NOT_PRESENT"


def test_cognito_evidence_is_synthetic_and_contains_no_raw_credentials(tmp_path: Path) -> None:
    summary = run_cognito_demo(tmp_path / "artifacts")
    manifest = json.loads((summary.run_dir / "manifest.json").read_text(encoding="utf-8"))
    registrations = json.loads((summary.run_dir / "registrations.json").read_text(encoding="utf-8"))

    assert manifest["slice"] == "day-12-cognito-dual-path"
    assert manifest["synthetic_identities_only"] is True
    assert manifest["raw_credentials_persisted"] is False
    assert manifest["client_secrets_persisted"] is False
    assert registrations["clients"][1]["secret_stored"] == "scrypt-verifier-only"

    all_evidence = "\n".join(
        path.read_text(encoding="utf-8") for path in summary.run_dir.rglob("*") if path.is_file()
    )
    assert not JWT_PATTERN.search(all_evidence)
    assert "PRIVATE KEY" not in all_evidence
    assert '"client_secret"' not in all_evidence
    assert "synthetic-m2m-secret" not in all_evidence
