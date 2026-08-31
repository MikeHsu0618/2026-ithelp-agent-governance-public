from datetime import UTC, datetime
from pathlib import Path

import jwt
import pytest

from identity_boundary.cognito_contract import CognitoContractError, OfflineCognitoUserPool
from identity_boundary.issuer import LocalIssuer
from identity_boundary.oauth_flows import create_pkce_pair
from identity_boundary.validator import TokenPolicy, TokenRejected, TokenValidator

ISSUER = "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_LabPool"
RESOURCE = "https://observability.lab.example/mcp"
HUMAN_CLIENT = "sre-console"
M2M_CLIENT = "sre-scheduler"
CALLBACK = "http://127.0.0.1:8765/callback"
NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture
def cognito_pool() -> tuple[OfflineCognitoUserPool, LocalIssuer, str]:
    issuer = LocalIssuer(issuer=ISSUER, key_id="day12-ephemeral")
    pool = OfflineCognitoUserPool(issuer=issuer)
    pool.register_human_client(
        client_id=HUMAN_CLIENT,
        redirect_uris=(CALLBACK,),
        allowed_scopes=frozenset({"openid", "platform/observability.query"}),
        allowed_resources=frozenset({RESOURCE}),
    )
    secret = "synthetic-m2m-secret-with-enough-entropy"
    pool.register_m2m_client(
        client_id=M2M_CLIENT,
        client_secret=secret,
        allowed_scopes=frozenset({"platform/observability.query"}),
    )
    return pool, issuer, secret


def test_human_token_is_resource_bound_and_cognito_shaped(cognito_pool) -> None:
    pool, _, _ = cognito_pool
    verifier, challenge = create_pkce_pair()

    token = pool.issue_human_access_token(
        client_id=HUMAN_CLIENT,
        redirect_uri=CALLBACK,
        requested_scopes=("openid", "platform/observability.query"),
        resource=RESOURCE,
        subject="user/sre-oncaller",
        code_verifier=verifier,
        code_challenge=challenge,
        additional_claims={"team": "platform"},
        issued_at=NOW,
    )

    assert token.claims["aud"] == RESOURCE
    assert token.claims["sub"] == "user/sre-oncaller"
    assert token.claims["client_id"] == HUMAN_CLIENT
    assert "typ" not in jwt.get_unverified_header(token.encoded)


def test_m2m_token_has_no_resource_audience_or_human_subject(cognito_pool) -> None:
    pool, _, secret = cognito_pool

    token = pool.issue_m2m_access_token(
        client_id=M2M_CLIENT,
        client_secret=secret,
        requested_scopes=("platform/observability.query",),
        issued_at=NOW,
    )

    assert token.claims["client_id"] == M2M_CLIENT
    assert token.claims["token_use"] == "access"
    assert "aud" not in token.claims
    assert "sub" not in token.claims
    assert "typ" not in jwt.get_unverified_header(token.encoded)


def test_m2m_rejects_public_client_and_resource_binding(cognito_pool) -> None:
    pool, _, secret = cognito_pool

    with pytest.raises(CognitoContractError, match="confidential") as public_error:
        pool.issue_m2m_access_token(
            client_id=HUMAN_CLIENT,
            client_secret=secret,
            requested_scopes=("platform/observability.query",),
            issued_at=NOW,
        )
    assert public_error.value.code == "UNAUTHORIZED_CLIENT"

    with pytest.raises(CognitoContractError, match="resource binding") as resource_error:
        pool.issue_m2m_access_token(
            client_id=M2M_CLIENT,
            client_secret=secret,
            requested_scopes=("platform/observability.query",),
            resource=RESOURCE,
            issued_at=NOW,
        )
    assert resource_error.value.code == "RESOURCE_BINDING_UNSUPPORTED"


def test_human_pkce_rejects_non_ascii_verifier_as_a_contract_error(cognito_pool) -> None:
    pool, _, _ = cognito_pool
    _, challenge = create_pkce_pair()

    with pytest.raises(CognitoContractError) as error:
        pool.issue_human_access_token(
            client_id=HUMAN_CLIENT,
            redirect_uri=CALLBACK,
            requested_scopes=("platform/observability.query",),
            resource=RESOURCE,
            subject="user/sre-oncaller",
            code_verifier="é" * 43,
            code_challenge=challenge,
            additional_claims={"team": "platform"},
            issued_at=NOW,
        )

    assert error.value.code == "PKCE_VERIFICATION_FAILED"


def test_gateway_profiles_validate_human_and_m2m_without_weakening_either(cognito_pool) -> None:
    pool, issuer, secret = cognito_pool
    verifier, challenge = create_pkce_pair()
    human_token = pool.issue_human_access_token(
        client_id=HUMAN_CLIENT,
        redirect_uri=CALLBACK,
        requested_scopes=("platform/observability.query",),
        resource=RESOURCE,
        subject="user/sre-oncaller",
        code_verifier=verifier,
        code_challenge=challenge,
        additional_claims={"team": "platform"},
        issued_at=NOW,
    )
    m2m_token = pool.issue_m2m_access_token(
        client_id=M2M_CLIENT,
        client_secret=secret,
        requested_scopes=("platform/observability.query",),
        issued_at=NOW,
    )

    human_validator = TokenValidator(
        jwks=issuer.jwks(),
        policy=TokenPolicy(
            issuer=ISSUER,
            audience=RESOURCE,
            client_id=HUMAN_CLIENT,
            required_scopes=frozenset({"platform/observability.query"}),
            required_claims=frozenset({"team"}),
            require_type_header=False,
        ),
    )
    m2m_validator = TokenValidator(
        jwks=issuer.jwks(),
        policy=TokenPolicy(
            issuer=ISSUER,
            audience=None,
            client_id=M2M_CLIENT,
            required_scopes=frozenset({"platform/observability.query"}),
            required_claims=frozenset(),
            require_subject=False,
            require_type_header=False,
            forbid_audience=True,
        ),
    )

    assert human_validator.validate(human_token.encoded)["sub"] == "user/sre-oncaller"
    assert m2m_validator.validate(m2m_token.encoded)["client_id"] == M2M_CLIENT

    with pytest.raises(TokenRejected) as wrong_profile:
        human_validator.validate(m2m_token.encoded)
    assert wrong_profile.value.code in {"REGISTERED_CLAIM_MISSING", "AUDIENCE_MISMATCH"}


def test_agentgateway_config_keeps_audience_validation_in_the_human_rule() -> None:
    config = (Path(__file__).parents[1] / "configs" / "agentgateway-cognito.yaml").read_text(
        encoding="utf-8"
    )

    assert ("      audiences:\n        - https://observability.lab.example/mcp\n") in config
    assert "          - aud\n" not in config
    assert "          - sub\n" not in config
    assert 'jwt.aud == "https://observability.lab.example/mcp"' in config
    assert "!has(jwt.aud)" in config
