import json
from pathlib import Path

import pytest
import yaml

from gateway_runtime.a2a_path import (
    A2A_VERSION,
    HttpResult,
    HttpStreamResult,
    build_agent_card_url,
    build_send_message_request,
    build_send_streaming_message_request,
    parse_sse_events,
    render_terminal,
    run_probe,
    select_jsonrpc_interface,
)


def _card(interface_url: str) -> dict:
    return {
        "name": "day16-agent",
        "capabilities": {"streaming": True},
        "supportedInterfaces": [
            {
                "url": interface_url,
                "protocolBinding": "JSONRPC",
                "protocolVersion": "0.3",
            },
            {
                "url": interface_url,
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            },
        ],
    }


def _v1_response() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": "day17-good",
        "result": {
            "task": {
                "id": "task-17",
                "contextId": "context-17",
                "status": {"state": "TASK_STATE_COMPLETED"},
                "history": [
                    {
                        "messageId": "agent-message-17",
                        "role": "ROLE_AGENT",
                        "parts": [{"text": "boundary-ok"}],
                    }
                ],
                "artifacts": [
                    {
                        "artifactId": "artifact-17",
                        "parts": [{"text": "boundary-ok"}],
                    }
                ],
            }
        },
    }


def _v1_stream() -> str:
    events = [
        {
            "jsonrpc": "2.0",
            "id": "day17-stream",
            "result": {
                "statusUpdate": {
                    "taskId": "task-stream-17",
                    "contextId": "context-stream-17",
                    "status": {"state": "TASK_STATE_SUBMITTED"},
                }
            },
        },
        {
            "jsonrpc": "2.0",
            "id": "day17-stream",
            "result": {
                "statusUpdate": {
                    "taskId": "task-stream-17",
                    "contextId": "context-stream-17",
                    "status": {"state": "TASK_STATE_WORKING"},
                }
            },
        },
        {
            "jsonrpc": "2.0",
            "id": "day17-stream",
            "result": {
                "statusUpdate": {
                    "taskId": "task-stream-17",
                    "contextId": "context-stream-17",
                    "status": {
                        "state": "TASK_STATE_WORKING",
                        "message": {
                            "role": "ROLE_AGENT",
                            "parts": [{"text": "boundary-ok"}],
                        },
                    },
                }
            },
        },
        {
            "jsonrpc": "2.0",
            "id": "day17-stream",
            "result": {
                "artifactUpdate": {
                    "taskId": "task-stream-17",
                    "contextId": "context-stream-17",
                    "artifact": {
                        "artifactId": "artifact-stream-17",
                        "parts": [{"text": "boundary-ok"}],
                    },
                    "lastChunk": True,
                }
            },
        },
        {
            "jsonrpc": "2.0",
            "id": "day17-stream",
            "result": {
                "statusUpdate": {
                    "taskId": "task-stream-17",
                    "contextId": "context-stream-17",
                    "status": {"state": "TASK_STATE_COMPLETED"},
                }
            },
        },
    ]
    return "\n\n".join(
        f"id: event-{index}\ndata: {json.dumps(event)}" for index, event in enumerate(events)
    )


def test_agent_card_url_uses_the_standard_well_known_path() -> None:
    assert build_agent_card_url("http://gateway.test/agents/day16/") == (
        "http://gateway.test/agents/day16/.well-known/agent-card.json"
    )


def test_interface_selection_requires_explicit_a2a_1_jsonrpc() -> None:
    card = _card("http://gateway.test/agents/day16")

    assert select_jsonrpc_interface(card) == "http://gateway.test/agents/day16"

    card["supportedInterfaces"] = card["supportedInterfaces"][:1]
    with pytest.raises(ValueError, match="A2A 1.0 JSONRPC"):
        select_jsonrpc_interface(card)


def test_send_message_request_uses_the_a2a_1_wire_shape() -> None:
    request = build_send_message_request(
        request_id="day17-good",
        message_id="message-17",
        text="Reply with boundary-ok.",
    )

    assert request["method"] == "SendMessage"
    assert request["params"]["message"]["role"] == "ROLE_USER"
    assert request["params"]["message"]["parts"] == [{"text": "Reply with boundary-ok."}]
    assert "kind" not in request["params"]["message"]


