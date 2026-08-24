from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class InputGuardDecision:
    allowed: bool
    reason: str
    version: str
    matched_keywords: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KeywordInputGuard:
    """A deliberately brittle keyword filter used to compare guard and authorization."""

    version: str
    blocked_keywords: tuple[str, ...] = ("delete_demo_database", "operator runbook")

    def inspect(self, records: list[dict[str, Any]]) -> InputGuardDecision:
        evidence = "\n".join(str(record.get("message", "")) for record in records).casefold()
        matches = tuple(keyword for keyword in self.blocked_keywords if keyword in evidence)
        if matches:
            return InputGuardDecision(
                allowed=False,
                reason="keyword_match",
                version=self.version,
                matched_keywords=matches,
            )
        return InputGuardDecision(
            allowed=True,
            reason="no_keyword_match",
            version=self.version,
        )
