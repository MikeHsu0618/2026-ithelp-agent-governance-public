import secrets
from datetime import UTC, datetime

import pytest

from identity_boundary.oauth_flows import (
    OAuthFlowError,
    OfflineAuthorizationServer,
    create_pkce_pair,
)
from identity_boundary.validator import TokenPolicy, TokenValidator

ISSUER = "https://issuer.lab.example/identity-boundary"
ENTRY_RESOURCE = "https://agent.lab.example/mcp"
TOOL_RESOURCE = "https://observability.lab.example/mcp"
PUBLIC_CLIENT = "sre-console"
SCHEDULER_CLIENT = "sre-scheduler"
RUNTIME_CLIENT = "sre-investigator-runtime"
REDIRECT_URI = "http://127.0.0.1:8765/callback"
TOKEN_ENDPOINT = "https://issuer.lab.example/identity-boundary/token"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"


@pytest.fixture
def oauth_server(issuer):
    server = OfflineAuthorizationServer(
        issuer=issuer,
        subject_token_policy=TokenPolicy(
            issuer=ISSUER,
            audience=ENTRY_RESOURCE,
            client_id=PUBLIC_CLIENT,
            required_scopes=frozenset({"agent.delegate"}),
            required_claims=frozenset({"may_act"}),
        ),
        actor_token_policy=TokenPolicy(
            issuer=ISSUER,
            audience=TOKEN_ENDPOINT,
            client_id=RUNTIME_CLIENT,
            required_scopes=frozenset({"agent.exchange"}),
            required_claims=frozenset(),
        ),
    )
    server.register_public_client(
        client_id=PUBLIC_CLIENT,
        redirect_uris=(REDIRECT_URI,),
        allowed_scopes=frozenset({"agent.delegate", "observability.query"}),
        allowed_resources=frozenset({ENTRY_RESOURCE}),
    )
    return server


def test_pkce_pair_uses_s256_and_rfc_length() -> None:
    verifier, challenge = create_pkce_pair()

    assert 43 <= len(verifier) <= 128
    assert len(challenge) == 43
    assert verifier != challenge
    assert "=" not in challenge


def test_public_client_redeems_one_time_code_with_pkce(oauth_server, issuer) -> None:
    verifier, challenge = create_pkce_pair()
    grant = oauth_server.authorize_code(
        client_id=PUBLIC_CLIENT,
        redirect_uri=REDIRECT_URI,
        scopes=frozenset({"agent.delegate"}),
        resource=ENTRY_RESOURCE,
        subject="user/sre-oncaller",
        code_challenge=challenge,
        code_challenge_method="S256",
    )

    token = oauth_server.redeem_code(
        client_id=PUBLIC_CLIENT,
        redirect_uri=REDIRECT_URI,
        authorization_code=grant.authorization_code,
        code_verifier=verifier,
    )
    claims = TokenValidator(
        jwks=issuer.jwks(),
        policy=TokenPolicy(
            issuer=ISSUER,
            audience=ENTRY_RESOURCE,
            client_id=PUBLIC_CLIENT,
            required_scopes=frozenset({"agent.delegate"}),
            required_claims=frozenset(),
        ),
    ).validate(token.encoded)

    assert claims["sub"] == "user/sre-oncaller"
    assert claims["aud"] == ENTRY_RESOURCE

    with pytest.raises(OAuthFlowError) as error:
        oauth_server.redeem_code(
            client_id=PUBLIC_CLIENT,
            redirect_uri=REDIRECT_URI,
            authorization_code=grant.authorization_code,
            code_verifier=verifier,
        )
    assert error.value.code == "INVALID_GRANT"


