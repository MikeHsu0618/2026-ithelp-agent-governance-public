import json
from types import SimpleNamespace

import pytest

from traceability_lab import cli
from traceability_lab.runner import validate_otlp_endpoint


def test_cli_run_prints_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli,
        "run_action",
        lambda **_: SimpleNamespace(
            to_json_dict=lambda: {"action_id": "act-day20-cli", "result": "CANARY_TRIGGERED"}
        ),
    )
    monkeypatch.setattr("sys.argv", ["traceability-lab", "run"])

    cli.main()

    assert json.loads(capsys.readouterr().out)["action_id"] == "act-day20-cli"


def test_cli_negative_reports_schema_rejection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["traceability-lab", "negative"])

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["result"] == "REJECTED"
    assert "policy" in output["reason"]


def test_cli_clean_delegates_to_guarded_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls = []
    monkeypatch.setattr(cli, "cleanup_artifacts", calls.append)
    monkeypatch.setattr("sys.argv", ["traceability-lab", "clean", "--lab-root", str(tmp_path)])

    cli.main()

    assert calls == [tmp_path]


def test_cli_package_evidence_redacts_local_artifact_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    run_dir = tmp_path / "artifacts" / "day20-fixture"
    run_dir.mkdir(parents=True)
    for filename in (
        "application-record.json",
        "governance-event.json",
        "operational-trace.json",
        "tool-receipt.json",
    ):
        (run_dir / filename).write_text(json.dumps({"source": filename}), encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "action_id": "act-day20-fixture",
                "trace_id": "a" * 32,
                "artifact_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    backend_report = tmp_path / "backend-report.json"
    backend_report.write_text(json.dumps({"correlation": "PASS"}), encoding="utf-8")
    destination = tmp_path / "public-evidence"
    monkeypatch.setattr(
        "sys.argv",
        [
            "traceability-lab",
            "package-evidence",
            "--artifact-dir",
            str(run_dir),
            "--backend-report",
            str(backend_report),
            "--destination",
            str(destination),
        ],
    )

    cli.main()

    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert "artifact_dir" not in manifest
    assert manifest["action_id"] == "act-day20-fixture"
    assert json.loads((destination / "backend-report.json").read_text())["correlation"] == "PASS"
    assert sorted(path.name for path in destination.iterdir()) == [
        "application-record.json",
        "backend-report.json",
        "governance-event.json",
        "manifest.json",
        "negative-report.json",
        "operational-trace.json",
        "tool-receipt.json",
    ]
    negative_report = json.loads((destination / "negative-report.json").read_text(encoding="utf-8"))
    assert negative_report["result"] == "REJECTED"
    assert "policy" in negative_report["reason"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://localhost:4318",
        "http://collector.example:4318",
        "http://user:pass@localhost:4318",
        "http://localhost:4318?token=secret",
    ],
)
def test_otlp_endpoint_is_restricted_to_plain_local_lab_urls(endpoint: str) -> None:
    with pytest.raises(ValueError, match="OTLP endpoint"):
        validate_otlp_endpoint(endpoint)


def test_otlp_endpoint_accepts_localhost() -> None:
    assert validate_otlp_endpoint("http://127.0.0.1:14318/") == "http://127.0.0.1:14318"
