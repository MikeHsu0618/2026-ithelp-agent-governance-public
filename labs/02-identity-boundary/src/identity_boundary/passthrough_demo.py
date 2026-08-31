"""Reproducible Day 10 token-passthrough and attribution cases."""

import hashlib
import json
import platform
import secrets
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from identity_boundary.artifacts import ArtifactStore
from identity_boundary.issuer import IssuedToken, LocalIssuer
from identity_boundary.passthrough import GovernedResource, credential_fingerprint
from identity_boundary.validator import TokenPolicy, TokenValidator

ISSUER = "https://issuer.lab.example/identity-boundary"
ENTRY_RESOURCE = "https://agent.lab.example/mcp"
TOOL_RESOURCE = "https://observability.lab.example/mcp"
USER_CLIENT = "sre-console"
RUNTIME_CLIENT = "sre-investigator-runtime"


@dataclass(frozen=True, slots=True)
class PassthroughCase:
    case_id: str
    token: str
    credential_label: str
    resource: GovernedResource
    delegation_context: dict[str, Any] | None
    expected_decision: str
    expected_code: str
    expected_attribution: str
    note: str


@dataclass(frozen=True, slots=True)
class PassthroughCaseResult:
    case_id: str
    expected_decision: str
    decision: str
    expected_code: str
    code: str
    expected_attribution: str
    attribution: str
    stage: str
    matched: bool


@dataclass(frozen=True, slots=True)
class PassthroughDemoSummary:
    run_id: str
    run_dir: Path
    matched: int
    total: int
    results: tuple[PassthroughCaseResult, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "matched": self.matched,
            "total": self.total,
            "results": [asdict(result) for result in self.results],
        }


def run_passthrough_demo(artifact_root: Path) -> PassthroughDemoSummary:
    """Run seven cases without persisting compact tokens or private key material."""

    now = datetime.now(UTC).replace(microsecond=0)
    run_id = f"day10-{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    store = ArtifactStore(artifact_root, run_id)
    issuer = LocalIssuer(issuer=ISSUER, key_id="day10-ephemeral")
    user_token, downstream_token = _issue_tokens(issuer, now)
    contexts = _build_contexts(now, user_token, downstream_token)
    cases = _build_cases(issuer, user_token, downstream_token, contexts)

    store.write_json("jwks.json", issuer.jwks())
    store.write_json("tokens/issuer-input/user-access.json", user_token.claims)
    store.write_json("tokens/issuer-input/downstream-access.json", downstream_token.claims)
    store.write_json("contexts/audience-bound-downstream.json", contexts["valid"])
    store.write_json("contexts/mismatched-fingerprint.json", contexts["mismatched"])
    store.write_json(
        "token-fingerprints.json",
        {
            "user_access_token": credential_fingerprint(user_token.encoded),
            "downstream_access_token": credential_fingerprint(downstream_token.encoded),
            "raw_credentials_persisted": False,
        },
    )

    results = tuple(_run_case(case, store, now) for case in cases)
    matched = sum(result.matched for result in results)
    summary = PassthroughDemoSummary(run_id, store.run_dir, matched, len(results), results)
    store.write_json("summary.json", summary.to_json_dict())
    store.write_json(
        "manifest.json",
        {
            "lab": "02-identity-boundary",
            "slice": "day-10-token-passthrough",
            "run_id": run_id,
            "generated_at": _isoformat(now),
            "fixture_hash": _fixture_hash(cases, user_token, downstream_token),
            "python_version": platform.python_version(),
            "pyjwt_version": version("PyJWT"),
            "jsonschema_version": version("jsonschema"),
            "matched": matched,
            "total": len(results),
            "raw_credentials_persisted": False,
            "private_key_persisted": False,
            "same_user_token_reused_across_hops": True,
            "synthetic_identities_only": True,
        },
    )
    return summary


def _issue_tokens(issuer: LocalIssuer, now: datetime) -> tuple[IssuedToken, IssuedToken]:
    user_token = issuer.issue_access_token(
        subject="user/sre-oncaller",
        audience=ENTRY_RESOURCE,
        client_id=USER_CLIENT,
        scopes=("agent.delegate", "observability.query"),
        additional_claims={"team": "platform"},
        issued_at=now,
    )
    downstream_token = issuer.issue_access_token(
        subject=f"client/{RUNTIME_CLIENT}",
        audience=TOOL_RESOURCE,
        client_id=RUNTIME_CLIENT,
        scopes=("observability.query",),
        additional_claims={},
        issued_at=now,
    )
    return user_token, downstream_token


