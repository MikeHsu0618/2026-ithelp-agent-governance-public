from __future__ import annotations

import json
from pathlib import Path

import pytest

from traceability_lab.identity import (
    ClaimVerificationError,
    RawIdentityClaims,
    build_identity_projections,
    verify_fixture_claims,
)


def valid_claims() -> RawIdentityClaims:
    return RawIdentityClaims(
        issuer="https://identity.invalid/pool/day22",
        audience="ithelp-agent-lab",
        subject="synthetic-sre-oncaller",
        email="sre-oncaller@identity.invalid",
        team="platform-sre",
        roles=("incident-responder", "reader"),
        tenant="ithelp-lab",
        raw_token="day22-raw-token-must-not-survive",
    )


def test_fixture_verification_rejects_wrong_issuer_or_audience() -> None:
    claims = valid_claims()

    with pytest.raises(ClaimVerificationError, match="issuer"):
        verify_fixture_claims(
            claims,
            expected_issuer="https://other.invalid/pool",
            expected_audience=claims.audience,
            pseudonym_key=b"x" * 32,
        )

    with pytest.raises(ClaimVerificationError, match="audience"):
        verify_fixture_claims(
            claims,
            expected_issuer=claims.issuer,
            expected_audience="other-client",
            pseudonym_key=b"x" * 32,
        )


def test_verified_context_replaces_direct_identifier_with_stable_reference() -> None:
    claims = valid_claims()

    principal = verify_fixture_claims(
        claims,
        expected_issuer=claims.issuer,
        expected_audience=claims.audience,
        pseudonym_key=b"x" * 32,
    )

    assert principal.principal_ref.startswith("prn_")
    assert (
        principal.principal_ref
        == verify_fixture_claims(
            claims,
            expected_issuer=claims.issuer,
            expected_audience=claims.audience,
            pseudonym_key=b"x" * 32,
        ).principal_ref
    )
    assert claims.email not in json.dumps(principal.to_dict(), sort_keys=True)
    assert claims.raw_token not in json.dumps(principal.to_dict(), sort_keys=True)


def test_each_destination_gets_an_explicit_identity_projection() -> None:
    claims = valid_claims()
    principal = verify_fixture_claims(
        claims,
        expected_issuer=claims.issuer,
        expected_audience=claims.audience,
        pseudonym_key=b"x" * 32,
    )

    projections = build_identity_projections(
        principal,
        action_id="act-day22-identity",
        route="agent-runtime",
        outcome="allowed",
    )

    assert projections.metrics == {
        "outcome": "allowed",
        "route": "agent-runtime",
        "team": "platform-sre",
    }
    assert projections.traces["principal.ref"] == principal.principal_ref
    assert projections.logs["principal.ref"] == principal.principal_ref
    assert projections.audit["actor.principal_ref"] == principal.principal_ref
    assert projections.audit["actor.issuer"] == claims.issuer
    assert projections.audit["actor.audience"] == claims.audience
    serialized = json.dumps(projections.to_dict(), sort_keys=True)
    assert claims.email not in serialized
    assert claims.raw_token not in serialized


def test_alloy_transform_removes_identity_fields_before_export() -> None:
    config = Path(__file__).parents[1].joinpath("config.alloy").read_text(encoding="utf-8")

    assert 'otelcol.processor.transform "identity_projection"' in config
    for context in ("span", "log", "datapoint"):
        assert f'context = "{context}"' in config
    for key in ("user.email", "auth.token"):
        assert config.count(f'delete_key(attributes, "{key}")') == 3
    for log_only_key in ("code.file.path", "code.function.name", "code.line.number"):
        assert config.count(f'delete_key(attributes, "{log_only_key}")') == 1
    for metric_only_key in (
        "conversation.id",
        "ithelp.governance.action_id",
        "principal.ref",
        "session.id",
        "user.id",
    ):
        assert config.count(f'delete_key(attributes, "{metric_only_key}")') == 1
    assert "otelcol.processor.transform.identity_projection.input" in config
