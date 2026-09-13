from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from traceability_lab.artifacts import ArtifactStore
from traceability_lab.runner import utc_now, validate_otlp_endpoint
from traceability_lab.scenarios import SCENARIOS, Scenario
from traceability_lab.telemetry import Telemetry


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario: str
    action_id: str
    trace_id: str
    http_status: int
    expected_result: str
    observed_result: str
    expected_services: tuple[str, ...]
    status: str


@dataclass(frozen=True, slots=True)
class SuiteSummary:
    run_id: str
    artifact_dir: str
    scenarios: tuple[ScenarioResult, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifact_dir": self.artifact_dir,
            "scenarios": [asdict(item) for item in self.scenarios],
        }


def validate_gateway_url(url: str) -> str:
    parsed = urlsplit(url.rstrip("/"))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("gateway URL must use http on localhost or 127.0.0.1")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("gateway URL must not include credentials, query, or fragment")
    return url.rstrip("/")


def classify_response(scenario: Scenario, status: int, payload: dict[str, Any]) -> str:
    if scenario.slug == "gateway-policy-deny" and status == 403:
        return "DENIED"
    result = payload.get("result")
    if isinstance(result, str):
        return result
    return f"UNEXPECTED_HTTP_{status}"


def run_suite(
    *,
    artifact_root: Path,
    otlp_endpoint: str,
    gateway_url: str,
    drop_mcp_context: bool = False,
) -> SuiteSummary:
    endpoint = validate_otlp_endpoint(otlp_endpoint)
    gateway = validate_gateway_url(gateway_url)
    run_id = f"day21-{uuid.uuid4().hex[:12]}"
    store = ArtifactStore(artifact_root, run_id)
    telemetry = Telemetry("ithelp-lab-client", endpoint)
    results: list[ScenarioResult] = []
    try:
        for scenario in SCENARIOS:
            action_id = f"act-{scenario.slug}-{uuid.uuid4().hex[:8]}"
            with telemetry.tracer.start_as_current_span(
                "agent.request",
                attributes={
                    "ithelp.governance.action_id": action_id,
                    "ithelp.lab.scenario": scenario.slug,
                },
            ) as span:
                context = span.get_span_context()
                headers = {"content-type": "application/json"}
                telemetry.inject(headers)
                body = {
                    "action_id": action_id,
                    "scenario": scenario.slug,
                    "drop_context": drop_mcp_context and scenario.slug == "normal-call",
                }
                status, payload = _post(gateway + scenario.request_path, headers, body)
                observed = classify_response(scenario, status, payload)
                telemetry.event(
                    {
                        "action_id": action_id,
                        "event": "client.observed_result",
                        "scenario": scenario.slug,
                        "result": observed,
                    }
                )
                results.append(
                    ScenarioResult(
                        scenario=scenario.slug,
                        action_id=action_id,
                        trace_id=f"{context.trace_id:032x}",
                        http_status=status,
                        expected_result=scenario.expected_result,
                        observed_result=observed,
                        expected_services=scenario.expected_services,
                        status="PASS" if observed == scenario.expected_result else "FAIL",
                    )
                )
    finally:
        telemetry.shutdown()

    summary = SuiteSummary(run_id, str(store.run_dir), tuple(results))
    store.write_json(
        "scenario-report.json",
        {
            **summary.to_json_dict(),
            "occurred_at": utc_now(),
            "drop_mcp_context": drop_mcp_context,
        },
    )
    store.write_json(
        "manifest.json",
        {
            "run_id": run_id,
            "artifact_dir": str(store.run_dir),
            "scenario_count": len(results),
            "all_scenarios_passed": all(item.status == "PASS" for item in results),
        },
    )
    return summary


def _post(url: str, headers: dict[str, str], body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = Request(
        url,
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - validated local URL
            return response.status, json.load(response)
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read())
        except json.JSONDecodeError:
            payload = {}
        return exc.code, payload
