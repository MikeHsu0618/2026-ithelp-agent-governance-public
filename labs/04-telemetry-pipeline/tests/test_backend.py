import json
from pathlib import Path
from urllib.error import URLError

import pytest

from traceability_lab.backend import (
    verify_backend,
    verify_identity_backend,
    verify_suite_backend,
)


def write_manifest(path: Path) -> None:
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "action_id": "act-day20-backend",
                "trace_id": "a" * 32,
            }
        )
    )


def test_backend_verification_correlates_tempo_and_loki(tmp_path: Path) -> None:
    write_manifest(tmp_path)

    def fetch_json(url: str) -> dict:
        if "/api/v2/traces/" in url:
            return {"resourceSpans": [{"value": "act-day20-backend"}]}
        return {"data": {"result": [{"values": [["1", "act-day20-backend"]]}]}}

    report = verify_backend(tmp_path, fetch_json=fetch_json)

    assert report == {
        "action_id": "act-day20-backend",
        "trace_id": "a" * 32,
        "tempo_trace": "PASS",
        "loki_governance_event": "PASS",
        "correlation": "PASS",
    }


def test_backend_verification_reports_missing_loki_event(tmp_path: Path) -> None:
    write_manifest(tmp_path)

    def fetch_json(url: str) -> dict:
        if "/api/v2/traces/" in url:
            return {"resourceSpans": [{"value": "act-day20-backend"}]}
        return {"data": {"result": []}}

    report = verify_backend(tmp_path, fetch_json=fetch_json, attempts=1)

    assert report["tempo_trace"] == "PASS"
    assert report["loki_governance_event"] == "FAIL"
    assert report["correlation"] == "FAIL"


def test_backend_verification_retries_eventual_ingestion(tmp_path: Path) -> None:
    write_manifest(tmp_path)
    calls = {"tempo": 0, "loki": 0}

    def fetch_json(url: str) -> dict:
        backend = "tempo" if "/api/v2/traces/" in url else "loki"
        calls[backend] += 1
        if calls[backend] == 1:
            return {"data": {"result": []}}
        return {"value": "act-day20-backend"}

    report = verify_backend(
        tmp_path,
        fetch_json=fetch_json,
        sleep=lambda _: None,
        attempts=2,
    )

    assert report["correlation"] == "PASS"
    assert calls == {"tempo": 2, "loki": 2}


@pytest.mark.parametrize(
    ("tempo_url", "loki_url"),
    [
        ("https://localhost:3200", "http://127.0.0.1:13100"),
        ("http://tempo.example:3200", "http://127.0.0.1:13100"),
        ("http://127.0.0.1:13200", "http://user:pass@localhost:3100"),
        ("http://127.0.0.1:13200", "http://localhost:3100?token=secret"),
    ],
)
def test_backend_verification_rejects_non_local_or_credentialed_urls(
    tmp_path: Path, tempo_url: str, loki_url: str
) -> None:
    write_manifest(tmp_path)

    with pytest.raises(ValueError, match="backend URL"):
        verify_backend(tmp_path, tempo_url=tempo_url, loki_url=loki_url)


def test_suite_backend_requires_expected_services_logs_and_gateway_metrics(tmp_path: Path) -> None:
    report_path = tmp_path / "scenario-report.json"
    report_path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario": "normal-call",
                        "action_id": "act-normal",
                        "trace_id": "c" * 32,
                        "expected_services": [
                            "ithelp-lab-client",
                            "agentgateway",
                            "agent-runtime",
                            "mcp-adapter",
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fetch_json(url: str) -> dict:
        if "/api/v2/traces/" in url:
            return {
                "trace": {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": name},
                                    }
                                ]
                            }
                        }
                        for name in (
                            "ithelp-lab-client",
                            "agentgateway",
                            "agent-runtime",
                            "mcp-adapter",
                        )
                    ]
                }
            }
        if url.endswith("/loki/api/v1/labels"):
            return {"status": "success", "data": ["service_name", "detected_level"]}
        if "/api/v1/query?" in url:
            return {"status": "success", "data": {"result": [{"value": ["1", "42"]}]}}
        return {"data": {"result": [{"values": [["1", "act-normal"]]}]}}

    report = verify_suite_backend(report_path, fetch_json=fetch_json, attempts=1)

    assert report["prometheus_agentgateway_metrics"] == "PASS"
    assert report["scenarios"][0]["trace_services"] == [
        "agent-runtime",
        "agentgateway",
        "ithelp-lab-client",
        "mcp-adapter",
    ]
    assert report["overall"] == "PASS"


