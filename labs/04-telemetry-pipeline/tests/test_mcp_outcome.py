from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from traceability_lab.mcp_outcome import (
    LAB_ACTION_ID,
    LAB_TRACE_ID,
    HttpExchange,
    assess_tool_exchange,
    build_loki_push_payload,
    find_tool_name,
    run_mcp_outcome_traffic,
)
from traceability_lab.service import HtmlGrafanaFixture

LAB_ROOT = Path(__file__).resolve().parents[1]


class FakeResponse(BytesIO):
    def __init__(
        self,
        body: bytes = b"",
        *,
        status: int = 200,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(body)
        self.status = status
        self.headers = {"content-type": content_type, **(headers or {})}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def _tool_exchange(structured_content: dict, *, is_error: bool = False) -> HttpExchange:
    payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {
            "content": [{"type": "text", "text": json.dumps(structured_content)}],
            "isError": is_error,
            "structuredContent": structured_content,
        },
    }
    return HttpExchange.from_http(
        status=200,
        content_type="application/json",
        body=json.dumps(payload).encode(),
        headers={"mcp-session-id": "session-redacted"},
    )


def test_assessment_separates_tool_error_from_http_and_json_rpc_success() -> None:
    exchange = _tool_exchange(
        {"error": "unmarshalling response (content: <html>...</html>)"},
        is_error=True,
    )

    assessment = assess_tool_exchange(exchange)

    assert assessment == {
        "client_http": "PASS",
        "mcp_contract": "PASS",
        "tool_result": "ERROR",
        "domain_outcome": "UNKNOWN",
        "classification": "TOOL_EXECUTION_ERROR",
    }


def test_assessment_marks_a_valid_empty_loki_result_as_no_match() -> None:
    exchange = _tool_exchange(
        {
            "data": [],
            "metadata": {
                "linesReturned": 0,
                "maxLinesAllowed": 5,
                "resultsTruncated": False,
            },
        }
    )

    assessment = assess_tool_exchange(exchange)

    assert assessment["client_http"] == "PASS"
    assert assessment["mcp_contract"] == "PASS"
    assert assessment["tool_result"] == "PASS"
    assert assessment["domain_outcome"] == "NO_MATCH"
    assert assessment["classification"] == "VALID_BUT_EMPTY"


def test_assessment_requires_a_real_log_entry_for_a_usable_result() -> None:
    exchange = _tool_exchange(
        {
            "data": [
                {
                    "line": "level=error action_id=act-day25-loki-query year=2026",
                    "labels": {"service_name": "day25-mcp-outcome"},
                    "structuredMetadata": {
                        "action_id": "act-day25-loki-query",
                        "trace_id": LAB_TRACE_ID,
                    },
                }
            ],
            "metadata": {"linesReturned": 1, "resultsTruncated": False},
        }
    )

    assessment = assess_tool_exchange(exchange)

    assert assessment["tool_result"] == "PASS"
    assert assessment["domain_outcome"] == "USABLE"
    assert assessment["classification"] == "USABLE_RESULT"


def test_assessment_rejects_nonempty_data_without_expected_correlation() -> None:
    exchange = _tool_exchange(
        {
            "data": [
                {
                    "line": "level=error action_id=other-action",
                    "labels": {"service_name": "another-service"},
                    "structuredMetadata": {
                        "action_id": "other-action",
                        "trace_id": "f" * 32,
                    },
                }
            ],
            "metadata": {"linesReturned": 1},
        }
    )

    assessment = assess_tool_exchange(exchange)

    assert assessment["client_http"] == "PASS"
    assert assessment["mcp_contract"] == "PASS"
    assert assessment["tool_result"] == "PASS"
    assert assessment["domain_outcome"] == "UNVERIFIED"
    assert assessment["classification"] == "CORRELATION_MISMATCH"


def test_non_200_cannot_pass_even_when_body_contains_a_valid_tool_result() -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {
            "structuredContent": {
                "data": [
                    {
                        "labels": {"service_name": "day25-mcp-outcome"},
                        "structuredMetadata": {
                            "action_id": LAB_ACTION_ID,
                            "trace_id": LAB_TRACE_ID,
                        },
                    }
                ],
                "metadata": {"linesReturned": 1},
            }
        },
    }
    exchange = HttpExchange.from_http(
        status=500,
        content_type="application/json",
        body=json.dumps(payload).encode(),
        headers={},
    )

    assessment = assess_tool_exchange(exchange)

    assert assessment == {
        "client_http": "FAIL",
        "mcp_contract": "NOT_EVALUATED",
        "tool_result": "NOT_REACHED",
        "domain_outcome": "UNKNOWN",
        "classification": "HTTP_ERROR",
    }


