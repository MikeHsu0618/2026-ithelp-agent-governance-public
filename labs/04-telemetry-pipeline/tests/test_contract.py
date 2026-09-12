from copy import deepcopy

import pytest

from traceability_lab.contract import (
    ContractError,
    build_action_context,
    build_application_record,
    build_governance_event,
    validate_governance_event,
)


def test_three_records_share_an_action_without_pretending_they_answer_the_same_questions() -> None:
    context = build_action_context(
        action_id="act-day20-contract",
        trace_id="1" * 32,
        span_id="2" * 16,
        occurred_at="2026-09-12T00:00:00Z",
    )

    application = build_application_record(context)
    governance = build_governance_event(context)

    assert application["action_id"] == governance["action_id"]
    assert application["actor_hint"] == "user/sre-oncaller"
    assert "principal" not in application
    assert governance["principal"] == {
        "assurance": "VERIFIED",
        "id": "user/sre-oncaller",
        "kind": "human",
        "source": "lab-fixture-idp",
    }
    assert governance["policy"]["decision"] == "ALLOW"
    assert governance["result"]["effect"] == {
        "count": 0,
        "kind": "NO_OP_CANARY",
        "status": "SIMULATED",
    }


def test_governance_event_requires_a_policy_version() -> None:
    context = build_action_context(
        action_id="act-day20-negative",
        trace_id="3" * 32,
        span_id="4" * 16,
        occurred_at="2026-09-12T00:00:00Z",
    )
    event = build_governance_event(context)
    invalid = deepcopy(event)
    invalid["policy"].pop("version")

    with pytest.raises(ContractError, match="policy"):
        validate_governance_event(invalid)


def test_governance_event_rejects_unbounded_or_secret_bearing_fields() -> None:
    context = build_action_context(
        action_id="act-day20-secret",
        trace_id="5" * 32,
        span_id="6" * 16,
        occurred_at="2026-09-12T00:00:00Z",
    )
    event = build_governance_event(context)
    invalid = deepcopy(event)
    invalid["raw_prompt"] = "do the dangerous thing"

    with pytest.raises(ContractError, match="raw_prompt"):
        validate_governance_event(invalid)