def test_streaming_request_and_sse_parser_use_the_a2a_1_wire_shape() -> None:
    request = build_send_streaming_message_request(
        request_id="day17-stream",
        message_id="message-stream-17",
        text="Reply with boundary-ok.",
    )

    assert request["method"] == "SendStreamingMessage"
    events = parse_sse_events(_v1_stream())
    assert len(events) == 5
    assert events[-1]["result"]["statusUpdate"]["status"]["state"] == ("TASK_STATE_COMPLETED")


def test_probe_separates_discovery_from_a_successful_a2a_1_invocation() -> None:
    gateway_base = "http://gateway.test/agents/day16"
    calls: list[tuple[str, str, dict[str, str], dict | None]] = []

    def transport(method: str, url: str, headers: dict[str, str], body: dict | None) -> HttpResult:
        calls.append((method, url, headers, body))
        if method == "GET":
            return HttpResult(200, _card(gateway_base))
        return HttpResult(200, _v1_response())

    def stream_transport(
        method: str, url: str, headers: dict[str, str], body: dict | None
    ) -> HttpStreamResult:
        calls.append((method, url, headers, body))
        return HttpStreamResult(200, "text/event-stream", _v1_stream())

    report = run_probe(
        gateway_base,
        transport=transport,
        stream_transport=stream_transport,
    )
    cases = {item["case_id"]: item for item in report["cases"]}

    assert cases["agent-card"]["status"] == "PASS"
    assert cases["a2a-1.0-send-message"]["status"] == "PASS"
    assert cases["a2a-1.0-send-message"]["task_state"] == "TASK_STATE_COMPLETED"
    assert cases["a2a-1.0-send-message"]["context_id"] == "context-17"
    assert cases["a2a-1.0-send-message"]["reply"] == "boundary-ok"
    assert cases["a2a-1.0-stream"]["status"] == "PASS"
    assert cases["a2a-1.0-stream"]["states"] == [
        "TASK_STATE_SUBMITTED",
        "TASK_STATE_WORKING",
        "TASK_STATE_WORKING",
        "TASK_STATE_COMPLETED",
    ]
    assert cases["a2a-1.0-stream"]["events"] == [
        "SUBMITTED",
        "WORKING",
        "AGENT_MESSAGE",
        "ARTIFACT(last)",
        "COMPLETED",
    ]
    assert cases["a2a-1.0-stream"]["last_chunk"] is True
    assert report["summary"] == {"matched": 3, "total": 3}

    post_headers = calls[1][2]
    assert post_headers["A2A-Version"] == A2A_VERSION
    assert calls[1][3]["method"] == "SendMessage"
    assert calls[2][2]["Accept"] == "text/event-stream"
    assert calls[2][3]["method"] == "SendStreamingMessage"


def test_probe_follows_the_bad_card_url_and_records_the_expected_routing_failure() -> None:
    discovery_base = "http://gateway.test/api/a2a/day16-lab/day16-agent"
    advertised_url = "http://gateway.test/api/a2a/api/a2a/day16-lab/day16-agent"
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], body: dict | None) -> HttpResult:
        calls.append(url)
        if method == "GET":
            return HttpResult(200, _card(advertised_url))
        return HttpResult(404, {"error": "agent route not found"})

    def stream_transport(
        method: str, url: str, headers: dict[str, str], body: dict | None
    ) -> HttpStreamResult:
        calls.append(url)
        return HttpStreamResult(404, "application/json", '{"error":"not found"}')

    report = run_probe(
        discovery_base,
        transport=transport,
        stream_transport=stream_transport,
        expect_routing_failure=True,
    )
    cases = {item["case_id"]: item for item in report["cases"]}

    assert cases["agent-card"]["status"] == "PASS"
    assert cases["a2a-1.0-send-message"]["status"] == "EXPECTED_FAIL"
    assert cases["a2a-1.0-send-message"]["http_status"] == 404
    assert cases["a2a-1.0-send-message"]["interface_url"] == advertised_url
    assert cases["a2a-1.0-stream"]["status"] == "EXPECTED_FAIL"
    assert report["summary"] == {"matched": 3, "total": 3}
    assert calls == [build_agent_card_url(discovery_base), advertised_url, advertised_url]


def test_probe_does_not_call_the_agent_when_discovery_fails() -> None:
    calls = 0

    def transport(method: str, url: str, headers: dict[str, str], body: dict | None) -> HttpResult:
        nonlocal calls
        calls += 1
        return HttpResult(404, {"error": "card not found"})

    with pytest.raises(RuntimeError, match="Agent Card"):
        run_probe("http://gateway.test/agents/day16", transport=transport)

    assert calls == 1


