"""Execute the Day 15 traffic-boundary cases through one live agentgateway."""

import json
import secrets
import tempfile
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from gateway_runtime.artifacts import ArtifactStore, assert_values_absent
from gateway_runtime.config import build_agentgateway_config, redacted_config
from gateway_runtime.credentials import EphemeralCredentials
from gateway_runtime.provider import MockProvider
from gateway_runtime.runtime import (
    AGENTGATEWAY_IMAGE,
    DockerGateway,
    validate_config,
    write_runtime_files,
)


def run_traffic_lab(artifact_root: Path) -> dict[str, Any]:
    """Verify response, SSE, caller auth, backend auth, and error propagation."""

    material = EphemeralCredentials.create()
    invalid_caller_key = secrets.token_urlsafe(32)
    raw_credentials = {
        material.human_virtual_key,
        material.workload_consumer_key,
        material.provider_key,
        invalid_caller_key,
    }
    run_id = datetime.now(UTC).strftime("day15-%Y%m%dT%H%M%SZ")
    store = ArtifactStore(artifact_root, run_id)

    with MockProvider(
        provider_key=material.provider_key,
        incoming_credentials={material.workload_consumer_key, invalid_caller_key},
        synchronize_stream=True,
    ) as provider:
        config = build_agentgateway_config(
            material,
            provider_host=f"host.docker.internal:{provider.port}",
            jwks_path="/config/jwks.json",
        )
        with tempfile.TemporaryDirectory(prefix="ithelp-lab03-traffic-") as runtime_directory:
            runtime_dir = Path(runtime_directory)
            write_runtime_files(runtime_dir, config, material.public_jwks())
            validate_config(runtime_dir / "agentgateway.json")
            with DockerGateway(runtime_dir) as gateway:
                results = _execute_cases(
                    gateway.url,
                    material.workload_consumer_key,
                    invalid_caller_key,
                    provider,
                )

    report: dict[str, Any] = {
        "schema": "ithelp.gateway-runtime.traffic-report.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "runtime": {
            "gateway_count": 1,
            "gateway_image": AGENTGATEWAY_IMAGE,
            "backend": "synthetic-openai-compatible-provider",
            "retry_policy": "disabled",
        },
        "cases": results,
        "summary": {
            "matched": sum(1 for result in results if result["matched"]),
            "total": len(results),
        },
    }
    store.write_json("evidence/traffic-report.json", report)
    store.write_json("evidence/agentgateway-config.redacted.json", redacted_config(config))
    store.write_text("evidence/traffic-decision-table.md", _decision_table(results))
    store.write_text("evidence/traffic-terminal.txt", _terminal_output(results, report["summary"]))
    store.write_json(
        "manifest.json",
        {
            "files": [
                "evidence/agentgateway-config.redacted.json",
                "evidence/traffic-decision-table.md",
                "evidence/traffic-report.json",
                "evidence/traffic-terminal.txt",
            ],
            "raw_credentials_persisted": False,
            "run_id": run_id,
        },
    )
    assert_values_absent(store.run_dir, raw_credentials)
    report["artifact_dir"] = str(store.run_dir)
    return report


def _execute_cases(
    gateway_url: str,
    caller_key: str,
    invalid_caller_key: str,
    provider: MockProvider,
) -> list[dict[str, Any]]:
    normal_status, normal_headers, normal_body = _post(gateway_url, caller_key=caller_key)
    normal_json = _json_body(normal_body)

    stream_status, stream_headers, stream_body = _post_stream(
        gateway_url,
        caller_key=caller_key,
        provider=provider,
        payload={"model": "lab-model", "messages": [], "stream": True},
    )
    stream_events = _sse_events(stream_body)

    before_missing = provider.total_request_count()
    missing_status, _, _ = _post(gateway_url, caller_key=None)
    missing_upstream_requests = provider.total_request_count() - before_missing
    before_invalid = provider.total_request_count()
    invalid_status, _, _ = _post(gateway_url, caller_key=invalid_caller_key)
    invalid_upstream_requests = provider.total_request_count() - before_invalid

    rate_status, rate_headers, rate_body = _post(
        gateway_url,
        caller_key=caller_key,
        payload={"model": "lab-rate-limited", "messages": []},
    )
    rate_json = _json_body(rate_body)
    rate_requests = provider.request_count("rate-limit")

    isolation_status, _, isolation_body = _post(gateway_url, caller_key=caller_key)
    isolation_json = _json_body(isolation_body)

    return [
        {
            "case_id": "normal-json",
            "http_status": normal_status,
            "content_type": normal_headers.get_content_type(),
            "result": normal_json.get("choices", [{}])[0].get("message", {}).get("content"),
            "matched": normal_status == 200 and normal_json.get("id") == "chatcmpl-lab",
        },
        {
            "case_id": "sse-stream",
            "http_status": stream_status,
            "content_type": stream_headers.get_content_type(),
            "events": stream_events,
            "first_event_before_upstream_complete": provider.stream_release_observed,
            "matched": stream_status == 200
            and stream_headers.get_content_type() == "text/event-stream"
            and stream_events == ["lab-", "ok", "[DONE]"]
            and provider.stream_release_observed,
        },
        {
            "case_id": "missing-caller-credential",
            "http_status": missing_status,
            "upstream_requests": missing_upstream_requests,
            "matched": missing_status == 401 and missing_upstream_requests == 0,
        },
        {
            "case_id": "invalid-caller-credential",
            "http_status": invalid_status,
            "upstream_requests": invalid_upstream_requests,
            "matched": invalid_status == 401 and invalid_upstream_requests == 0,
        },
        {
            "case_id": "upstream-rate-limit",
            "http_status": rate_status,
            "retry_after": rate_headers.get("retry-after"),
            "upstream_code": rate_json.get("error", {}).get("code"),
            "upstream_requests": rate_requests,
            "matched": rate_status == 429
            and rate_headers.get("retry-after") == "7"
            and rate_json.get("error", {}).get("code") == "synthetic_rate_limit"
            and rate_requests == 1,
        },
        {
            "case_id": "backend-credential-isolation",
            "http_status": isolation_status,
            "provider_auth": isolation_json.get("provider_auth"),
            "incoming_credential_forwarded": isolation_json.get("incoming_credential_forwarded"),
            "matched": isolation_status == 200
            and isolation_json.get("provider_auth") == "MATCHED"
            and isolation_json.get("incoming_credential_forwarded") is False,
        },
    ]


