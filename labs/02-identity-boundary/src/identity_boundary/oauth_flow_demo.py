"""Reproducible Day 11 PKCE, Client Credentials, and Token Exchange cases."""

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
from identity_boundary.issuer import IssuedToken, LocalIssuer
from identity_boundary.oauth_flows import (
    ACCESS_TOKEN_TYPE,
    OAuthFlowError,
    OfflineAuthorizationServer,
    create_pkce_pair,
)
from identity_boundary.passthrough import credential_fingerprint
from identity_boundary.validator import TokenPolicy

ISSUER = "https://issuer.lab.example/identity-boundary"
ENTRY_RESOURCE = "https://agent.lab.example/mcp"
TOOL_RESOURCE = "https://observability.lab.example/mcp"
PUBLIC_CLIENT = "sre-console"
SCHEDULER_CLIENT = "sre-scheduler"
RUNTIME_CLIENT = "sre-investigator-runtime"
REDIRECT_URI = "http://127.0.0.1:8765/callback"
TOKEN_ENDPOINT = f"{ISSUER}/token"


@dataclass(frozen=True, slots=True)
class OAuthFlowCase:
    case_id: str
    flow: str
    expected_decision: str
    expected_code: str
    resource: str
    note: str
    action: Callable[[], IssuedToken]


@dataclass(frozen=True, slots=True)
class OAuthFlowCaseResult:
    case_id: str
    flow: str
    expected_decision: str
    decision: str
    expected_code: str
    code: str
    subject: str
    actor: str
    resource: str
    scopes: tuple[str, ...]
    stage: str
    reason_code: str
    matched: bool


@dataclass(frozen=True, slots=True)
class OAuthFlowDemoSummary:
    run_id: str
    run_dir: Path
    matched: int
    total: int
    results: tuple[OAuthFlowCaseResult, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "matched": self.matched,
            "total": self.total,
            "results": [asdict(result) for result in self.results],
        }


def run_oauth_flow_demo(artifact_root: Path) -> OAuthFlowDemoSummary:
    """Run nine OAuth cases without persisting bearer or client credentials."""

    now = datetime.now(UTC).replace(microsecond=0)
    run_id = f"day11-{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    store = ArtifactStore(artifact_root, run_id)
    issuer = LocalIssuer(issuer=ISSUER, key_id="day11-ephemeral")
    server = _build_server(issuer)
    pkce_verifier, pkce_challenge = create_pkce_pair()
    scheduler_credential = secrets.token_urlsafe(32)
    runtime_credential = secrets.token_urlsafe(32)
    server.register_confidential_client(
        client_id=SCHEDULER_CLIENT,
        client_secret=scheduler_credential,
        allowed_grants=frozenset({"client_credentials"}),
        allowed_scopes=frozenset({"observability.query"}),
        allowed_resources=frozenset({TOOL_RESOURCE}),
    )
    server.register_confidential_client(
        client_id=RUNTIME_CLIENT,
        client_secret=runtime_credential,
        allowed_grants=frozenset({"token_exchange"}),
        allowed_scopes=frozenset({"observability.query"}),
        allowed_resources=frozenset({TOOL_RESOURCE}),
    )
    subject_token = _issue_subject_token(issuer, now, audience=ENTRY_RESOURCE)
    wrong_audience_subject = _issue_subject_token(issuer, now, audience=TOOL_RESOURCE)
    actor_token = _issue_actor_token(issuer, now)
    cases = _build_cases(
        server=server,
        pkce_verifier=pkce_verifier,
        pkce_challenge=pkce_challenge,
        scheduler_credential=scheduler_credential,
        runtime_credential=runtime_credential,
        subject_token=subject_token,
        wrong_audience_subject=wrong_audience_subject,
        actor_token=actor_token,
    )

    executions = tuple(_run_case(case, store, now) for case in cases)
    results = tuple(execution[0] for execution in executions)
    issued_tokens = {
        result.case_id: token
        for result, token in executions
        if token is not None and result.decision == "ISSUE"
    }
    matched = sum(result.matched for result in results)
    summary = OAuthFlowDemoSummary(run_id, store.run_dir, matched, len(results), results)

    store.write_json("jwks.json", issuer.jwks())
    store.write_json("registrations.json", {"clients": server.safe_registration_snapshot()})
    store.write_json("tokens/issuer-input/human-entry.json", subject_token.claims)
    store.write_json("tokens/issuer-input/runtime-actor.json", actor_token.claims)
    for case_id, token in issued_tokens.items():
        store.write_json(f"tokens/issuer-output/{case_id}.json", token.claims)
    store.write_json(
        "credential-fingerprints.json",
        {
            "human_subject_token": credential_fingerprint(subject_token.encoded),
            "runtime_actor_token": credential_fingerprint(actor_token.encoded),
            **{
                case_id: credential_fingerprint(token.encoded)
                for case_id, token in sorted(issued_tokens.items())
            },
            "raw_credentials_persisted": False,
        },
    )
    store.write_json("summary.json", summary.to_json_dict())
    store.write_json(
        "manifest.json",
        {
            "lab": "02-identity-boundary",
            "slice": "day-11-oauth-flows",
            "run_id": run_id,
            "generated_at": _isoformat(now),
            "fixture_hash": _fixture_hash(cases),
            "python_version": platform.python_version(),
            "pyjwt_version": version("PyJWT"),
            "matched": matched,
            "total": len(results),
            "raw_credentials_persisted": False,
            "authorization_codes_persisted": False,
            "pkce_verifiers_persisted": False,
            "client_secrets_persisted": False,
            "private_key_persisted": False,
            "synthetic_identities_only": True,
        },
    )
    return summary


