"""Command-line entrypoint for Lab 03."""

import argparse
from pathlib import Path

from gateway_runtime.artifacts import cleanup_artifacts
from gateway_runtime.demo import run_lab
from gateway_runtime.kagent_boundary import run_boundary_lab, validate_kind_context
from gateway_runtime.traffic import run_traffic_lab


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gateway-runtime")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run", help="run all nine cases through agentgateway")
    run.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    traffic = subcommands.add_parser("traffic", help="run the Day 15 traffic-boundary cases")
    traffic.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    kagent = subcommands.add_parser(
        "kagent-boundary", help="assess the Day 16 kagent and agentgateway ownership boundary"
    )
    kagent.add_argument("--config-dir", type=Path, default=Path("configs/day-16"))
    kagent.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    guard = subcommands.add_parser(
        "kagent-context-guard",
        help="refuse every kubeconfig context except the disposable Day 16 kind cluster",
    )
    guard.add_argument("--kubeconfig", type=Path, required=True)
    guard.add_argument("--context", required=True)
    clean = subcommands.add_parser("clean", help="remove only marked Lab 03 artifacts")
    clean.add_argument("--lab-root", type=Path, default=Path.cwd())
    return parser


def entrypoint() -> None:
    args = build_parser().parse_args()
    if args.command == "kagent-context-guard":
        validate_kind_context(args.kubeconfig, args.context)
        print(f"context-ok={args.context}")
        return

    if args.command == "clean":
        cleanup_artifacts(args.lab_root)
        print("Lab 03 artifacts removed")
        return

    if args.command == "kagent-boundary":
        report = run_boundary_lab(args.config_dir, args.artifact_root)
        evidence_name = "kagent-terminal.txt"
    elif args.command == "traffic":
        report = run_traffic_lab(args.artifact_root)
        evidence_name = "traffic-terminal.txt"
    else:
        report = run_lab(args.artifact_root)
        evidence_name = "terminal.txt"
    print(Path(report["artifact_dir"]) / "evidence" / evidence_name)
    if args.command == "kagent-boundary":
        summary = report["summary"]
        print(f"PASS {summary['pass']} / PARTIAL {summary['partial']} / FAIL {summary['fail']}")
    else:
        print(f"matched {report['summary']['matched']}/{report['summary']['total']}")
