import logging

from traceability_lab import telemetry
from traceability_lab.telemetry import Telemetry


class FakeProvider:
    def __init__(self, resource):
        self.resource = resource
        self.processors = []
        self.flushed = False
        self.stopped = False

    def add_span_processor(self, processor):
        self.processors.append(processor)

    def add_log_record_processor(self, processor):
        self.processors.append(processor)

    def get_tracer(self, name, version):
        return (name, version)

    def force_flush(self):
        self.flushed = True

    def shutdown(self):
        self.stopped = True


class FakeLoggingHandler(logging.Handler):
    def __init__(self, *, level, logger_provider):
        super().__init__(level)
        self.logger_provider = logger_provider
        self.records = []

    def emit(self, record):
        self.records.append(record)


def test_telemetry_configures_otlp_and_flushes_both_providers(monkeypatch) -> None:
    monkeypatch.setattr(telemetry.Resource, "create", lambda attributes: attributes)
    monkeypatch.setattr(telemetry, "TracerProvider", FakeProvider)
    monkeypatch.setattr(telemetry, "LoggerProvider", FakeProvider)
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", lambda *, endpoint: endpoint)
    monkeypatch.setattr(telemetry, "OTLPLogExporter", lambda *, endpoint: endpoint)
    monkeypatch.setattr(telemetry, "SimpleSpanProcessor", lambda exporter: ("trace", exporter))
    monkeypatch.setattr(telemetry, "SimpleLogRecordProcessor", lambda exporter: ("log", exporter))
    monkeypatch.setattr(telemetry, "LoggingHandler", FakeLoggingHandler)
    monkeypatch.setattr(telemetry.propagate, "extract", lambda headers: ("parent", headers))
    monkeypatch.setattr(
        telemetry.propagate,
        "inject",
        lambda headers: headers.update({"traceparent": "synthetic"}),
    )

    client = Telemetry("agent-runtime", "http://alloy:4318")

    assert client.trace_provider.resource["service.name"] == "agent-runtime"
    assert client.trace_provider.processors == [("trace", "http://alloy:4318/v1/traces")]
    assert client.logger_provider.processors == [("log", "http://alloy:4318/v1/logs")]
    assert client.extract({"traceparent": "incoming"}) == (
        "parent",
        {"traceparent": "incoming"},
    )
    headers = {}
    client.inject(headers)
    assert headers == {"traceparent": "synthetic"}

    client.event({"action_id": "act-test", "event": "runtime.accepted"})
    assert client.handler.records[0].action_id == "act-test"
    assert '"event": "runtime.accepted"' in client.handler.records[0].getMessage()

    client.shutdown()
    assert client.trace_provider.flushed is True
    assert client.trace_provider.stopped is True
    assert client.logger_provider.flushed is True
    assert client.logger_provider.stopped is True
    assert client.handler not in client.logger.handlers