def _build_server(issuer: LocalIssuer) -> OfflineAuthorizationServer:
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


def _issue_subject_token(issuer: LocalIssuer, now: datetime, *, audience: str) -> IssuedToken:
    return issuer.issue_access_token(
        subject="user/sre-oncaller",
        audience=audience,
        client_id=PUBLIC_CLIENT,
        scopes=("agent.delegate", "observability.query"),
        additional_claims={
            "team": "platform",
            "may_act": {"sub": f"client/{RUNTIME_CLIENT}"},
        },
        issued_at=now,
    )


def _issue_actor_token(issuer: LocalIssuer, now: datetime) -> IssuedToken:
    return issuer.issue_access_token(
        subject=f"client/{RUNTIME_CLIENT}",
        audience=TOKEN_ENDPOINT,
        client_id=RUNTIME_CLIENT,
        scopes=("agent.exchange",),
        additional_claims={},
        issued_at=now,
    )


def _build_cases(
    *,
    server: OfflineAuthorizationServer,
    pkce_verifier: str,
    pkce_challenge: str,
    scheduler_credential: str,
    runtime_credential: str,
    subject_token: IssuedToken,
    wrong_audience_subject: IssuedToken,
    actor_token: IssuedToken,
) -> tuple[OAuthFlowCase, ...]:
    return (
        OAuthFlowCase(
            "pkce_human_success",
            "PKCE",
            "ISSUE",
            "TOKEN_ISSUED",
            ENTRY_RESOURCE,
            "registered public client completes Authorization Code + PKCE",
            lambda: _complete_pkce(server, pkce_verifier, pkce_challenge),
        ),
        OAuthFlowCase(
            "pkce_callback_mismatch",
            "PKCE",
            "DENY",
            "REDIRECT_URI_MISMATCH",
            ENTRY_RESOURCE,
            "localhost and 127.0.0.1 are different registered redirect URIs",
            lambda: _authorize_only(
                server,
                client_id=PUBLIC_CLIENT,
                redirect_uri="http://localhost:8765/callback",
                scopes=frozenset({"agent.delegate"}),
                challenge=pkce_challenge,
            ),
        ),
        OAuthFlowCase(
            "pkce_invalid_scope",
            "PKCE",
            "DENY",
            "INVALID_SCOPE",
            ENTRY_RESOURCE,
            "discovery does not override the client scope allowlist",
            lambda: _authorize_only(
                server,
                client_id=PUBLIC_CLIENT,
                redirect_uri=REDIRECT_URI,
                scopes=frozenset({"admin.everything"}),
                challenge=pkce_challenge,
            ),
        ),
        OAuthFlowCase(
            "pkce_unregistered_client",
            "PKCE",
            "DENY",
            "CLIENT_NOT_REGISTERED",
            ENTRY_RESOURCE,
            "a client still needs CIMD, pre-registration, or legacy DCR",
            lambda: _authorize_only(
                server,
                client_id="unknown-cli",
                redirect_uri=REDIRECT_URI,
                scopes=frozenset({"agent.delegate"}),
                challenge=pkce_challenge,
            ),
        ),
        OAuthFlowCase(
            "client_credentials_success",
            "CLIENT_CREDENTIALS",
            "ISSUE",
            "TOKEN_ISSUED",
            TOOL_RESOURCE,
            "scheduler acts as itself without a Human subject",
            lambda: server.client_credentials(
                client_id=SCHEDULER_CLIENT,
                client_secret=scheduler_credential,
                scopes=frozenset({"observability.query"}),
                resource=TOOL_RESOURCE,
            ),
        ),
        OAuthFlowCase(
            "client_credentials_public_client",
            "CLIENT_CREDENTIALS",
            "DENY",
            "UNAUTHORIZED_CLIENT",
            ENTRY_RESOURCE,
            "a public CLI cannot authenticate with a durable shared credential",
            lambda: server.client_credentials(
                client_id=PUBLIC_CLIENT,
                client_secret=secrets.token_urlsafe(32),
                scopes=frozenset({"agent.delegate"}),
                resource=ENTRY_RESOURCE,
            ),
        ),
        OAuthFlowCase(
            "token_exchange_success",
            "TOKEN_EXCHANGE",
            "ISSUE",
            "TOKEN_ISSUED",
            TOOL_RESOURCE,
            "downstream token keeps user/sre-oncaller as subject and runtime as current actor",
            lambda: server.token_exchange(
                client_id=RUNTIME_CLIENT,
                client_secret=runtime_credential,
                subject_token=subject_token.encoded,
                subject_token_type=ACCESS_TOKEN_TYPE,
                actor_token=actor_token.encoded,
                actor_token_type=ACCESS_TOKEN_TYPE,
                scopes=frozenset({"observability.query"}),
                resource=TOOL_RESOURCE,
            ),
        ),
        OAuthFlowCase(
            "token_exchange_invalid_target",
            "TOKEN_EXCHANGE",
            "DENY",
            "INVALID_TARGET",
            "https://billing.lab.example/mcp",
            "runtime cannot exchange into a resource outside its target allowlist",
            lambda: server.token_exchange(
                client_id=RUNTIME_CLIENT,
                client_secret=runtime_credential,
                subject_token=subject_token.encoded,
                subject_token_type=ACCESS_TOKEN_TYPE,
                actor_token=actor_token.encoded,
                actor_token_type=ACCESS_TOKEN_TYPE,
                scopes=frozenset({"observability.query"}),
                resource="https://billing.lab.example/mcp",
            ),
        ),
        OAuthFlowCase(
            "token_exchange_wrong_subject_audience",
            "TOKEN_EXCHANGE",
            "DENY",
            "SUBJECT_TOKEN_INVALID",
            TOOL_RESOURCE,
            "runtime cannot redeem a subject token issued for another resource",
            lambda: server.token_exchange(
                client_id=RUNTIME_CLIENT,
                client_secret=runtime_credential,
                subject_token=wrong_audience_subject.encoded,
                subject_token_type=ACCESS_TOKEN_TYPE,
                actor_token=actor_token.encoded,
                actor_token_type=ACCESS_TOKEN_TYPE,
                scopes=frozenset({"observability.query"}),
                resource=TOOL_RESOURCE,
            ),
        ),
    )


