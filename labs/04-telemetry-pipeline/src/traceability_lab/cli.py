from __future__ import annotations

import argparse
import json
from pathlib import Path

from traceability_lab.artifacts import cleanup_artifacts, package_public_evidence
from traceability_lab.backend import (
    verify_backend,
    verify_cardinality_backend,
    verify_cost_fallback_backend,
    verify_identity_backend,
    verify_suite_backend,
)
from traceability_lab.cardinality import prepare_identity_material, run_cardinality_traffic
from traceability_lab.contract import (
    ContractError,
    build_action_context,
    build_governance_event,
    validate_governance_event,
)
from traceability_lab.cost_fallback import run_cost_fallback_traffic
from traceability_lab.identity_run import run_identity_projection
from traceability_lab.mcp_outcome import run_mcp_outcome_traffic
from traceability_lab.runner import run_action
from traceability_lab.sre_agent import run_sre_agent_investigation
from traceability_lab.suite import run_suite


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the safe Agent traceability Lab.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    run_parser.add_argument("--otlp-endpoint")

    suite_parser = subparsers.add_parser("run-suite")
    suite_parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    suite_parser.add_argument("--otlp-endpoint", default="http://127.0.0.1:14318")
    suite_parser.add_argument("--gateway-url", default="http://127.0.0.1:18080")
    suite_parser.add_argument("--drop-mcp-context", action="store_true")

    identity_parser = subparsers.add_parser("identity-projection")
    identity_parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    identity_parser.add_argument("--otlp-endpoint", default="http://127.0.0.1:14318")

    cardinality_prepare_parser = subparsers.add_parser("cardinality-prepare")
    cardinality_prepare_parser.add_argument("--runtime-dir", type=Path, required=True)

    cardinality_run_parser = subparsers.add_parser("cardinality-run")
    cardinality_run_parser.add_argument("--runtime-dir", type=Path, required=True)
    cardinality_run_parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    cardinality_run_parser.add_argument("--user-count", type=int, default=30)
    cardinality_run_parser.add_argument("--conversations-per-user", type=int, default=3)
    cardinality_run_parser.add_argument("--bounded-gateway-url", default="http://127.0.0.1:28081")
    cardinality_run_parser.add_argument("--user-gateway-url", default="http://127.0.0.1:28082")
    cardinality_run_parser.add_argument(
        "--conversation-gateway-url", default="http://127.0.0.1:28083"
    )

    cost_fallback_parser = subparsers.add_parser("cost-fallback-run")
    cost_fallback_parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    cost_fallback_parser.add_argument("--summary-output", type=Path)
    cost_fallback_parser.add_argument("--failover-gateway-url", default="http://127.0.0.1:28084")
    cost_fallback_parser.add_argument("--retry-gateway-url", default="http://127.0.0.1:28085")

    mcp_outcome_parser = subparsers.add_parser("mcp-outcome-run")
    mcp_outcome_parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    mcp_outcome_parser.add_argument("--summary-output", type=Path)
    mcp_outcome_parser.add_argument("--good-gateway-url", default="http://127.0.0.1:25080/mcp")
    mcp_outcome_parser.add_argument("--html-gateway-url", default="http://127.0.0.1:25081/mcp")
    mcp_outcome_parser.add_argument("--loki-url", default="http://127.0.0.1:25100")
    mcp_outcome_parser.add_argument("--grafana-url", default="http://127.0.0.1:25000")
    mcp_outcome_parser.add_argument("--html-fixture-url", default="http://127.0.0.1:25090")

    sre_agent_parser = subparsers.add_parser("sre-agent-run")
    sre_agent_parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    sre_agent_parser.add_argument("--summary-output", type=Path)
    sre_agent_parser.add_argument("--gateway-url", default="http://127.0.0.1:25080/mcp")
    sre_agent_parser.add_argument("--loki-url", default="http://127.0.0.1:25100")
    sre_agent_parser.add_argument("--grafana-url", default="http://127.0.0.1:25000")

    subparsers.add_parser("negative")

    verify_parser = subparsers.add_parser("verify-backend")
    verify_parser.add_argument("--artifact-dir", type=Path, required=True)
    verify_parser.add_argument("--tempo-url", default="http://127.0.0.1:13200")
    verify_parser.add_argument("--loki-url", default="http://127.0.0.1:13100")

    verify_suite_parser = subparsers.add_parser("verify-suite")
    verify_suite_parser.add_argument("--scenario-report", type=Path, required=True)
    verify_suite_parser.add_argument("--tempo-url", default="http://127.0.0.1:13200")
    verify_suite_parser.add_argument("--loki-url", default="http://127.0.0.1:13100")
    verify_suite_parser.add_argument("--prometheus-url", default="http://127.0.0.1:19090")

    verify_identity_parser = subparsers.add_parser("verify-identity")
    verify_identity_parser.add_argument("--projection-report", type=Path, required=True)
    verify_identity_parser.add_argument("--tempo-url", default="http://127.0.0.1:13200")
    verify_identity_parser.add_argument("--loki-url", default="http://127.0.0.1:13100")
    verify_identity_parser.add_argument("--prometheus-url", default="http://127.0.0.1:19090")

    verify_cardinality_parser = subparsers.add_parser("verify-cardinality")
    verify_cardinality_parser.add_argument("--run-report", type=Path, required=True)
    verify_cardinality_parser.add_argument("--loki-url", default="http://127.0.0.1:23100")
    verify_cardinality_parser.add_argument("--prometheus-url", default="http://127.0.0.1:29090")
    verify_cardinality_parser.add_argument("--tempo-url", default="http://127.0.0.1:23200")

    verify_cost_parser = subparsers.add_parser("verify-cost-fallback")
    verify_cost_parser.add_argument("--run-report", type=Path, required=True)
    verify_cost_parser.add_argument("--loki-url", default="http://127.0.0.1:24100")
    verify_cost_parser.add_argument("--prometheus-url", default="http://127.0.0.1:29091")
    verify_cost_parser.add_argument("--tempo-url", default="http://127.0.0.1:24200")
    verify_cost_parser.add_argument("--primary-provider-url", default="http://127.0.0.1:28086")
    verify_cost_parser.add_argument("--backup-provider-url", default="http://127.0.0.1:28087")
    verify_cost_parser.add_argument("--output", type=Path)

    package_parser = subparsers.add_parser("package-evidence")
    package_parser.add_argument("--artifact-dir", type=Path, required=True)
    package_parser.add_argument("--backend-report", type=Path, required=True)
    package_parser.add_argument("--destination", type=Path, required=True)

    clean_parser = subparsers.add_parser("clean")
    clean_parser.add_argument("--lab-root", type=Path, default=Path.cwd())
    return parser


