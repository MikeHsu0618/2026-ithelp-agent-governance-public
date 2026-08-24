import json
from pathlib import Path

from google.adk.models.llm_response import LlmResponse
from google.genai import types

from unsafe_agent.adk_agent import ExecutionState, build_live_model_recorder
from unsafe_agent.artifacts import ArtifactStore


def test_live_model_recorder_keeps_tool_decision_without_provider_metadata(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts", "live-test")
    state = ExecutionState()
    recorder = build_live_model_recorder(
        store=store,
        state=state,
        trace_id="a" * 32,
        span_id="b" * 16,
    )
    response = LlmResponse(
        model_version="gemini-test",
        custom_metadata={"provider-internal": "must-not-be-persisted"},
        content=types.Content(
            role="model",
            parts=[
                types.Part.from_function_call(
                    name="delete_demo_database",
                    args={"database": "payments-demo", "ticket": "INC-DEMO-001"},
                )
            ],
        ),
    )

    recorder(None, response)

    events = (store.run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert state.model_outputs[0]["tool_name"] == "delete_demo_database"
    assert "provider-internal" not in events


def test_live_model_recorder_preserves_text_as_model_output(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts", "live-text-test")
    state = ExecutionState()
    recorder = build_live_model_recorder(
        store=store,
        state=state,
        trace_id="a" * 32,
        span_id="b" * 16,
    )

    recorder(
        None,
        LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text="No Tool Call was proposed.")],
            )
        ),
    )

    assert state.model_outputs == [{"decision": "MODEL_TEXT", "text": "No Tool Call was proposed."}]
    assert not (store.run_dir / "events.jsonl").exists()


def test_live_model_recorder_ignores_empty_response(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts", "live-empty-test")
    state = ExecutionState()
    recorder = build_live_model_recorder(
        store=store,
        state=state,
        trace_id="a" * 32,
        span_id="b" * 16,
    )

    recorder(None, LlmResponse())

    assert json.loads(json.dumps(state.model_outputs)) == []
