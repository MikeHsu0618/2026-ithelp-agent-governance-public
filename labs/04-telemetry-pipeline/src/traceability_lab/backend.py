from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta
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


def _prometheus_scalar(payload: dict[str, Any]) -> int | None:
    result = payload.get("data", {}).get("result", [])
    if not result:
        return None
    value = result[0].get("value", [None, None])
    try:
        return int(float(value[1]))
    except (IndexError, TypeError, ValueError):
        return None


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


def verify_cardinality_backend(
    run_report: Path,
    *,
    prometheus_url: str = "http://127.0.0.1:29090",
    loki_url: str = "http://127.0.0.1:23100",
    tempo_url: str = "http://127.0.0.1:23200",
    fetch_json: Callable[[str], dict[str, Any]] = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 20,
) -> dict[str, Any]:
    """Compare observed gateway series with the exact request matrix that was executed."""

    source = json.loads(run_report.read_text(encoding="utf-8"))
    prometheus_base = validate_backend_url(prometheus_url)
    loki_base = validate_backend_url(loki_url)
    tempo_base = validate_backend_url(tempo_url)
    expected = {
        "bounded": int(source["team_count"]),
        "user": int(source["user_count"]),
        "conversation": int(source["conversation_count"]),
    }
    authentication_guards = (
        int(source.get("missing_token_status", 0)) == 401
        and int(source.get("wrong_audience_status", 0)) == 401
    )
    jobs = {
        "bounded": "agentgateway-bounded",
        "user": "agentgateway-user",
        "conversation": "agentgateway-conversation",
    }
    query_margin = timedelta(seconds=2)
    started_at = datetime.fromisoformat(str(source["started_at"]))
    finished_at = datetime.fromisoformat(str(source["finished_at"]))
    query_started_at = started_at - query_margin
    query_finished_at = finished_at + query_margin
    start_ns = str(int(query_started_at.timestamp() * 1_000_000_000))
    end_ns = str(int(query_finished_at.timestamp() * 1_000_000_000))
    metrics_endpoints = {}
    metrics_queries = {}
    for variant, job in jobs.items():
        query = (
            'count(agentgateway_requests_total{job="'
            + job
            + '",route="default/cardinality-run",status="200"})'
        )
        metrics_queries[variant] = query
        metrics_endpoints[variant] = f"{prometheus_base}/api/v1/query?{urlencode({'query': query})}"

    match = '{service_name="agentgateway"}'
    series_params = [("match[]", match), ("start", start_ns), ("end", end_ns)]
    series_endpoint = f"{loki_base}/loki/api/v1/series?{urlencode(series_params)}"
    log_params = {"query": match, "start": start_ns, "end": end_ns, "limit": 5000}
    log_endpoint = f"{loki_base}/loki/api/v1/query_range?{urlencode(log_params)}"
    label_endpoint = (
        f"{loki_base}/loki/api/v1/labels?{urlencode({'start': start_ns, 'end': end_ns})}"
    )
    sample_trace_id = str(source["sample_trace_id"])
    trace_endpoint = f"{tempo_base}/api/traces/{sample_trace_id}"
    observed: dict[str, int] = {}
    stream_count = 0
    identity_log = False
    identity_trace = False
    matched_principal = ""
    index_labels: list[str] = []
    identity_not_indexed = False
    for attempt in range(attempts):
        observed = {
            variant: value
            for variant, endpoint in metrics_endpoints.items()
            if (value := _prometheus_scalar(_fetch_available(fetch_json, endpoint))) is not None
        }
        series_payload = _fetch_available(fetch_json, series_endpoint)
        series = series_payload.get("data", [])
        stream_count = len(series) if isinstance(series, list) else 0
        label_payload = _fetch_available(fetch_json, label_endpoint)
        raw_labels = label_payload.get("data", [])
        index_labels = (
            sorted(str(item) for item in raw_labels) if isinstance(raw_labels, list) else []
        )
        identity_not_indexed = bool(index_labels) and not {
            "conversation_id",
            "correlation_conversation_id",
            "identity_user_id",
            "user_id",
        }.intersection(index_labels)
        log_payload = _fetch_available(fetch_json, log_endpoint)
        log_text = json.dumps(log_payload, sort_keys=True)
        identity_log = (
            str(source["sample_principal"]) in log_text
            and str(source["sample_conversation_id"]) in log_text
        )
        trace_payload = _fetch_available(fetch_json, trace_endpoint)
        trace_text = json.dumps(trace_payload, sort_keys=True)
        matched_principal = (
            str(source["sample_principal"]) if str(source["sample_principal"]) in trace_text else ""
        )
        identity_trace = bool(matched_principal)
        if (
            observed == expected
            and stream_count > 0
            and identity_log
            and identity_trace
            and identity_not_indexed
        ):
            break
        if attempt + 1 < attempts:
            sleep(1)

    counts_match = observed == expected
    bounded = observed.get("bounded", 0)
    growth = {
        variant: round(observed.get(variant, 0) / bounded, 2) if bounded else 0.0
        for variant in ("user", "conversation")
    }
    overall = (
        authentication_guards
        and counts_match
        and stream_count > 0
        and identity_log
        and identity_trace
        and identity_not_indexed
    )
    return {
        "authentication_guards": "PASS" if authentication_guards else "FAIL",
        "metric": "agentgateway_requests_total",
        "observed_series": dict(sorted(observed.items())),
        "expected_series": dict(sorted(expected.items())),
        "growth_vs_bounded": growth,
        "requests_per_variant": int(source["requests_per_variant"]),
        "query_window": {
            "finished_at": str(source["finished_at"]),
            "margin_seconds": int(query_margin.total_seconds()),
            "started_at": str(source["started_at"]),
        },
        "prometheus_queries": metrics_queries,
        "loki_selector": match,
        "tempo_trace_id": sample_trace_id,
        "series_match_executed_traffic": "PASS" if counts_match else "FAIL",
        "loki_stream_count": stream_count,
        "loki_index_labels": index_labels,
        "loki_identity_not_indexed": "PASS" if identity_not_indexed else "FAIL",
        "gateway_identity_log": "PASS" if identity_log else "FAIL",
        "gateway_jwt_trace": "PASS" if identity_trace else "FAIL",
        "tempo_matched_principal": matched_principal,
        "overall": "PASS" if overall else "FAIL",
    }
