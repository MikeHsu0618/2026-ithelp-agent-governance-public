from __future__ import annotations

import importlib
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

import incident_replay.backend as backend_module
from incident_replay.backend import fetch_json, query_modern_reference, validate_backend_url


def test_modern_reference_queries_trace_logs_and_gateway_metrics() -> None:
    requests: list[str] = []

    def fetch(url: str) -> dict[str, Any]:
        requests.append(url)
        if "/api/v2/traces/" in url:
            return {
                "trace": {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": "agentgateway"},
                                    }
                                ]
                            }
                        },
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": "agent-runtime"},
                                    }
                                ]
                            }
                        },
                    ]
                }
            }
        if "/loki/api/v1/query_range" in url:
            return {
                "data": {
                    "result": [{"values": [["1", '{"action_id":"act-modern-demo","event":"ok"}']]}]
                }
            }
        return {"data": {"result": [{"value": ["1", "12"]}]}}

    report = query_modern_reference(
        action_id="act-modern-demo",
        trace_id="b" * 32,
        fetch_json=fetch,
        attempts=1,
    )

    assert report["tempo"]["status"] == "OBSERVED"
    assert report["tempo"]["services"] == ["agent-runtime", "agentgateway"]
    assert report["loki"]["status"] == "OBSERVED"
    assert report["loki"]["matched_action"] is True
    assert report["prometheus"]["status"] == "OBSERVED"
    assert report["prometheus"]["scope"] == "AGGREGATE_ONLY"
    assert len(requests) == 3


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com:3100",
        "http://user:pass@127.0.0.1:3100",
        "file:///tmp/backend",
    ],
)
def test_backend_url_rejects_remote_credentials_and_non_http(url: str) -> None:
    with pytest.raises(ValueError):
        validate_backend_url(url)


def test_missing_modern_evidence_stays_unknown() -> None:
    report = query_modern_reference(
        action_id="act-missing-id",
        trace_id="c" * 32,
        fetch_json=lambda _url: {},
        attempts=1,
    )

    assert report["tempo"]["status"] == "UNKNOWN"
    assert report["loki"]["status"] == "UNKNOWN"
    assert report["prometheus"]["status"] == "UNKNOWN"


def test_modern_reference_waits_for_all_expected_trace_services() -> None:
    tempo_calls = 0
    sleeps: list[float] = []

    def fetch(url: str) -> dict[str, Any]:
        nonlocal tempo_calls
        if "/api/v2/traces/" in url:
            tempo_calls += 1
            services = ["agent-runtime"]
            if tempo_calls > 1:
                services.append("agentgateway")
            return {
                "trace": {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": service},
                                    }
                                ]
                            }
                        }
                        for service in services
                    ]
                }
            }
        if "/loki/api/v1/query_range" in url:
            return {"data": {"result": [{"values": [["1", '{"action_id":"act-modern-demo"}']]}]}}
        return {"data": {"result": [{"value": ["1", "12"]}]}}

    report = query_modern_reference(
        action_id="act-modern-demo",
        trace_id="d" * 32,
        expected_services=["agent-runtime", "agentgateway"],
        fetch_json=fetch,
        sleep=sleeps.append,
        attempts=3,
    )

    assert tempo_calls == 2
    assert sleeps == [1]
    assert report["tempo"]["services"] == ["agent-runtime", "agentgateway"]
    assert report["tempo"]["complete"] is True


