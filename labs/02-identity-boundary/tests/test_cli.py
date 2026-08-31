import json
from pathlib import Path

from identity_boundary.cli import main


def test_run_command_prints_a_copyable_summary(tmp_path: Path, capsys) -> None:
    exit_code = main(["run", "--artifact-root", str(tmp_path / "artifacts")])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "valid_access" in output
    assert "wrong_audience" in output
    assert "7/7 cases matched" in output
    assert "Encoded JWT persisted: no" in output


def test_run_command_can_print_machine_readable_json(tmp_path: Path, capsys) -> None:
    exit_code = main(["run", "--artifact-root", str(tmp_path / "artifacts"), "--output", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["matched"] == payload["total"] == 7
    assert Path(payload["run_dir"]).is_dir()


def test_clean_command_removes_generated_artifacts(tmp_path: Path, capsys) -> None:
    assert main(["run", "--artifact-root", str(tmp_path / "artifacts")]) == 0
    capsys.readouterr()

    exit_code = main(["clean", "--lab-root", str(tmp_path)])

    assert exit_code == 0
    assert not (tmp_path / "artifacts").exists()
    assert "Removed marked Lab 02 artifacts" in capsys.readouterr().out


def test_delegation_command_prints_actor_chain_summary(tmp_path: Path, capsys) -> None:
    exit_code = main(
        ["delegation", "--artifact-root", str(tmp_path / "artifacts"), "--output", "table"]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "human_delegated" in output
    assert "a2a_unknown_workload" in output
    assert "7/7 cases matched" in output
    assert "Raw credential persisted: no" in output


def test_passthrough_command_prints_audience_and_attribution_results(
    tmp_path: Path, capsys
) -> None:
    exit_code = main(
        ["passthrough", "--artifact-root", str(tmp_path / "artifacts"), "--output", "table"]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "passthrough_to_tool_strict" in output
    assert "passthrough_shared_audience" in output
    assert "COLLAPSED_TO_TOKEN_SUBJECT" in output
    assert "audience_bound_downstream" in output
    assert "FULL_CHAIN" in output
    assert "7/7 cases matched" in output
    assert "Raw credential persisted: no" in output


def test_oauth_command_prints_three_flow_results(tmp_path: Path, capsys) -> None:
    exit_code = main(["oauth", "--artifact-root", str(tmp_path / "artifacts"), "--output", "table"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "pkce_human_success" in output
    assert "client_credentials_success" in output
    assert "token_exchange_success" in output
    assert "pkce_callback_mismatch" in output
    assert "9/9 cases matched" in output
    assert "PKCE verifier persisted: no" in output
    assert "Client secret persisted: no" in output


def test_cognito_command_prints_two_identity_paths(tmp_path: Path, capsys) -> None:
    exit_code = main(
        ["cognito", "--artifact-root", str(tmp_path / "artifacts"), "--output", "table"]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "human_pkce_success" in output
    assert "m2m_client_credentials_success" in output
    assert "m2m_resource_binding" in output
    assert "9/9 cases matched" in output
    assert "M2M audience synthesized: no" in output
    assert "Client secret persisted: no" in output