def _build_cases(
    issuer: LocalIssuer,
    user_token: IssuedToken,
    downstream_token: IssuedToken,
    contexts: dict[str, dict[str, Any]],
) -> tuple[PassthroughCase, ...]:
    entry = _resource(
        issuer,
        resource_id=ENTRY_RESOURCE,
        accepted_audience=ENTRY_RESOURCE,
        client_id=USER_CLIENT,
        scope="agent.delegate",
        hop_kind="ENTRY",
    )
    strict_tool = _resource(
        issuer,
        resource_id=TOOL_RESOURCE,
        accepted_audience=TOOL_RESOURCE,
        client_id=RUNTIME_CLIENT,
        scope="observability.query",
        hop_kind="DOWNSTREAM",
        require_context=True,
    )
    shared_audience_tool = _resource(
        issuer,
        resource_id=TOOL_RESOURCE,
        accepted_audience=ENTRY_RESOURCE,
        client_id=USER_CLIENT,
        scope="observability.query",
        hop_kind="DOWNSTREAM",
    )
    return (
        PassthroughCase(
            "user_to_entry_resource",
            user_token.encoded,
            "user_access_token",
            entry,
            None,
            "ALLOW",
            "ALLOW",
            "TOKEN_SUBJECT_AT_ENTRY",
            "the Human token is valid at the resource it was issued for",
        ),
        PassthroughCase(
            "passthrough_to_tool_strict",
            user_token.encoded,
            "user_access_token",
            strict_tool,
            None,
            "DENY",
            "AUDIENCE_MISMATCH",
            "NOT_EVALUATED",
            "the unchanged Human token is not valid at the downstream MCP resource",
        ),
        PassthroughCase(
            "passthrough_shared_audience",
            user_token.encoded,
            "user_access_token",
            shared_audience_tool,
            None,
            "ALLOW",
            "ALLOW",
            "COLLAPSED_TO_TOKEN_SUBJECT",
            "sharing the entry audience makes the hop pass but leaves only "
            "user/sre-oncaller in audit",
        ),
        PassthroughCase(
            "audience_bound_downstream",
            downstream_token.encoded,
            "downstream_access_token",
            strict_tool,
            contexts["valid"],
            "ALLOW",
            "ALLOW",
            "FULL_CHAIN",
            "a distinct downstream credential is bound to the complete delegation context",
        ),
        PassthroughCase(
            "downstream_token_replay_entry",
            downstream_token.encoded,
            "downstream_access_token",
            entry,
            None,
            "DENY",
            "AUDIENCE_MISMATCH",
            "NOT_EVALUATED",
            "the downstream credential cannot be replayed at the entry resource",
        ),
        PassthroughCase(
            "missing_delegation_context",
            downstream_token.encoded,
            "downstream_access_token",
            strict_tool,
            None,
            "DENY",
            "DELEGATION_CONTEXT_REQUIRED",
            "NOT_EVALUATED",
            "a correct workload token alone cannot reconstruct who delegated the action",
        ),
        PassthroughCase(
            "mismatched_delegation_context",
            downstream_token.encoded,
            "downstream_access_token",
            strict_tool,
            contexts["mismatched"],
            "DENY",
            "DELEGATION_CONTEXT_MISMATCH",
            "NOT_EVALUATED",
            "a valid context must be bound to the exact credential and target",
        ),
    )


def _resource(
    issuer: LocalIssuer,
    *,
    resource_id: str,
    accepted_audience: str,
    client_id: str,
    scope: str,
    hop_kind: str,
    require_context: bool = False,
) -> GovernedResource:
    validator = TokenValidator(
        jwks=issuer.jwks(),
        policy=TokenPolicy(
            issuer=ISSUER,
            audience=accepted_audience,
            client_id=client_id,
            required_scopes=frozenset({scope}),
            required_claims=frozenset(),
        ),
    )
    return GovernedResource(
        resource_id=resource_id,
        action="query_logs" if hop_kind == "DOWNSTREAM" else "delegate_task",
        validator=validator,
        hop_kind=hop_kind,
        require_delegation_context=require_context,
    )


