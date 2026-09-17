from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from google.adk.models.llm_request import LlmRequest

import traceability_lab.sre_agent as sre_agent
from traceability_lab.sre_agent import (
    SreAgentState,
    build_fixture_model_callback,
    build_query_arguments,
    capture_tool_response,
    summarize_loki_response,
)


def test_query_arguments_keep_the_loki_scope_explicit() -> None:
    arguments = build_query_arguments(
        datasource_uid="grafana-loki",
        start="2026-09-16T01:00:00Z",
        end="2026-09-16T01:05:00Z",
        action_id="act-day25-adk-query",
    )

    assert arguments == {
        "datasourceUid": "grafana-loki",
        "startRfc3339": "2026-09-16T01:00:00Z",
        "endRfc3339": "2026-09-16T01:05:00Z",
        "limit": 5,
        "format": "full",
        "logql": ('{service_name="day25-sre-agent"} |= "act-day25-adk-query"'),
    }


def test_fixture_model_calls_the_real_mcp_tool_then_returns_a_summary() -> None:
    state = SreAgentState()
    arguments = build_query_arguments(
        datasource_uid="grafana-loki",
        start="2026-09-16T01:00:00Z",
        end="2026-09-16T01:05:00Z",
        action_id="act-day25-adk-query",
    )
    callback = build_fixture_model_callback(arguments=arguments, state=state)

    first = callback(None, LlmRequest())
    call = first.content.parts[0].function_call
    assert call.name == "query_loki_logs"
    assert dict(call.args) == arguments

    state.tool_summary = {
        "result": "USABLE",
        "lines_returned": 1,
        "action_id": "act-day25-adk-query",
        "trace_id": "25" * 16,
    }
    second = callback(None, LlmRequest())
    assert "查到 1 筆" in second.content.parts[0].text
    assert "act-day25-adk-query" in second.content.parts[0].text


def test_tool_response_is_reduced_to_bounded_correlation_fields() -> None:
    response = {
        "content": [{"type": "text", "text": "large raw response"}],
        "structuredContent": {
            "data": [
                {
                    "line": "level=error msg=synthetic_checkout_timeout",
                    "labels": {"service_name": "day25-sre-agent"},
                    "structuredMetadata": {
                        "action_id": "act-day25-adk-query",
                        "trace_id": "25" * 16,
                    },
                }
            ],
            "metadata": {"linesReturned": 1, "resultsTruncated": False},
        },
        "isError": False,
    }

    summary = summarize_loki_response(response)

    assert summary == {
        "result": "USABLE",
        "lines_returned": 1,
        "results_truncated": False,
        "service_name": "day25-sre-agent",
        "action_id": "act-day25-adk-query",
        "trace_id": "25" * 16,
    }
    assert "large raw response" not in str(summary)


def test_tool_response_accepts_mcp_content_text_without_structured_content() -> None:
    payload = {
        "data": [
            {
                "labels": {"service_name": "day25-sre-agent"},
                "structuredMetadata": {
                    "action_id": "act-day25-adk-query",
                    "trace_id": "25" * 16,
                },
            }
        ],
        "metadata": {"linesReturned": 1, "resultsTruncated": False},
    }
    response = {
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "isError": False,
    }

    summary = summarize_loki_response(response)

    assert summary["result"] == "USABLE"
    assert summary["action_id"] == "act-day25-adk-query"


@pytest.mark.parametrize(
    ("service_name", "action_id", "trace_id"),
    [
        ("wrong-service", "act-day25-adk-query", "25" * 16),
        ("day25-sre-agent", "wrong-action", "25" * 16),
        ("day25-sre-agent", "act-day25-adk-query", "f" * 32),
        (None, "act-day25-adk-query", "25" * 16),
    ],
)
def test_tool_response_rejects_missing_or_mismatched_correlation(
    service_name: str | None,
    action_id: str,
    trace_id: str,
) -> None:
    response = {
        "structuredContent": {
            "data": [
                {
                    "labels": ({"service_name": service_name} if service_name else {}),
                    "structuredMetadata": {
                        "action_id": action_id,
                        "trace_id": trace_id,
                    },
                }
            ],
            "metadata": {"linesReturned": 1},
        },
        "isError": False,
    }

    summary = summarize_loki_response(response)

    assert summary["result"] == "UNVERIFIED"
    assert summary["lines_returned"] == 1


def test_after_tool_callback_records_the_tool_name_arguments_and_summary() -> None:
    state = SreAgentState()
    response = {
        "structuredContent": {"data": [], "metadata": {"linesReturned": 0}},
        "isError": False,
    }

    result = capture_tool_response(state)(
        type("Tool", (), {"name": "query_loki_logs"})(),
        {"logql": '{service_name="day25-sre-agent"}'},
        None,
        response,
    )

    assert result is None
    assert state.tool_name == "query_loki_logs"
    assert state.tool_arguments == {"logql": '{service_name="day25-sre-agent"}'}
    assert state.tool_summary["result"] == "NO_MATCH"


def test_runner_passes_an_http_opener_to_loki_and_grafana_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    calls = []

    def fake_push(url, payload, opener):
        calls.append(("push", url, payload["streams"][0]["stream"], callable(opener)))

    def fake_discover(url, opener):
        calls.append(("discover", url, callable(opener)))
        return "grafana-loki"

    def fake_build(*, endpoint, arguments, state):
        state.tool_name = "query_loki_logs"
        state.tool_arguments = arguments
        state.tool_summary = {
            "result": "USABLE",
            "lines_returned": 1,
            "action_id": "act-day25-adk-query",
            "trace_id": "25" * 16,
        }
        return object()

    async def fake_run(_agent):
        return [{"type": "tool-result"}]

    monkeypatch.setattr(sre_agent, "_push_loki_log", fake_push)
    monkeypatch.setattr(sre_agent, "_discover_loki_datasource", fake_discover)
    monkeypatch.setattr(sre_agent, "build_sre_agent", fake_build)
    monkeypatch.setattr(sre_agent, "_run_agent", fake_run)

    summary = sre_agent.run_sre_agent_investigation(
        artifact_root=tmp_path / "artifacts",
        gateway_url="http://127.0.0.1:25080/mcp",
        loki_url="http://127.0.0.1:25100",
        grafana_url="http://127.0.0.1:25000",
        now=datetime(2026, 9, 16, 1, 0, tzinfo=UTC),
    )

    assert calls == [
        ("push", "http://127.0.0.1:25100", {"service_name": "day25-sre-agent"}, True),
        ("discover", "http://127.0.0.1:25000", True),
    ]
    assert summary.tool_summary["result"] == "USABLE"
    assert summary.configured_path == (
        "Google ADK",
        "agentgateway",
        "mcp-grafana",
        "Grafana",
        "Loki",
    )
