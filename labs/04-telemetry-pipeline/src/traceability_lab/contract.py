from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator


class ContractError(ValueError):
    """Raised when a governance event does not satisfy the public field set."""


@dataclass(frozen=True, slots=True)
class ActionContext:
    action_id: str
    trace_id: str
    span_id: str
    occurred_at: str


def build_action_context(
    *, action_id: str, trace_id: str, span_id: str, occurred_at: str
) -> ActionContext:
    return ActionContext(
        action_id=action_id,
        trace_id=trace_id,
        span_id=span_id,
        occurred_at=occurred_at,
    )


def build_application_record(context: ActionContext) -> dict[str, Any]:
    """Build the product-facing record without upgrading a UI hint to identity evidence."""

    return {
        "record_type": "application.action",
        "action_id": context.action_id,
        "session_id": "session/day20-fixture",
        "generation_id": "generation/day20-fixture",
        "actor_hint": "user/sre-oncaller",
        "agent_name": "sre-investigation-agent",
        "model": "deterministic-fixture",
        "tool_call": {
            "name": "delete_demo_database",
            "arguments_summary": "target=demo/database",
            "result": "CANARY_TRIGGERED",
        },
    }


def build_governance_event(context: ActionContext) -> dict[str, Any]:
    event = {
        "schema_version": "0.1",
        "event_id": f"evt-{context.action_id.removeprefix('act-')}",
        "action_id": context.action_id,
        "occurred_at": context.occurred_at,
        "correlation": {"trace_id": context.trace_id, "span_id": context.span_id},
        "principal": {
            "id": "user/sre-oncaller",
            "kind": "human",
            "assurance": "VERIFIED",
            "source": "lab-fixture-idp",
        },
        "delegation": {
            "on_behalf_of": "user/sre-oncaller",
            "actor_chain": [
                "user/sre-oncaller",
                "agent/sre-investigation-agent",
                "workload/sre-investigation-agent",
            ],
        },
        "workload": {
            "id": "workload/sre-investigation-agent",
            "kind": "workload",
            "assurance": "ASSERTED",
            "source": "lab-fixture-runtime",
        },
        "agent": {
            "name": "sre-investigation-agent",
            "version": "day20-fixture",
            "artifact_digest": "sha256:" + ("d20a" * 16),
        },
        "target": {"tool": "delete_demo_database", "resource": "demo/database"},
        "policy": {
            "id": "tool-boundary",
            "version": "v3",
            "decision": "ALLOW",
            "enforcement_point": "lab-authorizer",
        },
        "approval": {"status": "NOT_APPLICABLE"},
        "result": {
            "status": "CANARY_TRIGGERED",
            "effect": {"kind": "NO_OP_CANARY", "status": "SIMULATED", "count": 0},
        },
    }
    validate_governance_event(event)
    return event


def validate_governance_event(event: dict[str, Any]) -> None:
    schema_path = files("traceability_lab.schemas").joinpath("governed-action-v0.1.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(event),
        key=lambda item: list(item.path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "event"
        raise ContractError(f"{location}: {error.message}")
