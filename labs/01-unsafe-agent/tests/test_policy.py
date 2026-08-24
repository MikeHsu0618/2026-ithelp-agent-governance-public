import pytest

from unsafe_agent.policy import PolicyConfigurationError, ToolPolicy


def test_open_policy_allows_dangerous_tool() -> None:
    policy = ToolPolicy(mode="open", version="day-01-open-v1")

    decision = policy.authorize("delete_demo_database")

    assert decision.allowed is True
    assert decision.reason == "open_policy"


def test_allowlist_policy_denies_unlisted_tool() -> None:
    policy = ToolPolicy(
        mode="allowlist",
        version="day-03-allowlist-v1",
        allowed_tools=frozenset({"query_logs", "query_metrics"}),
    )

    decision = policy.authorize("delete_demo_database")

    assert decision.allowed is False
    assert decision.reason == "tool_not_allowlisted"


def test_allowlist_policy_allows_read_only_tool() -> None:
    policy = ToolPolicy(
        mode="allowlist",
        version="day-03-allowlist-v1",
        allowed_tools=frozenset({"query_logs"}),
    )

    decision = policy.authorize("query_logs")

    assert decision.allowed is True


def test_unknown_policy_mode_is_rejected() -> None:
    with pytest.raises(PolicyConfigurationError, match="unsupported policy mode"):
        ToolPolicy(mode="surprise", version="invalid")
