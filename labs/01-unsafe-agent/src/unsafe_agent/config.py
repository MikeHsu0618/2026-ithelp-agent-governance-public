from dataclasses import dataclass
from pathlib import Path

SUPPORTED_SCENARIOS = frozenset({"normal", "attack", "attack-obfuscated"})
SUPPORTED_MODEL_MODES = frozenset({"fixture", "live"})
SUPPORTED_POLICY_MODES = frozenset({"open", "allowlist"})
SUPPORTED_INPUT_GUARD_MODES = frozenset({"none", "keyword"})


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Validated inputs for one isolated Lab 01 run."""

    scenario: str
    model_mode: str
    policy_mode: str
    artifact_root: Path
    fixture_dir: Path
    input_guard_mode: str = "none"
    model_name: str = "gemini-2.5-flash"
    policy_version: str | None = None
    input_guard_version: str | None = None

    def __post_init__(self) -> None:
        if self.scenario not in SUPPORTED_SCENARIOS:
            raise ValueError(f"unsupported scenario: {self.scenario}")
        if self.model_mode not in SUPPORTED_MODEL_MODES:
            raise ValueError(f"unsupported model mode: {self.model_mode}")
        if self.policy_mode not in SUPPORTED_POLICY_MODES:
            raise ValueError(f"unsupported policy mode: {self.policy_mode}")
        if self.input_guard_mode not in SUPPORTED_INPUT_GUARD_MODES:
            raise ValueError(f"unsupported input guard mode: {self.input_guard_mode}")

        fixture_path = self.fixture_dir / f"{self.scenario}-log.jsonl"
        if not fixture_path.is_file():
            raise ValueError(f"fixture does not exist: {fixture_path}")

        if self.policy_version is None:
            version = "day-01-open-v1" if self.policy_mode == "open" else "day-03-allowlist-v1"
            object.__setattr__(self, "policy_version", version)
        if self.input_guard_version is None:
            version = "disabled" if self.input_guard_mode == "none" else "day-03-keyword-v1"
            object.__setattr__(self, "input_guard_version", version)
