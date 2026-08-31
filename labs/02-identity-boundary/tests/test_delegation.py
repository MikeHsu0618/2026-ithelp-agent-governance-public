from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from identity_boundary.delegation import (
    DelegationContextRejected,
    load_delegation_schema,
    validate_delegation_context,
)


def valid_context() -> dict:
    return {
        "schema_version": "delegation-context/v0.1",
        "event_id": "evt-day09-001",
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
        "timestamp": "2026-08-19T08:00:00Z",
        "flow_kind": "HUMAN_DELEGATED",
        "actor_chain": {
            "human": {
                "state": "PRESENT",
                "principal": "user/sre-oncaller",
                "evidence_source": "verified_access_token.sub",
                "evidence_level": "VERIFIED",
            },
            "service": {
                "state": "PRESENT",
                "principal": "client/sre-console",
                "evidence_source": "verified_access_token.client_id",
                "evidence_level": "CONTEXT_ONLY",
            },
            "agents": [
                {
                    "sequence": 0,
                    "principal": "agent/sre-copilot",
                    "version": "v1",
                    "role": "DELEGATING",
                    "evidence_source": "controlled_deployment_metadata",
                    "evidence_level": "ASSERTED",
                },
                {
                    "sequence": 1,
                    "principal": "agent/sre-investigator",
                    "version": "v1",
                    "role": "EXECUTING",
                    "evidence_source": "controlled_deployment_metadata",
                    "evidence_level": "ASSERTED",
                },
            ],
            "workload": {
                "state": "PRESENT",
                "principal": "k8s://lab/identity-boundary/sa/sre-agent",
                "evidence_source": "kubernetes.serviceaccount",
                "evidence_level": "ASSERTED",
            },
        },
        "credential": {
            "type": "OAUTH_ACCESS_TOKEN",
            "issuer": "https://issuer.lab.example/identity-boundary",
            "subject": "user/sre-oncaller",
            "client_id": "sre-console",
            "audiences": ["mcp://lab/observability/query"],
            "fingerprint": "sha256:" + "a" * 64,
        },
        "target": {
            "resource": "mcp://lab/observability/query",
            "action": "query_logs",
        },
    }


def test_published_schema_is_valid_draft_2020_12() -> None:
    schema = load_delegation_schema()

    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("delegation-context-v0.1.schema.json")


def test_valid_multi_agent_context_passes_schema_and_semantics() -> None:
    validate_delegation_context(valid_context())


def test_issuer_scoped_opaque_subject_does_not_require_a_display_prefix() -> None:
    context = valid_context()
    opaque_subject = "5fcb9c42-8768-4d67-8b88-21f540ad2517"
    context["actor_chain"]["human"]["principal"] = opaque_subject
    context["credential"]["subject"] = opaque_subject

    validate_delegation_context(context)


def test_unknown_workload_is_explicit_and_does_not_invent_a_principal() -> None:
    context = valid_context()
    context["actor_chain"]["workload"] = {
        "state": "UNKNOWN",
        "reason": "upstream runtime did not propagate workload identity",
    }

    validate_delegation_context(context)


def test_null_identity_is_rejected_instead_of_becoming_unknown() -> None:
    context = valid_context()
    context["actor_chain"]["human"] = None

    with pytest.raises(DelegationContextRejected) as error:
        validate_delegation_context(context)

    assert error.value.code == "NULL_NOT_ALLOWED"
    assert error.value.stage == "schema"


def test_actor_only_record_is_rejected_as_information_loss() -> None:
    context = {
        "schema_version": "delegation-context/v0.1",
        "event_id": "evt-day09-actor-only",
        "actor": "user/sre-oncaller",
    }

    with pytest.raises(DelegationContextRejected) as error:
        validate_delegation_context(context)

    assert error.value.code == "REQUIRED_FIELD_MISSING"


def test_duplicate_agent_sequence_is_rejected_after_schema_validation() -> None:
    context = valid_context()
    context["actor_chain"]["agents"][1]["sequence"] = 0

    with pytest.raises(DelegationContextRejected) as error:
        validate_delegation_context(context)

    assert error.value.code == "AGENT_SEQUENCE_INVALID"
    assert error.value.stage == "semantics"


def test_executing_agent_must_be_last_in_the_chain() -> None:
    context = valid_context()
    context["actor_chain"]["agents"][0]["role"] = "EXECUTING"
    context["actor_chain"]["agents"][1]["role"] = "DELEGATING"

    with pytest.raises(DelegationContextRejected) as error:
        validate_delegation_context(context)

    assert error.value.code == "AGENT_ROLE_INVALID"


def test_schema_does_not_accept_raw_bearer_token_field() -> None:
    context = deepcopy(valid_context())
    context["credential"]["access_token"] = "header.payload.signature"

    with pytest.raises(DelegationContextRejected) as error:
        validate_delegation_context(context)

    assert error.value.code == "FIELD_NOT_ALLOWED"


def test_w3c_all_zero_trace_id_is_rejected() -> None:
    context = valid_context()
    context["trace_id"] = "0" * 32

    with pytest.raises(DelegationContextRejected) as error:
        validate_delegation_context(context)

    assert error.value.code == "CONTEXT_SCHEMA_INVALID"
