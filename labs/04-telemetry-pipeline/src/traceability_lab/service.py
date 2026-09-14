from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from opentelemetry.trace import Status, StatusCode

from traceability_lab.scenarios import get_scenario
from traceability_lab.telemetry import Telemetry


@dataclass(frozen=True, slots=True)
class RuntimePlan:
    result: str
    spans: tuple[str, ...]
    downstream_path: str


def build_runtime_plan(scenario_slug: str) -> RuntimePlan:
    get_scenario(scenario_slug)
    plans = {
        "normal-call": RuntimePlan(
            "CANARY_TRIGGERED", ("agent.runtime", "mcp.call"), "/mcp/execute"
        ),
        "hitl-approved": RuntimePlan(
            "APPROVED_AND_EXECUTED",
            ("agent.runtime", "hitl.approval", "mcp.call"),
            "/mcp/execute",
        ),
        "a2a-routing-failure": RuntimePlan(
            "ROUTING_FAILED", ("agent.runtime", "a2a.route"), "/a2a/missing"
        ),
        "llm-fallback": RuntimePlan(
            "FALLBACK_SUCCEEDED",
            (
                "agent.runtime",
                "llm.primary.failed",
                "llm.fallback.succeeded",
                "mcp.call",
            ),
            "/mcp/execute",
        ),
    }
    try:
        return plans[scenario_slug]
    except KeyError as exc:
        raise ValueError(f"scenario does not reach Runtime: {scenario_slug}") from exc


class LabApplication:
    def __init__(self, role: str, telemetry: Telemetry, gateway_url: str) -> None:
        self.role = role
        self.telemetry = telemetry
        self.gateway_url = gateway_url.rstrip("/")

    def handle(
        self, path: str, headers: dict[str, str], body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        if path == "/healthz":
            return HTTPStatus.OK, {"status": "ok", "role": self.role}
        if self.role == "runtime" and path == "/agent/run":
            return self._handle_runtime(headers, body)
        if self.role == "mcp" and path == "/mcp/execute":
            return self._handle_mcp(headers, body)
        if self.role == "cardinality" and path == "/cardinality/run":
            return HTTPStatus.OK, {
                "effect": "NO_OP_CARDINALITY_SAMPLE",
                "side_effects": 0,
                "status": "ok",
            }
        return HTTPStatus.NOT_FOUND, {"error": "route_not_found"}

    def _handle_runtime(
        self, headers: dict[str, str], body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        action_id = _required_text(body, "action_id")
        scenario_slug = _required_text(body, "scenario")
        plan = build_runtime_plan(scenario_slug)
        parent = self.telemetry.extract(headers)
        with self.telemetry.tracer.start_as_current_span(
            "agent.runtime",
            context=parent,
            attributes={
                "ithelp.governance.action_id": action_id,
                "ithelp.lab.scenario": scenario_slug,
            },
        ):
            self.telemetry.event(
                {
                    "action_id": action_id,
                    "event": "runtime.accepted",
                    "scenario": scenario_slug,
                }
            )
            for span_name in plan.spans[1:-1]:
                with self.telemetry.tracer.start_as_current_span(
                    span_name,
                    attributes={"ithelp.governance.action_id": action_id},
                ) as span:
                    if span_name.endswith("failed"):
                        span.set_status(Status(StatusCode.ERROR, "synthetic provider failure"))

            if plan.downstream_path == "/a2a/missing":
                return self._call_missing_a2a(action_id, scenario_slug, plan)
            return self._call_mcp(action_id, scenario_slug, plan, body)

    def _call_missing_a2a(
        self, action_id: str, scenario_slug: str, plan: RuntimePlan
    ) -> tuple[int, dict[str, Any]]:
        with self.telemetry.tracer.start_as_current_span(
            "a2a.route", attributes={"ithelp.governance.action_id": action_id}
        ) as span:
            try:
                self._post(plan.downstream_path, action_id, scenario_slug, drop_context=False)
            except (HTTPError, URLError) as exc:
                span.set_status(Status(StatusCode.ERROR, "synthetic route failure"))
                self.telemetry.event(
                    {
                        "action_id": action_id,
                        "event": "a2a.routing_failed",
                        "result": plan.result,
                        "error_type": type(exc).__name__,
                    }
                )
                return HTTPStatus.BAD_GATEWAY, {
                    "action_id": action_id,
                    "result": plan.result,
                }
        raise RuntimeError("synthetic missing A2A route unexpectedly succeeded")

    def _call_mcp(
        self, action_id: str, scenario_slug: str, plan: RuntimePlan, body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        with self.telemetry.tracer.start_as_current_span(
            "mcp.call", attributes={"ithelp.governance.action_id": action_id}
        ):
            receipt = self._post(
                plan.downstream_path,
                action_id,
                scenario_slug,
                drop_context=bool(body.get("drop_context")),
            )
        self.telemetry.event(
            {
                "action_id": action_id,
                "event": "runtime.completed",
                "result": plan.result,
            }
        )
        return HTTPStatus.OK, {
            "action_id": action_id,
            "result": plan.result,
            "receipt": receipt,
        }

    def _post(
        self, path: str, action_id: str, scenario_slug: str, *, drop_context: bool
    ) -> dict[str, Any]:
        headers = {"content-type": "application/json"}
        if not drop_context:
            self.telemetry.inject(headers)
        request = Request(
            self.gateway_url + path,
            data=json.dumps({"action_id": action_id, "scenario": scenario_slug}).encode(),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=5) as response:  # noqa: S310 - fixed in-lab gateway URL
            return json.load(response)

    def _handle_mcp(
        self, headers: dict[str, str], body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        action_id = _required_text(body, "action_id")
        scenario_slug = _required_text(body, "scenario")
        parent = self.telemetry.extract(headers)
        with self.telemetry.tracer.start_as_current_span(
            "mcp.tool.execute",
            context=parent,
            attributes={
                "ithelp.governance.action_id": action_id,
                "gen_ai.tool.name": "delete_demo_database",
                "ithelp.lab.scenario": scenario_slug,
            },
        ):
            receipt = {
                "action_id": action_id,
                "effect": "NO_OP_CANARY",
                "side_effects": 0,
                "status": "CANARY_TRIGGERED",
            }
            self.telemetry.event({"event": "mcp.receipt", **receipt})
            return HTTPStatus.OK, receipt


def _required_text(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def make_handler(application: LabApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            headers = {key.casefold(): value for key, value in self.headers.items()}
            self._respond(*application.handle(self.path, headers, {}))

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            try:
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("request body must be a JSON object")
                headers = {key.casefold(): value for key, value in self.headers.items()}
                status, payload = application.handle(self.path, headers, body)
            except (ValueError, json.JSONDecodeError) as exc:
                status, payload = HTTPStatus.BAD_REQUEST, {"error": str(exc)}
            self._respond(status, payload)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _respond(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("runtime", "mcp", "cardinality"), required=True)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://alloy:4318")
    service_names = {
        "runtime": "agent-runtime",
        "mcp": "mcp-adapter",
        "cardinality": "cardinality-backend",
    }
    service_name = service_names[args.role]
    telemetry = Telemetry(service_name, endpoint.rstrip("/"))
    application = LabApplication(
        args.role,
        telemetry,
        os.environ.get("LAB_GATEWAY_URL", "http://agentgateway:3000"),
    )
    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(application))
    try:
        server.serve_forever()
    finally:
        telemetry.shutdown()


if __name__ == "__main__":
    main()
