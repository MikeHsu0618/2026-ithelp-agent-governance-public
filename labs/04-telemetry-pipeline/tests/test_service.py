from io import BytesIO
from urllib.error import URLError

import pytest

from traceability_lab import service
from traceability_lab.service import LabApplication, build_runtime_plan


class FakeSpan:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def set_status(self, status):
        self.status = status


class FakeTracer:
    def start_as_current_span(self, *_args, **_kwargs):
        return FakeSpan()


class FakeTelemetry:
    def __init__(self) -> None:
        self.tracer = FakeTracer()
        self.events = []

    def extract(self, headers):
        return headers

    def inject(self, headers):
        headers["traceparent"] = "synthetic"

    def event(self, payload):
        self.events.append(payload)


def test_hitl_plan_records_approval_before_the_tool_call() -> None:
    plan = build_runtime_plan("hitl-approved")

    assert plan.result == "APPROVED_AND_EXECUTED"
    assert plan.spans == ("agent.runtime", "hitl.approval", "mcp.call")
    assert plan.downstream_path == "/mcp/execute"


def test_fallback_plan_keeps_both_provider_attempts() -> None:
    plan = build_runtime_plan("llm-fallback")

    assert plan.result == "FALLBACK_SUCCEEDED"
    assert plan.spans == (
        "agent.runtime",
        "llm.primary.failed",
        "llm.fallback.succeeded",
        "mcp.call",
    )


def test_a2a_failure_stops_before_mcp() -> None:
    plan = build_runtime_plan("a2a-routing-failure")

    assert plan.result == "ROUTING_FAILED"
    assert plan.downstream_path == "/a2a/missing"
    assert "mcp.call" not in plan.spans


def test_runtime_calls_mcp_and_keeps_the_safe_receipt() -> None:
    telemetry = FakeTelemetry()
    application = LabApplication("runtime", telemetry, "http://agentgateway:3000")
    application._post = lambda *_, **__: {
        "status": "CANARY_TRIGGERED",
        "side_effects": 0,
    }

    status, payload = application.handle(
        "/agent/run",
        {"traceparent": "synthetic"},
        {"action_id": "act-normal", "scenario": "normal-call"},
    )

    assert status == 200
    assert payload["receipt"]["side_effects"] == 0
    assert telemetry.events[-1]["event"] == "runtime.completed"


def test_runtime_reports_a2a_routing_failure() -> None:
    telemetry = FakeTelemetry()
    application = LabApplication("runtime", telemetry, "http://agentgateway:3000")

    def fail(*_, **__):
        raise URLError("synthetic missing agent")

    application._post = fail
    status, payload = application.handle(
        "/agent/run",
        {},
        {"action_id": "act-a2a", "scenario": "a2a-routing-failure"},
    )

    assert status == 502
    assert payload["result"] == "ROUTING_FAILED"
    assert telemetry.events[-1]["event"] == "a2a.routing_failed"


def test_mcp_adapter_returns_a_noop_receipt_and_emits_it() -> None:
    telemetry = FakeTelemetry()
    application = LabApplication("mcp", telemetry, "http://agentgateway:3000")

    status, payload = application.handle(
        "/mcp/execute",
        {},
        {"action_id": "act-mcp", "scenario": "normal-call"},
    )

    assert status == 200
    assert payload["effect"] == "NO_OP_CANARY"
    assert payload["side_effects"] == 0
    assert telemetry.events == [{"event": "mcp.receipt", **payload}]


def test_health_and_unknown_routes_are_explicit() -> None:
    application = LabApplication("mcp", FakeTelemetry(), "http://agentgateway:3000")

    assert application.handle("/healthz", {}, {}) == (200, {"status": "ok", "role": "mcp"})
    assert application.handle("/unknown", {}, {}) == (404, {"error": "route_not_found"})


def test_cardinality_backend_only_returns_a_stable_safe_receipt() -> None:
    application = LabApplication("cardinality", FakeTelemetry(), "http://unused.invalid")

    status, payload = application.handle(
        "/cardinality/run",
        {},
        {"experiment": "day23"},
    )

    assert status == 200
    assert payload == {
        "effect": "NO_OP_CARDINALITY_SAMPLE",
        "side_effects": 0,
        "status": "ok",
    }


def test_gateway_denial_never_builds_a_runtime_plan() -> None:
    with pytest.raises(ValueError, match="does not reach Runtime"):
        build_runtime_plan("gateway-policy-deny")


def test_service_rejects_a_missing_action_id() -> None:
    application = LabApplication("mcp", FakeTelemetry(), "http://agentgateway:3000")

    with pytest.raises(ValueError, match="action_id"):
        application.handle("/mcp/execute", {}, {"scenario": "normal-call"})


def test_missing_a2a_fixture_cannot_accidentally_turn_into_success() -> None:
    application = LabApplication("runtime", FakeTelemetry(), "http://agentgateway:3000")
    application._post = lambda *_, **__: {"unexpected": "success"}

    with pytest.raises(RuntimeError, match="unexpectedly succeeded"):
        application.handle(
            "/agent/run",
            {},
            {"action_id": "act-a2a", "scenario": "a2a-routing-failure"},
        )


def test_downstream_call_injects_trace_context(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return BytesIO(b'{"status":"CANARY_TRIGGERED"}')

    monkeypatch.setattr(service, "urlopen", fake_urlopen)
    application = LabApplication("runtime", FakeTelemetry(), "http://agentgateway:3000")

    result = application._post("/mcp/execute", "act-normal", "normal-call", drop_context=False)

    assert result == {"status": "CANARY_TRIGGERED"}
    assert captured["request"].headers["Traceparent"] == "synthetic"
    assert captured["timeout"] == 5
