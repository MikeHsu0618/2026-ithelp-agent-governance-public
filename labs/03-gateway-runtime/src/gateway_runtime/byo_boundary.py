"""Day 18 BYO Agent, Agent-as-Tool, HITL, and identity probe."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

ACTOR = "sre-oncaller"
RESOURCE = "demo/cache"
WELL_KNOWN_AGENT_CARD_PATH = "/.well-known/agent-card.json"


@dataclass(frozen=True)
class HttpResult:
    """HTTP response shape shared by the live and in-memory transports."""

    status: int
    body: dict[str, Any]


Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None], HttpResult]
Decision = Literal["approve", "reject"]


def build_message_request(message_id: str, text: str) -> dict[str, Any]:
    """Build a direct A2A message/send request for a new conversation."""

    return {
        "jsonrpc": "2.0",
        "id": f"request-{message_id}",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": message_id,
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }


def build_decision_request(
    *,
    request_id: str,
    message_id: str,
    task_id: str,
    context_id: str,
    decision: Decision,
) -> dict[str, Any]:
    """Resume a pending A2A task with an explicit HITL decision."""

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": {
            "message": {
                "messageId": message_id,
                "taskId": task_id,
                "contextId": context_id,
                "role": "user",
                "parts": [
                    {
                        "kind": "data",
                        "data": {"decision_type": decision},
                    }
                ],
            }
        },
    }


def extract_task(response: dict[str, Any]) -> dict[str, Any]:
    """Return a Task from either a direct or agentgateway-wrapped response."""

    result = response.get("result")
    if isinstance(result, dict):
        task = result.get("task", result)
        if isinstance(task, dict) and task.get("id") and isinstance(task.get("status"), dict):
            return task
    error = response.get("error", "missing result")
    raise RuntimeError(f"response does not contain an A2A task: {error}")


def run_probe(
    parent_url: str,
    byo_url: str,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """Run approve and reject paths through a declarative parent and BYO child."""

    send = transport or _http_transport
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-user-id": ACTOR,
    }
    card_url = byo_url.rstrip("/") + WELL_KNOWN_AGENT_CARD_PATH
    card_result = send("GET", card_url, {"Accept": "application/json"}, None)
    card_ok = card_result.status == 200 and bool(card_result.body.get("name"))

    approved = _run_decision_path(send, parent_url, headers, "approve")
    rejected = _run_decision_path(send, parent_url, headers, "reject")

    approved_text = approved["reply"]
    rejected_text = rejected["reply"]
    agent_as_tool_ok = (
        approved["paused_state"] == "input-required"
        and approved["final_state"] == "completed"
        and "ACTION_EXECUTED" in approved_text
    )
    approval_ok = agent_as_tool_ok and f"resource={RESOURCE}" in approved_text
    rejection_ok = (
        rejected["paused_state"] == "input-required"
        and rejected["final_state"] == "completed"
        and "ACTION_SKIPPED" in rejected_text
        and "ACTION_EXECUTED" not in rejected_text
    )
    identity_ok = f"actor={ACTOR}" in approved_text

    cases = [
        {
            "case_id": "byo-agent-card",
            "layer": "registration-and-discovery",
            "label": "BYO Agent Card",
            "status": "PASS" if card_ok else "FAIL",
            "http_status": card_result.status,
            "agent_name": card_result.body.get("name", "NOT_AVAILABLE"),
        },
        {
            "case_id": "agent-as-tool",
            "layer": "platform-integration",
            "label": "Declarative Agent -> BYO Agent",
            "status": "PASS" if agent_as_tool_ok else "FAIL",
            "paused_state": approved["paused_state"],
            "final_state": approved["final_state"],
        },
        {
            "case_id": "nested-hitl-approve",
            "layer": "runtime-interoperability",
            "label": "Nested HITL approve/resume",
            "status": "PASS" if approval_ok else "FAIL",
            "reply": approved_text,
        },
        {
            "case_id": "nested-hitl-reject",
            "layer": "runtime-interoperability",
            "label": "Nested HITL reject/resume",
            "status": "PASS" if rejection_ok else "FAIL",
            "reply": rejected_text,
            "rejected_without_execution": rejection_ok,
        },
        {
            "case_id": "identity-propagation",
            "layer": "identity",
            "label": "Synthetic actor propagation",
            "status": "PASS" if identity_ok else "FAIL",
            "expected_actor": ACTOR,
            "reply": approved_text,
        },
    ]
    matched = sum(case["status"] == "PASS" for case in cases)
    return {
        "schema": "ithelp.byo-boundary-report.v1",
        "actor": ACTOR,
        "resource": RESOURCE,
        "cases": cases,
        "summary": {"matched": matched, "total": len(cases)},
    }


def render_terminal(report: dict[str, Any]) -> str:
    """Render the public evidence without dumping raw protocol payloads."""

    cases = {case["case_id"]: case for case in report["cases"]}
    summary = report["summary"]
    rows = [
        "DAY 18 / BYO PLATFORM BOUNDARY",
        "",
    ]
    for case in report["cases"]:
        rows.append(f"{case['label']:<36} {case['status']}")
    rows.extend(
        [
            "",
            f"approve-reply={cases['nested-hitl-approve']['reply']}",
            f"reject-reply={cases['nested-hitl-reject']['reply']}",
            (
                "rejected-without-execution="
                f"{str(cases['nested-hitl-reject']['rejected_without_execution']).lower()}"
            ),
            f"matched {summary['matched']}/{summary['total']}",
        ]
    )
    return "\n".join(rows)


def _run_decision_path(
    send: Transport,
    parent_url: str,
    headers: dict[str, str],
    decision: Decision,
) -> dict[str, str]:
    message_id = str(uuid.uuid4())
    start = build_message_request(
        message_id,
        (
            f"Ask the BYO Agent to change {RESOURCE}. "
            "Use the registered Agent tool and return its exact result."
        ),
    )
    start_result = send("POST", parent_url.rstrip("/"), headers, start)
    if start_result.status != 200:
        raise RuntimeError(f"initial A2A request returned HTTP {start_result.status}")
    pending_task = extract_task(start_result.body)
    pending_state = _normalize_state(pending_task.get("status", {}).get("state"))
    if pending_state != "input-required":
        raise RuntimeError(f"pending A2A task must be input-required, got {pending_state}")
    task_id = str(pending_task["id"])
    context_id = pending_task.get("contextId")
    if not isinstance(context_id, str) or not context_id.strip():
        raise RuntimeError("pending A2A task is missing a contextId")

    resume = build_decision_request(
        request_id=f"day18-{decision}",
        message_id=str(uuid.uuid4()),
        task_id=task_id,
        context_id=context_id,
        decision=decision,
    )
    resume_result = send("POST", parent_url.rstrip("/"), headers, resume)
    if resume_result.status != 200:
        raise RuntimeError(f"A2A resume returned HTTP {resume_result.status}")
    final_task = extract_task(resume_result.body)
    if str(final_task.get("id")) != task_id:
        raise RuntimeError("A2A resume changed task id")
    if final_task.get("contextId") != context_id:
        raise RuntimeError("A2A resume changed contextId")
    final_state = _normalize_state(final_task.get("status", {}).get("state"))
    if final_state != "completed":
        raise RuntimeError(f"final A2A task must be completed, got {final_state}")

    return {
        "paused_state": pending_state,
        "final_state": final_state,
        "reply": " ".join(_task_texts(final_task)).strip(),
    }


def _normalize_state(value: Any) -> str:
    state = str(value or "not-available").lower()
    state = state.removeprefix("task_state_").replace("_", "-")
    return state


def _task_texts(task: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for artifact in task.get("artifacts", []):
        for part in artifact.get("parts", []):
            if part.get("text"):
                texts.append(str(part["text"]))
    if texts:
        return texts

    status_message = task.get("status", {}).get("message", {})
    for part in status_message.get("parts", []):
        if part.get("text"):
            texts.append(str(part["text"]))
    return texts


def _http_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None,
) -> HttpResult:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode())
            return HttpResult(response.status, payload)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"error": raw}
        return HttpResult(exc.code, payload)


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-url", required=True)
    parser.add_argument("--byo-url", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_probe(args.parent_url, args.byo_url)
    output = (
        json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_terminal(report)
    )
    print(output)
    if report["summary"]["matched"] != report["summary"]["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    _main()
