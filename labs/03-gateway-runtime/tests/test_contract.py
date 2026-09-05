import pytest

from gateway_runtime.contract import (
    CredentialCase,
    GatewayObservation,
    assess,
)


def observation(
    *,
    status_code: int = 200,
    kind: str | None = None,
    human: str | None = None,
    workload: str | None = None,
    consumer: str | None = None,
    provider_auth: str = "MATCHED",
    forwarded: bool = False,
) -> GatewayObservation:
    return GatewayObservation(
        status_code=status_code,
        audit_kind=kind,
        human=human,
        workload=workload,
        consumer=consumer,
        provider_auth=provider_auth,
        incoming_credential_forwarded=forwarded,
    )


def test_disabled_human_key_exposes_stale_mapping() -> None:
    case = CredentialCase(
        case_id="human-key-after-offboarding",
        credential_kind="HUMAN_VIRTUAL_KEY",
        identity_state="DISABLED",
        expected_code="STALE_MAPPING_ALLOWED",
    )

    result = assess(
        case,
        observation(
            kind="HUMAN_VIRTUAL_KEY",
            human="user/sre-oncaller",
            workload="NOT_APPLICABLE",
            consumer="key/human-sre-oncaller",
        ),
    )

    assert result.matched is True
    assert result.gateway_decision == "ALLOW"
    assert result.control_result == "RISK_EXPOSED"
    assert result.code == "STALE_MAPPING_ALLOWED"


def test_workload_key_is_a_valid_non_human_isolation_boundary() -> None:
    case = CredentialCase(
        case_id="workload-key",
        credential_kind="WORKLOAD_CONSUMER_KEY",
        identity_state="NOT_APPLICABLE",
        expected_code="WORKLOAD_KEY_ISOLATED",
    )

    result = assess(
        case,
        observation(
            kind="WORKLOAD_CONSUMER_KEY",
            human="NOT_APPLICABLE",
            workload="workload/runtime-a",
            consumer="key/runtime-a",
        ),
    )

    assert result.matched is True
    assert result.control_result == "CONTROL_OK"
    assert result.code == "WORKLOAD_KEY_ISOLATED"


def test_retired_workload_key_is_rejected() -> None:
    case = CredentialCase(
        case_id="retired-workload-key",
        credential_kind="RETIRED_WORKLOAD_CONSUMER_KEY",
        identity_state="NOT_APPLICABLE",
        expected_code="OLD_KEY_REJECTED",
    )

    result = assess(
        case,
        observation(status_code=401, provider_auth="NOT_REACHED"),
    )

    assert result.matched is True
    assert result.gateway_decision == "DENY"
    assert result.control_result == "CONTROL_OK"
    assert result.code == "OLD_KEY_REJECTED"


def test_verified_jwt_preserves_human_and_client_attribution() -> None:
    case = CredentialCase(
        case_id="jwt-human",
        credential_kind="JWT_PRINCIPAL",
        identity_state="ACTIVE",
        expected_code="JWT_PRINCIPAL_VERIFIED",
    )

    result = assess(
        case,
        observation(
            kind="JWT_PRINCIPAL",
            human="user/sre-oncaller",
            workload="NOT_APPLICABLE",
            consumer="client/agent-ui",
        ),
    )

    assert result.matched is True
    assert result.control_result == "CONTROL_OK"
    assert result.code == "JWT_PRINCIPAL_VERIFIED"


def test_wrong_audience_jwt_is_rejected() -> None:
    case = CredentialCase(
        case_id="jwt-wrong-audience",
        credential_kind="JWT_WRONG_AUDIENCE",
        identity_state="ACTIVE",
        expected_code="JWT_AUDIENCE_REJECTED",
    )

    result = assess(
        case,
        observation(status_code=401, provider_auth="NOT_REACHED"),
    )

    assert result.matched is True
    assert result.code == "JWT_AUDIENCE_REJECTED"


@pytest.mark.parametrize(
    ("credential_kind", "expected_code"),
    [
        ("JWT_WRONG_ISSUER", "JWT_ISSUER_REJECTED"),
        ("JWT_MISSING_ISSUER", "JWT_ISSUER_REQUIRED"),
        ("JWT_MISSING_AUDIENCE", "JWT_AUDIENCE_REQUIRED"),
    ],
)
def test_invalid_jwt_claim_boundaries_are_rejected(
    credential_kind: str,
    expected_code: str,
) -> None:
    case = CredentialCase(
        case_id="jwt-claim-boundary",
        credential_kind=credential_kind,
        identity_state="ACTIVE",
        expected_code=expected_code,
    )

    result = assess(
        case,
        observation(status_code=401, provider_auth="NOT_REACHED"),
    )

    assert result.matched is True
    assert result.code == expected_code


def test_provider_key_or_forwarding_failure_never_counts_as_a_match() -> None:
    case = CredentialCase(
        case_id="workload-key",
        credential_kind="WORKLOAD_CONSUMER_KEY",
        identity_state="NOT_APPLICABLE",
        expected_code="WORKLOAD_KEY_ISOLATED",
    )

    result = assess(
        case,
        observation(
            kind="WORKLOAD_CONSUMER_KEY",
            human="NOT_APPLICABLE",
            workload="workload/runtime-a",
            consumer="key/runtime-a",
            provider_auth="MISMATCH",
            forwarded=True,
        ),
    )

    assert result.matched is False
    assert result.control_result == "CONTROL_FAILED"
    assert result.code == "UPSTREAM_CREDENTIAL_BOUNDARY_FAILED"
