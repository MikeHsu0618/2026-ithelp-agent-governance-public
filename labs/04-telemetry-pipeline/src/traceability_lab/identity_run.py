from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from traceability_lab.artifacts import ArtifactStore
from traceability_lab.identity import (
    RawIdentityClaims,
    build_identity_projections,
    verify_fixture_claims,
)
from traceability_lab.runner import utc_now, validate_otlp_endpoint
from traceability_lab.telemetry import Telemetry

SYNTHETIC_EMAIL = "sre-oncaller@identity.invalid"
SYNTHETIC_TOKEN = "day22-raw-token-must-not-survive"
SYNTHETIC_ISSUER = "https://identity.invalid/pool/day22"
SYNTHETIC_AUDIENCE = "ithelp-agent-lab"
LAB_PSEUDONYM_KEY = b"day22-public-fixture-key-not-for-production"


@dataclass(frozen=True, slots=True)
class IdentityRunSummary:
    run_id: str
    action_id: str
    trace_id: str
    principal_ref: str
    team: str
    artifact_dir: str

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_identity_projection(*, artifact_root: Path, otlp_endpoint: str) -> IdentityRunSummary:
    """Send deliberately contaminated signals through Alloy and save only safe evidence."""

    endpoint = validate_otlp_endpoint(otlp_endpoint)
    run_id = f"day22-{uuid.uuid4().hex[:12]}"
    action_id = f"act-{run_id}"
    store = ArtifactStore(artifact_root, run_id)
    claims = RawIdentityClaims(
        issuer=SYNTHETIC_ISSUER,
        audience=SYNTHETIC_AUDIENCE,
        subject="synthetic-sre-oncaller",
        email=SYNTHETIC_EMAIL,
        team="platform-sre",
        roles=("incident-responder", "reader"),
        tenant="ithelp-lab",
        raw_token=SYNTHETIC_TOKEN,
    )
    principal = verify_fixture_claims(
        claims,
        expected_issuer=SYNTHETIC_ISSUER,
        expected_audience=SYNTHETIC_AUDIENCE,
        pseudonym_key=LAB_PSEUDONYM_KEY,
    )
    projections = build_identity_projections(
        principal,
        action_id=action_id,
        route="agent-runtime",
        outcome="allowed",
    )
    contaminated = {
        "auth.token": SYNTHETIC_TOKEN,
        "principal.ref": principal.principal_ref,
        "user.email": SYNTHETIC_EMAIL,
    }

    telemetry = Telemetry("identity-projection-lab", endpoint)
    try:
        with telemetry.tracer.start_as_current_span(
            "identity.projection",
            attributes={**projections.traces, **contaminated},
        ) as span:
            trace_id = f"{span.get_span_context().trace_id:032x}"
            telemetry.event(
                {
                    "action_id": action_id,
                    "event": "identity.projection.accepted",
                    "result": "SAFE_PROJECTION_EXPORTED",
                },
                attributes={**projections.logs, **contaminated},
            )
            telemetry.record_action(
                {
                    **projections.metrics,
                    **contaminated,
                    "session.id": "session-day22-synthetic",
                }
            )
    finally:
        telemetry.shutdown()

    summary = IdentityRunSummary(
        run_id=run_id,
        action_id=action_id,
        trace_id=trace_id,
        principal_ref=principal.principal_ref,
        team=principal.team,
        artifact_dir=str(store.run_dir),
    )
    store.write_json(
        "identity-projection.json",
        {
            **summary.to_json_dict(),
            "occurred_at": utc_now(),
            "raw_stage": "NOT_EXPORTED",
            "collector_forbidden_keys": ["auth.token", "user.email"],
            "metric_labels": sorted(projections.metrics),
            "trace_attributes": sorted(projections.traces),
            "log_attributes": sorted(projections.logs),
        },
    )
    store.write_json("audit-event.json", projections.audit)
    return summary
