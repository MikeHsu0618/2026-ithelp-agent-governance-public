"""Day 17 A2A discovery, routing, and invocation probe."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

A2A_VERSION = "1.0"
WELL_KNOWN_AGENT_CARD_PATH = "/.well-known/agent-card.json"
EXPECTED_REPLY = "boundary-ok"
EXPECTED_STREAM_EVENTS = [
    "SUBMITTED",
    "WORKING",
    "AGENT_MESSAGE",
    "ARTIFACT(last)",
    "COMPLETED",
]


@dataclass(frozen=True)
class HttpResult:
    """Small HTTP response shape that keeps the probe easy to test."""

    status: int
    body: dict[str, Any]


@dataclass(frozen=True)
class HttpStreamResult:
    """Raw SSE response plus the media type needed for protocol checks."""

    status: int
    content_type: str
    body: str


Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None], HttpResult]
StreamTransport = Callable[[str, str, dict[str, str], dict[str, Any] | None], HttpStreamResult]


def build_agent_card_url(agent_base_url: str) -> str:
    """Return the standard well-known Agent Card URL for one routed agent."""

    return agent_base_url.rstrip("/") + WELL_KNOWN_AGENT_CARD_PATH


def select_jsonrpc_interface(card: dict[str, Any]) -> str:
    """Select the explicit A2A 1.0 JSON-RPC interface from an Agent Card."""

    for interface in card.get("supportedInterfaces", []):
        if (
            interface.get("protocolVersion") == A2A_VERSION
            and interface.get("protocolBinding") == "JSONRPC"
            and interface.get("url")
        ):
            return str(interface["url"]).rstrip("/")
    raise ValueError("Agent Card does not advertise an A2A 1.0 JSONRPC interface")


def build_send_message_request(request_id: str, message_id: str, text: str) -> dict[str, Any]:
    """Build the A2A 1.0 JSON-RPC SendMessage request used by the live probe."""

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": message_id,
                "role": "ROLE_USER",
                "parts": [{"text": text}],
            }
        },
    }


def build_send_streaming_message_request(
    request_id: str, message_id: str, text: str
) -> dict[str, Any]:
    """Build the A2A 1.0 streaming request used by the same live probe."""

    request = build_send_message_request(request_id, message_id, text)
    request["method"] = "SendStreamingMessage"
    return request


def parse_sse_events(raw: str) -> list[dict[str, Any]]:
    """Decode JSON payloads from Server-Sent Events without hiding their order."""

    events: list[dict[str, Any]] = []
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(
            line.removeprefix("data:").lstrip()
            for line in block.splitlines()
            if line.startswith("data:")
        )
        if not data:
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise RuntimeError("A2A stream returned a non-JSON SSE data event") from exc
        if isinstance(payload, dict):
            events.append(payload)
    return events


def run_probe(
    agent_base_url: str,
    transport: Transport | None = None,
    stream_transport: StreamTransport | None = None,
    *,
    expect_routing_failure: bool = False,
) -> dict[str, Any]:
    """Read a card and follow its advertised A2A 1.0 interface exactly once."""

    send = transport or _http_transport
    stream_send = stream_transport or _http_stream_transport
    card_url = build_agent_card_url(agent_base_url)
    card_result = send("GET", card_url, {"Accept": "application/json"}, None)
    if card_result.status != 200:
        raise RuntimeError(f"Agent Card request returned HTTP {card_result.status}")

    try:
        interface_url = select_jsonrpc_interface(card_result.body)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    request = build_send_message_request(
        request_id="day17-good",
        message_id=str(uuid.uuid4()),
        text=f"Reply with {EXPECTED_REPLY} and do not call a tool.",
    )
    headers = {
        "Accept": "application/json",
        "A2A-Version": A2A_VERSION,
        "Content-Type": "application/json",
    }
    invocation_result = send("POST", interface_url, headers, request)
    task = _task_from_response(invocation_result.body)
    task_state = task.get("status", {}).get("state", "")
    context_id = task.get("contextId", "")
    reply_text = " ".join(_message_texts(task)).strip()
    execution_ok = (
        invocation_result.status == 200
        and not invocation_result.body.get("error")
        and task_state == "TASK_STATE_COMPLETED"
        and EXPECTED_REPLY in reply_text
    )
    if expect_routing_failure:
        invocation_status = "EXPECTED_FAIL" if invocation_result.status == 404 else "FAIL"
        task_state = "NOT_REACHED"
        context_id = "NOT_AVAILABLE"
        reply_text = "NOT_AVAILABLE"
    else:
        invocation_status = "PASS" if execution_ok else "FAIL"

    stream_request = build_send_streaming_message_request(
        request_id="day17-stream",
        message_id=str(uuid.uuid4()),
        text=f"Reply with {EXPECTED_REPLY} and do not call a tool.",
    )
    stream_headers = {
        "Accept": "text/event-stream",
        "A2A-Version": A2A_VERSION,
        "Content-Type": "application/json",
    }
    stream_result = stream_send("POST", interface_url, stream_headers, stream_request)
    stream_events = parse_sse_events(stream_result.body) if stream_result.status == 200 else []
    stream_evidence = _stream_evidence(stream_events)
    stream_ok = (
        stream_result.status == 200
        and stream_result.content_type.startswith("text/event-stream")
        and stream_evidence["events"] == EXPECTED_STREAM_EVENTS
        and stream_evidence["states"][-1:] == ["TASK_STATE_COMPLETED"]
        and stream_evidence["last_chunk"] is True
        and EXPECTED_REPLY in stream_evidence["reply"]
        and len(stream_evidence["task_ids"]) == 1
        and len(stream_evidence["context_ids"]) == 1
    )
    if expect_routing_failure:
        stream_status = "EXPECTED_FAIL" if stream_result.status == 404 else "FAIL"
        stream_evidence = {
            "states": ["NOT_REACHED"],
            "events": ["NOT_REACHED"],
            "last_chunk": False,
            "task_ids": [],
            "context_ids": [],
            "reply": "NOT_AVAILABLE",
        }
    else:
        stream_status = "PASS" if stream_ok else "FAIL"

    cases = [
        {
            "case_id": "agent-card",
            "layer": "discovery",
            "label": "Agent Card",
            "http_status": card_result.status,
            "status": "PASS",
            "protocol_version": A2A_VERSION,
            "interface_url": interface_url,
        },
        {
            "case_id": "a2a-1.0-stream",
            "layer": "routing" if expect_routing_failure else "protocol-and-execution",
            "label": "A2A 1.0 / SSE stream",
            "http_status": stream_result.status,
            "status": stream_status,
            "method": stream_request["method"],
            "content_type": stream_result.content_type,
            "states": stream_evidence["states"],
            "events": stream_evidence["events"],
            "last_chunk": stream_evidence["last_chunk"],
            "task_ids": stream_evidence["task_ids"],
            "context_ids": stream_evidence["context_ids"],
            "reply": stream_evidence["reply"],
            "interface_url": interface_url,
        },
        {
            "case_id": "a2a-1.0-send-message",
            "layer": "routing" if expect_routing_failure else "protocol-and-execution",
            "label": "A2A 1.0 / SendMessage",
            "http_status": invocation_result.status,
            "status": invocation_status,
            "method": request["method"],
            "task_state": task_state or "NOT_AVAILABLE",
            "context_id": context_id or "NOT_AVAILABLE",
            "reply": reply_text or "NOT_AVAILABLE",
            "interface_url": interface_url,
        },
    ]
    matched = sum(item["status"] in {"PASS", "EXPECTED_FAIL"} for item in cases)
    return {
        "schema": "ithelp.a2a-path-report.v1",
        "a2a_version": A2A_VERSION,
        "cases": cases,
        "summary": {"matched": matched, "total": len(cases)},
    }


def render_terminal(report: dict[str, Any]) -> str:
    """Render a compact evidence view without hiding the expected negative case."""

    cases = {item["case_id"]: item for item in report["cases"]}
    discovery = cases["agent-card"]
    invocation = cases["a2a-1.0-send-message"]
    stream = cases["a2a-1.0-stream"]
    summary = report["summary"]
    return (
        "\n".join(
            [
                "DAY 17 / A2A PATH",
                "",
                (
                    f"{discovery['label']:<30} HTTP {discovery['http_status']:<3} "
                    f"{discovery['status']}"
                ),
                (
                    f"{invocation['label']:<30} HTTP {invocation['http_status']:<3} "
                    f"{invocation['status']}"
                ),
                (f"{stream['label']:<30} HTTP {stream['http_status']:<3} {stream['status']}"),
                "",
                f"advertised-url={invocation['interface_url']}",
                f"task-state={invocation['task_state']}",
                f"context-id={invocation['context_id']}",
                f"agent-reply={invocation['reply']}",
                f"stream-events={' > '.join(stream['events'])}",
                f"stream-last-chunk={str(stream['last_chunk']).lower()}",
                f"stream-task-id={_one_or_not_available(stream['task_ids'])}",
                f"stream-context-id={_one_or_not_available(stream['context_ids'])}",
                "",
                f"matched {summary['matched']}/{summary['total']}",
            ]
        )
        + "\n"
    )


def _task_from_response(body: dict[str, Any]) -> dict[str, Any]:
    result = body.get("result", {})
    task = result.get("task")
    return task if isinstance(task, dict) else {}


def _message_texts(task: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for message in task.get("history", []):
        if message.get("role") != "ROLE_AGENT":
            continue
        for part in message.get("parts", []):
            if isinstance(part.get("text"), str):
                texts.append(part["text"])
    for artifact in task.get("artifacts", []):
        for part in artifact.get("parts", []):
            if isinstance(part.get("text"), str):
                texts.append(part["text"])
    return list(dict.fromkeys(texts))


def _stream_evidence(events: list[dict[str, Any]]) -> dict[str, Any]:
    states: list[str] = []
    event_labels: list[str] = []
    task_ids: set[str] = set()
    context_ids: set[str] = set()
    texts: list[str] = []
    last_chunk = False
    for event in events:
        result = event.get("result", {})
        update = result.get("statusUpdate") or result.get("artifactUpdate") or {}
        if isinstance(update.get("taskId"), str):
            task_ids.add(update["taskId"])
        if isinstance(update.get("contextId"), str):
            context_ids.add(update["contextId"])
        status = update.get("status", {})
        if isinstance(status.get("state"), str):
            states.append(status["state"])
            label = status["state"].removeprefix("TASK_STATE_")
            message = status.get("message", {})
            if label == "WORKING" and message.get("role") == "ROLE_AGENT":
                label = "AGENT_MESSAGE"
            event_labels.append(label)
        artifact = update.get("artifact", {})
        for part in artifact.get("parts", []):
            if isinstance(part.get("text"), str):
                texts.append(part["text"])
        last_chunk = last_chunk or update.get("lastChunk") is True
        if artifact:
            event_labels.append("ARTIFACT(last)" if update.get("lastChunk") is True else "ARTIFACT")
    return {
        "states": states,
        "events": event_labels,
        "last_chunk": last_chunk,
        "task_ids": sorted(task_ids),
        "context_ids": sorted(context_ids),
        "reply": " ".join(texts).strip(),
    }


def _one_or_not_available(values: list[str]) -> str:
    return values[0] if len(values) == 1 else "NOT_AVAILABLE"


def _http_transport(
    method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None
) -> HttpResult:
    payload = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            response_body = response.read()
            return HttpResult(response.status, _decode_json(response_body))
    except urllib.error.HTTPError as exc:
        return HttpResult(exc.code, _decode_json(exc.read()))


def _http_stream_transport(
    method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None
) -> HttpStreamResult:
    payload = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return HttpStreamResult(
                response.status,
                response.headers.get("Content-Type", ""),
                response.read().decode(errors="replace"),
            )
    except urllib.error.HTTPError as exc:
        return HttpStreamResult(
            exc.code,
            exc.headers.get("Content-Type", ""),
            exc.read().decode(errors="replace"),
        )


def _decode_json(raw: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"raw": raw.decode(errors="replace")}
    return decoded if isinstance(decoded, dict) else {"value": decoded}


def entrypoint() -> None:
    parser = argparse.ArgumentParser(prog="day17-a2a-probe")
    parser.add_argument("--gateway-base", required=True)
    parser.add_argument("--expect-routing-failure", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    report = run_probe(args.gateway_base, expect_routing_failure=args.expect_routing_failure)
    output = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.as_json
        else render_terminal(report)
    )
    print(output)
    if report["summary"]["matched"] != report["summary"]["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    entrypoint()
