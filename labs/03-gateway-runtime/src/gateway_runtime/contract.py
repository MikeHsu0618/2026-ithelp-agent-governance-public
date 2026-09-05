"""Assessment contract for the credential-boundary cases."""

from dataclasses import asdict, dataclass
from typing import Literal

CredentialKind = Literal[
    "HUMAN_VIRTUAL_KEY",
    "WORKLOAD_CONSUMER_KEY",
    "RETIRED_WORKLOAD_CONSUMER_KEY",
    "JWT_PRINCIPAL",
    "JWT_WRONG_ISSUER",
    "JWT_WRONG_AUDIENCE",
    "JWT_MISSING_ISSUER",
    "JWT_MISSING_AUDIENCE",
]
IdentityState = Literal["ACTIVE", "DISABLED", "NOT_APPLICABLE"]


@dataclass(frozen=True)
class CredentialCase:
    """One credential and directory-state combination sent through the gateway."""

    case_id: str
    credential_kind: CredentialKind
    identity_state: IdentityState
    expected_code: str


@dataclass(frozen=True)
class GatewayObservation:
    """Safe fields observed at the caller and the synthetic provider."""

    status_code: int
    audit_kind: str | None = None
    human: str | None = None
    workload: str | None = None
    consumer: str | None = None
    provider_auth: str = "NOT_REACHED"
    incoming_credential_forwarded: bool = False


@dataclass(frozen=True)
class CaseResult:
    """A stable, publication-safe result for one case."""

    case_id: str
    credential_kind: str
    identity_state: str
    gateway_decision: str
    control_result: str
    code: str
    human: str
    workload: str
    consumer: str
    provider_auth: str
    incoming_credential_forwarded: bool
    matched: bool

    def to_event(self) -> dict[str, str | bool]:
        return asdict(self)


def assess(case: CredentialCase, observation: GatewayObservation) -> CaseResult:
    """Classify what the gateway proved without treating a key label as identity truth."""

    gateway_decision = "ALLOW" if observation.status_code == 200 else "DENY"
    code, control_result = _classify(case, observation)
    return CaseResult(
        case_id=case.case_id,
        credential_kind=case.credential_kind,
        identity_state=case.identity_state,
        gateway_decision=gateway_decision,
        control_result=control_result,
        code=code,
        human=observation.human or "NOT_OBSERVED",
        workload=observation.workload or "NOT_OBSERVED",
        consumer=observation.consumer or "NOT_OBSERVED",
        provider_auth=observation.provider_auth,
        incoming_credential_forwarded=observation.incoming_credential_forwarded,
        matched=code == case.expected_code,
    )


def _classify(case: CredentialCase, observation: GatewayObservation) -> tuple[str, str]:
    if observation.status_code == 200 and (
        observation.provider_auth != "MATCHED" or observation.incoming_credential_forwarded
    ):
        return "UPSTREAM_CREDENTIAL_BOUNDARY_FAILED", "CONTROL_FAILED"

    if observation.status_code == 401:
        if case.credential_kind == "RETIRED_WORKLOAD_CONSUMER_KEY":
            return "OLD_KEY_REJECTED", "CONTROL_OK"
        if case.credential_kind == "JWT_WRONG_ISSUER":
            return "JWT_ISSUER_REJECTED", "CONTROL_OK"
        if case.credential_kind == "JWT_WRONG_AUDIENCE":
            return "JWT_AUDIENCE_REJECTED", "CONTROL_OK"
        if case.credential_kind == "JWT_MISSING_ISSUER":
            return "JWT_ISSUER_REQUIRED", "CONTROL_OK"
        if case.credential_kind == "JWT_MISSING_AUDIENCE":
            return "JWT_AUDIENCE_REQUIRED", "CONTROL_OK"
        return "UNEXPECTED_GATEWAY_REJECTION", "CONTROL_FAILED"

    if observation.status_code != 200:
        return "UNEXPECTED_GATEWAY_RESULT", "CONTROL_FAILED"

    if case.credential_kind == "HUMAN_VIRTUAL_KEY":
        if not _matches(
            observation,
            kind="HUMAN_VIRTUAL_KEY",
            human="user/sre-oncaller",
            workload="NOT_APPLICABLE",
            consumer="key/human-sre-oncaller",
        ):
            return "ATTRIBUTION_MISMATCH", "CONTROL_FAILED"
        if case.identity_state == "DISABLED":
            return "STALE_MAPPING_ALLOWED", "RISK_EXPOSED"
        return "KEY_MAPPING_ACTIVE", "CONTROL_OK"

    if case.credential_kind == "WORKLOAD_CONSUMER_KEY" and _matches(
        observation,
        kind="WORKLOAD_CONSUMER_KEY",
        human="NOT_APPLICABLE",
        workload="workload/runtime-a",
        consumer="key/runtime-a",
    ):
        return "WORKLOAD_KEY_ISOLATED", "CONTROL_OK"

    if case.credential_kind == "JWT_PRINCIPAL" and _matches(
        observation,
        kind="JWT_PRINCIPAL",
        human="user/sre-oncaller",
        workload="NOT_APPLICABLE",
        consumer="client/agent-ui",
    ):
        return "JWT_PRINCIPAL_VERIFIED", "CONTROL_OK"

    return "ATTRIBUTION_MISMATCH", "CONTROL_FAILED"


def _matches(
    observation: GatewayObservation,
    *,
    kind: str,
    human: str,
    workload: str,
    consumer: str,
) -> bool:
    return (
        observation.audit_kind == kind
        and observation.human == human
        and observation.workload == workload
        and observation.consumer == consumer
    )
