from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from incident_replay.evidence import EvidenceCase

EVIDENCE_STATUSES = frozenset({"VERIFIED", "OBSERVED", "UNKNOWN", "NOT_APPLICABLE"})
TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
SPAN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


def _field(
    value: Any,
    status: str,
    sources: list[str] | tuple[str, ...],
    reason: str,
) -> dict[str, Any]:
    if status not in EVIDENCE_STATUSES:
        raise ValueError(f"unsupported evidence status: {status}")
    return {
        "value": value,
        "status": status,
        "sources": list(sources),
        "reason": reason,
    }


def _matching_event(
    events: tuple[dict[str, Any], ...], event_type: str, target_tool: str
) -> dict[str, Any] | None:
    matches = [
        event
        for event in events
        if event.get("event_type") == event_type and event.get("tool_name") == target_tool
    ]
    if len(matches) > 1:
        raise ValueError(
            f"ambiguous historical evidence: multiple {event_type} events for {target_tool}"
        )
    return matches[0] if matches else None


def _resource(tool_call: dict[str, Any] | None, executed: dict[str, Any] | None) -> Any:
    if executed and executed.get("resource") is not None:
        return executed["resource"]
    arguments = tool_call.get("arguments", {}) if tool_call else {}
    if isinstance(arguments, dict):
        return arguments.get("database") or arguments.get("resource")
    return None


def _argument_resource(arguments: Any) -> Any:
    if not isinstance(arguments, dict):
        return None
    return arguments.get("database") or arguments.get("resource")


def _timestamp(event: dict[str, Any]) -> datetime:
    raw = str(event.get("timestamp", ""))
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid event timestamp: {raw!r}") from exc


def _action_timeline(events: tuple[dict[str, Any], ...], target_tool: str) -> list[dict[str, Any]]:
    trace_context_events = {"run.started", "run.completed", "input.guard.decision"}
    selected = [
        event
        for event in events
        if event.get("event_type") in trace_context_events or event.get("tool_name") == target_tool
    ]
    return sorted(selected, key=_timestamp)


