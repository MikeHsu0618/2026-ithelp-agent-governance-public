from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from incident_replay.backend import query_modern_reference, validate_action_id, validate_trace_id
from incident_replay.contract import validate_replay_report
from incident_replay.evidence import load_case
from incident_replay.historical import reconstruct_action


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconstruct an Agent action without inventing missing evidence."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    historical = commands.add_parser(
        "historical", help="Reconstruct an action from a SHA-256-locked evidence case."
    )
    historical.add_argument("--case-dir", type=Path, required=True)
    historical.add_argument("--target-tool", required=True)
    historical.add_argument("--output", type=Path, required=True)

    modern = commands.add_parser(
        "modern", help="Verify a later action against the local LGTM backends."
    )
    modern.add_argument("--scenario-report", type=Path, required=True)
    modern.add_argument("--scenario", default="normal-call")
    modern.add_argument("--tempo-url", default="http://127.0.0.1:13200")
    modern.add_argument("--loki-url", default="http://127.0.0.1:13100")
    modern.add_argument("--prometheus-url", default="http://127.0.0.1:19090")
    modern.add_argument("--attempts", type=int, default=10)
    modern.add_argument("--output", type=Path, required=True)
    return parser


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _scenario_identifiers(report_path: Path, scenario_name: str) -> tuple[str, str, list[str]]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    scenarios = payload.get("scenarios", []) if isinstance(payload, dict) else []
    scenario = next(
        (
            item
            for item in scenarios
            if isinstance(item, dict) and item.get("scenario") == scenario_name
        ),
        None,
    )
    if scenario is None:
        raise ValueError(f"scenario not found in report: {scenario_name}")
    action_id = scenario.get("action_id")
    trace_id = scenario.get("trace_id")
    if not isinstance(action_id, str) or not isinstance(trace_id, str):
        raise ValueError(f"scenario is missing action_id or trace_id: {scenario_name}")
    action_id = validate_action_id(action_id)
    trace_id = validate_trace_id(trace_id)
    expected_services = scenario.get("expected_services")
    if (
        not isinstance(expected_services, list)
        or not expected_services
        or not all(
            isinstance(service, str) and service and service == service.strip()
            for service in expected_services
        )
        or len(set(expected_services)) != len(expected_services)
    ):
        raise ValueError(f"scenario has invalid expected_services: {scenario_name}")
    return action_id, trace_id, expected_services


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "historical":
        report = reconstruct_action(load_case(args.case_dir), target_tool=args.target_tool)
        validate_replay_report(report)
        _write_json(args.output, report)
        return 0

    action_id, trace_id, expected_services = _scenario_identifiers(
        args.scenario_report, args.scenario
    )
    report = query_modern_reference(
        action_id=action_id,
        trace_id=trace_id,
        expected_services=expected_services,
        tempo_url=args.tempo_url,
        loki_url=args.loki_url,
        prometheus_url=args.prometheus_url,
        attempts=args.attempts,
    )
    _write_json(args.output, report)
    complete = (
        report.get("tempo", {}).get("complete") is True
        and report.get("loki", {}).get("matched_action") is True
        and report.get("prometheus", {}).get("status") == "OBSERVED"
    )
    return 0 if complete else 1


if __name__ == "__main__":  # pragma: no cover - console script entry point
    raise SystemExit(main())
