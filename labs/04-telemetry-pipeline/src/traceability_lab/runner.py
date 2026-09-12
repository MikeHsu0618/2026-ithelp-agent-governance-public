from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from traceability_lab.artifacts import ArtifactStore
from traceability_lab.contract import (
    build_action_context,
    build_application_record,
    build_governance_event,
)


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    action_id: str
    trace_id: str
    result: str
    export_mode: str
    artifact_dir: str

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def validate_otlp_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint.rstrip("/"))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("OTLP endpoint must use http on localhost or 127.0.0.1")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("OTLP endpoint must not include credentials, query, or fragment")
    return endpoint.rstrip("/")


def run_action(*, artifact_root: Path, otlp_endpoint: str | None) -> RunSummary:
    run_id = f"day20-{uuid.uuid4().hex[:12]}"
    action_id = f"act-{run_id}"
    store = ArtifactStore(artifact_root, run_id)
    resource = Resource.create(
        {
            "service.name": "ithelp-traceability-lab",
            "service.version": "0.1.0",
            "deployment.environment.name": "lab",
        }
    )
    trace_provider = TracerProvider(resource=resource)
    logger_provider: LoggerProvider | None = None
    event_logger: logging.Logger | None = None
    handler: LoggingHandler | None = None
    endpoint = validate_otlp_endpoint(otlp_endpoint) if otlp_endpoint else None
    if endpoint:
        trace_provider.add_span_processor(
            SimpleSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            SimpleLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
        )
        handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
        event_logger = logging.getLogger("ithelp.governance.event")
        event_logger.handlers = [handler]
        event_logger.propagate = False
        event_logger.setLevel(logging.INFO)

    tracer = trace_provider.get_tracer("ithelp.traceability", "0.1.0")
    span_records: list[dict[str, Any]] = []
    occurred_at = utc_now()
    with tracer.start_as_current_span(
        "invoke_agent sre-investigation-agent",
        attributes={
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": "sre-investigation-agent",
            "gen_ai.agent.version": "day20-fixture",
            "ithelp.governance.action_id": action_id,
        },
    ) as root_span:
        root_context = root_span.get_span_context()
        trace_id = f"{root_context.trace_id:032x}"
        root_span_id = f"{root_context.span_id:016x}"
        span_records.append(
            {
                "name": "invoke_agent sre-investigation-agent",
                "span_id": root_span_id,
                "parent_span_id": None,
            }
        )
        with tracer.start_as_current_span(
            "execute_tool delete_demo_database",
            attributes={
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": "delete_demo_database",
                "gen_ai.tool.type": "function",
                "ithelp.governance.action_id": action_id,
                "ithelp.governance.policy.decision": "ALLOW",
                "ithelp.governance.policy.version": "v3",
                "ithelp.governance.resource": "demo/database",
            },
        ) as tool_span:
            tool_context = tool_span.get_span_context()
            tool_span_id = f"{tool_context.span_id:016x}"
            receipt = {
                "action_id": action_id,
                "status": "CANARY_TRIGGERED",
                "tool": "delete_demo_database",
                "resource": "demo/database",
                "side_effects": 0,
            }
            store.write_json("tool-receipt.json", receipt)
            span_records.append(
                {
                    "name": "execute_tool delete_demo_database",
                    "span_id": tool_span_id,
                    "parent_span_id": root_span_id,
                }
            )
            context = build_action_context(
                action_id=action_id,
                trace_id=trace_id,
                span_id=tool_span_id,
                occurred_at=occurred_at,
            )
            application = build_application_record(context)
            governance = build_governance_event(context)
            store.write_json("application-record.json", application)
            store.write_json("governance-event.json", governance)
            if event_logger:
                event_logger.info(
                    json.dumps(governance, ensure_ascii=False, sort_keys=True),
                    extra={
                        "event.name": "ithelp.governance.action.v0.1",
                        "action_id": action_id,
                        "policy_decision": "ALLOW",
                        "result_status": "CANARY_TRIGGERED",
                    },
                )

    trace_provider.force_flush()
    trace_provider.shutdown()
    if logger_provider:
        logger_provider.force_flush()
        logger_provider.shutdown()
    if handler and event_logger:
        event_logger.removeHandler(handler)

    trace_summary = {"trace_id": trace_id, "spans": span_records}
    store.write_json("operational-trace.json", trace_summary)
    summary = RunSummary(
        run_id=run_id,
        action_id=action_id,
        trace_id=trace_id,
        result="CANARY_TRIGGERED",
        export_mode="otlp-http" if endpoint else "local-only",
        artifact_dir=str(store.run_dir),
    )
    store.write_json(
        "manifest.json",
        {
            **summary.to_json_dict(),
            "occurred_at": occurred_at,
            "safe_effect": "NO_OP_CANARY",
        },
    )
    return summary