def reconstruct_action(case: EvidenceCase, *, target_tool: str) -> dict[str, Any]:
    manifest_trace = case.manifest.get("trace_id")
    if not isinstance(manifest_trace, str) or not TRACE_ID_PATTERN.fullmatch(manifest_trace):
        raise ValueError("manifest trace_id must be 32 lowercase hexadecimal characters")
    trace_ids = {manifest_trace}
    for index, item in enumerate(case.events, 1):
        event_trace = item.get("trace_id")
        if not isinstance(event_trace, str) or not TRACE_ID_PATTERN.fullmatch(event_trace):
            raise ValueError(f"events.jsonl:{index} has an invalid trace_id")
        trace_ids.add(event_trace)
    if len(trace_ids) != 1:
        raise ValueError(f"evidence contains multiple trace IDs: {sorted(trace_ids)}")
    trace_id = next(iter(trace_ids))

    timeline = _action_timeline(case.events, target_tool)
    tool_call = _matching_event(case.events, "model.tool_call", target_tool)
    policy = _matching_event(case.events, "policy.decision", target_tool)
    executed = _matching_event(case.events, "tool.executed", target_tool)
    completed = _matching_event(case.events, "run.completed", target_tool)
    action_events = [event for event in (tool_call, policy, executed, completed) if event]
    if not action_events:
        raise ValueError(f"historical evidence contains no events for target Tool {target_tool}")
    for event in action_events:
        span_id = event.get("span_id")
        if not isinstance(span_id, str) or not SPAN_ID_PATTERN.fullmatch(span_id):
            raise ValueError(
                "action events must contain a 16-character lowercase hexadecimal span_id"
            )
    if len(action_events) > 1:
        span_ids = [event.get("span_id") for event in action_events]
        if len(set(span_ids)) != 1:
            raise ValueError("action events contain inconsistent span IDs")
        for earlier, later in zip(action_events, action_events[1:], strict=False):
            if _timestamp(earlier) > _timestamp(later):
                raise ValueError("action event order is inconsistent")
    matching_canaries = [
        item
        for item in case.canary_events
        if item.get("trace_id") == trace_id and item.get("tool_name") == target_tool
    ]
    if len(matching_canaries) > 1:
        raise ValueError(
            f"ambiguous historical evidence: multiple canary receipts for {target_tool}"
        )
    canary = matching_canaries[0] if matching_canaries else None
    if canary:
        try:
            _timestamp(canary)
        except ValueError as exc:
            raise ValueError("canary receipt has an invalid timestamp") from exc
        canary_result = canary.get("result")
        canary_resource = canary.get("database") or canary.get("resource")
        if not isinstance(canary_result, str) or not canary_result:
            raise ValueError("canary receipt must contain a non-empty result")
        if not isinstance(canary_resource, str) or not canary_resource:
            raise ValueError("canary receipt must contain a non-empty resource")
    decision = policy.get("decision") if policy else None
    if decision == "DENY" and (executed or canary):
        raise ValueError("DENY decision contradicts execution or canary evidence")
    if decision == "DENY" and completed:
        denied_results = {"DENY", "DENIED", "POLICY_DENIED"}
        if completed.get("result") not in denied_results or completed.get("canary_delta") not in {
            None,
            0,
        }:
            raise ValueError("DENY decision contradicts the completion outcome")

    resource_candidates = (
        (_resource(None, executed), "events.jsonl:tool.executed"),
        (
            _argument_resource(policy.get("tool_arguments")) if policy else None,
            "events.jsonl:policy.decision",
        ),
        (_resource(tool_call, None), "events.jsonl:model.tool_call"),
        (
            (canary.get("database") or canary.get("resource")) if canary else None,
            "canary.jsonl",
        ),
    )
    resource_values = [value for value, _source in resource_candidates if value is not None]
    if resource_values and any(value != resource_values[0] for value in resource_values[1:]):
        raise ValueError("action evidence contains inconsistent resources")
    resource_value, resource_source = next(
        ((value, source) for value, source in resource_candidates if value is not None),
        (None, None),
    )

    result_values = [
        event.get("result")
        for event in (executed, completed, canary)
        if event and event.get("result") is not None
    ]
    if result_values and any(value != result_values[0] for value in result_values[1:]):
        raise ValueError("action evidence contains inconsistent results")
    event_id = (
        "evt-replay-"
        + uuid.uuid5(uuid.NAMESPACE_URL, f"ithelp:{case.case_id}:{trace_id}:{target_tool}").hex
    )

    result_candidates = (
        (executed, "events.jsonl:tool.executed"),
        (completed, "events.jsonl:run.completed"),
    )
    result_event, result_source = next(
        (
            (event, source)
            for event, source in result_candidates
            if event and event.get("result") is not None
        ),
        (None, None),
    )
    result_value = result_event.get("result") if result_event else None
    result_reason = (
        "The target Tool execution event records the action result."
        if result_source == "events.jsonl:tool.executed"
        else "The target-specific run summary records the action outcome."
        if result_source == "events.jsonl:run.completed"
        else "The historical evidence contains no result for this action."
    )
    if canary:
        receipt = _field(
            canary,
            "OBSERVED",
            ["canary.jsonl"],
            "The no-op canary artifact corroborates that the Lab Tool executed.",
        )
    elif decision == "DENY":
        receipt = _field(
            None,
            "NOT_APPLICABLE",
            ["events.jsonl:policy.decision"],
            "The policy denied this Tool before execution, so no effect receipt should exist.",
        )
    else:
        receipt = _field(
            None,
            "UNKNOWN",
            [],
            "The historical evidence contains no effect receipt for this Tool.",
        )

    trace_sources = []
    if manifest_trace:
        trace_sources.append("manifest.json")
    if any(item.get("trace_id") == trace_id for item in case.events):
        trace_sources.append("events.jsonl")
    policy_version = policy.get("policy_version") if policy else None
    policy_version_source = "events.jsonl:policy.decision" if policy_version else None
    if not policy_version:
        policy_version = case.manifest.get("policy_version")
        policy_version_source = "manifest.json" if policy_version else None
    span_event = action_events[0]
    span_value = span_event["span_id"]
    span_source = f"events.jsonl:{span_event['event_type']}"
    tool_sources = [f"events.jsonl:{event['event_type']}" for event in action_events]

    return {
        "schema_version": "1.0",
        "record_kind": "RECONSTRUCTED_GOVERNANCE_EVENT",
        "event_id": event_id,
        "case_id": case.case_id,
        "run_id": case.manifest.get("run_id"),
        "identifiers": {
            "original_event_id": _field(
                None,
                "UNKNOWN",
                [],
                "The original run did not assign a governance event ID.",
            ),
            "action_id": _field(
                None,
                "UNKNOWN",
                [],
                "The original run correlated records only with trace_id and span_id.",
            ),
            "trace_id": _field(
                trace_id,
                "OBSERVED",
                trace_sources,
                "The trace ID is preserved in the locked historical sources listed here.",
            ),
            "span_id": _field(
                span_value,
                "OBSERVED",
                [span_source],
                "A target-specific action event records the local OpenTelemetry span ID.",
            ),
        },
        "identity": {
            "principal": _field(
                None,
                "UNKNOWN",
                [],
                "No verified human or service principal was recorded for the original run.",
            ),
            "on_behalf_of": _field(
                None,
                "UNKNOWN",
                [],
                "The original run contains no delegation evidence.",
            ),
            "workload": _field(
                None,
                "UNKNOWN",
                [],
                "The runtime name does not prove a workload identity.",
            ),
        },
        "agent": {
            "runtime": _field(
                case.manifest.get("runtime"),
                "OBSERVED" if case.manifest.get("runtime") else "UNKNOWN",
                ["manifest.json"] if case.manifest.get("runtime") else [],
                "The manifest records the framework runtime, not a verified deployment identity."
                if case.manifest.get("runtime")
                else "The historical manifest does not record a framework runtime.",
            ),
            "model": _field(
                case.manifest.get("model_name"),
                "OBSERVED" if case.manifest.get("model_name") else "UNKNOWN",
                ["manifest.json"] if case.manifest.get("model_name") else [],
                "The model name is a run manifest observation."
                if case.manifest.get("model_name")
                else "The historical manifest does not record a model name.",
            ),
            "artifact_digest": _field(
                None,
                "UNKNOWN",
                [],
                "The run did not record the Agent artifact digest or deployment revision.",
            ),
        },
        "credential_reference": _field(
            None,
            "UNKNOWN",
            [],
            "No credential fingerprint or reference was retained.",
        ),
        "target": {
            "tool": _field(
                target_tool,
                "OBSERVED",
                tool_sources,
                "The Tool name appears in the listed target-specific action events.",
            ),
            "resource": _field(
                resource_value,
                "OBSERVED" if resource_value is not None else "UNKNOWN",
                [resource_source] if resource_source else [],
                "The target resource is present in the cited action evidence."
                if resource_value is not None
                else "The original run did not record a target resource.",
            ),
        },
        "policy": {
            "id": _field(
                None,
                "UNKNOWN",
                [],
                "The event records a policy version but no stable policy artifact ID.",
            ),
            "version": _field(
                policy_version,
                "OBSERVED" if policy_version is not None else "UNKNOWN",
                [policy_version_source] if policy_version_source else [],
                "The policy version is recorded by the Lab runtime."
                if policy_version is not None
                else "The historical evidence does not record a policy version.",
            ),
            "decision": _field(
                decision,
                "OBSERVED" if decision else "UNKNOWN",
                ["events.jsonl:policy.decision"] if decision else [],
                "The runtime emitted the policy decision, but no independent "
                "decision receipt exists."
                if decision
                else "The historical evidence does not record a policy decision.",
            ),
            "enforcement_point": _field(
                None,
                "UNKNOWN",
                [],
                "The original event does not identify a separately verified enforcement point.",
            ),
        },
        "approval": _field(
            None,
            "UNKNOWN",
            [],
            "The historical event does not say whether approval was absent or merely unrecorded.",
        ),
        "result": {
            "status": _field(
                result_value,
                "OBSERVED" if result_value is not None else "UNKNOWN",
                [result_source] if result_source else [],
                result_reason,
            ),
            "effect_receipt": receipt,
        },
        "backend_presence": {
            name: _field(
                None,
                "UNKNOWN",
                [],
                f"The original run does not contain evidence that {name} received this trace.",
            )
            for name in ("tempo", "loki", "prometheus", "gateway")
        },
        "integrity": {
            "repository_lock": _field(
                case.locked_files,
                "VERIFIED",
                ["evidence-lock.json"],
                "SHA-256 verifies that inputs still match the Day 26 repository lock.",
            ),
            "original_tamper_evidence": _field(
                None,
                "UNKNOWN",
                [],
                "A later repository hash is not an append-only or signed record from event time.",
            ),
            "retention_guarantee": _field(
                None,
                "UNKNOWN",
                [],
                "The Lab has files on disk but no retention or legal-hold guarantee.",
            ),
        },
        "timeline": timeline,
    }