def test_pkce_rejects_a_verifier_that_does_not_match_the_code(oauth_server) -> None:
    verifier, challenge = create_pkce_pair()
    wrong_verifier, _ = create_pkce_pair()
    grant = oauth_server.authorize_code(
        client_id=PUBLIC_CLIENT,
        redirect_uri=REDIRECT_URI,
        scopes=frozenset({"agent.delegate"}),
        resource=ENTRY_RESOURCE,
        subject="user/sre-oncaller",
        code_challenge=challenge,
        code_challenge_method="S256",
    )

    with pytest.raises(OAuthFlowError) as error:
        oauth_server.redeem_code(
            client_id=PUBLIC_CLIENT,
            redirect_uri=REDIRECT_URI,
            authorization_code=grant.authorization_code,
            code_verifier=wrong_verifier,
        )

    assert verifier != wrong_verifier
    assert error.value.code == "INVALID_GRANT"


@pytest.mark.parametrize(
    ("override", "expected_code"),
    [
        ({"redirect_uri": "http://localhost:8765/callback"}, "REDIRECT_URI_MISMATCH"),
        ({"scopes": frozenset({"admin.everything"})}, "INVALID_SCOPE"),
        ({"client_id": "unknown-cli"}, "CLIENT_NOT_REGISTERED"),
    ],
)
def test_pkce_authorization_rejects_registration_mismatches(
    oauth_server, override: dict[str, object], expected_code: str
) -> None:
    _, challenge = create_pkce_pair()
    request: dict[str, object] = {
        "client_id": PUBLIC_CLIENT,
        "redirect_uri": REDIRECT_URI,
        "scopes": frozenset({"agent.delegate"}),
        "resource": ENTRY_RESOURCE,
        "subject": "user/sre-oncaller",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **override,
    }

    with pytest.raises(OAuthFlowError) as error:
        oauth_server.authorize_code(**request)

    assert error.value.code == expected_code


def test_pkce_authorization_rejects_a_non_base64url_challenge(oauth_server) -> None:
    with pytest.raises(OAuthFlowError) as error:
        oauth_server.authorize_code(
            client_id=PUBLIC_CLIENT,
            redirect_uri=REDIRECT_URI,
            scopes=frozenset({"agent.delegate"}),
            resource=ENTRY_RESOURCE,
            subject="user/sre-oncaller",
            code_challenge="!" * 43,
            code_challenge_method="S256",
        )

    assert error.value.code == "PKCE_REQUIRED"


def test_client_credentials_issues_workload_token_only_to_confidential_client(
    oauth_server, issuer
) -> None:
    client_secret = secrets.token_urlsafe(32)
    oauth_server.register_confidential_client(
        client_id=SCHEDULER_CLIENT,
        client_secret=client_secret,
        allowed_grants=frozenset({"client_credentials"}),
        allowed_scopes=frozenset({"observability.query"}),
        allowed_resources=frozenset({TOOL_RESOURCE}),
    )

    token = oauth_server.client_credentials(
        client_id=SCHEDULER_CLIENT,
        client_secret=client_secret,
        scopes=frozenset({"observability.query"}),
        resource=TOOL_RESOURCE,
    )
    claims = TokenValidator(
        jwks=issuer.jwks(),
        policy=TokenPolicy(
            issuer=ISSUER,
            audience=TOOL_RESOURCE,
            client_id=SCHEDULER_CLIENT,
            required_scopes=frozenset({"observability.query"}),
            required_claims=frozenset(),
        ),
    ).validate(token.encoded)

    assert claims["sub"] == f"client/{SCHEDULER_CLIENT}"
    assert "act" not in claims

    with pytest.raises(OAuthFlowError) as error:
        oauth_server.client_credentials(
            client_id=PUBLIC_CLIENT,
            client_secret=secrets.token_urlsafe(32),
            scopes=frozenset({"agent.delegate"}),
            resource=ENTRY_RESOURCE,
        )
    assert error.value.code == "UNAUTHORIZED_CLIENT"


