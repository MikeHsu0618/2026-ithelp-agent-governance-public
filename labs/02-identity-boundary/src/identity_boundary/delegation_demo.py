"""Reproducible Day 9 cases for Delegation Context v0.1."""

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
from identity_boundary.delegation import (
    DelegationContextRejected,
    load_delegation_schema,
    validate_delegation_context,
)


@dataclass(frozen=True, slots=True)
class DelegationCase:
    case_id: str
    context: dict[str, Any]
    expected_accepted: bool
    expected_code: str
    note: str


@dataclass(frozen=True, slots=True)
class DelegationCaseResult:
    case_id: str
    expected_accepted: bool
    accepted: bool
    expected_code: str
    code: str
    stage: str
    matched: bool


@dataclass(frozen=True, slots=True)
class DelegationDemoSummary:
    run_id: str
    run_dir: Path
    matched: int
    total: int
    results: tuple[DelegationCaseResult, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "matched": self.matched,
            "total": self.total,
            "results": [asdict(result) for result in self.results],
        }


def run_delegation_demo(artifact_root: Path) -> DelegationDemoSummary:
    """Validate seven positive and negative contexts and persist safe evidence."""

    now = datetime.now(UTC).replace(microsecond=0)
    run_id = f"day09-{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    store = ArtifactStore(artifact_root, run_id)
    cases = _build_cases(now)
    store.write_json("schemas/delegation-context-v0.1.schema.json", load_delegation_schema())

    results = tuple(_run_case(case, store, now) for case in cases)
    matched = sum(result.matched for result in results)
    summary = DelegationDemoSummary(run_id, store.run_dir, matched, len(results), results)
    store.write_json("summary.json", summary.to_json_dict())
    store.write_json(
        "manifest.json",
        {
            "lab": "02-identity-boundary",
            "slice": "day-09-delegation-context",
            "run_id": run_id,
            "generated_at": _isoformat(now),
            "fixture_hash": _fixture_hash(cases),
            "python_version": platform.python_version(),
            "jsonschema_version": version("jsonschema"),
            "matched": matched,
            "total": len(results),
            "raw_credentials_persisted": False,
            "synthetic_identities_only": True,
        },
    )
    return summary


def _build_cases(now: datetime) -> tuple[DelegationCase, ...]:
    human_delegated = _human_delegated_context(now)

    scheduled_service = deepcopy(human_delegated)
    scheduled_service.update(
        event_id="evt-day09-scheduled-service",
        flow_kind="SERVICE_AUTONOMOUS",
    )
    scheduled_service["actor_chain"]["human"] = {
        "state": "NOT_APPLICABLE",
        "reason": "scheduled execution has no interactive human",
    }
    scheduled_service["actor_chain"]["service"] = _identity(
        "client/sre-scheduler", "verified_client_credentials.client_id", "VERIFIED"
    )
    scheduled_service["actor_chain"]["agents"] = [
        _agent(0, "agent/sre-scheduler", "v1", "EXECUTING")
    ]
    scheduled_service["credential"].update(
        subject="client/sre-scheduler",
        client_id="sre-scheduler",
        fingerprint=_fingerprint("scheduled-service"),
    )

    a2a_unknown = deepcopy(human_delegated)
    a2a_unknown.update(event_id="evt-day09-a2a-unknown", flow_kind="AGENT_TO_AGENT")
    a2a_unknown["actor_chain"]["human"] = {
        "state": "UNKNOWN",
        "reason": "upstream agent did not propagate human identity",
    }
    a2a_unknown["actor_chain"]["service"] = _identity(
        "client/sre-copilot", "verified_access_token.client_id", "CONTEXT_ONLY"
    )
    a2a_unknown["actor_chain"]["workload"] = {
        "state": "UNKNOWN",
        "reason": "upstream runtime did not propagate workload identity",
    }
    a2a_unknown["credential"].update(
        subject="agent/sre-copilot",
        client_id="sre-copilot",
        fingerprint=_fingerprint("a2a-unknown"),
    )

    missing_workload = deepcopy(human_delegated)
    missing_workload["event_id"] = "evt-day09-missing-workload"
    del missing_workload["actor_chain"]["workload"]

    human_null = deepcopy(human_delegated)
    human_null["event_id"] = "evt-day09-human-null"
    human_null["actor_chain"]["human"] = None

    duplicate_sequence = deepcopy(human_delegated)
    duplicate_sequence["event_id"] = "evt-day09-duplicate-sequence"
    duplicate_sequence["actor_chain"]["agents"][1]["sequence"] = 0

    actor_only = {
        "schema_version": "delegation-context/v0.1",
        "event_id": "evt-day09-actor-only",
        "actor": "user/sre-oncaller",
    }

    return (
        DelegationCase(
            "human_delegated",
            human_delegated,
            True,
            "ACCEPT",
            "human, service, two agents, workload, credential, and target remain queryable",
        ),
        DelegationCase(
            "scheduled_service",
            scheduled_service,
            True,
            "ACCEPT",
            "a scheduled run records human as NOT_APPLICABLE rather than null",
        ),
        DelegationCase(
            "a2a_unknown_workload",
            a2a_unknown,
            True,
            "ACCEPT",
            "missing upstream evidence remains UNKNOWN and is never inferred from a name",
        ),
        DelegationCase(
            "missing_workload_slot",
            missing_workload,
            False,
            "REQUIRED_FIELD_MISSING",
            "all identity slots must remain present even when their value is unknown",
        ),
        DelegationCase(
            "human_null",
            human_null,
            False,
            "NULL_NOT_ALLOWED",
            "null cannot distinguish unknown from not applicable",
        ),
        DelegationCase(
            "duplicate_agent_sequence",
            duplicate_sequence,
            False,
            "AGENT_SEQUENCE_INVALID",
            "an audit chain must preserve deterministic delegation order",
        ),
        DelegationCase(
            "actor_only",
            actor_only,
            False,
            "REQUIRED_FIELD_MISSING",
            "one actor string destroys delegation and execution attribution",
        ),
    )