def _build_contexts(
    now: datetime,
    user_token: IssuedToken,
    downstream_token: IssuedToken,
) -> dict[str, dict[str, Any]]:
    context = {
        "schema_version": "delegation-context/v0.1",
        "event_id": "evt-day10-audience-bound-downstream",
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
        "timestamp": _isoformat(now),
        "flow_kind": "HUMAN_DELEGATED",
        "actor_chain": {
            "human": _identity(
                "user/sre-oncaller",
                "verified_upstream_access_token.sub",
                "VERIFIED",
            ),
            "service": _identity(
                "client/sre-console", "verified_upstream_access_token.client_id", "CONTEXT_ONLY"
            ),
            "agents": [
                _agent(0, "agent/sre-copilot", "v1", "DELEGATING"),
                _agent(1, "agent/sre-investigator", "v1", "EXECUTING"),
            ],
            "workload": _identity(
                "k8s://lab/identity-boundary/sa/sre-agent",
                "kubernetes.serviceaccount",
                "ASSERTED",
            ),
        },
        "credential": {
            "type": "OAUTH_ACCESS_TOKEN",
            "issuer": str(downstream_token.claims["iss"]),
            "subject": str(downstream_token.claims["sub"]),
            "client_id": str(downstream_token.claims["client_id"]),
            "audiences": [str(downstream_token.claims["aud"])],
            "fingerprint": credential_fingerprint(downstream_token.encoded),
        },
        "target": {"resource": TOOL_RESOURCE, "action": "query_logs"},
    }
    mismatched = deepcopy(context)
    mismatched["event_id"] = "evt-day10-mismatched-context"
    mismatched["credential"]["fingerprint"] = credential_fingerprint(user_token.encoded)
    return {"valid": context, "mismatched": mismatched}


def _run_case(
    case: PassthroughCase,
    store: ArtifactStore,
    now: datetime,
) -> PassthroughCaseResult:
    decision = case.resource.authorize(case.token, case.delegation_context)
    matched = (
        decision.decision == case.expected_decision
        and decision.code == case.expected_code
        and decision.attribution == case.expected_attribution
    )
    result = PassthroughCaseResult(
        case.case_id,
        case.expected_decision,
        decision.decision,
        case.expected_code,
        decision.code,
        case.expected_attribution,
        decision.attribution,
        decision.stage,
        matched,
    )
    store.write_json(
        f"expected/{case.case_id}.json",
        {
            "case_id": case.case_id,
            "credential_label": case.credential_label,
            "expected_decision": case.expected_decision,
            "expected_code": case.expected_code,
            "expected_attribution": case.expected_attribution,
            "note": case.note,
        },
    )
    store.append_jsonl(
        "events.jsonl",
        {
            "event_type": "resource.authorization",
            "timestamp": _isoformat(now),
            "case_id": case.case_id,
            "decision": decision.decision,
            "code": decision.code,
            "stage": decision.stage,
            "attribution": decision.attribution,
            "matched_expected": matched,
            **decision.audit,
        },
    )
    return result


def _identity(principal: str, source: str, level: str) -> dict[str, str]:
    return {
        "state": "PRESENT",
        "principal": principal,
        "evidence_source": source,
        "evidence_level": level,
    }


def _agent(sequence: int, principal: str, agent_version: str, role: str) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "principal": principal,
        "version": agent_version,
        "role": role,
        "evidence_source": "controlled_deployment_metadata",
        "evidence_level": "ASSERTED",
    }


def _fixture_hash(
    cases: tuple[PassthroughCase, ...],
    user_token: IssuedToken,
    downstream_token: IssuedToken,
) -> str:
    payload = {
        "tokens": {
            "user_access_token": _stable_claims(user_token.claims),
            "downstream_access_token": _stable_claims(downstream_token.claims),
        },
        "cases": [
            {
                "case_id": case.case_id,
                "credential_label": case.credential_label,
                "resource": case.resource.resource_id,
                "action": case.resource.action,
                "accepted_audience": case.resource.validator.policy.audience,
                "accepted_client": case.resource.validator.policy.client_id,
                "required_scopes": sorted(case.resource.validator.policy.required_scopes),
                "delegation_context": _stable_context(case.delegation_context),
                "expected_decision": case.expected_decision,
                "expected_code": case.expected_code,
                "expected_attribution": case.expected_attribution,
            }
            for case in cases
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _stable_claims(claims: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in claims.items() if key not in {"iat", "exp"}}


def _stable_context(context: dict[str, Any] | None) -> dict[str, Any] | None:
    if context is None:
        return None
    stable = deepcopy(context)
    stable.pop("timestamp", None)
    stable["credential"]["fingerprint"] = "sha256:<per-run>"
    return stable


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
