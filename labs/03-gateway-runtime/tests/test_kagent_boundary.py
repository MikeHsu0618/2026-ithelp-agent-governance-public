from pathlib import Path

import pytest

from gateway_runtime.cli import build_parser
from gateway_runtime.kagent_boundary import (
    UnsafeKubeContextError,
    assess_boundary,
    ownership_matrix,
    render_terminal,
    run_boundary_lab,
    validate_kind_context,
)


def _fixture_values() -> dict:
    return {
        "proxy": {"url": "http://agentgateway-proxy.agentgateway-system.svc.cluster.local:80"},
        "kmcp": {"enabled": False},
        "kagent-tools": {"enabled": False},
    }


def _fixture_resources() -> list[dict]:
    return [
        {
            "apiVersion": "kagent.dev/v1alpha2",
            "kind": "ModelConfig",
            "metadata": {"name": "day16-model", "namespace": "day16-lab"},
            "spec": {
                "provider": "OpenAI",
                "model": "synthetic-model",
                "apiKeySecret": "day16-model-credential",
                "apiKeySecretKey": "api-key",
                "openAI": {
                    "baseUrl": (
                        "http://agentgateway-proxy.agentgateway-system.svc.cluster.local:80/v1"
                    ),
                    "reasoningEffort": "low",
                },
            },
        },
        {
            "apiVersion": "kagent.dev/v1alpha2",
            "kind": "RemoteMCPServer",
            "metadata": {"name": "day16-tools", "namespace": "day16-lab"},
            "spec": {
                "description": "Synthetic read-only tools",
                "protocol": "STREAMABLE_HTTP",
                "url": "http://mcp-everything.day16-lab.svc.cluster.local:3001/mcp",
                "headersFrom": [
                    {
                        "name": "Authorization",
                        "valueFrom": {
                            "type": "Secret",
                            "name": "day16-mcp-credential",
                            "key": "authorization",
                        },
                    }
                ],
            },
        },
        {
            "apiVersion": "kagent.dev/v1alpha2",
            "kind": "Agent",
            "metadata": {"name": "day16-agent", "namespace": "day16-lab"},
            "spec": {
                "type": "Declarative",
                "declarative": {
                    "runtime": "go",
                    "modelConfig": "day16-model",
                    "systemMessage": "Use read-only tools.",
                    "tools": [
                        {
                            "type": "McpServer",
                            "mcpServer": {
                                "apiGroup": "kagent.dev",
                                "kind": "RemoteMCPServer",
                                "name": "day16-tools",
                                "toolNames": ["echo"],
                            },
                        }
                    ],
                },
            },
        },
    ]


