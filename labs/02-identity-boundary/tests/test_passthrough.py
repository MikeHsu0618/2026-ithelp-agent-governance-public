from datetime import UTC, datetime

import pytest

from identity_boundary.issuer import LocalIssuer
from identity_boundary.passthrough import GovernedResource, credential_fingerprint
from identity_boundary.validator import TokenPolicy, TokenValidator

ISSUER = "https://issuer.lab.example/identity-boundary"
RESOURCE = "https://observability.lab.example/mcp"


@pytest.fixture
def issuer() -> LocalIssuer:
    return LocalIssuer(issuer=ISSUER, key_id="passthrough-unit")


@pytest.fixture
def resource(issuer: LocalIssuer) -> GovernedResource:
    validator = TokenValidator(
        jwks=issuer.jwks(),
        policy=TokenPolicy(
            issuer=ISSUER,
            audience=RESOURCE,
            client_id="runtime",
            required_scopes=frozenset({"observability.query"}),
            required_claims=frozenset(),
        ),
    )
    return GovernedResource(
        resource_id=RESOURCE,
        action="query_logs",
        validator=validator,
        hop_kind="DOWNSTREAM",
        require_delegation_context=True,
    )


def test_invalid_token_returns_stable_deny_instead_of_hashing_error(
    resource: GovernedResource,
) -> None:
    decision = resource.authorize("")

    assert decision.decision == "DENY"
    assert decision.code == "TOKEN_INVALID"
    assert decision.stage == "input"
    assert decision.audit["credential_fingerprint"] == "UNAVAILABLE"


def test_structurally_invalid_context_has_stable_public_code(
    issuer: LocalIssuer, resource: GovernedResource
) -> None:
    token = issuer.issue_access_token(
        subject="client/runtime",
        audience=RESOURCE,
        client_id="runtime",
        scopes=("observability.query",),
        additional_claims={},
        issued_at=datetime.now(UTC),
    )

    decision = resource.authorize(token.encoded, {"actor": "user/sre-oncaller"})

    assert decision.decision == "DENY"
    assert decision.code == "DELEGATION_CONTEXT_INVALID"
    assert decision.stage == "context"
    assert decision.audit["token_subject"] == "UNVERIFIED"


def test_resource_configuration_and_fingerprint_reject_ambiguous_inputs(
    resource: GovernedResource,
) -> None:
    with pytest.raises(ValueError, match="resource_id and action"):
        GovernedResource("", "query_logs", resource.validator, "DOWNSTREAM")
    with pytest.raises(ValueError, match="hop_kind"):
        GovernedResource(RESOURCE, "query_logs", resource.validator, "SIDEWAYS")
    with pytest.raises(ValueError, match="non-empty string"):
        credential_fingerprint("")


def test_non_human_token_subject_is_not_relabelled_as_a_human(
    issuer: LocalIssuer, resource: GovernedResource
) -> None:
    token = issuer.issue_access_token(
        subject="client/runtime",
        audience=RESOURCE,
        client_id="runtime",
        scopes=("observability.query",),
        additional_claims={},
        issued_at=datetime.now(UTC),
    )
    entry = GovernedResource(
        resource_id=RESOURCE,
        action="query_logs",
        validator=resource.validator,
        hop_kind="ENTRY",
    )

    decision = entry.authorize(token.encoded)

    assert decision.decision == "ALLOW"
    assert decision.audit["token_subject"] == "client/runtime"
    assert decision.audit["human_principal"] == "UNKNOWN"
