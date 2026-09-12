from __future__ import annotations

import argparse
import json
from pathlib import Path

from traceability_lab.artifacts import cleanup_artifacts, package_public_evidence
from traceability_lab.backend import verify_backend
from traceability_lab.contract import (
    ContractError,
    build_action_context,
    build_governance_event,
    validate_governance_event,
)
from traceability_lab.runner import run_action


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the safe Agent traceability Lab.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    run_parser.add_argument("--otlp-endpoint")

    subparsers.add_parser("negative")

    verify_parser = subparsers.add_parser("verify-backend")
    verify_parser.add_argument("--artifact-dir", type=Path, required=True)
    verify_parser.add_argument("--tempo-url", default="http://127.0.0.1:13200")
    verify_parser.add_argument("--loki-url", default="http://127.0.0.1:13100")

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
    summary = run_action(artifact_root=args.artifact_root, otlp_endpoint=args.otlp_endpoint)
    print(json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=True))