def test_sse_decoder_selects_the_response_matching_the_request_id() -> None:
    body = (
        b'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
        b'event: message\ndata: {"jsonrpc":"2.0","id":7,"result":{"ignored":true}}\n\n'
        b'event: message\ndata: {"jsonrpc":"2.0","id":9,"result":{"tools":[]}}\n\n'
    )

    exchange = HttpExchange.from_http(
        status=200,
        content_type="text/event-stream; charset=utf-8",
        body=body,
        headers={},
        expected_response_id=9,
    )

    assert exchange.payload == {"jsonrpc": "2.0", "id": 9, "result": {"tools": []}}


def test_non_json_http_200_fails_before_the_mcp_contract() -> None:
    exchange = HttpExchange.from_http(
        status=200,
        content_type="text/html; charset=utf-8",
        body=b"<html><title>Grafana</title></html>",
        headers={},
    )

    assessment = assess_tool_exchange(exchange)

    assert assessment == {
        "client_http": "PASS",
        "mcp_contract": "FAIL",
        "tool_result": "NOT_REACHED",
        "domain_outcome": "UNKNOWN",
        "classification": "MCP_DECODE_FAILED",
    }


def test_find_tool_name_accepts_agentgateway_prefixing() -> None:
    tools = [
        {"name": "grafana__list_datasources"},
        {"name": "grafana__query_loki_logs"},
    ]

    assert find_tool_name(tools, "query_loki_logs") == "grafana__query_loki_logs"


def test_loki_push_payload_keeps_query_dimensions_out_of_stream_labels() -> None:
    payload = build_loki_push_payload(
        timestamp_ns=1_789_056_000_000_000_000,
        action_id="act-day25-loki-query",
        trace_id="a" * 32,
    )

    stream = payload["streams"][0]
    assert stream["stream"] == {"service_name": "day25-mcp-outcome"}
    assert stream["values"][0][2] == {
        "action_id": "act-day25-loki-query",
        "trace_id": "a" * 32,
    }
    assert "year=2026" in stream["values"][0][1]


def test_html_grafana_fixture_returns_valid_datasource_then_html_query() -> None:
    fixture = HtmlGrafanaFixture()

    datasource = fixture.handle("/api/datasources/uid/loki", {})
    query = fixture.handle(
        "/api/datasources/proxy/uid/loki/loki/api/v1/query_range?query=%7Bservice_name%3Dday25%7D",
        {"x-loki-response-encoding-flags": "categorize-labels"},
    )
    status, content_type, body = query

    assert datasource[0] == 200
    assert json.loads(datasource[2])["type"] == "loki"
    assert status == 200
    assert content_type == "text/html; charset=utf-8"
    assert body.startswith(b"<!doctype html>")
    assert fixture.events[-1] == {
        "path": "/api/datasources/proxy/uid/loki/loki/api/v1/query_range",
        "request_encoding_flags": "categorize-labels",
        "response_content_type": "text/html; charset=utf-8",
        "response_status": 200,
    }


def test_day25_compose_uses_real_mcp_grafana_behind_agentgateway() -> None:
    compose = (LAB_ROOT / "docker-compose.day25.yaml").read_text(encoding="utf-8")
    good_gateway = (LAB_ROOT / "configs/day-25/agentgateway-grafana.yaml").read_text(
        encoding="utf-8"
    )

    assert "grafana/mcp-grafana:1.4.2@sha256:f87fa67a561f7b3d" in compose
    assert "--transport" in compose and "streamable-http" in compose
    assert "MCP_GRAFANA_SERVER_TOKEN" in compose
    assert compose.count("--loki-enforced-matchers") == 2
    assert compose.count('service_name=~"day25-.*"') == 2
    for bypass_flag in (
        "--disable-api",
        "--disable-rendering",
        "--disable-sift",
        "--disable-assistant",
    ):
        assert compose.count(bypass_flag) == 2
    assert "OTEL_EXPORTER_OTLP_ENDPOINT: http://alloy:4317" in compose
    assert 'OTEL_EXPORTER_OTLP_INSECURE: "true"' in compose
    assert "OTEL_EXPORTER_OTLP_PROTOCOL" not in compose
    assert "host: http://mcp-grafana:8000/mcp" in good_gateway
    assert "backendAuth:" in good_gateway
    assert "agentgateway" in good_gateway