def test_confidential_client_rejects_an_invalid_credential(oauth_server) -> None:
    client_credential = secrets.token_urlsafe(32)
    oauth_server.register_confidential_client(
        client_id=SCHEDULER_CLIENT,
        client_secret=client_credential,
        allowed_grants=frozenset({"client_credentials"}),
        allowed_scopes=frozenset({"observability.query"}),
        allowed_resources=frozenset({TOOL_RESOURCE}),
    )

    with pytest.raises(OAuthFlowError) as error:
        oauth_server.client_credentials(
            client_id=SCHEDULER_CLIENT,
            client_secret=secrets.token_urlsafe(32),
            scopes=frozenset({"observability.query"}),
            resource=TOOL_RESOURCE,
        )

    assert error.value.code == "INVALID_CLIENT"
    assert error.value.stage == "client_authentication"


def test_token_exchange_preserves_human_subject_and_names_current_actor(
    oauth_server, issuer
) -> None:
    runtime_secret = secrets.token_urlsafe(32)
    oauth_server.register_confidential_client(
        client_id=RUNTIME_CLIENT,
        client_secret=runtime_secret,
        allowed_grants=frozenset({"token_exchange"}),
        allowed_scopes=frozenset({"observability.query"}),
        allowed_resources=frozenset({TOOL_RESOURCE}),
    )
    subject_token = issuer.issue_access_token(
        subject="user/sre-oncaller",
        audience=ENTRY_RESOURCE,
        client_id=PUBLIC_CLIENT,
        scopes=("agent.delegate", "observability.query"),
        additional_claims={
            "team": "platform",
            "may_act": {"sub": f"client/{RUNTIME_CLIENT}"},
        },
        issued_at=datetime.now(UTC),
    )
    actor_token = issuer.issue_access_token(
        subject=f"client/{RUNTIME_CLIENT}",
        audience=TOKEN_ENDPOINT,
        client_id=RUNTIME_CLIENT,
        scopes=("agent.exchange",),
        additional_claims={},
        issued_at=datetime.now(UTC),
    )

    downstream = oauth_server.token_exchange(
        client_id=RUNTIME_CLIENT,
        client_secret=runtime_secret,
        subject_token=subject_token.encoded,
        subject_token_type=ACCESS_TOKEN_TYPE,
        actor_token=actor_token.encoded,
        actor_token_type=ACCESS_TOKEN_TYPE,
        scopes=frozenset({"observability.query"}),
        resource=TOOL_RESOURCE,
    )
    claims = TokenValidator(
        jwks=issuer.jwks(),
        policy=TokenPolicy(
            issuer=ISSUER,
            audience=TOOL_RESOURCE,
            client_id=RUNTIME_CLIENT,
            required_scopes=frozenset({"observability.query"}),
            required_claims=frozenset({"act"}),
        ),
    ).validate(downstream.encoded)

    assert claims["sub"] == "user/sre-oncaller"
    assert claims["act"] == {"sub": f"client/{RUNTIME_CLIENT}"}
    assert claims["aud"] == TOOL_RESOURCE