def test_suite_backend_exposes_a_broken_mcp_trace(tmp_path: Path) -> None:
    report_path = tmp_path / "scenario-report.json"
    report_path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario": "normal-call",
                        "action_id": "act-broken",
                        "trace_id": "d" * 32,
                        "expected_services": ["ithelp-lab-client", "mcp-adapter"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fetch_json(url: str) -> dict:
        if "/api/v2/traces/" in url:
            return {
                "trace": {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": "ithelp-lab-client"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        return {"data": {"result": [{"value": ["1", "1"]}]}}

    report = verify_suite_backend(report_path, fetch_json=fetch_json, attempts=1)

    assert report["scenarios"][0]["missing_services"] == ["mcp-adapter"]
    assert report["overall"] == "FAIL"


def test_suite_backend_retries_when_backends_are_still_starting(tmp_path: Path) -> None:
    report_path = tmp_path / "scenario-report.json"
    report_path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario": "normal-call",
                        "action_id": "act-eventual",
                        "trace_id": "e" * 32,
                        "expected_services": ["ithelp-lab-client"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    calls = {}

    def fetch_json(url: str) -> dict:
        if "/api/v2/traces/" in url:
            backend = "tempo"
        elif "/api/v1/query?" in url:
            backend = "metrics"
        else:
            backend = "loki"
        calls[backend] = calls.get(backend, 0) + 1
        if calls[backend] == 1:
            raise URLError("backend is starting")
        if backend == "tempo":
            return {
                "trace": {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": "ithelp-lab-client"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        if backend == "metrics":
            return {"data": {"result": [{"value": ["1", "1"]}]}}
        return {"data": {"result": [{"values": [["1", "act-eventual"]]}]}}

    report = verify_suite_backend(
        report_path,
        fetch_json=fetch_json,
        sleep=lambda _: None,
        attempts=2,
    )

    assert report["overall"] == "PASS"
    assert calls == {"tempo": 2, "loki": 2, "metrics": 2}


def test_identity_backend_requires_safe_fields_and_absent_sensitive_fields(tmp_path: Path) -> None:
    report_path = tmp_path / "identity-projection.json"
    report_path.write_text(
        json.dumps(
            {
                "action_id": "act-day22-identity",
                "trace_id": "f" * 32,
                "principal_ref": "prn_safe",
                "team": "platform-sre",
            }
        ),
        encoding="utf-8",
    )

    def fetch_json(url: str) -> dict:
        if "/api/v2/traces/" in url:
            return {
                "trace": {
                    "resourceSpans": [
                        {
                            "scopeSpans": [
                                {
                                    "spans": [
                                        {
                                            "attributes": [
                                                {"key": "principal.ref", "value": "prn_safe"},
                                                {
                                                    "key": "ithelp.governance.action_id",
                                                    "value": "act-day22-identity",
                                                },
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            }
        if url.endswith("/loki/api/v1/labels"):
            return {"status": "success", "data": ["service_name", "detected_level"]}
        if "/api/v1/query?" in url:
            return {
                "data": {
                    "result": [
                        {
                            "metric": {
                                "__name__": "ithelp_agent_actions_total",
                                "team": "platform-sre",
                                "route": "agent-runtime",
                                "outcome": "allowed",
                            },
                            "value": ["1", "1"],
                        }
                    ]
                }
            }
        return {
            "data": {
                "result": [
                    {
                        "stream": {
                            "service_name": "identity-projection-lab",
                            "principal_ref": "prn_safe",
                        },
                        "values": [["1", '{"action_id":"act-day22-identity"}']],
                    }
                ]
            }
        }

    report = verify_identity_backend(report_path, fetch_json=fetch_json, attempts=1)

    assert report == {
        "action_id": "act-day22-identity",
        "tempo_safe_projection": "PASS",
        "loki_safe_projection": "PASS",
        "loki_principal_not_indexed": "PASS",
        "prometheus_bounded_labels": "PASS",
        "forbidden_fields_absent": "PASS",
        "overall": "PASS",
    }


def test_identity_backend_fails_when_raw_email_reaches_a_backend(tmp_path: Path) -> None:
    report_path = tmp_path / "identity-projection.json"
    report_path.write_text(
        json.dumps(
            {
                "action_id": "act-day22-leak",
                "trace_id": "a" * 32,
                "principal_ref": "prn_safe",
                "team": "platform-sre",
            }
        ),
        encoding="utf-8",
    )

    def fetch_json(url: str) -> dict:
        if "/api/v2/traces/" in url:
            return {"value": "prn_safe act-day22-leak sre-oncaller@identity.invalid"}
        if url.endswith("/loki/api/v1/labels"):
            return {"status": "success", "data": ["service_name"]}
        if "/api/v1/query?" in url:
            return {"data": {"result": [{"metric": {"team": "platform-sre"}, "value": ["1", "1"]}]}}
        return {"value": "prn_safe act-day22-leak"}

    report = verify_identity_backend(report_path, fetch_json=fetch_json, attempts=1)

    assert report["forbidden_fields_absent"] == "FAIL"
    assert report["overall"] == "FAIL"


def test_identity_backend_fails_when_local_code_path_reaches_loki(tmp_path: Path) -> None:
    report_path = tmp_path / "identity-projection.json"
    report_path.write_text(
        json.dumps(
            {
                "action_id": "act-day22-path-leak",
                "trace_id": "b" * 32,
                "principal_ref": "prn_safe",
                "team": "platform-sre",
            }
        ),
        encoding="utf-8",
    )

    def fetch_json(url: str) -> dict:
        if "/api/v2/traces/" in url:
            return {"value": "prn_safe act-day22-path-leak"}
        if url.endswith("/loki/api/v1/labels"):
            return {"status": "success", "data": ["service_name"]}
        if "/api/v1/query?" in url:
            return {"data": {"result": [{"metric": {"team": "platform-sre"}, "value": ["1", "1"]}]}}
        return {
            "value": "prn_safe act-day22-path-leak",
            "code_file_path": "synthetic-project/telemetry.py",
        }

    report = verify_identity_backend(report_path, fetch_json=fetch_json, attempts=1)

    assert report["forbidden_fields_absent"] == "FAIL"
    assert report["overall"] == "FAIL"


def test_identity_backend_fails_when_principal_becomes_a_loki_index_label(tmp_path: Path) -> None:
    report_path = tmp_path / "identity-projection.json"
    report_path.write_text(
        json.dumps(
            {
                "action_id": "act-day22-label-leak",
                "trace_id": "c" * 32,
                "principal_ref": "prn_safe",
                "team": "platform-sre",
            }
        ),
        encoding="utf-8",
    )

    def fetch_json(url: str) -> dict:
        if "/api/v2/traces/" in url:
            return {"value": "prn_safe act-day22-label-leak"}
        if url.endswith("/loki/api/v1/labels"):
            return {"status": "success", "data": ["service_name", "principal_ref"]}
        if "/api/v1/query?" in url:
            return {"data": {"result": [{"metric": {"team": "platform-sre"}, "value": ["1", "1"]}]}}
        return {"value": "prn_safe act-day22-label-leak"}

    report = verify_identity_backend(report_path, fetch_json=fetch_json, attempts=1)

    assert report["loki_principal_not_indexed"] == "FAIL"
    assert report["overall"] == "FAIL"
