from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

_ACTION_ID = re.compile(r"^act-[a-z0-9-]{8,80}$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


_URL_OPENER = build_opener(ProxyHandler({}), _NoRedirectHandler)


def fetch_json(url: str) -> dict[str, Any]:
    with _URL_OPENER.open(url, timeout=5) as response:
        payload = json.load(response)
    return payload if isinstance(payload, dict) else {}


def _fetch_available(loader: Callable[[str], dict[str, Any]], url: str) -> dict[str, Any]:
    try:
        return loader(url)
    except (HTTPError, URLError, TimeoutError):
        return {}


def validate_backend_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "http":
        raise ValueError("backend URL must use http")
    if parsed.username or parsed.password:
        raise ValueError("backend URL must not contain credentials")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("backend URL must use a loopback host")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("backend URL must be an origin without path, query, or fragment")
    return url.rstrip("/")


def validate_action_id(action_id: str) -> str:
    if not _ACTION_ID.fullmatch(action_id):
        raise ValueError("action_id must match act-[a-z0-9-]{8,80}")
    return action_id


def validate_trace_id(trace_id: str) -> str:
    if not _TRACE_ID.fullmatch(trace_id):
        raise ValueError("trace_id must be 32 lowercase hexadecimal characters")
    return trace_id


def _service_names(payload: dict[str, Any]) -> list[str]:
    trace = payload.get("trace", payload)
    if not isinstance(trace, dict):
        return []
    names: set[str] = set()
    resource_spans_items = trace.get("resourceSpans", [])
    if not isinstance(resource_spans_items, list):
        return []
    for resource_spans in resource_spans_items:
        if not isinstance(resource_spans, dict):
            continue
        resource = resource_spans.get("resource", {})
        if not isinstance(resource, dict):
            continue
        attributes = resource.get("attributes", [])
        if not isinstance(attributes, list):
            continue
        for attribute in attributes:
            if not isinstance(attribute, dict):
                continue
            if attribute.get("key") == "service.name":
                value_object = attribute.get("value", {})
                value = value_object.get("stringValue") if isinstance(value_object, dict) else None
                if isinstance(value, str) and value:
                    names.add(value)
    return sorted(names)


def _loki_lines(payload: dict[str, Any]) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return lines
    results = data.get("result", [])
    if not isinstance(results, list):
        return lines
    for stream in results:
        if not isinstance(stream, dict):
            continue
        values = stream.get("values", [])
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, list) and len(value) >= 2:
                lines.append((str(value[0]), str(value[1])))
    return lines


def _line_matches_action(line: str, action_id: str) -> bool:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("action_id") == action_id


def _prometheus_value(payload: dict[str, Any]) -> float | None:
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return None
    result = data.get("result", [])
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        return None
    value = result[0].get("value", [])
    if not isinstance(value, list) or len(value) < 2:
        return None
    try:
        parsed = float(value[1])
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def query_modern_reference(
    *,
    action_id: str,
    trace_id: str,
    expected_services: list[str] | None = None,
    tempo_url: str = "http://127.0.0.1:13200",
    loki_url: str = "http://127.0.0.1:13100",
    prometheus_url: str = "http://127.0.0.1:19090",
    fetch_json: Callable[[str], dict[str, Any]] = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 10,
) -> dict[str, Any]:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    action_id = validate_action_id(action_id)
    trace_id = validate_trace_id(trace_id)
    tempo_base = validate_backend_url(tempo_url)
    loki_base = validate_backend_url(loki_url)
    prometheus_base = validate_backend_url(prometheus_url)
    tempo_endpoint = f"{tempo_base}/api/v2/traces/{trace_id}"
    loki_query = '{service_name=~"agentgateway|agent-runtime|mcp-adapter|ithelp-lab-client"}'
    loki_query += f' |= "{action_id}"'
    loki_endpoint = f"{loki_base}/loki/api/v1/query_range?{urlencode({'query': loki_query})}"
    metrics_query = 'count({__name__=~"agentgateway_.*"})'
    metrics_endpoint = f"{prometheus_base}/api/v1/query?{urlencode({'query': metrics_query})}"
    expected = sorted({service for service in (expected_services or []) if service})

    services_seen: set[str] = set()
    matching_lines: set[tuple[str, str]] = set()
    metric_value: float | None = None
    for attempt in range(attempts):
        services_seen.update(_service_names(_fetch_available(fetch_json, tempo_endpoint)))
        matching_lines.update(
            (timestamp, line)
            for timestamp, line in _loki_lines(_fetch_available(fetch_json, loki_endpoint))
            if _line_matches_action(line, action_id)
        )
        observed_metric = _prometheus_value(_fetch_available(fetch_json, metrics_endpoint))
        if observed_metric is not None and (metric_value is None or observed_metric > metric_value):
            metric_value = observed_metric
        services = sorted(services_seen)
        trace_complete = set(expected).issubset(services) if expected else bool(services)
        if trace_complete and matching_lines and metric_value is not None and metric_value > 0:
            break
        if attempt + 1 < attempts:
            sleep(1)

    services = sorted(services_seen)
    matched_action = bool(matching_lines)
    missing_services = sorted(set(expected) - set(services))
    trace_complete = not missing_services if expected else bool(services)
    return {
        "action_id": action_id,
        "trace_id": trace_id,
        "tempo": {
            "status": "OBSERVED" if services else "UNKNOWN",
            "services": services,
            "expected_services": expected,
            "missing_services": missing_services,
            "complete": trace_complete,
            "source": tempo_endpoint,
        },
        "loki": {
            "status": "OBSERVED" if matched_action else "UNKNOWN",
            "matched_action": matched_action,
            "line_count": len(matching_lines),
            "query": loki_query,
        },
        "prometheus": {
            "status": "OBSERVED" if metric_value is not None and metric_value > 0 else "UNKNOWN",
            "scope": "AGGREGATE_ONLY",
            "sample_count": metric_value,
            "query": metrics_query,
            "reason": (
                "A nonzero series count confirms Gateway metrics exist, but not this action."
                if metric_value is not None and metric_value > 0
                else "No nonzero Gateway metric series count was observed."
            ),
        },
    }
