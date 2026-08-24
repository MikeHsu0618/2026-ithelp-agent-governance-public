from dataclasses import dataclass


class PolicyConfigurationError(ValueError):
    """Raised when a policy cannot make a deterministic decision."""


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str
    version: str


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    """A deliberately small policy boundary used before ADK executes a Tool."""

    mode: str
    version: str
    allowed_tools: frozenset[str] = frozenset({"query_logs", "query_metrics"})

    def __post_init__(self) -> None:
        if self.mode not in {"open", "allowlist"}:
            raise PolicyConfigurationError(f"unsupported policy mode: {self.mode}")

    def authorize(self, tool_name: str) -> PolicyDecision:
        if self.mode == "open":
            return PolicyDecision(allowed=True, reason="open_policy", version=self.version)
        if tool_name in self.allowed_tools:
            return PolicyDecision(allowed=True, reason="tool_allowlisted", version=self.version)
        return PolicyDecision(
            allowed=False,
            reason="tool_not_allowlisted",
            version=self.version,
        )
