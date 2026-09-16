from __future__ import annotations

import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from traceability_lab.backend import verify_cost_fallback_backend
from traceability_lab.cost_fallback import (
    BACKUP_MODEL,
    PRIMARY_MODEL,
    DeterministicLlmProvider,
    run_cost_fallback_traffic,
)

LAB_ROOT = Path(__file__).resolve().parents[1]


class FakeResponse(BytesIO):
    def __init__(self, payload: dict, *, status: int = 200) -> None:
        super().__init__(json.dumps(payload).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def test_primary_fixture_returns_usage_only_for_a_successful_openai_response() -> None:
    provider = DeterministicLlmProvider("primary")

    status, successful = provider.handle(
        "/v1/chat/completions",
        {"x-action-id": "act-day24-primary-success"},
        {
            "model": PRIMARY_MODEL,
            "messages": [{"role": "user", "content": "PRIMARY_OK"}],
        },
    )
    failed_status, failed = provider.handle(
        "/v1/chat/completions",
        {"x-action-id": "act-day24-no-retry"},
        {
            "model": PRIMARY_MODEL,
            "messages": [{"role": "user", "content": "FAIL_PRIMARY"}],
        },
    )

    assert status == 200
    assert successful["model"] == PRIMARY_MODEL
    assert successful["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 5,
        "total_tokens": 16,
    }
    assert failed_status == 503
    assert "usage" not in failed
    assert provider.events[-1]["usage_evidence"] == "UNKNOWN"


def test_backup_fixture_uses_anthropic_shape_and_preserves_action_id() -> None:
    provider = DeterministicLlmProvider("backup")

    status, payload = provider.handle(
        "/v1/messages",
        {"x-action-id": "act-day24-with-retry"},
        {
            "model": BACKUP_MODEL,
            "messages": [{"role": "user", "content": "FAIL_PRIMARY"}],
        },
    )

    assert status == 200
    assert payload["model"] == BACKUP_MODEL
    assert payload["usage"] == {"input_tokens": 7, "output_tokens": 3}
    assert provider.events == [
        {
            "action_id": "act-day24-with-retry",
            "outcome": "SUCCESS",
            "provider": "backup",
            "request_model": BACKUP_MODEL,
            "response_model": BACKUP_MODEL,
            "usage_evidence": "PROVIDER_RESPONSE",
        }
    ]


def test_day24_configs_make_eviction_and_client_retry_boundaries_explicit() -> None:
    failover = (LAB_ROOT / "configs/day-24/agentgateway-failover.yaml").read_text(encoding="utf-8")
    client_retry = (LAB_ROOT / "configs/day-24/agentgateway-client-retry.yaml").read_text(
        encoding="utf-8"
    )

    assert "consecutiveFailures: 1" in failover
    assert "duration: 60s" in failover
    assert "priority: 0" in failover and "priority: 1" in failover
    assert "adminAddr: 0.0.0.0:15000" in failover
    assert "database:" in failover
    assert "sqlite:///tmp/day24-failover.db?mode=rwc" in failover
    assert "adminAddr: 0.0.0.0:15000" in client_retry
    assert "database:" in client_retry
    assert "sqlite:///tmp/day24-client-retry.db?mode=rwc" in client_retry
    assert "does not accept retry under llm.policies" in client_retry
    assert "    retry:" not in client_retry


def test_day24_compose_exposes_the_official_agentgateway_analytics_ui() -> None:
    compose = (LAB_ROOT / "docker-compose.day24.yaml").read_text(encoding="utf-8")

    assert "127.0.0.1:28095:15000" in compose


def test_day24_dashboard_excludes_unknown_failed_attempts_from_estimated_cost() -> None:
    payload = json.loads(
        (LAB_ROOT / "configs/day-24/grafana-dashboard.json").read_text(encoding="utf-8")
    )
    dashboard = payload["dashboard"]
    expressions = [
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
        if "expr" in target
    ]

    assert dashboard["uid"] == "day24-agentgateway-cost-fallback"
    assert any('gen_ai_response_model!="unknown"' in expression for expression in expressions)
    assert any("agentgateway_gen_ai_client_token_usage_sum" in item for item in expressions)
    assert any("act-day24-failover-with-retry" in item for item in expressions)


def test_vendored_official_dashboard_matches_agentgateway_v1_5_0() -> None:
    dashboard = LAB_ROOT / ("configs/day-24/official-dashboard/agentgateway-dashboard-v1.5.0.json")

    assert sha256(dashboard.read_bytes()).hexdigest() == (
        "1380d6720d4eb1814546264fe1ce22a38ea6a33dfa0ef2c7a4fa9283baab253f"
    )


def test_cost_fallback_run_keeps_failure_unknown_and_records_served_model(
    tmp_path: Path,
) -> None:
    requests = []
    attempts_by_action: dict[str, int] = {}

    def opener(request, timeout):
        requests.append((request, timeout))
        prompt = json.loads(request.data)["messages"][0]["content"]
        action_id = request.headers["X-action-id"]
        attempts_by_action[action_id] = attempts_by_action.get(action_id, 0) + 1
        if request.full_url.startswith("http://failover") and prompt == "FAIL_PRIMARY":
            body = BytesIO(b'{"error":{"message":"primary unavailable"}}')
            raise HTTPError(request.full_url, 503, "unavailable", {}, body)
        if (
            request.full_url.startswith("http://retry")
            and prompt == "FAIL_PRIMARY"
            and attempts_by_action[action_id] == 1
        ):
            body = BytesIO(b'{"error":{"message":"primary unavailable"}}')
            raise HTTPError(request.full_url, 503, "unavailable", {}, body)
        model = PRIMARY_MODEL if prompt == "PRIMARY_OK" else BACKUP_MODEL
        tokens = 16 if model == PRIMARY_MODEL else 10
        return FakeResponse(
            {
                "id": "chatcmpl-day24",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "fixture"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": tokens - 5,
                    "completion_tokens": 5,
                    "total_tokens": tokens,
                },
            }
        )

    summary = run_cost_fallback_traffic(
        artifact_root=tmp_path,
        failover_gateway_url="http://failover",
        retry_gateway_url="http://retry",
        opener=opener,
    )

    scenarios = {item["scenario"]: item for item in summary.scenarios}
    assert scenarios["primary-success"]["result"] == "PRIMARY_SERVED"
    assert scenarios["primary-success"]["response_model"] == PRIMARY_MODEL
    assert scenarios["failover-without-retry"] == {
        "action_id": "act-day24-failover-without-retry",
        "gateway": "failover-only",
        "http_status": 503,
        "response_model": "UNKNOWN",
        "response_tokens": "UNKNOWN",
        "result": "REQUEST_FAILED_AFTER_EVICTION",
        "scenario": "failover-without-retry",
    }
    assert scenarios["failover-with-retry"]["result"] == "BACKUP_SERVED"
    assert scenarios["failover-with-retry"]["response_model"] == BACKUP_MODEL
    assert scenarios["failover-with-retry"]["response_tokens"] == 10
    assert scenarios["failover-with-retry"]["client_attempts"] == 2
    assert scenarios["failover-with-retry"]["retry_layer"] == "client"

    assert len(requests) == 4
    assert requests[0][0].headers["Authorization"] == "Bearer sk-day24-platform"
    assert requests[0][0].headers["X-action-id"] == "act-day24-primary-success"
    assert all(timeout == 10 for _, timeout in requests)
    assert requests[2][0].headers["X-action-id"] == requests[3][0].headers["X-action-id"]

    report_path = Path(summary.artifact_dir) / "cost-fallback-run.json"
    report_text = report_path.read_text(encoding="utf-8")
    assert "sk-day24-platform" not in report_text
    assert "UNKNOWN" in report_text


