from __future__ import annotations

import json
from pathlib import Path

from traceability_lab import identity_run


class FakeSpanContext:
    trace_id = int("b" * 32, 16)


class FakeSpan:
    def __init__(self, attributes):
        self.attributes = attributes

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get_span_context(self):
        return FakeSpanContext()


class FakeTracer:
    def __init__(self):
        self.spans = []

    def start_as_current_span(self, name, attributes):
        assert name == "identity.projection"
        span = FakeSpan(attributes)
        self.spans.append(span)
        return span


class FakeTelemetry:
    instances = []

    def __init__(self, service_name, endpoint):
        self.service_name = service_name
        self.endpoint = endpoint
        self.tracer = FakeTracer()
        self.events = []
        self.metrics = []
        self.closed = False
        self.instances.append(self)

    def event(self, payload, *, attributes=None):
        self.events.append((payload, attributes))

    def record_action(self, attributes):
        self.metrics.append(attributes)

    def shutdown(self):
        self.closed = True


def test_identity_projection_emits_contaminated_signals_but_saves_only_safe_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    FakeTelemetry.instances.clear()
    monkeypatch.setattr(identity_run, "Telemetry", FakeTelemetry)
    monkeypatch.setattr(identity_run.uuid, "uuid4", lambda: type("U", (), {"hex": "1" * 32})())

    summary = identity_run.run_identity_projection(
        artifact_root=tmp_path,
        otlp_endpoint="http://127.0.0.1:14318",
    )

    telemetry = FakeTelemetry.instances[0]
    span_attributes = telemetry.tracer.spans[0].attributes
    assert span_attributes["user.email"] == identity_run.SYNTHETIC_EMAIL
    assert span_attributes["auth.token"] == identity_run.SYNTHETIC_TOKEN
    assert telemetry.events[0][1]["principal.ref"] == summary.principal_ref
    assert telemetry.metrics[0]["principal.ref"] == summary.principal_ref
    assert telemetry.metrics[0]["session.id"] == "session-day22-synthetic"
    assert telemetry.closed is True

    artifact_dir = Path(summary.artifact_dir)
    report = json.loads((artifact_dir / "identity-projection.json").read_text())
    audit = json.loads((artifact_dir / "audit-event.json").read_text())
    serialized = json.dumps({"report": report, "audit": audit}, sort_keys=True)
    assert report["principal_ref"] == summary.principal_ref
    assert identity_run.SYNTHETIC_EMAIL not in serialized
    assert identity_run.SYNTHETIC_TOKEN not in serialized
    assert audit["actor.principal_ref"] == summary.principal_ref
