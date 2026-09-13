import pytest

from traceability_lab import suite
from traceability_lab.scenarios import get_scenario
from traceability_lab.suite import classify_response, run_suite, validate_gateway_url


class FakeSpan:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get_span_context(self):
        return type("Context", (), {"trace_id": 1234})()


class FakeTracer:
    def start_as_current_span(self, *_args, **_kwargs):
        return FakeSpan()


class FakeTelemetry:
    def __init__(self, *_args) -> None:
        self.tracer = FakeTracer()

    def inject(self, headers):
        headers["traceparent"] = "synthetic"

    def event(self, _payload):
        return None

    def shutdown(self):
        return None


def test_policy_denial_is_classified_from_the_gateway_status() -> None:
    scenario = get_scenario("gateway-policy-deny")

    assert classify_response(scenario, 403, {}) == "DENIED"


def test_runtime_result_is_read_from_the_response_body() -> None:
    scenario = get_scenario("llm-fallback")

    assert classify_response(scenario, 200, {"result": "FALLBACK_SUCCEEDED"}) == (
        "FALLBACK_SUCCEEDED"
    )


def test_unexpected_response_is_visible_instead_of_being_coerced_to_pass() -> None:
    scenario = get_scenario("normal-call")

    assert classify_response(scenario, 502, {"error": "upstream"}) == "UNEXPECTED_HTTP_502"


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost:18080",
        "http://gateway.example:18080",
        "http://user:pass@localhost:18080",
        "http://localhost:18080?token=secret",
    ],
)
def test_gateway_url_is_restricted_to_the_local_lab(url: str) -> None:
    with pytest.raises(ValueError, match="gateway URL"):
        validate_gateway_url(url)


def test_suite_runs_every_scenario_and_persists_the_report(monkeypatch, tmp_path) -> None:
    observed_paths = []

    def fake_post(url, _headers, body):
        observed_paths.append((url, body["scenario"], body["drop_context"]))
        if body["scenario"] == "gateway-policy-deny":
            return 403, {}
        if body["scenario"] == "a2a-routing-failure":
            return 502, {"result": "ROUTING_FAILED"}
        expected = {
            "normal-call": "CANARY_TRIGGERED",
            "hitl-approved": "APPROVED_AND_EXECUTED",
            "llm-fallback": "FALLBACK_SUCCEEDED",
        }
        return 200, {"result": expected[body["scenario"]]}

    monkeypatch.setattr(suite, "Telemetry", FakeTelemetry)
    monkeypatch.setattr(suite, "_post", fake_post)

    summary = run_suite(
        artifact_root=tmp_path / "artifacts",
        otlp_endpoint="http://127.0.0.1:14318",
        gateway_url="http://127.0.0.1:18080",
        drop_mcp_context=True,
    )

    assert len(summary.scenarios) == 5
    assert all(result.status == "PASS" for result in summary.scenarios)
    assert observed_paths[0][2] is True
    assert all(item[2] is False for item in observed_paths[1:])
    assert (tmp_path / "artifacts" / summary.run_id / "scenario-report.json").is_file()