def test_kind_guard_accepts_only_the_owned_day16_context(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "day16.kubeconfig"
    kubeconfig.write_text("fixture\n", encoding="utf-8")

    validate_kind_context(kubeconfig, "kind-ithelp-day16")

    for context in ("production-cluster", "kind-other-lab", "ithelp-day16"):
        with pytest.raises(UnsafeKubeContextError):
            validate_kind_context(kubeconfig, context)


def test_kind_guard_accepts_an_explicitly_owned_day19_context(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "day19.kubeconfig"
    kubeconfig.write_text("fixture\n", encoding="utf-8")

    validate_kind_context(
        kubeconfig,
        "kind-ithelp-day19",
        expected_context="kind-ithelp-day19",
    )


def test_kind_guard_rejects_an_arbitrary_self_declared_context(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "other.kubeconfig"
    kubeconfig.write_text("fixture\n", encoding="utf-8")

    with pytest.raises(UnsafeKubeContextError, match="not an owned Lab context"):
        validate_kind_context(
            kubeconfig,
            "production-cluster",
            expected_context="production-cluster",
        )


def test_kind_guard_refuses_the_default_kubeconfig() -> None:
    with pytest.raises(UnsafeKubeContextError):
        validate_kind_context(Path.home() / ".kube" / "config", "kind-ithelp-day16")


def test_boundary_assessment_keeps_runtime_control_and_traffic_separate() -> None:
    report = assess_boundary(_fixture_values(), _fixture_resources())
    checks = {item["check_id"]: item for item in report["checks"]}

    assert report["versions"] == {"kagent": "0.10.0", "agentgateway": "1.5.0"}
    assert checks["declarative-runtime"]["status"] == "PASS"
    assert checks["llm-through-agentgateway"]["status"] == "PASS"
    assert checks["mcp-proxy-rewrite"]["status"] == "PASS"
    assert checks["reasoning-effort"]["status"] == "PASS"
    assert checks["mcp-credential-lifecycle"]["status"] == "PARTIAL"
    assert checks["advanced-workflow"]["status"] == "PARTIAL"
    assert report["summary"] == {"pass": 4, "partial": 2, "fail": 0, "total": 6}


def test_boundary_assessment_fails_when_paths_bypass_agentgateway() -> None:
    values = _fixture_values()
    values["proxy"]["url"] = ""
    resources = _fixture_resources()
    resources[0]["spec"]["openAI"]["baseUrl"] = "https://api.openai.com/v1"

    report = assess_boundary(values, resources)
    checks = {item["check_id"]: item for item in report["checks"]}

    assert checks["llm-through-agentgateway"]["status"] == "FAIL"
    assert checks["mcp-proxy-rewrite"]["status"] == "FAIL"


def test_ownership_matrix_has_one_source_of_truth_for_each_responsibility() -> None:
    rows = ownership_matrix()

    assert len(rows) == 8
    assert len({row["responsibility"] for row in rows}) == len(rows)
    assert all(row["source_of_truth"] for row in rows)
    assert next(row for row in rows if row["responsibility"] == "agent-runtime")["owner"] == (
        "application-team"
    )
    assert (
        next(row for row in rows if row["responsibility"] == "mcp-traffic-policy")["owner"]
        == "agentgateway"
    )


def test_terminal_output_labels_partial_results_without_calling_them_passes() -> None:
    output = render_terminal(assess_boundary(_fixture_values(), _fixture_resources()))

    assert "DAY 16 / KAGENT BOUNDARY" in output
    assert "mcp-credential-lifecycle" in output
    assert "PARTIAL" in output
    assert "PASS 4 / PARTIAL 2 / FAIL 0" in output


def test_boundary_runner_reads_public_yaml_and_writes_evidence(tmp_path: Path) -> None:
    config_dir = tmp_path / "day-16"
    config_dir.mkdir()
    values = _fixture_values()
    resources = _fixture_resources()
    import yaml

    (config_dir / "kagent-values.yaml").write_text(
        yaml.safe_dump(values, sort_keys=False), encoding="utf-8"
    )
    (config_dir / "kagent-resources.yaml").write_text(
        "---\n".join(yaml.safe_dump(item, sort_keys=False) for item in resources),
        encoding="utf-8",
    )

    report = run_boundary_lab(config_dir, tmp_path / "artifacts")
    evidence_dir = Path(report["artifact_dir"]) / "evidence"

    assert (evidence_dir / "kagent-boundary-report.json").is_file()
    assert (evidence_dir / "ownership-matrix.md").is_file()
    assert "PASS 4 / PARTIAL 2 / FAIL 0" in (evidence_dir / "kagent-terminal.txt").read_text()
    assert report["summary"]["partial"] == 2


def test_cli_accepts_the_day16_config_and_artifact_paths(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "kagent-boundary",
            "--config-dir",
            str(tmp_path / "configs"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )

    assert args.command == "kagent-boundary"
    assert args.config_dir == tmp_path / "configs"
    assert args.artifact_root == tmp_path / "artifacts"


def test_cli_accepts_the_day16_context_guard(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "kagent-context-guard",
            "--kubeconfig",
            str(tmp_path / "day16.kubeconfig"),
            "--context",
            "kind-ithelp-day16",
        ]
    )

    assert args.command == "kagent-context-guard"
    assert args.kubeconfig == tmp_path / "day16.kubeconfig"
    assert args.context == "kind-ithelp-day16"
    assert args.expected_context == "kind-ithelp-day16"


def test_cli_accepts_an_explicit_day19_context_guard(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "kagent-context-guard",
            "--kubeconfig",
            str(tmp_path / "day19.kubeconfig"),
            "--context",
            "kind-ithelp-day19",
            "--expected-context",
            "kind-ithelp-day19",
        ]
    )

    assert args.expected_context == "kind-ithelp-day19"
