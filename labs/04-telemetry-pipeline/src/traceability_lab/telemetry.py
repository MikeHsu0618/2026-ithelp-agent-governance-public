from __future__ import annotations

import json
import logging
from typing import Any

from opentelemetry import propagate
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
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

        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
            export_interval_millis=60_000,
        )
        self.meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        self.meter = self.meter_provider.get_meter("ithelp.day22", "0.3.0")
        self.action_counter = self.meter.create_counter(
            "ithelp_agent_actions",
            description="Synthetic governed Agent actions emitted by the iT Help Lab.",
            unit="{action}",
        )

    def extract(self, headers: dict[str, str]) -> Any:
        return propagate.extract(headers)

    def inject(self, headers: dict[str, str]) -> None:
        propagate.inject(headers)

    def event(
        self,
        payload: dict[str, Any],
        *,
        attributes: dict[str, str] | None = None,
    ) -> None:
        log_attributes = {"action_id": payload.get("action_id", "missing")}
        if attributes:
            log_attributes.update(attributes)
        self.logger.info(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            extra=log_attributes,
        )

    def record_action(self, attributes: dict[str, str]) -> None:
        self.action_counter.add(1, attributes=attributes)

    def shutdown(self) -> None:
        self.trace_provider.force_flush()
        self.logger_provider.force_flush()
        self.meter_provider.force_flush()
        self.trace_provider.shutdown()
        self.logger_provider.shutdown()
        self.meter_provider.shutdown()
        self.logger.removeHandler(self.handler)