def test_token_exchange_rejects_unknown_target_and_wrong_subject_audience(
    oauth_server, issuer
) -> None:
    runtime_secret = secrets.token_urlsafe(32)
    oauth_server.register_confidential_client(
        client_id=RUNTIME_CLIENT,
        client_secret=runtime_secret,
        allowed_grants=frozenset({"token_exchange"}),
        allowed_scopes=frozenset({"observability.query"}),
        allowed_resources=frozenset({TOOL_RESOURCE}),
    )
    valid_subject = issuer.issue_access_token(
        subject="user/sre-oncaller",
        audience=ENTRY_RESOURCE,
        client_id=PUBLIC_CLIENT,
        scopes=("agent.delegate",),
        additional_claims={"may_act": {"sub": f"client/{RUNTIME_CLIENT}"}},
    )
    wrong_subject = issuer.issue_access_token(
        subject="user/sre-oncaller",
        audience=TOOL_RESOURCE,
        client_id=PUBLIC_CLIENT,
        scopes=("agent.delegate",),
        additional_claims={"may_act": {"sub": f"client/{RUNTIME_CLIENT}"}},
    )
    actor_token = issuer.issue_access_token(
        subject=f"client/{RUNTIME_CLIENT}",
        audience=TOKEN_ENDPOINT,
        client_id=RUNTIME_CLIENT,
        scopes=("agent.exchange",),
        additional_claims={},
    )

    with pytest.raises(OAuthFlowError) as target_error:
        oauth_server.token_exchange(
            client_id=RUNTIME_CLIENT,
            client_secret=runtime_secret,
            subject_token=valid_subject.encoded,
            subject_token_type=ACCESS_TOKEN_TYPE,
            actor_token=actor_token.encoded,
            actor_token_type=ACCESS_TOKEN_TYPE,
            scopes=frozenset({"observability.query"}),
            resource="https://billing.lab.example/mcp",
        )
    assert target_error.value.code == "INVALID_TARGET"

    with pytest.raises(OAuthFlowError) as subject_error:
        oauth_server.token_exchange(
            client_id=RUNTIME_CLIENT,
            client_secret=runtime_secret,
            subject_token=wrong_subject.encoded,
            subject_token_type=ACCESS_TOKEN_TYPE,
            actor_token=actor_token.encoded,
            actor_token_type=ACCESS_TOKEN_TYPE,
            scopes=frozenset({"observability.query"}),
            resource=TOOL_RESOURCE,
        )
    assert subject_error.value.code == "SUBJECT_TOKEN_INVALID"
    assert subject_error.value.reason_code == "AUDIENCE_MISMATCH"


def test_token_exchange_rejects_an_actor_not_authorized_by_the_subject(
    oauth_server, issuer
) -> None:
    runtime_secret = secrets.token_urlsafe(32)
    oauth_server.register_confidential_client(
        client_id=RUNTIME_CLIENT,
        client_secret=runtime_secret,
        allowed_grants=frozenset({"token_exchange"}),
        allowed_scopes=frozenset({"observability.query"}),
        allowed_resources=frozenset({TOOL_RESOURCE}),
    )
    subject_token = issuer.issue_access_token(
        subject="user/sre-oncaller",
        audience=ENTRY_RESOURCE,
        client_id=PUBLIC_CLIENT,
        scopes=("agent.delegate",),
        additional_claims={"may_act": {"sub": "client/another-runtime"}},
    )
    actor_token = issuer.issue_access_token(
        subject=f"client/{RUNTIME_CLIENT}",
        audience=TOKEN_ENDPOINT,
        client_id=RUNTIME_CLIENT,
        scopes=("agent.exchange",),
        additional_claims={},
    )

    with pytest.raises(OAuthFlowError) as error:
        oauth_server.token_exchange(
            client_id=RUNTIME_CLIENT,
            client_secret=runtime_secret,
            subject_token=subject_token.encoded,
            subject_token_type=ACCESS_TOKEN_TYPE,
            actor_token=actor_token.encoded,
            actor_token_type=ACCESS_TOKEN_TYPE,
            scopes=frozenset({"observability.query"}),
            resource=TOOL_RESOURCE,
        )

    assert error.value.code == "ACTOR_NOT_AUTHORIZED"
    assert error.value.stage == "delegation_policy"


def test_safe_registration_snapshot_never_exposes_client_secret(oauth_server) -> None:
    client_secret = secrets.token_urlsafe(32)
    oauth_server.register_confidential_client(
        client_id=SCHEDULER_CLIENT,
        client_secret=client_secret,
        allowed_grants=frozenset({"client_credentials"}),
        allowed_scopes=frozenset({"observability.query"}),
        allowed_resources=frozenset({TOOL_RESOURCE}),
    )

    snapshot = oauth_server.safe_registration_snapshot()

    assert client_secret not in str(snapshot)
    assert all("secret" not in key for item in snapshot for key in item)
