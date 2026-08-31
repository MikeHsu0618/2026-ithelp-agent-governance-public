"""Reproducible Day 12 Cognito Human and M2M contract cases."""

import hashlib
import json
import platform
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from identity_boundary.artifacts import ArtifactStore
from identity_boundary.cognito_contract import CognitoContractError, OfflineCognitoUserPool
from identity_boundary.issuer import IssuedToken, LocalIssuer
from identity_boundary.oauth_flows import create_pkce_pair
from identity_boundary.passthrough import credential_fingerprint
from identity_boundary.validator import TokenPolicy, TokenRejected, TokenValidator

ISSUER = "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_LabPool"
RESOURCE = "https://observability.lab.example/mcp"
HUMAN_CLIENT = "sre-console"
M2M_CLIENT = "sre-scheduler"
CALLBACK = "http://127.0.0.1:8765/callback"
QUERY_SCOPE = "platform/observability.query"


@dataclass(frozen=True, slots=True)
class CognitoSuccess:
    token: IssuedToken
    subject: str
    actor: str


@dataclass(frozen=True, slots=True)
class CognitoCase:
    case_id: str
    path: str
    expected_decision: str
    expected_code: str
    note: str
    action: Callable[[], CognitoSuccess]


@dataclass(frozen=True, slots=True)
class CognitoCaseResult:
    case_id: str
    path: str
    expected_decision: str
    decision: str
    expected_code: str
    code: str
    subject: str
    actor: str
    audience: str
    stage: str
    matched: bool


@dataclass(frozen=True, slots=True)
class CognitoDemoSummary:
    run_id: str
    run_dir: Path
    matched: int
    total: int
    results: tuple[CognitoCaseResult, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "matched": self.matched,
            "total": self.total,
            "results": [asdict(result) for result in self.results],
        }


def run_cognito_demo(artifact_root: Path) -> CognitoDemoSummary:
    """Run nine Cognito-shaped cases without persisting bearer or client credentials."""

    now = datetime.now(UTC).replace(microsecond=0)
    run_id = f"day12-{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    store = ArtifactStore(artifact_root, run_id)
    issuer = LocalIssuer(issuer=ISSUER, key_id="day12-ephemeral")
    pool, client_secret = _build_pool(issuer)
    human_validator, m2m_validator = _build_validators(issuer)
    verifier, challenge = create_pkce_pair()
    cases = _build_cases(
        pool=pool,
        human_validator=human_validator,
        m2m_validator=m2m_validator,
        client_secret=client_secret,
        verifier=verifier,
        challenge=challenge,
        now=now,
    )

    executions = tuple(_run_case(case) for case in cases)
    results = tuple(execution[0] for execution in executions)
    allowed_tokens = {
        result.case_id: outcome.token
        for result, outcome in executions
        if outcome is not None and result.decision == "ALLOW"
    }
    matched = sum(result.matched for result in results)
    summary = CognitoDemoSummary(run_id, store.run_dir, matched, len(results), results)

    store.write_json("jwks.json", issuer.jwks())
    store.write_json("registrations.json", {"clients": pool.safe_registration_snapshot()})
    store.write_json("summary.json", summary.to_json_dict())
    for case_id, token in sorted(allowed_tokens.items()):
        store.write_json(f"tokens/verified-claims/{case_id}.json", token.claims)
    store.write_json(
        "credential-fingerprints.json",
        {
            **{
                case_id: credential_fingerprint(token.encoded)
                for case_id, token in sorted(allowed_tokens.items())
            },
            "raw_credentials_persisted": False,
        },
    )
    store.write_json(
        "manifest.json",
        {
            "lab": "02-identity-boundary",
            "slice": "day-12-cognito-dual-path",
            "run_id": run_id,
            "generated_at": _isoformat(now),
            "fixture_hash": _fixture_hash(cases),
            "python_version": platform.python_version(),
            "pyjwt_version": version("PyJWT"),
            "matched": matched,
            "total": len(results),
            "raw_credentials_persisted": False,
            "client_secrets_persisted": False,
            "pkce_verifiers_persisted": False,
            "private_key_persisted": False,
            "m2m_audience_synthesized": False,
            "synthetic_identities_only": True,
        },
    )
    return summary


