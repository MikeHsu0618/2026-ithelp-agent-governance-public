from __future__ import annotations

import hashlib
import hmac
from dataclasses import asdict, dataclass
from typing import Any


class ClaimVerificationError(ValueError):
    """Raised when the deterministic Day 22 claim fixture fails its boundary checks."""


@dataclass(frozen=True, slots=True)
class RawIdentityClaims:
    """Synthetic pre-verification input; never pass this object to telemetry exporters."""

    issuer: str
    audience: str
    subject: str
    email: str
    team: str
    roles: tuple[str, ...]
    tenant: str
    raw_token: str


@dataclass(frozen=True, slots=True)
class VerifiedPrincipalContext:
    principal_ref: str
    issuer: str
    audience: str
    team: str
    roles: tuple[str, ...]
    tenant: str
    assurance: str = "fixture-issuer-audience-checked"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IdentityProjections:
    metrics: dict[str, str]
    traces: dict[str, str]
    logs: dict[str, str]
    audit: dict[str, str | list[str]]

    def to_dict(self) -> dict[str, dict[str, str] | dict[str, str | list[str]]]:
        return asdict(self)


def verify_fixture_claims(
    claims: RawIdentityClaims,
    *,
    expected_issuer: str,
    expected_audience: str,
    pseudonym_key: bytes,
) -> VerifiedPrincipalContext:
    """Validate a deterministic fixture and produce a pseudonymous principal context.

    This is intentionally not a JWT parser or signature verifier. Day 08 owns that Lab.
    """

    if claims.issuer != expected_issuer:
        raise ClaimVerificationError("fixture issuer does not match the trusted issuer")
    if claims.audience != expected_audience:
        raise ClaimVerificationError("fixture audience does not match this workload")
    if len(pseudonym_key) < 32:
        raise ClaimVerificationError("pseudonym key must contain at least 32 bytes")
    if not claims.subject or not claims.team or not claims.roles:
        raise ClaimVerificationError("fixture subject, team, and roles must be present")

    digest = hmac.new(
        pseudonym_key,
        f"{claims.issuer}\x00{claims.subject}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return VerifiedPrincipalContext(
        principal_ref=f"prn_{digest[:20]}",
        issuer=claims.issuer,
        audience=claims.audience,
        team=claims.team,
        roles=claims.roles,
        tenant=claims.tenant,
    )


def build_identity_projections(
    principal: VerifiedPrincipalContext,
    *,
    action_id: str,
    route: str,
    outcome: str,
) -> IdentityProjections:
    """Project verified identity into destination-specific allowlists."""

    primary_role = principal.roles[0]
    return IdentityProjections(
        metrics={
            "outcome": outcome,
            "route": route,
            "team": principal.team,
        },
        traces={
            "ithelp.governance.action_id": action_id,
            "principal.assurance": principal.assurance,
            "principal.ref": principal.principal_ref,
            "principal.role": primary_role,
            "principal.team": principal.team,
            "principal.tenant": principal.tenant,
        },
        logs={
            "action_id": action_id,
            "principal.ref": principal.principal_ref,
            "principal.team": principal.team,
        },
        audit={
            "action.id": action_id,
            "actor.assurance": principal.assurance,
            "actor.audience": principal.audience,
            "actor.issuer": principal.issuer,
            "actor.principal_ref": principal.principal_ref,
            "actor.roles": list(principal.roles),
            "actor.team": principal.team,
            "actor.tenant": principal.tenant,
        },
    )
