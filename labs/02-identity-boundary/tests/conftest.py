from datetime import UTC, datetime

import pytest

from identity_boundary.issuer import LocalIssuer
from identity_boundary.validator import TokenPolicy, TokenValidator

ISSUER = "https://issuer.lab.example/identity-boundary"
AUDIENCE = "mcp://lab/observability/query"
CLIENT_ID = "sre-console"
SUBJECT = "user/sre-oncaller"
NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture(scope="session")
def issuer() -> LocalIssuer:
    return LocalIssuer(issuer=ISSUER, key_id="day-08-signing-key")


@pytest.fixture(scope="session")
def policy() -> TokenPolicy:
    return TokenPolicy(
        issuer=ISSUER,
        audience=AUDIENCE,
        client_id=CLIENT_ID,
        required_scopes=frozenset({"observability.query"}),
        required_claims=frozenset({"team"}),
    )


@pytest.fixture(scope="session")
def validator(issuer: LocalIssuer, policy: TokenPolicy) -> TokenValidator:
    return TokenValidator(jwks=issuer.jwks(), policy=policy)
