"""Command-line interface for the Day 8–12 identity-boundary demos."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from identity_boundary.artifacts import cleanup_artifacts
from identity_boundary.cognito_demo import CognitoDemoSummary, run_cognito_demo
from identity_boundary.delegation_demo import DelegationDemoSummary, run_delegation_demo
from identity_boundary.demo import DemoSummary, run_demo
from identity_boundary.oauth_flow_demo import OAuthFlowDemoSummary, run_oauth_flow_demo
from identity_boundary.passthrough_demo import PassthroughDemoSummary, run_passthrough_demo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the offline Lab 02 JWT boundary cases")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run all positive and negative token cases")
    run.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    run.add_argument("--output", choices=("table", "json"), default="table")

    delegation = subparsers.add_parser("delegation", help="validate Day 9 delegation-context cases")
    delegation.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    delegation.add_argument("--output", choices=("table", "json"), default="table")

    passthrough = subparsers.add_parser(
        "passthrough", help="run Day 10 audience and attribution cases"
    )
    passthrough.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    passthrough.add_argument("--output", choices=("table", "json"), default="table")

    oauth = subparsers.add_parser(
        "oauth", help="compare PKCE, Client Credentials, and Token Exchange cases"
    )
    oauth.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    oauth.add_argument("--output", choices=("table", "json"), default="table")

    cognito = subparsers.add_parser(
        "cognito", help="compare Cognito-shaped Human and M2M app-client paths"
    )
    cognito.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    cognito.add_argument("--output", choices=("table", "json"), default="table")

    clean = subparsers.add_parser("clean", help="remove only marked Lab 02 artifacts")
    clean.add_argument("--lab-root", type=Path, default=Path.cwd())
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "clean":
        cleanup_artifacts(args.lab_root)
        print("Removed marked Lab 02 artifacts")
        return 0

    if args.command == "delegation":
        delegation_summary = run_delegation_demo(args.artifact_root)
        if args.output == "json":
            print(json.dumps(delegation_summary.to_json_dict(), ensure_ascii=False, indent=2))
        else:
            _print_delegation_table(delegation_summary)
        return 0 if delegation_summary.matched == delegation_summary.total else 1

    if args.command == "passthrough":
        passthrough_summary = run_passthrough_demo(args.artifact_root)
        if args.output == "json":
            print(json.dumps(passthrough_summary.to_json_dict(), ensure_ascii=False, indent=2))
        else:
            _print_passthrough_table(passthrough_summary)
        return 0 if passthrough_summary.matched == passthrough_summary.total else 1

    if args.command == "oauth":
        oauth_summary = run_oauth_flow_demo(args.artifact_root)
        if args.output == "json":
            print(json.dumps(oauth_summary.to_json_dict(), ensure_ascii=False, indent=2))
        else:
            _print_oauth_table(oauth_summary)
        return 0 if oauth_summary.matched == oauth_summary.total else 1

    if args.command == "cognito":
        cognito_summary = run_cognito_demo(args.artifact_root)
        if args.output == "json":
            print(json.dumps(cognito_summary.to_json_dict(), ensure_ascii=False, indent=2))
        else:
            _print_cognito_table(cognito_summary)
        return 0 if cognito_summary.matched == cognito_summary.total else 1

    summary = run_demo(args.artifact_root)
    if args.output == "json":
        print(json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2))
    else:
        _print_table(summary)
    return 0 if summary.matched == summary.total else 1


def _print_table(summary: DemoSummary) -> None:
    print(f"{'CASE':<24} {'EXPECTED':<10} {'ACTUAL':<10} CODE")
    print("-" * 74)
    for result in summary.results:
        expected = "ALLOW" if result.expected_allowed else "DENY"
        actual = "ALLOW" if result.allowed else "DENY"
        print(f"{result.case_id:<24} {expected:<10} {actual:<10} {result.code}")
    print()
    print(f"{summary.matched}/{summary.total} cases matched")
    print(f"Evidence: {summary.run_dir}")
    print("Encoded JWT persisted: no")
    print("Private key persisted: no")


def _print_delegation_table(summary: DelegationDemoSummary) -> None:
    print(f"{'CASE':<28} {'EXPECTED':<10} {'ACTUAL':<10} CODE")
    print("-" * 82)
    for result in summary.results:
        expected = "ACCEPT" if result.expected_accepted else "REJECT"
        actual = "ACCEPT" if result.accepted else "REJECT"
        print(f"{result.case_id:<28} {expected:<10} {actual:<10} {result.code}")
    print()
    print(f"{summary.matched}/{summary.total} cases matched")
    print(f"Evidence: {summary.run_dir}")
    print("Raw credential persisted: no")


def _print_passthrough_table(summary: PassthroughDemoSummary) -> None:
    print(f"{'CASE':<34} {'DECISION':<10} {'CODE':<30} ATTRIBUTION")
    print("-" * 112)
    for result in summary.results:
        print(f"{result.case_id:<34} {result.decision:<10} {result.code:<30} {result.attribution}")
    print()
    print(f"{summary.matched}/{summary.total} cases matched")
    print(f"Evidence: {summary.run_dir}")
    print("Same Human token reused across passthrough hops: yes (fingerprint only)")
    print("Raw credential persisted: no")


def _print_oauth_table(summary: OAuthFlowDemoSummary) -> None:
    print(f"{'CASE':<41} {'FLOW':<20} {'DECISION':<9} {'CODE':<28} PRINCIPAL")
    print("-" * 126)
    for result in summary.results:
        principal = (
            result.subject
            if result.subject == result.actor
            else f"{result.subject} via {result.actor}"
        )
        print(
            f"{result.case_id:<41} {result.flow:<20} "
            f"{result.decision:<9} {result.code:<28} {principal}"
        )
    print()
    print(f"{summary.matched}/{summary.total} cases matched")
    print(f"Evidence: {summary.run_dir}")
    print("Authorization code persisted: no")
    print("PKCE verifier persisted: no")
    print("Client secret persisted: no")
    print("Raw credential persisted: no")


def _print_cognito_table(summary: CognitoDemoSummary) -> None:
    print(f"{'CASE':<39} {'PATH':<8} {'DECISION':<9} {'CODE':<31} ACTOR")
    print("-" * 120)
    for result in summary.results:
        print(
            f"{result.case_id:<39} {result.path:<8} "
            f"{result.decision:<9} {result.code:<31} {result.actor}"
        )
    print()
    print(f"{summary.matched}/{summary.total} cases matched")
    print(f"Evidence: {summary.run_dir}")
    print("M2M audience synthesized: no")
    print("PKCE verifier persisted: no")
    print("Client secret persisted: no")
    print("Raw credential persisted: no")


def entrypoint() -> None:
    raise SystemExit(main())