def _complete_pkce(
    server: OfflineAuthorizationServer, verifier: str, challenge: str
) -> IssuedToken:
    grant = server.authorize_code(
        client_id=PUBLIC_CLIENT,
        redirect_uri=REDIRECT_URI,
        scopes=frozenset({"agent.delegate"}),
        resource=ENTRY_RESOURCE,
        subject="user/sre-oncaller",
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    return server.redeem_code(
        client_id=PUBLIC_CLIENT,
        redirect_uri=REDIRECT_URI,
        authorization_code=grant.authorization_code,
        code_verifier=verifier,
    )


def _authorize_only(
    server: OfflineAuthorizationServer,
    *,
    client_id: str,
    redirect_uri: str,
    scopes: frozenset[str],
    challenge: str,
) -> IssuedToken:
    server.authorize_code(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
        resource=ENTRY_RESOURCE,
        subject="user/sre-oncaller",
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    raise AssertionError("negative authorization case unexpectedly issued a code")


def _run_case(
    case: OAuthFlowCase, store: ArtifactStore, now: datetime
) -> tuple[OAuthFlowCaseResult, IssuedToken | None]:
    try:
        token = case.action()
        decision = "ISSUE"
        code = "TOKEN_ISSUED"
        subject = str(token.claims["sub"])
        actor_claim = token.claims.get("act")
        actor = (
            str(actor_claim["sub"])
            if isinstance(actor_claim, dict) and "sub" in actor_claim
            else subject
        )
        scopes = tuple(str(token.claims["scope"]).split())
        stage = "complete"
        reason_code = "NOT_APPLICABLE"
    except OAuthFlowError as error:
        token = None
        decision = "DENY"
        code = error.code
        subject = "NOT_ISSUED"
        actor = "NOT_ISSUED"
        scopes = ()
        stage = error.stage
        reason_code = error.reason_code

    matched = decision == case.expected_decision and code == case.expected_code
    result = OAuthFlowCaseResult(
        case.case_id,
        case.flow,
        case.expected_decision,
        decision,
        case.expected_code,
        code,
        subject,
        actor,
        case.resource,
        scopes,
        stage,
        reason_code,
        matched,
    )
    store.write_json(
        f"expected/{case.case_id}.json",
        {
            "case_id": case.case_id,
            "flow": case.flow,
            "resource": case.resource,
            "expected_decision": case.expected_decision,
            "expected_code": case.expected_code,
            "note": case.note,
        },
    )
    store.append_jsonl(
        "events.jsonl",
        {
            "event_type": "oauth.flow.decision",
            "timestamp": _isoformat(now),
            "case_id": case.case_id,
            "flow": case.flow,
            "decision": decision,
            "code": code,
            "stage": stage,
            "reason_code": reason_code,
            "subject": subject,
            "actor": actor,
            "resource": case.resource,
            "scopes": list(scopes),
            "matched_expected": matched,
        },
    )
    return result, token


def _fixture_hash(cases: tuple[OAuthFlowCase, ...]) -> str:
    payload = [
        {
            "case_id": case.case_id,
            "flow": case.flow,
            "resource": case.resource,
            "expected_decision": case.expected_decision,
            "expected_code": case.expected_code,
            "note": case.note,
        }
        for case in cases
    ]
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
