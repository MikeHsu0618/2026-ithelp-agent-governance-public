from __future__ import annotations

import json
import logging
from typing import Any

from opentelemetry import propagate
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor


class Telemetry:
    """Small OTLP wrapper shared by the synthetic client, Runtime, and MCP adapter."""

    def __init__(self, service_name: str, endpoint: str) -> None:
        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": "0.2.0",
                "deployment.environment.name": "lab",
            }
        )
        self.trace_provider = TracerProvider(resource=resource)
        self.trace_provider.add_span_processor(
            SimpleSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )
        self.tracer = self.trace_provider.get_tracer("ithelp.day21", "0.2.0")

        self.logger_provider = LoggerProvider(resource=resource)
        self.logger_provider.add_log_record_processor(
            SimpleLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
        )
        self.handler = LoggingHandler(level=logging.INFO, logger_provider=self.logger_provider)
        self.logger = logging.getLogger(f"ithelp.day21.{service_name}")
        self.logger.handlers = [self.handler]
        self.logger.propagate = False
        self.logger.setLevel(logging.INFO)

    def extract(self, headers: dict[str, str]) -> Any:
        return propagate.extract(headers)

    def inject(self, headers: dict[str, str]) -> None:
        propagate.inject(headers)

    def event(self, payload: dict[str, Any]) -> None:
        self.logger.info(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            extra={"action_id": payload.get("action_id", "missing")},
        )

    def shutdown(self) -> None:
        self.trace_provider.force_flush()
        self.logger_provider.force_flush()
        self.trace_provider.shutdown()
        self.logger_provider.shutdown()
        self.logger.removeHandler(self.handler)