def run_negative_case() -> dict[str, str]:
    context = build_action_context(
        action_id="act-day20-negative-case",
        trace_id="a" * 32,
        span_id="b" * 16,
        occurred_at="2026-09-12T00:00:00Z",
    )
    event = build_governance_event(context)
    del event["policy"]["version"]
    try:
        validate_governance_event(event)
    except ContractError as exc:
        return {
            "case": "missing-policy-version",
            "result": "REJECTED",
            "reason": str(exc),
        }
    raise RuntimeError("negative case unexpectedly passed validation")


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "clean":
        cleanup_artifacts(args.lab_root)
        return
    if args.command == "negative":
        print(json.dumps(run_negative_case(), ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "cardinality-prepare":
        material = prepare_identity_material(args.runtime_dir)
        print(json.dumps(material.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "cardinality-run":
        summary = run_cardinality_traffic(
            runtime_dir=args.runtime_dir,
            artifact_root=args.artifact_root,
            gateway_urls={
                "bounded": args.bounded_gateway_url,
                "user": args.user_gateway_url,
                "conversation": args.conversation_gateway_url,
            },
            user_count=args.user_count,
            conversations_per_user=args.conversations_per_user,
        )
        print(json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "cost-fallback-run":
        summary = run_cost_fallback_traffic(
            artifact_root=args.artifact_root,
            failover_gateway_url=args.failover_gateway_url,
            retry_gateway_url=args.retry_gateway_url,
        )
        if args.summary_output:
            args.summary_output.parent.mkdir(parents=True, exist_ok=True)
            args.summary_output.write_text(
                json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
        print(json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        if any(item["result"] == "UNEXPECTED_MODEL" for item in summary.scenarios):
            raise SystemExit(2)
        return
    if args.command == "mcp-outcome-run":
        summary = run_mcp_outcome_traffic(
            artifact_root=args.artifact_root,
            good_gateway_url=args.good_gateway_url,
            html_gateway_url=args.html_gateway_url,
            loki_url=args.loki_url,
            grafana_url=args.grafana_url,
            html_fixture_url=args.html_fixture_url,
        )
        payload = summary.to_json_dict()
        if args.summary_output:
            args.summary_output.parent.mkdir(parents=True, exist_ok=True)
            args.summary_output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        expected = {
            "upstream-200-html": {
                "client_http": "PASS",
                "mcp_contract": "PASS",
                "tool_result": "ERROR",
                "domain_outcome": "UNKNOWN",
                "classification": "TOOL_EXECUTION_ERROR",
            },
            "valid-empty-query": {
                "client_http": "PASS",
                "mcp_contract": "PASS",
                "tool_result": "PASS",
                "domain_outcome": "NO_MATCH",
                "classification": "VALID_BUT_EMPTY",
            },
            "usable-loki-result": {
                "client_http": "PASS",
                "mcp_contract": "PASS",
                "tool_result": "PASS",
                "domain_outcome": "USABLE",
                "classification": "USABLE_RESULT",
            },
        }
        observed = {item["scenario"]: item["assessment"] for item in summary.scenarios}
        if observed != expected:
            raise SystemExit(2)
        return
    if args.command == "sre-agent-run":
        summary = run_sre_agent_investigation(
            artifact_root=args.artifact_root,
            gateway_url=args.gateway_url,
            loki_url=args.loki_url,
            grafana_url=args.grafana_url,
        )
        payload = summary.to_json_dict()
        if args.summary_output:
            args.summary_output.parent.mkdir(parents=True, exist_ok=True)
            args.summary_output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "package-evidence":
        package_public_evidence(
            artifact_dir=args.artifact_dir,
            backend_report=args.backend_report,
            destination=args.destination,
        )
        (args.destination / "negative-report.json").write_text(
            json.dumps(run_negative_case(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return
    if args.command == "verify-backend":
        report = verify_backend(
            args.artifact_dir,
            tempo_url=args.tempo_url,
            loki_url=args.loki_url,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if report["correlation"] != "PASS":
            raise SystemExit(2)
        return
    if args.command == "verify-suite":
        report = verify_suite_backend(
            args.scenario_report,
            tempo_url=args.tempo_url,
            loki_url=args.loki_url,
            prometheus_url=args.prometheus_url,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if report["overall"] != "PASS":
            raise SystemExit(2)
        return
    if args.command == "verify-identity":
        report = verify_identity_backend(
            args.projection_report,
            tempo_url=args.tempo_url,
            loki_url=args.loki_url,
            prometheus_url=args.prometheus_url,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if report["overall"] != "PASS":
            raise SystemExit(2)
        return
    if args.command == "verify-cardinality":
        report = verify_cardinality_backend(
            args.run_report,
            loki_url=args.loki_url,
            prometheus_url=args.prometheus_url,
            tempo_url=args.tempo_url,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if report["overall"] != "PASS":
            raise SystemExit(2)
        return
    if args.command == "verify-cost-fallback":
        report = verify_cost_fallback_backend(
            args.run_report,
            loki_url=args.loki_url,
            prometheus_url=args.prometheus_url,
            tempo_url=args.tempo_url,
            primary_provider_url=args.primary_provider_url,
            backup_provider_url=args.backup_provider_url,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if report["overall"] != "PASS":
            raise SystemExit(2)
        return
    if args.command == "identity-projection":
        summary = run_identity_projection(
            artifact_root=args.artifact_root,
            otlp_endpoint=args.otlp_endpoint,
        )
        print(json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "run-suite":
        summary = run_suite(
            artifact_root=args.artifact_root,
            otlp_endpoint=args.otlp_endpoint,
            gateway_url=args.gateway_url,
            drop_mcp_context=args.drop_mcp_context,
        )
        print(json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        if any(item.status != "PASS" for item in summary.scenarios):
            raise SystemExit(2)
        return
    summary = run_action(artifact_root=args.artifact_root, otlp_endpoint=args.otlp_endpoint)
    print(json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=True))
