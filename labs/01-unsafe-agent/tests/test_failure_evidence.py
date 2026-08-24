import asyncio
import json
from pathlib import Path

import pytest

from unsafe_agent import runner
from unsafe_agent.artifacts import ArtifactStore
from unsafe_agent.config import RunConfig
from unsafe_agent.runner import LabRunError, run_scenario


def test_provider_failure_is_redacted_and_persisted(
    monkeypatch, tmp_path: Path, fixture_dir: Path
) -> None:
    async def blocked_provider(*args, **kwargs) -> None:
        raise RuntimeError(
            "403 API_KEY_SERVICE_BLOCKED consumer projects/SYNTHETIC_ID token=must-not-persist"
        )

    monkeypatch.setattr(runner, "run_adk_agent", blocked_provider)

    with pytest.raises(LabRunError, match="API_KEY_SERVICE_BLOCKED") as exc_info:
        run_scenario(
            RunConfig(
                scenario="attack",
                model_mode="live",
                policy_mode="open",
                artifact_root=tmp_path / "artifacts",
                fixture_dir=fixture_dir,
            )
        )

    error_text = (exc_info.value.artifact_dir / "error.json").read_text(encoding="utf-8")
    error = json.loads(error_text)
    assert error["error_code"] == "API_KEY_SERVICE_BLOCKED"
    assert error["retryable"] is False
    assert "SYNTHETIC_ID" not in error_text
    assert "must-not-persist" not in error_text


def test_unknown_provider_failure_keeps_only_exception_class(
    monkeypatch, tmp_path: Path, fixture_dir: Path
) -> None:
    class SyntheticProviderFailure(RuntimeError):
        pass

    async def unknown_provider_failure(*args, **kwargs) -> None:
        raise SyntheticProviderFailure("private provider payload")

    monkeypatch.setattr(runner, "run_adk_agent", unknown_provider_failure)

    with pytest.raises(LabRunError) as exc_info:
        run_scenario(
            RunConfig(
                scenario="attack",
                model_mode="live",
                policy_mode="open",
                artifact_root=tmp_path / "artifacts",
                fixture_dir=fixture_dir,
            )
        )

    error = json.loads((exc_info.value.artifact_dir / "error.json").read_text(encoding="utf-8"))
    assert error["error_code"] == "PROVIDER_ERROR"
    assert error["exception_type"] == "SyntheticProviderFailure"
    assert "private provider payload" not in json.dumps(error)


def test_adk_runner_closes_when_event_stream_fails(monkeypatch, tmp_path: Path) -> None:
    class SessionService:
        async def create_session(self, **kwargs) -> None:
            return None

    class FailingRunner:
        instance = None

        def __init__(self, **kwargs) -> None:
            self.session_service = SessionService()
            self.closed = False
            FailingRunner.instance = self

        async def run_async(self, **kwargs):
            if False:
                yield None
            raise RuntimeError("synthetic event stream failure")

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(runner, "InMemoryRunner", FailingRunner)
    store = ArtifactStore(tmp_path / "artifacts", "failing-stream")

    with pytest.raises(RuntimeError, match="synthetic event stream failure"):
        asyncio.run(runner.run_adk_agent(object(), "prompt", store))

    assert FailingRunner.instance is not None
    assert FailingRunner.instance.closed is True