def _human_delegated_context(now: datetime) -> dict[str, Any]:
    return {
        "schema_version": "delegation-context/v0.1",
        "event_id": "evt-day09-human-delegated",
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
        "timestamp": _isoformat(now),
        "flow_kind": "HUMAN_DELEGATED",
        "actor_chain": {
            "human": _identity("user/sre-oncaller", "verified_access_token.sub", "VERIFIED"),
            "service": _identity(
                "client/sre-console", "verified_access_token.client_id", "CONTEXT_ONLY"
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
            "issuer": "https://issuer.lab.example/identity-boundary",
            "subject": "user/sre-oncaller",
            "client_id": "sre-console",
            "audiences": ["mcp://lab/observability/query"],
            "fingerprint": _fingerprint("human-delegated"),
        },
        "target": {
            "resource": "mcp://lab/observability/query",
            "action": "query_logs",
        },
    }


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


def _run_case(
    case: DelegationCase,
    store: ArtifactStore,
    now: datetime,
) -> DelegationCaseResult:
    try:
        validate_delegation_context(case.context)
        accepted, code, stage = True, "ACCEPT", "complete"
    except DelegationContextRejected as error:
        accepted, code, stage = False, error.code, error.stage

    matched = accepted == case.expected_accepted and code == case.expected_code
    result = DelegationCaseResult(
        case.case_id,
        case.expected_accepted,
        accepted,
        case.expected_code,
        code,
        stage,
        matched,
    )
    store.write_json(f"contexts/{case.case_id}.json", case.context)
    store.write_json(
        f"expected/{case.case_id}.json",
        {
            "case_id": case.case_id,
            "expected_accepted": case.expected_accepted,
            "expected_code": case.expected_code,
            "note": case.note,
        },
    )
    store.append_jsonl(
        "events.jsonl",
        {
            "event_type": "delegation_context.validation",
            "timestamp": _isoformat(now),
            "case_id": case.case_id,
            "decision": "ACCEPT" if accepted else "REJECT",
            "decision_code": code,
            "stage": stage,
            "matched_expected": matched,
            **_query_fields(case.context),
        },
    )
    return result


def _query_fields(context: dict[str, Any]) -> dict[str, Any]:
    chain = context.get("actor_chain")
    if not isinstance(chain, dict):
        return {
            "human_state": "MISSING",
            "service_state": "MISSING",
            "agent_chain": [],
            "workload_state": "MISSING",
        }

    agents = chain.get("agents") if isinstance(chain.get("agents"), list) else []
    return {
        "human_state": _slot_state(chain.get("human")),
        "service_state": _slot_state(chain.get("service")),
        "agent_chain": [
            f"{agent.get('principal', 'UNKNOWN')}@{agent.get('version', 'UNKNOWN')}"
            for agent in agents
            if isinstance(agent, dict)
        ],
        "workload_state": _slot_state(chain.get("workload")),
    }


def _slot_state(slot: Any) -> str:
    return str(slot.get("state", "MISSING")) if isinstance(slot, dict) else "MISSING"


def _fingerprint(label: str) -> str:
    digest = hashlib.sha256(f"synthetic-day09:{label}".encode()).hexdigest()
    return f"sha256:{digest}"


def _fixture_hash(cases: tuple[DelegationCase, ...]) -> str:
    payload = [
        {
            "case_id": case.case_id,
            "context": {key: value for key, value in case.context.items() if key != "timestamp"},
            "expected_accepted": case.expected_accepted,
            "expected_code": case.expected_code,
        }
        for case in cases
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