def test_backend_verifier_separates_gateway_estimate_from_failed_and_invoice_cost(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "cost-fallback-run.json"
    report_path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "action_id": "act-day24-primary-success",
                        "result": "PRIMARY_SERVED",
                        "scenario": "primary-success",
                    },
                    {
                        "action_id": "act-day24-failover-without-retry",
                        "result": "REQUEST_FAILED_AFTER_EVICTION",
                        "scenario": "failover-without-retry",
                    },
                    {
                        "action_id": "act-day24-failover-with-retry",
                        "result": "BACKUP_SERVED",
                        "scenario": "failover-with-retry",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    streams = [
        _loki_stream(
            action_id="act-day24-primary-success",
            provider="openai",
            request_model=PRIMARY_MODEL,
            response_model=PRIMARY_MODEL,
            status="200",
            cost="0.00006375",
            input_tokens="11",
            output_tokens="5",
        ),
        _loki_stream(
            action_id="act-day24-failover-without-retry",
            provider="openai",
            request_model=PRIMARY_MODEL,
            status="503",
            cost="0",
        ),
        _loki_stream(
            action_id="act-day24-failover-with-retry",
            provider="openai",
            request_model=PRIMARY_MODEL,
            status="503",
            cost="0",
        ),
        _loki_stream(
            action_id="act-day24-failover-with-retry",
            provider="anthropic",
            request_model=BACKUP_MODEL,
            response_model=BACKUP_MODEL,
            status="200",
            cost="0.000066",
            input_tokens="7",
            output_tokens="3",
        ),
    ]

    def loader(url: str) -> dict:
        parsed = urlsplit(url)
        if parsed.path.endswith("/events"):
            provider = "backup" if parsed.port == 28087 else "primary"
            if provider == "backup":
                return {
                    "events": [
                        {
                            "action_id": "act-day24-failover-with-retry",
                            "outcome": "SUCCESS",
                            "provider": "backup",
                        }
                    ]
                }
            return {
                "events": [
                    {"action_id": "act-day24-primary-success", "outcome": "SUCCESS"},
                    {
                        "action_id": "act-day24-failover-without-retry",
                        "outcome": "HTTP_503",
                    },
                    {"action_id": "act-day24-failover-with-retry", "outcome": "HTTP_503"},
                ]
            }
        if "/loki/" in parsed.path:
            return {"data": {"result": streams}, "status": "success"}
        if "/api/traces/" in parsed.path:
            return {"batches": [{"resource": {"serviceName": "agentgateway"}}]}
        if parsed.path.endswith("/api/v1/query"):
            query = parse_qs(parsed.query)["query"][0]
            if "cost_usd_total" in query:
                return _prometheus_vector(
                    ("openai", PRIMARY_MODEL, PRIMARY_MODEL, "0.00006375"),
                    ("openai", PRIMARY_MODEL, "unknown", "0"),
                    ("anthropic", BACKUP_MODEL, BACKUP_MODEL, "0.000066"),
                )
            if "token_usage_sum" in query:
                return _prometheus_vector(
                    ("openai", PRIMARY_MODEL, PRIMARY_MODEL, "16"),
                    ("anthropic", BACKUP_MODEL, BACKUP_MODEL, "10"),
                )
            if "cost_catalog" in query:
                return _prometheus_vector(
                    ("openai", PRIMARY_MODEL, PRIMARY_MODEL, "1"),
                    ("anthropic", BACKUP_MODEL, BACKUP_MODEL, "1"),
                )
        raise AssertionError(f"unexpected URL: {url}")

    report = verify_cost_fallback_backend(
        report_path,
        fetch_json=loader,
        attempts=1,
        loki_url="http://127.0.0.1:24100",
        prometheus_url="http://127.0.0.1:29091",
        tempo_url="http://127.0.0.1:24200",
        primary_provider_url="http://127.0.0.1:28086",
        backup_provider_url="http://127.0.0.1:28087",
    )

    assert report["overall"] == "PASS"
    assert report["observed_attempts"]["failover-with-retry"] == 2
    assert report["gateway_estimated_cost_usd"] == "0.00012975"
    assert report["failed_attempt_usage"] == "UNKNOWN"
    assert report["failed_attempt_cost"] == "UNKNOWN"
    assert report["final_provider_invoice"] == "OUT_OF_SCOPE"


def _loki_stream(
    *,
    action_id: str,
    provider: str,
    request_model: str,
    status: str,
    cost: str,
    response_model: str | None = None,
    input_tokens: str | None = None,
    output_tokens: str | None = None,
) -> dict:
    stream = {
        "agw_ai_usage_cost_total": cost,
        "attribution_team": "platform",
        "correlation_action_id": action_id,
        "gen_ai_provider_name": provider,
        "gen_ai_request_model": request_model,
        "http_status": status,
        "service_name": "agentgateway",
        "trace_id": action_id.replace("act-day24-", "").ljust(32, "0")[:32],
    }
    if response_model:
        stream["gen_ai_response_model"] = response_model
    if input_tokens:
        stream["gen_ai_usage_input_tokens"] = input_tokens
    if output_tokens:
        stream["gen_ai_usage_output_tokens"] = output_tokens
    return {"stream": stream, "values": [["1", ""]]}


def _prometheus_vector(*rows: tuple[str, str, str, str]) -> dict:
    return {
        "data": {
            "result": [
                {
                    "metric": {
                        "gen_ai_request_model": request_model,
                        "gen_ai_response_model": response_model,
                        "gen_ai_system": provider,
                        "team": "platform",
                    },
                    "value": [1, value],
                }
                for provider, request_model, response_model, value in rows
            ]
        },
        "status": "success",
    }