def test_modern_reference_retries_temporarily_unavailable_backends() -> None:
    calls: dict[str, int] = {"tempo": 0, "loki": 0, "prometheus": 0}
    sleeps: list[float] = []

    def fetch(url: str) -> dict[str, Any]:
        backend = (
            "tempo"
            if "/api/v2/traces/" in url
            else "loki"
            if "/loki/api/v1/query_range" in url
            else "prometheus"
        )
        calls[backend] += 1
        if calls[backend] == 1:
            raise URLError("not ready")
        if backend == "tempo":
            return {
                "trace": {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": "agentgateway"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        if backend == "loki":
            return {"data": {"result": [{"values": [["1", '{"action_id":"act-modern-demo"}']]}]}}
        return {"data": {"result": [{"value": ["1", "12"]}]}}

    report = query_modern_reference(
        action_id="act-modern-demo",
        trace_id="e" * 32,
        expected_services=["agentgateway"],
        fetch_json=fetch,
        sleep=sleeps.append,
        attempts=2,
    )

    assert calls == {"tempo": 2, "loki": 2, "prometheus": 2}
    assert sleeps == [1]
    assert report["tempo"]["complete"] is True
    assert report["loki"]["matched_action"] is True
    assert report["prometheus"]["status"] == "OBSERVED"


def test_modern_reference_retains_evidence_observed_on_different_polls() -> None:
    calls: dict[str, int] = {"tempo": 0, "loki": 0, "prometheus": 0}

    def fetch(url: str) -> dict[str, Any]:
        backend = (
            "tempo"
            if "/api/v2/traces/" in url
            else "loki"
            if "/loki/api/v1/query_range" in url
            else "prometheus"
        )
        calls[backend] += 1
        if backend == "tempo" and calls[backend] == 1:
            return {
                "trace": {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": "agentgateway"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        if backend == "loki" and calls[backend] == 2:
            return {"data": {"result": [{"values": [["1", '{"action_id":"act-modern-demo"}']]}]}}
        if backend == "prometheus":
            value = "12" if calls[backend] == 1 else "0"
            return {"data": {"result": [{"value": ["1", value]}]}}
        return {}

    report = query_modern_reference(
        action_id="act-modern-demo",
        trace_id="f" * 32,
        expected_services=["agentgateway"],
        fetch_json=fetch,
        sleep=lambda _seconds: None,
        attempts=2,
    )

    assert report["tempo"]["complete"] is True
    assert report["loki"]["matched_action"] is True
    assert report["prometheus"]["sample_count"] == 12


def test_malformed_backend_payloads_stay_unknown() -> None:
    report = query_modern_reference(
        action_id="act-modern-demo",
        trace_id="f" * 32,
        fetch_json=lambda url: {"trace": None} if "traces" in url else {"data": None},
        sleep=lambda _seconds: None,
        attempts=1,
    )

    assert report["tempo"]["status"] == "UNKNOWN"
    assert report["loki"]["status"] == "UNKNOWN"
    assert report["prometheus"]["status"] == "UNKNOWN"


@pytest.mark.parametrize("metric", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_gateway_metric_is_not_evidence(metric: str) -> None:
    def fetch(url: str) -> dict[str, Any]:
        if "/api/v2/traces/" in url:
            return {"trace": {"resourceSpans": []}}
        if "/loki/api/v1/query_range" in url:
            return {"data": {"result": []}}
        return {"data": {"result": [{"value": ["1", metric]}]}}

    report = query_modern_reference(
        action_id="act-modern-demo",
        trace_id="f" * 32,
        fetch_json=fetch,
        sleep=lambda _seconds: None,
        attempts=1,
    )

    assert report["prometheus"]["sample_count"] is None
    assert report["prometheus"]["status"] == "UNKNOWN"


def test_loki_action_match_requires_exact_structured_field() -> None:
    def fetch(url: str) -> dict[str, Any]:
        if "/api/v2/traces/" in url:
            return {
                "trace": {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": "agentgateway"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        if "/loki/api/v1/query_range" in url:
            return {"data": {"result": [{"values": [["1", '{"action_id":"act-modern-extra"}']]}]}}
        return {"data": {"result": [{"value": ["1", "12"]}]}}

    report = query_modern_reference(
        action_id="act-modern-demo",
        trace_id="f" * 32,
        expected_services=["agentgateway"],
        fetch_json=fetch,
        sleep=lambda _seconds: None,
        attempts=1,
    )

    assert report["loki"]["matched_action"] is False
    assert report["loki"]["line_count"] == 0


def test_zero_gateway_metric_series_does_not_confirm_activity() -> None:
    def fetch(url: str) -> dict[str, Any]:
        if "/api/v2/traces/" in url:
            return {
                "trace": {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": "agentgateway"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        if "/loki/api/v1/query_range" in url:
            return {"data": {"result": [{"values": [["1", '{"action_id":"act-modern-demo"}']]}]}}
        return {"data": {"result": [{"value": ["1", "0"]}]}}

    report = query_modern_reference(
        action_id="act-modern-demo",
        trace_id="f" * 32,
        expected_services=["agentgateway"],
        fetch_json=fetch,
        sleep=lambda _seconds: None,
        attempts=1,
    )

    assert report["prometheus"]["sample_count"] == 0
    assert report["prometheus"]["status"] == "UNKNOWN"


@pytest.mark.parametrize(
    ("action_id", "trace_id"),
    [
        ('act-modern-demo" |= "anything', "f" * 32),
        ("act-modern-demo", "../api/search"),
        ("act-modern-demo", "F" * 32),
        ("act-short", "f" * 32),
    ],
)
def test_modern_reference_rejects_malformed_identifiers(action_id: str, trace_id: str) -> None:
    with pytest.raises(ValueError, match="action_id|trace_id"):
        query_modern_reference(
            action_id=action_id,
            trace_id=trace_id,
            fetch_json=lambda _url: {},
            attempts=1,
        )


def test_fetch_json_does_not_follow_redirects() -> None:
    destination_hits = 0

    class QuietHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

    class DestinationHandler(QuietHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
            nonlocal destination_hits
            destination_hits += 1
            body = json.dumps({"unexpected": True}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    destination = HTTPServer(("127.0.0.1", 0), DestinationHandler)
    destination_url = f"http://127.0.0.1:{destination.server_port}/redirected"

    class RedirectHandler(QuietHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
            self.send_response(302)
            self.send_header("location", destination_url)
            self.end_headers()

    redirect = HTTPServer(("127.0.0.1", 0), RedirectHandler)
    threads = [Thread(target=server.serve_forever) for server in (destination, redirect)]
    for thread in threads:
        thread.start()
    try:
        with pytest.raises(HTTPError):
            fetch_json(f"http://127.0.0.1:{redirect.server_port}/start")
        assert destination_hits == 0
    finally:
        for server in (redirect, destination):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join()


def test_fetch_json_ignores_environment_http_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy_hits = 0

    class ProxyHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
            nonlocal proxy_hits
            proxy_hits += 1
            body = b'{"forged": true}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class LocalHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
            body = b'{"local": true}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    proxy = HTTPServer(("127.0.0.1", 0), ProxyHandler)
    local = HTTPServer(("127.0.0.1", 0), LocalHandler)
    threads = [Thread(target=server.serve_forever) for server in (proxy, local)]
    for thread in threads:
        thread.start()
    try:
        with monkeypatch.context() as environment:
            proxy_url = f"http://127.0.0.1:{proxy.server_port}"
            environment.setenv("HTTP_PROXY", proxy_url)
            environment.setenv("http_proxy", proxy_url)
            environment.setenv("NO_PROXY", "")
            environment.setenv("no_proxy", "")
            reloaded = importlib.reload(backend_module)

            payload = reloaded.fetch_json(f"http://127.0.0.1:{local.server_port}/probe")

        assert payload == {"local": True}
        assert proxy_hits == 0
    finally:
        for server in (proxy, local):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join()
        importlib.reload(backend_module)


def test_malformed_tempo_service_name_is_not_observed() -> None:
    def fetch(url: str) -> dict[str, Any]:
        if "/api/v2/traces/" in url:
            return {
                "trace": {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": {"forged": "agentgateway"}},
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        if "/loki/api/v1/query_range" in url:
            return {"data": {"result": [{"values": [["1", '{"action_id":"act-modern-demo"}']]}]}}
        return {"data": {"result": [{"value": ["1", "1"]}]}}

    report = query_modern_reference(
        action_id="act-modern-demo",
        trace_id="f" * 32,
        expected_services=["agentgateway"],
        fetch_json=fetch,
        attempts=1,
    )

    assert report["tempo"]["services"] == []
    assert report["tempo"]["status"] == "UNKNOWN"
    assert report["tempo"]["complete"] is False


def test_loki_counts_identical_events_at_distinct_timestamps() -> None:
    event = '{"action_id":"act-modern-demo","event":"ok"}'

    def fetch(url: str) -> dict[str, Any]:
        if "/api/v2/traces/" in url:
            return {
                "trace": {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": "agentgateway"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        if "/loki/api/v1/query_range" in url:
            return {"data": {"result": [{"values": [["1", event], ["2", event]]}]}}
        return {"data": {"result": [{"value": ["1", "1"]}]}}

    report = query_modern_reference(
        action_id="act-modern-demo",
        trace_id="f" * 32,
        expected_services=["agentgateway"],
        fetch_json=fetch,
        attempts=1,
    )

    assert report["loki"]["line_count"] == 2
