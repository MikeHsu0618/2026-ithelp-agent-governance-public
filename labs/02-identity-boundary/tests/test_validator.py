from datetime import timedelta

import jwt
import pytest

from identity_boundary.issuer import LocalIssuer
from identity_boundary.validator import TokenPolicy, TokenRejected, TokenValidator

from .conftest import AUDIENCE, CLIENT_ID, ISSUER, NOW, SUBJECT


def issue_valid_access_token(issuer: LocalIssuer, **overrides: object):
    arguments = {
        "subject": SUBJECT,
        "audience": AUDIENCE,
        "client_id": CLIENT_ID,
        "scopes": ("observability.query",),
        "additional_claims": {"team": "platform"},
        "issued_at": NOW,
        "lifetime": timedelta(minutes=5),
    }
    arguments.update(overrides)
    return issuer.issue_access_token(**arguments)


def test_valid_resource_bound_access_token_is_accepted(
    issuer: LocalIssuer, validator: TokenValidator
) -> None:
    token = issue_valid_access_token(issuer)

    claims = validator.validate(token.encoded)

    assert claims["sub"] == SUBJECT
    assert claims["aud"] == AUDIENCE
    assert claims["team"] == "platform"


@pytest.mark.parametrize(
    ("overrides", "expected_code", "expected_stage"),
    [
        ({"issuer_override": "https://wrong.example/issuer"}, "ISSUER_MISMATCH", "claims"),
        ({"audience": "mcp://lab/admin/delete"}, "AUDIENCE_MISMATCH", "claims"),
        ({"lifetime": timedelta(seconds=-1)}, "TOKEN_EXPIRED", "claims"),
        ({"scopes": ("profile",)}, "SCOPE_MISSING", "policy"),
        ({"additional_claims": {}}, "CLAIM_MISSING", "policy"),
    ],
)
def test_invalid_access_tokens_are_denied_at_the_expected_boundary(
    issuer: LocalIssuer,
    validator: TokenValidator,
    overrides: dict[str, object],
    expected_code: str,
    expected_stage: str,
) -> None:
    token = issue_valid_access_token(issuer, **overrides)

    with pytest.raises(TokenRejected) as caught:
        validator.validate(token.encoded)

    assert caught.value.code == expected_code
    assert caught.value.stage == expected_stage


def test_id_token_with_team_claim_cannot_replace_an_access_token(
    issuer: LocalIssuer, validator: TokenValidator
) -> None:
    token = issuer.issue_id_token(
        subject=SUBJECT,
        audience=CLIENT_ID,
        additional_claims={"team": "platform"},
        issued_at=NOW,
        lifetime=timedelta(minutes=5),
    )

    with pytest.raises(TokenRejected) as caught:
        validator.validate(token.encoded)

    assert token.claims["team"] == "platform"
    assert caught.value.code == "TOKEN_TYPE_INVALID"
    assert caught.value.stage == "header"


def test_access_token_from_unknown_signing_key_is_denied(
    validator: TokenValidator,
) -> None:
    untrusted_issuer = LocalIssuer(issuer=ISSUER, key_id="untrusted-key")
    token = issue_valid_access_token(untrusted_issuer)

    with pytest.raises(TokenRejected) as caught:
        validator.validate(token.encoded)

    assert caught.value.code == "KEY_NOT_FOUND"
    assert caught.value.stage == "key"


def test_access_token_for_another_oauth_client_is_denied(
    issuer: LocalIssuer, validator: TokenValidator
) -> None:
    token = issue_valid_access_token(issuer, client_id="another-client")

    with pytest.raises(TokenRejected) as caught:
        validator.validate(token.encoded)

    assert caught.value.code == "CLIENT_MISMATCH"
    assert caught.value.stage == "policy"


def test_malformed_trusted_jwk_returns_a_stable_rejection(
    issuer: LocalIssuer, policy: TokenPolicy
) -> None:
    token = issue_valid_access_token(issuer)
    malformed_jwks = issuer.jwks()
    malformed_jwks["keys"][0]["n"] = "not-a-valid-rsa-modulus"
    validator = TokenValidator(jwks=malformed_jwks, policy=policy)

    with pytest.raises(TokenRejected) as caught:
        validator.validate(token.encoded)

    assert caught.value.code == "KEY_INVALID"
    assert caught.value.stage == "key"


def test_issuer_refuses_additional_claims_that_override_registered_claims(
    issuer: LocalIssuer,
) -> None:
    with pytest.raises(ValueError, match="registered claim"):
        issue_valid_access_token(issuer, additional_claims={"iss": "https://attacker.example"})


def test_validator_rejects_algorithm_outside_allowlist(
    policy: TokenPolicy,
) -> None:
    unsigned = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": SUBJECT,
            "exp": int((NOW + timedelta(minutes=5)).timestamp()),
        },
        key="",
        algorithm="none",
        headers={"kid": "day-08-signing-key", "typ": "at+jwt"},
    )
    validator = TokenValidator(jwks={"keys": []}, policy=policy)

    with pytest.raises(TokenRejected) as caught:
        validator.validate(unsigned)

    assert caught.value.code == "ALGORITHM_NOT_ALLOWED"
    assert caught.value.stage == "header"


def test_validator_rejects_unsafe_key_identifier(issuer: LocalIssuer, policy: TokenPolicy) -> None:
    token = issuer.issue_access_token(
        subject=SUBJECT,
        audience=AUDIENCE,
        client_id=CLIENT_ID,
        scopes=("observability.query",),
        additional_claims={"team": "platform"},
        issued_at=NOW,
        lifetime=timedelta(minutes=5),
        key_id_override="../../keys/private.pem",
    )
    validator = TokenValidator(jwks=issuer.jwks(), policy=policy)

    with pytest.raises(TokenRejected) as caught:
        validator.validate(token.encoded)

    assert caught.value.code == "INVALID_HEADER"
    assert caught.value.stage == "header"


def test_validator_rejects_oversized_token(issuer: LocalIssuer, policy: TokenPolicy) -> None:
    token = issue_valid_access_token(
        issuer,
        additional_claims={"team": "platform", "padding": "x" * 4096},
    )
    validator = TokenValidator(jwks=issuer.jwks(), policy=policy, max_token_bytes=512)

    with pytest.raises(TokenRejected) as caught:
        validator.validate(token.encoded)

    assert caught.value.code == "TOKEN_TOO_LARGE"
    assert caught.value.stage == "input"