def _build_pool(issuer: LocalIssuer) -> tuple[OfflineCognitoUserPool, str]:
    pool = OfflineCognitoUserPool(issuer=issuer)
    pool.register_human_client(
        client_id=HUMAN_CLIENT,
        redirect_uris=(CALLBACK,),
        allowed_scopes=frozenset({"openid", QUERY_SCOPE}),
        allowed_resources=frozenset({RESOURCE}),
    )
    client_secret = secrets.token_urlsafe(32)
    pool.register_m2m_client(
        client_id=M2M_CLIENT,
        client_secret=client_secret,
        allowed_scopes=frozenset({QUERY_SCOPE}),
    )
    return pool, client_secret


def _build_validators(issuer: LocalIssuer) -> tuple[TokenValidator, TokenValidator]:
    human = TokenValidator(
        jwks=issuer.jwks(),
        policy=TokenPolicy(
            issuer=ISSUER,
            audience=RESOURCE,
            client_id=HUMAN_CLIENT,
            required_scopes=frozenset({QUERY_SCOPE}),
            required_claims=frozenset({"team"}),
            require_type_header=False,
        ),
    )
    m2m = TokenValidator(
        jwks=issuer.jwks(),
        policy=TokenPolicy(
            issuer=ISSUER,
            audience=None,
            client_id=M2M_CLIENT,
            required_scopes=frozenset({QUERY_SCOPE}),
            required_claims=frozenset(),
            require_subject=False,
            require_type_header=False,
            forbid_audience=True,
        ),
    )
    return human, m2m


