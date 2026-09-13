from traceability_lab.scenarios import SCENARIOS, get_scenario


def test_day21_suite_contains_five_fixed_scenarios() -> None:
    assert [scenario.slug for scenario in SCENARIOS] == [
        "normal-call",
        "gateway-policy-deny",
        "hitl-approved",
        "a2a-routing-failure",
        "llm-fallback",
    ]


def test_each_scenario_declares_the_expected_boundary_and_result() -> None:
    assert get_scenario("normal-call").expected_services == (
        "ithelp-lab-client",
        "agentgateway",
        "agent-runtime",
        "mcp-adapter",
    )
    assert get_scenario("gateway-policy-deny").expected_result == "DENIED"
    assert get_scenario("a2a-routing-failure").expected_result == "ROUTING_FAILED"
    assert get_scenario("llm-fallback").expected_result == "FALLBACK_SUCCEEDED"


def test_unknown_scenario_is_rejected() -> None:
    try:
        get_scenario("not-a-scenario")
    except ValueError as exc:
        assert "unknown scenario" in str(exc)
    else:
        raise AssertionError("unknown scenario unexpectedly passed")