def test_runner_records_three_distinct_outcomes_from_the_same_http_status(
    tmp_path: Path,
) -> None:
    requests = []

    def json_response(payload: dict, *, session: bool = False) -> FakeResponse:
        headers = {"mcp-session-id": "session-sensitive"} if session else {}
        return FakeResponse(json.dumps(payload).encode(), headers=headers)

    def opener(request, timeout):
        requests.append((request, timeout))
        if request.full_url.endswith("/loki/api/v1/push"):
            return FakeResponse(status=204)
        if request.full_url.endswith(":25000/api/datasources"):
            return json_response([{"name": "Loki", "type": "loki", "uid": "grafana-loki"}])
        if request.full_url.endswith(":25090/events"):
            return json_response(
                {
                    "events": [
                        {
                            "path": "/api/datasources/proxy/uid/loki/loki/api/v1/query_range",
                            "request_encoding_flags": "categorize-labels",
                            "response_content_type": "text/html; charset=utf-8",
                            "response_status": 200,
                        }
                    ]
                }
            )

        if request.get_method() == "DELETE":
            return FakeResponse(status=204)

        payload = json.loads(request.data)
        if payload["method"] == "initialize":
            return json_response(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "agentgateway", "version": "1.5.0"},
                    },
                },
                session=True,
            )
        if payload["method"] == "notifications/initialized":
            return FakeResponse(status=202)
        if payload["method"] == "tools/list":
            return json_response(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "tools": [
                            {"name": "list_datasources"},
                            {"name": "query_loki_logs"},
                        ]
                    },
                }
            )
        assert payload["method"] == "tools/call"
        if ":25081/" in request.full_url:
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": "unmarshalling response (content: <html>...</html>)",
                    }
                ],
                "isError": True,
            }
        elif "year=2025" in payload["params"]["arguments"]["logql"]:
            result = {
                "content": [{"type": "text", "text": '{"data":[]}'}],
                "structuredContent": {"data": [], "metadata": {"linesReturned": 0}},
            }
        else:
            result = {
                "content": [{"type": "text", "text": '{"data":[{"line":"match"}]}'}],
                "structuredContent": {
                    "data": [
                        {
                            "line": "match",
                            "labels": {"service_name": "day25-mcp-outcome"},
                            "structuredMetadata": {
                                "action_id": LAB_ACTION_ID,
                                "trace_id": LAB_TRACE_ID,
                            },
                        }
                    ],
                    "metadata": {"linesReturned": 1},
                },
            }
        return json_response({"jsonrpc": "2.0", "id": payload["id"], "result": result})

    summary = run_mcp_outcome_traffic(
        artifact_root=tmp_path,
        good_gateway_url="http://127.0.0.1:25080/mcp",
        html_gateway_url="http://127.0.0.1:25081/mcp",
        loki_url="http://127.0.0.1:25100",
        grafana_url="http://127.0.0.1:25000",
        html_fixture_url="http://127.0.0.1:25090",
        opener=opener,
    )

    observed = {
        item["scenario"]: item["assessment"]["classification"] for item in summary.scenarios
    }
    assert observed == {
        "upstream-200-html": "TOOL_EXECUTION_ERROR",
        "valid-empty-query": "VALID_BUT_EMPTY",
        "usable-loki-result": "USABLE_RESULT",
    }
    assert summary.datasource_uid == "grafana-loki"
    assert "." not in summary.query_window["start"]
    assert "." not in summary.query_window["end"]
    assert summary.scenarios[0]["upstream_grafana_api"][0]["response_status"] == 200
    assert "session-sensitive" not in json.dumps(summary.to_json_dict())
    artifact_dir = Path(summary.artifact_dir)
    assert (artifact_dir / "mcp-outcome-report.json").is_file()
    assert "3/3 client-facing calls returned HTTP 200." in (
        artifact_dir / "terminal.txt"
    ).read_text(encoding="utf-8")
    assert any(request.full_url.endswith("/loki/api/v1/push") for request, _ in requests)
    assert sum(request.get_method() == "DELETE" for request, _ in requests) == 2
    assert all(timeout in {10, 20} for _, timeout in requests)
