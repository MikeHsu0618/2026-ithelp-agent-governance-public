from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from traceability_lab.artifacts import ArtifactStore

PRIMARY_MODEL = "day24-primary"
BACKUP_MODEL = "day24-backup"
VIRTUAL_MODEL = "day24-resilient-agent"
LAB_API_KEY = "sk-day24-platform"


class DeterministicLlmProvider:
    """Small, deterministic provider fixture for exercising the real Gateway data path."""

    def __init__(self, provider: str) -> None:
        if provider not in {"primary", "backup"}:
            raise ValueError("provider must be primary or backup")
        self.provider = provider
        self.events: list[dict[str, Any]] = []

    def handle(
        self,
        path: str,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        if path == "/healthz":
            return HTTPStatus.OK, {"provider": self.provider, "status": "ok"}
        if path == "/events":
            return HTTPStatus.OK, {"events": self.events}
        if path not in {"/v1/chat/completions", "/v1/messages"}:
            return HTTPStatus.NOT_FOUND, {"error": {"message": "route_not_found"}}

        action_id = headers.get("x-action-id", "UNKNOWN")
        request_model = str(body.get("model", "UNKNOWN"))
        if self.provider == "primary" and _contains_failure_trigger(body):
            self.events.append(
                {
                    "action_id": action_id,
                    "outcome": "HTTP_503",
                    "provider": self.provider,
                    "request_model": request_model,
                    "response_model": "UNKNOWN",
                    "usage_evidence": "UNKNOWN",
                }
            )
            return HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": {
                    "message": "deterministic primary outage",
                    "type": "day24_fixture_unavailable",
                }
            }

        response_model = PRIMARY_MODEL if self.provider == "primary" else BACKUP_MODEL
        self.events.append(
            {
                "action_id": action_id,
                "outcome": "SUCCESS",
                "provider": self.provider,
                "request_model": request_model,
                "response_model": response_model,
                "usage_evidence": "PROVIDER_RESPONSE",
            }
        )
        if self.provider == "backup":
            return HTTPStatus.OK, _anthropic_response(response_model)
        return HTTPStatus.OK, _openai_response(response_model)


@dataclass(frozen=True, slots=True)
class CostFallbackSummary:
    artifact_dir: str
    scenarios: tuple[dict[str, Any], ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "artifact_dir": self.artifact_dir,
            "cost_contract": {
                "failed_attempt_usage": "UNKNOWN unless the provider returns usage evidence",
                "final_invoice": "OUT_OF_SCOPE",
                "gateway_cost": "MODEL_CATALOG_ESTIMATE",
            },
            "scenarios": list(self.scenarios),
        }


def run_cost_fallback_traffic(
    *,
    artifact_root: Path,
    failover_gateway_url: str,
    retry_gateway_url: str,
    opener: Callable[..., Any] = urlopen,
    now: datetime | None = None,
) -> CostFallbackSummary:
    run_time = now or datetime.now(UTC)
    store = ArtifactStore(artifact_root, f"day24-{run_time.strftime('%Y%m%dT%H%M%SZ')}")
    cases = (
        (
            "primary-success",
            "act-day24-primary-success",
            "failover-only",
            failover_gateway_url,
            "PRIMARY_OK",
        ),
        (
            "failover-without-retry",
            "act-day24-failover-without-retry",
            "failover-only",
            failover_gateway_url,
            "FAIL_PRIMARY",
        ),
        (
            "failover-with-retry",
            "act-day24-failover-with-retry",
            "client-retry",
            retry_gateway_url,
            "FAIL_PRIMARY",
        ),
    )
    outcomes: list[dict[str, Any]] = []
    for scenario, action_id, gateway, gateway_url, prompt in cases:
        first = _invoke_gateway(
            scenario=scenario,
            action_id=action_id,
            gateway=gateway,
            gateway_url=gateway_url,
            prompt=prompt,
            opener=opener,
        )
        if scenario != "failover-with-retry" or first["http_status"] == HTTPStatus.OK:
            outcomes.append(first)
            continue
        second = _invoke_gateway(
            scenario=scenario,
            action_id=action_id,
            gateway=gateway,
            gateway_url=gateway_url,
            prompt=prompt,
            opener=opener,
        )
        second.update(
            {
                "client_attempts": 2,
                "first_attempt_http_status": first["http_status"],
                "first_attempt_usage": "UNKNOWN",
                "retry_layer": "client",
            }
        )
        outcomes.append(second)
    outcome_tuple = tuple(outcomes)
    summary = CostFallbackSummary(artifact_dir=str(store.run_dir), scenarios=outcome_tuple)
    store.write_json("cost-fallback-run.json", summary.to_json_dict())
    return summary


def _invoke_gateway(
    *,
    scenario: str,
    action_id: str,
    gateway: str,
    gateway_url: str,
    prompt: str,
    opener: Callable[..., Any],
) -> dict[str, Any]:
    request = Request(
        f"{gateway_url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(
            {
                "model": VIRTUAL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode(),
        headers={
            "authorization": f"Bearer {LAB_API_KEY}",
            "content-type": "application/json",
            "x-action-id": action_id,
        },
        method="POST",
    )
    try:
        with opener(request, timeout=10) as response:
            status = response.status
            payload = json.load(response)
    except HTTPError as exc:
        status = exc.code
        raw_body = exc.read()
        try:
            payload = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            payload = {}

    response_model = payload.get("model", "UNKNOWN")
    usage = payload.get("usage")
    response_tokens: int | str = "UNKNOWN"
    if isinstance(usage, dict) and isinstance(usage.get("total_tokens"), int):
        response_tokens = usage["total_tokens"]

    if status != HTTPStatus.OK:
        result = "REQUEST_FAILED_AFTER_EVICTION"
        response_model = "UNKNOWN"
        response_tokens = "UNKNOWN"
    elif response_model == PRIMARY_MODEL:
        result = "PRIMARY_SERVED"
    elif response_model == BACKUP_MODEL:
        result = "BACKUP_SERVED"
    else:
        result = "UNEXPECTED_MODEL"

    return {
        "action_id": action_id,
        "gateway": gateway,
        "http_status": status,
        "response_model": response_model,
        "response_tokens": response_tokens,
        "result": result,
        "scenario": scenario,
    }


def _contains_failure_trigger(body: dict[str, Any]) -> bool:
    return "FAIL_PRIMARY" in json.dumps(body, ensure_ascii=False)


def _openai_response(model: str) -> dict[str, Any]:
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "index": 0,
                "message": {"content": "fixture response", "role": "assistant"},
            }
        ],
        "created": 1_789_056_000,
        "id": f"chatcmpl-{model}",
        "model": model,
        "object": "chat.completion",
        "usage": {"completion_tokens": 5, "prompt_tokens": 11, "total_tokens": 16},
    }


def _anthropic_response(model: str) -> dict[str, Any]:
    return {
        "content": [{"text": "fixture response", "type": "text"}],
        "id": f"msg-{model}",
        "model": model,
        "role": "assistant",
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "type": "message",
        "usage": {"input_tokens": 7, "output_tokens": 3},
    }
