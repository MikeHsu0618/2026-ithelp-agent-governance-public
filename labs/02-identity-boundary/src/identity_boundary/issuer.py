"""Ephemeral RSA issuer for synthetic Lab 02 tokens."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

REGISTERED_CLAIMS = frozenset(
    {"iss", "aud", "sub", "client_id", "token_use", "scope", "iat", "exp"}
)


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A compact token and the synthetic claims used to create it.

    The demo persists ``claims`` but never persists ``encoded``.
    """

    encoded: str
    claims: dict[str, Any]


class LocalIssuer:
    """Issues short-lived synthetic JWTs with an in-memory RSA private key."""

    def __init__(self, *, issuer: str, key_id: str) -> None:
        if not issuer.startswith("https://"):
            raise ValueError("issuer must use https")
        if not key_id:
            raise ValueError("key_id must not be empty")

        self.issuer = issuer
        self.key_id = key_id
        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwks(self) -> dict[str, list[dict[str, Any]]]:
        """Return the public JWK Set; private key material never leaves this object."""

        jwk = json.loads(RSAAlgorithm.to_jwk(self._private_key.public_key()))
        jwk.update({"alg": "RS256", "kid": self.key_id, "use": "sig"})
        return {"keys": [jwk]}

    def issue_access_token(
        self,
        *,
        subject: str | None,
        audience: str | None,
        client_id: str,
        scopes: tuple[str, ...],
        additional_claims: Mapping[str, Any],
        issued_at: datetime | None = None,
        lifetime: timedelta = timedelta(minutes=5),
        issuer_override: str | None = None,
        key_id_override: str | None = None,
        token_type_header: str | None = "at+jwt",
    ) -> IssuedToken:
        """Issue a synthetic access token with an explicitly selected claim shape."""

        now = _as_utc(issued_at or datetime.now(UTC))
        _reject_registered_claim_overrides(additional_claims)
        claims: dict[str, Any] = {
            "iss": issuer_override or self.issuer,
            "client_id": client_id,
            "token_use": "access",
            "scope": " ".join(scopes),
            "iat": int(now.timestamp()),
            "exp": int((now + lifetime).timestamp()),
            **dict(additional_claims),
        }
        if audience is not None:
            claims["aud"] = audience
        if subject is not None:
            claims["sub"] = subject
        return self._encode(claims, token_type=token_type_header, key_id=key_id_override)

    def issue_id_token(
        self,
        *,
        subject: str,
        audience: str,
        additional_claims: Mapping[str, Any],
        issued_at: datetime | None = None,
        lifetime: timedelta = timedelta(minutes=5),
    ) -> IssuedToken:
        """Issue a synthetic OIDC ID token for the cross-token confusion case."""

        now = _as_utc(issued_at or datetime.now(UTC))
        _reject_registered_claim_overrides(additional_claims)
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": audience,
            "sub": subject,
            "token_use": "id",
            "iat": int(now.timestamp()),
            "exp": int((now + lifetime).timestamp()),
            **dict(additional_claims),
        }
        return self._encode(claims, token_type="id+jwt")

    def _encode(
        self,
        claims: dict[str, Any],
        *,
        token_type: str | None,
        key_id: str | None = None,
    ) -> IssuedToken:
        encoded = jwt.encode(
            claims,
            self._private_key,
            algorithm="RS256",
            headers={"kid": key_id or self.key_id, "typ": token_type},
        )
        return IssuedToken(encoded=encoded, claims=claims)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("issued_at must be timezone-aware")
    return value.astimezone(UTC)


def _reject_registered_claim_overrides(additional_claims: Mapping[str, Any]) -> None:
    collisions = REGISTERED_CLAIMS.intersection(additional_claims)
    if collisions:
        names = ", ".join(sorted(collisions))
        raise ValueError(f"additional_claims must not override a registered claim: {names}")
