from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Scenario:
    slug: str
    request_path: str
    expected_result: str
    expected_services: tuple[str, ...]


_FULL_PATH = (
    "ithelp-lab-client",
    "agentgateway",
    "agent-runtime",
    "mcp-adapter",
)

SCENARIOS = (
    Scenario("normal-call", "/agent/run", "CANARY_TRIGGERED", _FULL_PATH),
    Scenario(
        "gateway-policy-deny",
        "/agent/denied",
        "DENIED",
        ("ithelp-lab-client", "agentgateway"),
    ),
    Scenario("hitl-approved", "/agent/run", "APPROVED_AND_EXECUTED", _FULL_PATH),
    Scenario(
        "a2a-routing-failure",
        "/agent/run",
        "ROUTING_FAILED",
        ("ithelp-lab-client", "agentgateway", "agent-runtime"),
    ),
    Scenario("llm-fallback", "/agent/run", "FALLBACK_SUCCEEDED", _FULL_PATH),
)


def get_scenario(slug: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.slug == slug:
            return scenario
    raise ValueError(f"unknown scenario: {slug}")