def test_probe_rejects_an_incomplete_stream_event_sequence() -> None:
    gateway_base = "http://gateway.test/agents/day16"
    stream_blocks = _v1_stream().split("\n\n")
    incomplete_stream = "\n\n".join(stream_blocks[:2] + stream_blocks[3:])

    def transport(method: str, url: str, headers: dict[str, str], body: dict | None) -> HttpResult:
        if method == "GET":
            return HttpResult(200, _card(gateway_base))
        return HttpResult(200, _v1_response())

    report = run_probe(
        gateway_base,
        transport=transport,
        stream_transport=lambda *_: HttpStreamResult(200, "text/event-stream", incomplete_stream),
    )
    cases = {item["case_id"]: item for item in report["cases"]}

    assert cases["a2a-1.0-stream"]["events"] == [
        "SUBMITTED",
        "WORKING",
        "ARTIFACT(last)",
        "COMPLETED",
    ]
    assert cases["a2a-1.0-stream"]["status"] == "FAIL"


def test_terminal_output_makes_the_expected_failure_unambiguous() -> None:
    def transport(method: str, url: str, headers: dict[str, str], body: dict | None) -> HttpResult:
        if method == "GET":
            return HttpResult(
                200,
                _card("http://gateway.test/api/a2a/api/a2a/day16-lab/day16-agent"),
            )
        return HttpResult(404, {"error": "agent route not found"})

    output = render_terminal(
        run_probe(
            "http://gateway.test/api/a2a/day16-lab/day16-agent",
            transport=transport,
            stream_transport=lambda *_: HttpStreamResult(
                404, "application/json", '{"error":"not found"}'
            ),
            expect_routing_failure=True,
        )
    )

    assert "DAY 17 / A2A PATH" in output
    assert "Agent Card" in output
    assert "A2A 1.0 / SendMessage" in output
    assert "A2A 1.0 / SSE stream" in output
    assert "EXPECTED_FAIL" in output
    assert "NOT_REACHED" in output
    assert "matched 3/3" in output


def test_live_report_is_json_serializable() -> None:
    responses = iter(
        [
            HttpResult(200, _card("http://gateway.test/agents/day16")),
            HttpResult(200, _v1_response()),
        ]
    )

    def transport(method: str, url: str, headers: dict[str, str], body: dict | None) -> HttpResult:
        return next(responses)

    report = run_probe(
        "http://gateway.test/agents/day16",
        transport=transport,
        stream_transport=lambda *_: HttpStreamResult(200, "text/event-stream", _v1_stream()),
    )

    assert json.loads(json.dumps(report))["schema"] == "ithelp.a2a-path-report.v1"


def test_public_routes_keep_the_incident_path_and_add_an_a2a_aware_path() -> None:
    config_path = Path(__file__).parents[1] / "configs/day-17/a2a-route.yaml"
    resources = [
        item for item in yaml.safe_load_all(config_path.read_text(encoding="utf-8")) if item
    ]
    backends = {
        item["metadata"]["name"]: item
        for item in resources
        if item["kind"] == "AgentgatewayBackend"
    }
    routes = {item["metadata"]["name"]: item for item in resources if item["kind"] == "HTTPRoute"}

    assert backends["day17-kagent-http"]["spec"]["static"] == {
        "host": "kagent-controller.kagent.svc.cluster.local",
        "port": 8083,
    }
    incident_rule = routes["day17-kagent-http"]["spec"]["rules"][0]
    assert incident_rule["matches"][0]["path"] == {
        "type": "PathPrefix",
        "value": "/api/a2a/day16-lab/day16-agent",
    }
    assert "filters" not in incident_rule

    assert backends["day17-kagent-a2a"]["spec"]["a2a"] == {
        "host": "kagent-controller.kagent.svc.cluster.local",
        "port": 8083,
    }
    rule = routes["day17-kagent-a2a"]["spec"]["rules"][0]
    assert rule["matches"][0]["path"] == {
        "type": "PathPrefix",
        "value": "/agents/day16",
    }
    assert rule["filters"][0]["urlRewrite"]["path"] == {
        "type": "ReplacePrefixMatch",
        "replacePrefixMatch": "/api/a2a/day16-lab/day16-agent",
    }
    assert rule["backendRefs"] == [
        {
            "group": "agentgateway.dev",
            "kind": "AgentgatewayBackend",
            "name": "day17-kagent-a2a",
        }
    ]
