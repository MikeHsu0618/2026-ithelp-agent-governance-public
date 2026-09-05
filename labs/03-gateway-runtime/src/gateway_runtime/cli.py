"""Command-line entrypoint for Lab 03."""

import argparse
from pathlib import Path

from gateway_runtime.artifacts import cleanup_artifacts
from gateway_runtime.demo import run_lab
from gateway_runtime.traffic import run_traffic_lab


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gateway-runtime")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run", help="run all nine cases through agentgateway")
    run.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    traffic = subcommands.add_parser("traffic", help="run the Day 15 traffic-boundary cases")
    traffic.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    clean = subcommands.add_parser("clean", help="remove only marked Lab 03 artifacts")
    clean.add_argument("--lab-root", type=Path, default=Path.cwd())
    return parser


def entrypoint() -> None:
    args = build_parser().parse_args()
    if args.command == "clean":
        cleanup_artifacts(args.lab_root)
        print("Lab 03 artifacts removed")
        return

    if args.command == "traffic":
        report = run_traffic_lab(args.artifact_root)
        evidence_name = "traffic-terminal.txt"
    else:
        report = run_lab(args.artifact_root)
        evidence_name = "terminal.txt"
    print(Path(report["artifact_dir"]) / "evidence" / evidence_name)
    print(f"matched {report['summary']['matched']}/{report['summary']['total']}")
