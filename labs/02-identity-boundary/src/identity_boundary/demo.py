"""Seven reproducible JWT boundary cases and their evidence artifacts."""

import hashlib
import json
import platform
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any

from identity_boundary.artifacts import ArtifactStore
from identity_boundary.issuer import IssuedToken, LocalIssuer
from identity_boundary.validator import TokenPolicy, TokenRejected, TokenValidator

ISSUER = "https://issuer.lab.example/identity-boundary"
AUDIENCE = "mcp://lab/observability/query"
CLIENT_ID = "sre-console"
SUBJECT = "user/sre-oncaller"
REQUIRED_SCOPE = "observability.query"
KEY_ID = "day-08-signing-key"


@dataclass(frozen=True, slots=True)
class TokenCase:
    case_id: str
    token: IssuedToken
    expected_allowed: bool
    expected_code: str
    note: str


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    expected_allowed: bool
    allowed: bool
    expected_code: str
    code: str
    stage: str
    matched: bool


@dataclass(frozen=True, slots=True)
class DemoSummary:
    run_id: str
    run_dir: Path
    matched: int
    total: int
    results: tuple[CaseResult, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "matched": self.matched,
            "total": self.total,
            "results": [asdict(result) for result in self.results],
        }


def run_demo(artifact_root: Path) -> DemoSummary:
    """Run all cases with an ephemeral issuer and persist only safe evidence."""

    now = datetime.now(UTC).replace(microsecond=0)
    run_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    store = ArtifactStore(artifact_root, run_id)
    issuer = LocalIssuer(issuer=ISSUER, key_id=KEY_ID)
    policy = TokenPolicy(
        issuer=ISSUER,
        audience=AUDIENCE,
        client_id=CLIENT_ID,
        required_scopes=frozenset({REQUIRED_SCOPE}),
        required_claims=frozenset({"team"}),
    )
    validator = TokenValidator(jwks=issuer.jwks(), policy=policy)
    cases = _build_cases(issuer, now)

    store.write_json("jwks.json", issuer.jwks())
    results = tuple(_run_case(case, validator, store, now) for case in cases)
    matched = sum(result.matched for result in results)
    summary = DemoSummary(
        run_id=run_id,
        run_dir=store.run_dir,
        matched=matched,
        total=len(results),
        results=results,
    )
    store.write_json("summary.json", summary.to_json_dict())
    store.write_json(
        "manifest.json",
        {
            "lab": "02-identity-boundary",
            "slice": "day-08-token-validation",
            "run_id": run_id,
            "generated_at": _isoformat(now),
            "fixture_hash": _fixture_hash(cases),
            "python_version": platform.python_version(),
            "pyjwt_version": version("PyJWT"),
            "matched": matched,
            "total": len(results),
            "encoded_tokens_persisted": False,
            "private_key_persisted": False,
        },
    )
    return summary


def _build_cases(issuer: LocalIssuer, now: datetime) -> tuple[TokenCase, ...]:
    base: dict[str, Any] = {
        "subject": SUBJECT,
        "audience": AUDIENCE,
        "client_id": CLIENT_ID,
        "scopes": (REQUIRED_SCOPE,),
        "additional_claims": {"team": "platform"},
        "issued_at": now,
        "lifetime": timedelta(minutes=5),
    }

    def access(**overrides: Any) -> IssuedToken:
        arguments = {**base, **overrides}
        return issuer.issue_access_token(**arguments)

    return (
        TokenCase(
            "valid_access",
            access(),
            True,
            "ALLOW",
            "signature, resource, client, scope, and policy claim all match",
        ),
        TokenCase(
            "wrong_issuer",
            access(issuer_override="https://wrong.example/issuer"),
            False,
            "ISSUER_MISMATCH",
            "signature is valid but the issuer is not trusted",
        ),
        TokenCase(
            "wrong_audience",
            access(audience="mcp://lab/admin/delete"),
            False,
            "AUDIENCE_MISMATCH",
            "token is not bound to this MCP resource",
        ),
        TokenCase(
            "expired_access",
            access(lifetime=timedelta(seconds=-1)),
            False,
            "TOKEN_EXPIRED",
            "expired credentials fail before policy evaluation",
        ),
        TokenCase(
            "missing_scope",
            access(scopes=("profile",)),
            False,
            "SCOPE_MISSING",
            "authentication succeeded but OAuth permission is absent",
        ),
        TokenCase(
            "access_missing_team",
            access(additional_claims={}),
            False,
            "CLAIM_MISSING",
            "valid access token lacks the attribute required by policy",
        ),
        TokenCase(
            "id_token_has_team",
            issuer.issue_id_token(
                subject=SUBJECT,
                audience=CLIENT_ID,
                additional_claims={"team": "platform"},
                issued_at=now,
                lifetime=timedelta(minutes=5),
            ),
            False,
            "TOKEN_TYPE_INVALID",
            "identity data in an ID token does not make it an API access token",
        ),
    )


def _run_case(
    case: TokenCase,
    validator: TokenValidator,
    store: ArtifactStore,
    now: datetime,
) -> CaseResult:
    try:
        validator.validate(case.token.encoded)
        allowed, code, stage = True, "ALLOW", "complete"
    except TokenRejected as error:
        allowed, code, stage = False, error.code, error.stage

    matched = allowed == case.expected_allowed and code == case.expected_code
    result = CaseResult(
        case_id=case.case_id,
        expected_allowed=case.expected_allowed,
        allowed=allowed,
        expected_code=case.expected_code,
        code=code,
        stage=stage,
        matched=matched,
    )
    store.write_json(
        f"tokens/decoded/{case.case_id}.json",
        {
            "case_id": case.case_id,
            "source": "issuer-input-claims",
            "warning": (
                "These synthetic claims are evidence input, not a substitute for validation."
            ),
            "claims": case.token.claims,
        },
    )
    store.write_json(
        f"expected/{case.case_id}.json",
        {
            "case_id": case.case_id,
            "expected_allowed": case.expected_allowed,
            "expected_code": case.expected_code,
            "note": case.note,
        },
    )
    store.append_jsonl(
        "events.jsonl",
        {
            "event_type": "validation.decision",
            "timestamp": _isoformat(now),
            "case_id": case.case_id,
            "decision": "ALLOW" if allowed else "DENY",
            "decision_code": code,
            "stage": stage,
            "matched_expected": matched,
        },
    )
    return result


def _fixture_hash(cases: tuple[TokenCase, ...]) -> str:
    contract = [
        {
            "case_id": case.case_id,
            "expected_allowed": case.expected_allowed,
            "expected_code": case.expected_code,
            "note": case.note,
            "claims": {
                **{
                    name: value
                    for name, value in case.token.claims.items()
                    if name not in {"iat", "exp"}
                },
                "lifetime_seconds": case.token.claims["exp"] - case.token.claims["iat"],
            },
        }
        for case in cases
    ]
    payload = json.dumps(contract, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