def _build_cases(
    *,
    pool: OfflineCognitoUserPool,
    human_validator: TokenValidator,
    m2m_validator: TokenValidator,
    client_secret: str,
    verifier: str,
    challenge: str,
    now: datetime,
) -> tuple[CognitoCase, ...]:
    def human_token(
        *,
        callback: str = CALLBACK,
        scopes: tuple[str, ...] = (QUERY_SCOPE,),
        additional_claims: dict[str, Any] | None = None,
    ) -> IssuedToken:
        return pool.issue_human_access_token(
            client_id=HUMAN_CLIENT,
            redirect_uri=callback,
            requested_scopes=scopes,
            resource=RESOURCE,
            subject="user/sre-oncaller",
            code_verifier=verifier,
            code_challenge=challenge,
            additional_claims=(
                additional_claims if additional_claims is not None else {"team": "platform"}
            ),
            issued_at=now,
        )

    def allow_human() -> CognitoSuccess:
        token = human_token()
        claims = human_validator.validate(token.encoded)
        principal = str(claims["sub"])
        return CognitoSuccess(token, principal, principal)

    def missing_human_claim() -> CognitoSuccess:
        token = human_token(additional_claims={})
        human_validator.validate(token.encoded)
        raise AssertionError("validator unexpectedly accepted a missing Human policy claim")

    def m2m_token(
        *,
        client_id: str = M2M_CLIENT,
        supplied_secret: str = client_secret,
        scopes: tuple[str, ...] = (QUERY_SCOPE,),
        resource: str | None = None,
    ) -> IssuedToken:
        return pool.issue_m2m_access_token(
            client_id=client_id,
            client_secret=supplied_secret,
            requested_scopes=scopes,
            resource=resource,
            issued_at=now,
        )

    def allow_m2m() -> CognitoSuccess:
        token = m2m_token()
        claims = m2m_validator.validate(token.encoded)
        return CognitoSuccess(token, "NOT_APPLICABLE", f"client/{claims['client_id']}")

    return (
        CognitoCase(
            "human_pkce_success",
            "HUMAN",
            "ALLOW",
            "POLICY_ALLOWED",
            "Public app client, PKCE, resource-bound aud, and Human subject all match.",
            allow_human,
        ),
        CognitoCase(
            "human_callback_mismatch",
            "HUMAN",
            "DENY",
            "REDIRECT_URI_MISMATCH",
            "The callback must match the app-client registration exactly.",
            lambda: _unexpected_success(human_token(callback="http://127.0.0.1:9999/callback")),
        ),
        CognitoCase(
            "human_scope_invalid",
            "HUMAN",
            "DENY",
            "INVALID_SCOPE",
            "A Human client cannot request a scope absent from its registration.",
            lambda: _unexpected_success(human_token(scopes=("platform/admin",))),
        ),
        CognitoCase(
            "human_missing_policy_claim",
            "HUMAN",
            "DENY",
            "CLAIM_MISSING",
            "A signed token can still lack an input required by gateway policy.",
            missing_human_claim,
        ),
        CognitoCase(
            "m2m_client_credentials_success",
            "M2M",
            "ALLOW",
            "POLICY_ALLOWED",
            "The verified client_id becomes the machine actor; no Human subject is invented.",
            allow_m2m,
        ),
        CognitoCase(
            "m2m_public_client",
            "M2M",
            "DENY",
            "UNAUTHORIZED_CLIENT",
            "Client Credentials requires a separate confidential app client.",
            lambda: _unexpected_success(m2m_token(client_id=HUMAN_CLIENT)),
        ),
        CognitoCase(
            "m2m_wrong_secret",
            "M2M",
            "DENY",
            "INVALID_CLIENT",
            "A wrong credential fails before token policy evaluation.",
            lambda: _unexpected_success(m2m_token(supplied_secret="wrong-secret")),
        ),
        CognitoCase(
            "m2m_openid_scope",
            "M2M",
            "DENY",
            "INVALID_SCOPE",
            "Client Credentials can request custom resource-server scopes only.",
            lambda: _unexpected_success(m2m_token(scopes=("openid",))),
        ),
        CognitoCase(
            "m2m_resource_binding",
            "M2M",
            "DENY",
            "RESOURCE_BINDING_UNSUPPORTED",
            "Cognito does not resource-bind client-credentials access tokens.",
            lambda: _unexpected_success(m2m_token(resource=RESOURCE)),
        ),
    )


def _unexpected_success(token: IssuedToken) -> CognitoSuccess:
    return CognitoSuccess(token, "UNEXPECTED", "UNEXPECTED")


def _run_case(case: CognitoCase) -> tuple[CognitoCaseResult, CognitoSuccess | None]:
    try:
        outcome = case.action()
        decision = "ALLOW"
        code = "POLICY_ALLOWED"
        stage = "gateway_policy"
        subject = outcome.subject
        actor = outcome.actor
        audience = str(outcome.token.claims.get("aud", "NOT_PRESENT"))
    except (CognitoContractError, TokenRejected) as error:
        outcome = None
        decision = "DENY"
        code = error.code
        stage = error.stage
        subject = "NOT_EVALUATED"
        actor = "NOT_EVALUATED"
        audience = "NOT_EVALUATED"

    result = CognitoCaseResult(
        case_id=case.case_id,
        path=case.path,
        expected_decision=case.expected_decision,
        decision=decision,
        expected_code=case.expected_code,
        code=code,
        subject=subject,
        actor=actor,
        audience=audience,
        stage=stage,
        matched=decision == case.expected_decision and code == case.expected_code,
    )
    return result, outcome


def _fixture_hash(cases: tuple[CognitoCase, ...]) -> str:
    payload = [
        {
            "case_id": case.case_id,
            "path": case.path,
            "expected_decision": case.expected_decision,
            "expected_code": case.expected_code,
            "note": case.note,
        }
        for case in cases
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
