"""Resource-bound authorization and delegation-context binding for Day 10."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from identity_boundary.delegation import DelegationContextRejected, validate_delegation_context
from identity_boundary.validator import TokenRejected, TokenValidator

ALLOW = "ALLOW"
DENY = "DENY"
NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True, slots=True)
class BoundaryDecision:
    """A safe authorization result that can be written to audit evidence."""

    decision: str
    code: str
    stage: str
    attribution: str
    audit: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GovernedResource:
    """Validate one presented token and, when required, bind its actor context."""

    resource_id: str
    action: str
    validator: TokenValidator
    hop_kind: str
    require_delegation_context: bool = False

    def __post_init__(self) -> None:
        if not self.resource_id or not self.action:
            raise ValueError("resource_id and action must not be empty")
        if self.hop_kind not in {"ENTRY", "DOWNSTREAM"}:
            raise ValueError("hop_kind must be ENTRY or DOWNSTREAM")

    def authorize(
        self,
        token: str,
        delegation_context: Mapping[str, Any] | None = None,
    ) -> BoundaryDecision:
        """Return an ALLOW or stable DENY without exposing the bearer credential."""

        try:
            fingerprint = credential_fingerprint(token)
        except ValueError:
            fingerprint = "UNAVAILABLE"
        base_audit = _empty_audit(self.resource_id, self.action, fingerprint)
        try:
            claims = self.validator.validate(token)
        except TokenRejected as error:
            return BoundaryDecision(DENY, error.code, error.stage, NOT_EVALUATED, base_audit)

        if self.require_delegation_context:
            if delegation_context is None:
                return BoundaryDecision(
                    DENY,
                    "DELEGATION_CONTEXT_REQUIRED",
                    "context",
                    NOT_EVALUATED,
                    base_audit,
                )
            try:
                validate_delegation_context(delegation_context)
            except DelegationContextRejected:
                return BoundaryDecision(
                    DENY,
                    "DELEGATION_CONTEXT_INVALID",
                    "context",
                    NOT_EVALUATED,
                    base_audit,
                )
            if not _context_matches_request(
                delegation_context,
                claims,
                fingerprint,
                self.resource_id,
                self.action,
            ):
                return BoundaryDecision(
                    DENY,
                    "DELEGATION_CONTEXT_MISMATCH",
                    "context",
                    NOT_EVALUATED,
                    base_audit,
                )

        attribution, audit = _build_attribution(
            claims,
            delegation_context if self.require_delegation_context else None,
            self.hop_kind,
            base_audit,
        )
        return BoundaryDecision(ALLOW, ALLOW, "complete", attribution, audit)


def credential_fingerprint(token: str) -> str:
    """Hash a synthetic Lab token for correlation without persisting the credential."""

    if not isinstance(token, str) or not token:
        raise ValueError("token must be a non-empty string")
    return f"sha256:{hashlib.sha256(token.encode('utf-8')).hexdigest()}"


def _context_matches_request(
    context: Mapping[str, Any],
    claims: Mapping[str, Any],
    fingerprint: str,
    resource_id: str,
    action: str,
) -> bool:
    credential = context["credential"]
    target = context["target"]
    return bool(
        credential["fingerprint"] == fingerprint
        and credential["issuer"] == claims["iss"]
        and credential["subject"] == claims["sub"]
        and credential["client_id"] == claims["client_id"]
        and set(credential["audiences"]) == set(_audiences(claims["aud"]))
        and target["resource"] == resource_id
        and target["action"] == action
    )


def _audiences(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    return ()


def _build_attribution(
    claims: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    hop_kind: str,
    base_audit: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    audit = {
        **base_audit,
        "token_subject": str(claims["sub"]),
        "token_client_id": str(claims["client_id"]),
    }
    if context is None:
        audit["human_principal"] = _human_principal(claims["sub"])
        if hop_kind == "ENTRY":
            return "TOKEN_SUBJECT_AT_ENTRY", audit
        return "COLLAPSED_TO_TOKEN_SUBJECT", audit

    chain = context["actor_chain"]
    human = chain["human"]
    workload = chain["workload"]
    executing = chain["agents"][-1]
    audit.update(
        {
            "human_principal": _identity_value(human),
            "executing_agent": f"{executing['principal']}@{executing['version']}",
            "workload_principal": _identity_value(workload),
        }
    )
    if human["state"] == "PRESENT" and workload["state"] == "PRESENT":
        return "FULL_CHAIN", audit
    return "PARTIAL_CONTEXT", audit


def _empty_audit(resource_id: str, action: str, fingerprint: str) -> dict[str, Any]:
    return {
        "resource": resource_id,
        "action": action,
        "credential_fingerprint": fingerprint,
        "human_principal": "UNVERIFIED",
        "token_subject": "UNVERIFIED",
        "token_client_id": "UNVERIFIED",
        "executing_agent": "UNKNOWN",
        "workload_principal": "UNKNOWN",
    }


def _identity_value(slot: Mapping[str, Any]) -> str:
    if slot["state"] == "PRESENT":
        return str(slot["principal"])
    return str(slot["state"])


def _human_principal(subject: Any) -> str:
    value = str(subject)
    return value if value.startswith("user/") else "UNKNOWN"
