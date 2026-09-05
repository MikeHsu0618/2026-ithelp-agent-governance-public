import jwt

from gateway_runtime.credentials import EphemeralCredentials


def test_ephemeral_credentials_issue_day12_shaped_human_jwt() -> None:
    material = EphemeralCredentials.create()

    token = material.issue_human_jwt()
    claims = jwt.decode(token, options={"verify_signature": False})

    assert claims["iss"] == "https://identity.lab.example/"
    assert claims["aud"] == "agentgateway-lab"
    assert claims["sub"] == "user/sre-oncaller"
    assert claims["client_id"] == "client/agent-ui"
    assert claims["team"] == "team/platform"
    assert claims["scope"] == "llm.invoke"
    assert claims["token_use"] == "access"


def test_ephemeral_credentials_can_issue_claim_boundary_tokens() -> None:
    material = EphemeralCredentials.create()

    wrong_issuer = jwt.decode(
        material.issue_human_jwt(issuer="https://other-issuer.lab.example/"),
        options={"verify_signature": False},
    )
    missing_issuer = jwt.decode(
        material.issue_human_jwt(omit_claims={"iss"}),
        options={"verify_signature": False},
    )
    missing_audience = jwt.decode(
        material.issue_human_jwt(omit_claims={"aud"}),
        options={"verify_signature": False},
    )

    assert wrong_issuer["iss"] == "https://other-issuer.lab.example/"
    assert "iss" not in missing_issuer
    assert "aud" not in missing_audience


def test_public_jwks_never_contains_private_rsa_parameters() -> None:
    material = EphemeralCredentials.create()

    jwks = material.public_jwks()

    assert len(jwks["keys"]) == 1
    assert jwks["keys"][0]["kid"] == material.key_id
    assert "d" not in jwks["keys"][0]
    assert (
        len(
            {
                material.human_virtual_key,
                material.workload_consumer_key,
                material.retired_workload_key,
                material.provider_key,
            }
        )
        == 4
    )