def _post(
    gateway_url: str,
    *,
    caller_key: str | None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, Message, bytes]:
    headers = {"content-type": "application/json", "x-demo-credential": "api-key"}
    if caller_key is not None:
        headers["authorization"] = f"Bearer {caller_key}"
    request = Request(
        gateway_url + "/v1/chat/completions",
        data=json.dumps(payload or {"model": "lab-model", "messages": []}).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, response.headers, response.read()
    except HTTPError as error:
        return error.code, error.headers, error.read()


def _post_stream(
    gateway_url: str,
    *,
    caller_key: str,
    provider: MockProvider,
    payload: dict[str, Any],
) -> tuple[int, Message, bytes]:
    request = Request(
        gateway_url + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "authorization": f"Bearer {caller_key}",
            "content-type": "application/json",
            "x-demo-credential": "api-key",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=3) as response:
            try:
                first_record = response.readline() + response.readline()
            finally:
                provider.release_stream()
            return response.status, response.headers, first_record + response.read()
    except HTTPError as error:
        provider.release_stream()
        return error.code, error.headers, error.read()


def _json_body(raw_body: bytes) -> dict[str, Any]:
    return json.loads(raw_body) if raw_body else {}


def _sse_events(raw_body: bytes) -> list[str]:
    events: list[str] = []
    for line in raw_body.decode().splitlines():
        if not line.startswith("data: "):
            continue
        data = line.removeprefix("data: ")
        if data == "[DONE]":
            events.append(data)
            continue
        events.append(json.loads(data)["choices"][0]["delta"]["content"])
    return events


def _decision_table(results: list[dict[str, Any]]) -> str:
    lines = [
        "| Case | HTTP | Matched | Evidence |",
        "| --- | ---: | --- | --- |",
    ]
    for result in results:
        evidence = _evidence_summary(result)
        lines.append(
            f"| {result['case_id']} | {result['http_status']} | "
            f"{'PASS' if result['matched'] else 'FAIL'} | {evidence} |"
        )
    return "\n".join(lines) + "\n"


def _evidence_summary(result: dict[str, Any]) -> str:
    case_id = result["case_id"]
    if case_id == "sse-stream":
        return "SSE lab- / ok / DONE"
    if case_id == "upstream-rate-limit":
        retry_after = result["retry_after"]
        upstream_requests = result["upstream_requests"]
        return f"Retry-After={retry_after}; upstream_requests={upstream_requests}"
    if case_id == "backend-credential-isolation":
        return "provider=MATCHED; caller_forwarded=false"
    if case_id in {"missing-caller-credential", "invalid-caller-credential"}:
        return f"upstream_requests={result['upstream_requests']}"
    return "status preserved"


def _terminal_output(results: list[dict[str, Any]], summary: dict[str, int]) -> str:
    lines = ["DAY 15 / TRAFFIC BOUNDARY", "", "one agentgateway / retry disabled", ""]
    for result in results:
        lines.append(
            f"{result['case_id']:<31} HTTP {result['http_status']:<3}  "
            f"{'PASS' if result['matched'] else 'FAIL'}"
        )
    lines.extend(["", f"matched {summary['matched']}/{summary['total']}"])
    return "\n".join(lines) + "\n"
