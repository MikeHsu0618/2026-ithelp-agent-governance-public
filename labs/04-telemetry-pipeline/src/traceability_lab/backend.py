from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen


def fetch_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:  # noqa: S310 - URL is validated before use
        return json.load(response)


def _fetch_available(loader: Callable[[str], dict[str, Any]], url: str) -> dict[str, Any]:
    try:
        return loader(url)
    except (HTTPError, URLError, TimeoutError):
        return {}


def validate_backend_url(url: str) -> str:
    parsed = urlsplit(url.rstrip("/"))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("backend URL must use http on localhost or 127.0.0.1")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("backend URL must not include credentials, query, or fragment")
    return url.rstrip("/")


def verify_backend(
    artifact_dir: Path,
    *,
    tempo_url: str = "http://127.0.0.1:13200",
    loki_url: str = "http://127.0.0.1:13100",
    fetch_json: Callable[[str], dict[str, Any]] = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 10,
) -> dict[str, str]:
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    action_id = str(manifest["action_id"])
    trace_id = str(manifest["trace_id"])
    tempo_base = validate_backend_url(tempo_url)
    loki_base = validate_backend_url(loki_url)
    tempo_endpoint = f"{tempo_base}/api/v2/traces/{trace_id}"
    query = '{service_name="ithelp-traceability-lab"} |= "' + action_id + '"'
    loki_endpoint = f"{loki_base}/loki/api/v1/query_range?{urlencode({'query': query})}"
    tempo_found = False
    loki_found = False
    for attempt in range(attempts):
        tempo_payload = _fetch_available(fetch_json, tempo_endpoint)
        loki_payload = _fetch_available(fetch_json, loki_endpoint)
        tempo_found = action_id in json.dumps(tempo_payload, sort_keys=True)
        loki_found = action_id in json.dumps(loki_payload, sort_keys=True)
        if tempo_found and loki_found:
            break
        if attempt + 1 < attempts:
            sleep(1)
    return {
        "action_id": action_id,
        "trace_id": trace_id,
        "tempo_trace": "PASS" if tempo_found else "FAIL",
        "loki_governance_event": "PASS" if loki_found else "FAIL",
        "correlation": "PASS" if tempo_found and loki_found else "FAIL",
    }


def _service_names(tempo_payload: dict[str, Any]) -> list[str]:
    trace = tempo_payload.get("trace", tempo_payload)
    names: set[str] = set()
    for resource_spans in trace.get("resourceSpans", []):
        attributes = resource_spans.get("resource", {}).get("attributes", [])
        for attribute in attributes:
            if attribute.get("key") == "service.name":
                value = attribute.get("value", {}).get("stringValue")
                if isinstance(value, str):
                    names.add(value)
    return sorted(names)


def _prometheus_has_samples(payload: dict[str, Any]) -> bool:
    for item in payload.get("data", {}).get("result", []):
        value = item.get("value", [None, "0"])
        try:
            if float(value[1]) > 0:
                return True
        except (IndexError, TypeError, ValueError):
            continue
    return False


def verify_suite_backend(
    scenario_report: Path,
    *,
    tempo_url: str = "http://127.0.0.1:13200",
    loki_url: str = "http://127.0.0.1:13100",
    prometheus_url: str = "http://127.0.0.1:19090",
    fetch_json: Callable[[str], dict[str, Any]] = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 10,
) -> dict[str, Any]:
    source = json.loads(scenario_report.read_text(encoding="utf-8"))
    tempo_base = validate_backend_url(tempo_url)
    loki_base = validate_backend_url(loki_url)
    prometheus_base = validate_backend_url(prometheus_url)
    scenario_checks: list[dict[str, Any]] = []

    for scenario in source["scenarios"]:
        action_id = str(scenario["action_id"])
        trace_id = str(scenario["trace_id"])
        expected = sorted(str(name) for name in scenario["expected_services"])
        tempo_endpoint = f"{tempo_base}/api/v2/traces/{trace_id}"
        query = '{service_name=~"agentgateway|agent-runtime|mcp-adapter|ithelp-lab-client"}'
        query += f' |= "{action_id}"'
        loki_endpoint = f"{loki_base}/loki/api/v1/query_range?{urlencode({'query': query})}"
        services: list[str] = []
        log_found = False
        for attempt in range(attempts):
            services = _service_names(_fetch_available(fetch_json, tempo_endpoint))
            log_payload = _fetch_available(fetch_json, loki_endpoint)
            log_found = action_id in json.dumps(log_payload, sort_keys=True)
            if set(expected).issubset(services) and log_found:
                break
            if attempt + 1 < attempts:
                sleep(1)
        missing = sorted(set(expected) - set(services))
        scenario_checks.append(
            {
                "scenario": scenario["scenario"],
                "action_id": action_id,
                "trace_id": trace_id,
                "trace_services": services,
                "missing_services": missing,
                "tempo_trace": "PASS" if not missing else "FAIL",
                "loki_event": "PASS" if log_found else "FAIL",
                "correlation": "PASS" if not missing and log_found else "FAIL",
            }
        )

    metrics_query = 'count({__name__=~"agentgateway_.*"})'
    metrics_endpoint = f"{prometheus_base}/api/v1/query?{urlencode({'query': metrics_query})}"
    metrics_found = False
    for attempt in range(attempts):
        metrics_found = _prometheus_has_samples(_fetch_available(fetch_json, metrics_endpoint))
        if metrics_found:
            break
        if attempt + 1 < attempts:
            sleep(1)
    all_scenarios_passed = all(item["correlation"] == "PASS" for item in scenario_checks)
    return {
        "scenarios": scenario_checks,
        "prometheus_agentgateway_metrics": "PASS" if metrics_found else "FAIL",
        "overall": "PASS" if all_scenarios_passed and metrics_found else "FAIL",
    }
