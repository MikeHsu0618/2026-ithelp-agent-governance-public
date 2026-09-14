from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

from traceability_lab.identity_run import SYNTHETIC_EMAIL, SYNTHETIC_TOKEN


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


def verify_identity_backend(
    projection_report: Path,
    *,
    tempo_url: str = "http://127.0.0.1:13200",
    loki_url: str = "http://127.0.0.1:13100",
    prometheus_url: str = "http://127.0.0.1:19090",
    fetch_json: Callable[[str], dict[str, Any]] = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 10,
) -> dict[str, str]:
    source = json.loads(projection_report.read_text(encoding="utf-8"))
    action_id = str(source["action_id"])
    trace_id = str(source["trace_id"])
    principal_ref = str(source["principal_ref"])
    team = str(source["team"])
    tempo_base = validate_backend_url(tempo_url)
    loki_base = validate_backend_url(loki_url)
    prometheus_base = validate_backend_url(prometheus_url)
    tempo_endpoint = f"{tempo_base}/api/v2/traces/{trace_id}"
    loki_query = '{service_name="identity-projection-lab"} |= "' + action_id + '"'
    loki_endpoint = f"{loki_base}/loki/api/v1/query_range?{urlencode({'query': loki_query})}"
    loki_labels_endpoint = f"{loki_base}/loki/api/v1/labels"
    metrics_query = 'ithelp_agent_actions_total{team="' + team + '"}'
    metrics_endpoint = f"{prometheus_base}/api/v1/query?{urlencode({'query': metrics_query})}"

    tempo_payload: dict[str, Any] = {}
    loki_payload: dict[str, Any] = {}
    metrics_payload: dict[str, Any] = {}
    tempo_safe = False
    loki_safe = False
    loki_principal_not_indexed = False
    metrics_bounded = False
    forbidden_absent = False
    forbidden_fragments = (
        "auth.token",
        "code.file.path",
        "code_file_path",
        "user.email",
        SYNTHETIC_EMAIL,
        SYNTHETIC_TOKEN,
    )
    metric_forbidden = (
        "action_id",
        "conversation.id",
        "conversation_id",
        "principal.ref",
        "principal_ref",
        "session.id",
        "session_id",
        "user.email",
        "user_email",
        "user.id",
        "user_id",
    )

    for attempt in range(attempts):
        tempo_payload = _fetch_available(fetch_json, tempo_endpoint)
        loki_payload = _fetch_available(fetch_json, loki_endpoint)
        loki_labels_payload = _fetch_available(fetch_json, loki_labels_endpoint)
        metrics_payload = _fetch_available(fetch_json, metrics_endpoint)
        tempo_text = json.dumps(tempo_payload, sort_keys=True)
        loki_text = json.dumps(loki_payload, sort_keys=True)
        metrics_text = json.dumps(metrics_payload, sort_keys=True)
        tempo_safe = action_id in tempo_text and principal_ref in tempo_text
        loki_safe = action_id in loki_text and principal_ref in loki_text
        label_names = loki_labels_payload.get("data", [])
        loki_principal_not_indexed = (
            isinstance(label_names, list)
            and bool(label_names)
            and "principal.ref" not in label_names
            and "principal_ref" not in label_names
        )
        metrics_bounded = (
            team in metrics_text
            and _prometheus_has_samples(metrics_payload)
            and not any(fragment in metrics_text for fragment in metric_forbidden)
        )
        all_backend_text = tempo_text + loki_text + metrics_text
        forbidden_absent = not any(fragment in all_backend_text for fragment in forbidden_fragments)
        if (
            tempo_safe
            and loki_safe
            and loki_principal_not_indexed
            and metrics_bounded
            and forbidden_absent
        ):
            break
        if attempt + 1 < attempts:
            sleep(1)

    overall = (
        tempo_safe
        and loki_safe
        and loki_principal_not_indexed
        and metrics_bounded
        and forbidden_absent
    )
    return {
        "action_id": action_id,
        "tempo_safe_projection": "PASS" if tempo_safe else "FAIL",
        "loki_safe_projection": "PASS" if loki_safe else "FAIL",
        "loki_principal_not_indexed": "PASS" if loki_principal_not_indexed else "FAIL",
        "prometheus_bounded_labels": "PASS" if metrics_bounded else "FAIL",
        "forbidden_fields_absent": "PASS" if forbidden_absent else "FAIL",
        "overall": "PASS" if overall else "FAIL",
    }
