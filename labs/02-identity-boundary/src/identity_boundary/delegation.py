"""Validation for the published Delegation Context v0.1 contract."""

import json
from collections.abc import Mapping
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMA_FILENAME = "delegation-context-v0.1.schema.json"


class DelegationContextRejected(ValueError):
    """A stable, public rejection code for invalid delegation evidence."""

    def __init__(self, code: str, stage: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.stage = stage
        self.detail = detail


@lru_cache(maxsize=1)
def load_delegation_schema() -> dict[str, Any]:
    """Load the schema from package data so installed CLI builds keep working."""

    resource = files("identity_boundary.schemas").joinpath(SCHEMA_FILENAME)
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_delegation_context(context: Mapping[str, Any]) -> None:
    """Validate structure first, then rules that JSON Schema cannot express clearly."""

    null_path = _first_null_path(context)
    if null_path is not None:
        raise DelegationContextRejected(
            "NULL_NOT_ALLOWED",
            "schema",
            f"use an explicit identity state instead of null at {null_path}",
        )

    errors = list(Draft202012Validator(load_delegation_schema()).iter_errors(context))
    if errors:
        error = min(errors, key=_error_priority)
        raise DelegationContextRejected(
            _schema_error_code(error),
            "schema",
            _safe_schema_detail(error),
        )

    _validate_timestamp(str(context["timestamp"]))
    actor_chain = context["actor_chain"]
    agents = actor_chain["agents"]
    sequences = [agent["sequence"] for agent in agents]
    if sequences != list(range(len(agents))):
        raise DelegationContextRejected(
            "AGENT_SEQUENCE_INVALID",
            "semantics",
            "agent sequence must be unique, ordered, and start at zero",
        )

    roles = [agent["role"] for agent in agents]
    if roles[-1] != "EXECUTING" or any(role != "DELEGATING" for role in roles[:-1]):
        raise DelegationContextRejected(
            "AGENT_ROLE_INVALID",
            "semantics",
            "only the last agent may have the EXECUTING role",
        )

    _validate_flow_semantics(str(context["flow_kind"]), actor_chain)


def _first_null_path(value: Any, path: str = "$") -> str | None:
    if value is None:
        return path
    if isinstance(value, Mapping):
        for key, child in value.items():
            found = _first_null_path(child, f"{path}.{key}")
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _first_null_path(child, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def _error_priority(error: ValidationError) -> tuple[int, int, str]:
    order = {"required": 0, "additionalProperties": 1}
    return order.get(error.validator, 2), len(error.absolute_path), error.json_path


def _schema_error_code(error: ValidationError) -> str:
    if error.validator == "required":
        return "REQUIRED_FIELD_MISSING"
    if error.validator == "additionalProperties":
        return "FIELD_NOT_ALLOWED"
    return "CONTEXT_SCHEMA_INVALID"


def _safe_schema_detail(error: ValidationError) -> str:
    if error.validator == "required":
        return f"required field missing at {error.json_path}"
    if error.validator == "additionalProperties":
        return f"field is not allowed at {error.json_path}"
    return f"schema validation failed at {error.json_path}"


def _validate_timestamp(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DelegationContextRejected(
            "TIMESTAMP_INVALID", "semantics", "timestamp must be an RFC 3339 value"
        ) from error
    if parsed.utcoffset() is None:
        raise DelegationContextRejected(
            "TIMESTAMP_INVALID", "semantics", "timestamp must include a UTC offset"
        )


def _validate_flow_semantics(flow_kind: str, actor_chain: Mapping[str, Any]) -> None:
    human_state = actor_chain["human"]["state"]
    service_state = actor_chain["service"]["state"]
    agent_count = len(actor_chain["agents"])

    if flow_kind == "HUMAN_DELEGATED" and human_state != "PRESENT":
        raise DelegationContextRejected(
            "FLOW_IDENTITY_MISMATCH",
            "semantics",
            "HUMAN_DELEGATED requires a present human identity",
        )
    if flow_kind == "SERVICE_AUTONOMOUS" and (
        human_state != "NOT_APPLICABLE" or service_state != "PRESENT"
    ):
        raise DelegationContextRejected(
            "FLOW_IDENTITY_MISMATCH",
            "semantics",
            "SERVICE_AUTONOMOUS requires a service and NOT_APPLICABLE human slot",
        )
    if flow_kind == "AGENT_TO_AGENT" and agent_count < 2:
        raise DelegationContextRejected(
            "FLOW_IDENTITY_MISMATCH",
            "semantics",
            "AGENT_TO_AGENT requires at least two agents in the chain",
        )
