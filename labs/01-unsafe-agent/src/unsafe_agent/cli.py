import argparse
import json
import logging
import os
import sys
from pathlib import Path

from unsafe_agent.artifacts import cleanup_artifacts
from unsafe_agent.config import RunConfig
from unsafe_agent.replay import replay_trace
from unsafe_agent.runner import LabRunError, run_scenario


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the safe iThome Lab 01 Agent.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one isolated scenario.")
    run_parser.add_argument(
        "--scenario", choices=("normal", "attack", "attack-obfuscated"), required=True
    )
    run_parser.add_argument("--model", choices=("fixture", "live"), required=True)
    run_parser.add_argument("--policy", choices=("open", "allowlist"), required=True)
    run_parser.add_argument("--input-guard", choices=("none", "keyword"), default="none")
    run_parser.add_argument("--model-name", default=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    run_parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    run_parser.add_argument("--fixture-dir", type=Path, default=Path("fixtures"))

    clean_parser = subparsers.add_parser("clean", help="Remove marked Lab 01 artifacts.")
    clean_parser.add_argument("--lab-root", type=Path, default=Path.cwd())

    replay_parser = subparsers.add_parser("replay", help="Print one trace as an event timeline.")
    replay_parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    replay_parser.add_argument("--trace-id", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "clean":
        cleanup_artifacts(args.lab_root)
        return
    if args.command == "replay":
        print(
            json.dumps(
                replay_trace(args.artifact_root, args.trace_id), ensure_ascii=False, indent=2
            )
        )
        return

    previous_logging_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        try:
            summary = run_scenario(
                RunConfig(
                    scenario=args.scenario,
                    model_mode=args.model,
                    policy_mode=args.policy,
                    input_guard_mode=args.input_guard,
                    artifact_root=args.artifact_root,
                    fixture_dir=args.fixture_dir,
                    model_name=args.model_name,
                )
            )
        except LabRunError as exc:
            print(
                json.dumps(
                    {
                        "artifact_dir": str(exc.artifact_dir),
                        "error_code": exc.error_code,
                        "trace_id": exc.trace_id,
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            raise SystemExit(2) from None
    finally:
        logging.disable(previous_logging_level)
    print(json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=True))
