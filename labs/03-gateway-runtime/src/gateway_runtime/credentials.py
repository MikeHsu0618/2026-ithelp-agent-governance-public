"""Create short-lived synthetic credentials without writing private material to disk."""

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm


@dataclass(frozen=True)
class EphemeralCredentials:
    """All raw credentials for one run; artifacts keep fingerprints only."""

    human_virtual_key: str
    workload_consumer_key: str
    retired_workload_key: str
    provider_key: str
    private_key: rsa.RSAPrivateKey = field(repr=False)
    key_id: str = "lab-key-01"
    issuer: str = "https://identity.lab.example/"
    audience: str = "agentgateway-lab"

    @classmethod
    def create(cls) -> "EphemeralCredentials":
        return cls(
            human_virtual_key=f"vk-human-{secrets.token_urlsafe(24)}",
            workload_consumer_key=f"vk-runtime-a-{secrets.token_urlsafe(24)}",
            retired_workload_key=f"vk-runtime-a-old-{secrets.token_urlsafe(24)}",
            provider_key=f"provider-{secrets.token_urlsafe(24)}",
            private_key=rsa.generate_private_key(public_exponent=65537, key_size=2048),
        )

    def issue_human_jwt(
        self,
        *,
        issuer: str | None = None,
        audience: str | None = None,
        omit_claims: frozenset[str] | set[str] = frozenset(),
    ) -> str:
        now = datetime.now(UTC)
        claims: dict[str, Any] = {
            "iss": issuer or self.issuer,
            "aud": audience or self.audience,
            "sub": "user/sre-oncaller",
            "client_id": "client/agent-ui",
            "team": "team/platform",
            "scope": "llm.invoke",
            "token_use": "access",
            "iat": now,
            "nbf": now - timedelta(seconds=5),
            "exp": now + timedelta(minutes=5),
            "jti": secrets.token_hex(16),
        }
        for claim in omit_claims:
            claims.pop(claim, None)
        return jwt.encode(
            claims,
            self.private_key,
            algorithm="RS256",
            headers={"kid": self.key_id, "typ": "JWT"},
        )

    def public_jwks(self) -> dict[str, list[dict[str, Any]]]:
        encoded = RSAAlgorithm.to_jwk(self.private_key.public_key())
        public_jwk = json.loads(encoded) if isinstance(encoded, str) else encoded
        public_jwk.update({"kid": self.key_id, "use": "sig", "alg": "RS256"})
        return {"keys": [public_jwk]}

    def raw_secrets(self) -> tuple[str, ...]:
        return (
            self.human_virtual_key,
            self.workload_consumer_key,
            self.retired_workload_key,
            self.provider_key,
        )

    @staticmethod
    def fingerprint(value: str) -> str:
        return f"sha256:{hashlib.sha256(value.encode()).hexdigest()[:16]}"
