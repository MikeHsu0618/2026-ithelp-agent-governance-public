from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from google.adk.agents import Agent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.genai import types

from traceability_lab.artifacts import ArtifactStore
from traceability_lab.mcp_outcome import (
    _discover_loki_datasource,
    _push_loki_log,
    build_loki_push_payload,
)

SRE_AGENT_ACTION_ID = "act-day25-adk-query"
SRE_AGENT_TRACE_ID = "25" * 16
SRE_AGENT_SERVICE = "day25-sre-agent"


@dataclass(slots=True)
class SreAgentState:
    model_calls: int = 0
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    tool_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SreAgentRunSummary:
    artifact_dir: str
    runtime: str
    configured_path: tuple[str, ...]
    tool_name: str
    tool_arguments: dict[str, Any]
    tool_summary: dict[str, Any]

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["configured_path"] = list(self.configured_path)
        return payload


def build_query_arguments(
    *, datasource_uid: str, start: str, end: str, action_id: str
) -> dict[str, Any]:
    return {
        "datasourceUid": datasource_uid,
        "startRfc3339": start,
        "endRfc3339": end,
        "limit": 5,
        "format": "full",
        "logql": f'{{service_name="{SRE_AGENT_SERVICE}"}} |= "{action_id}"',
    }


def summarize_loki_response(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("isError") is True:
        return {"result": "ERROR", "lines_returned": 0}

    structured = response.get("structuredContent")
    if not isinstance(structured, dict):
        content = response.get("content")
        if isinstance(content, list) and content and isinstance(content[0], dict):
            text = content[0].get("text")
            if isinstance(text, str):
                try:
                    decoded = json.loads(text)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, dict):
                    structured = decoded
        if not isinstance(structured, dict):
            return {"result": "UNKNOWN", "lines_returned": 0}
    data = structured.get("data")
    metadata = structured.get("metadata")
    if not isinstance(data, list) or not isinstance(metadata, dict):
        return {"result": "UNKNOWN", "lines_returned": 0}
    if not data:
        return {
            "result": "NO_MATCH",
            "lines_returned": int(metadata.get("linesReturned", 0)),
            "results_truncated": bool(metadata.get("resultsTruncated", False)),
        }

    matching_item = next(
        (
            item
            for item in data
            if _has_expected_correlation(
                item,
                service_name=SRE_AGENT_SERVICE,
                action_id=SRE_AGENT_ACTION_ID,
                trace_id=SRE_AGENT_TRACE_ID,
            )
        ),
        None,
    )
    if matching_item is None:
        return {
            "result": "UNVERIFIED",
            "lines_returned": int(metadata.get("linesReturned", len(data))),
            "results_truncated": bool(metadata.get("resultsTruncated", False)),
        }
    labels = matching_item["labels"]
    structured_metadata = matching_item["structuredMetadata"]
    return {
        "result": "USABLE",
        "lines_returned": int(metadata.get("linesReturned", len(data))),
        "results_truncated": bool(metadata.get("resultsTruncated", False)),
        "service_name": labels.get("service_name"),
        "action_id": structured_metadata.get("action_id"),
        "trace_id": structured_metadata.get("trace_id"),
    }


def capture_tool_response(state: SreAgentState):
    def callback(tool, args, tool_context, tool_response):
        _ = tool_context
        state.tool_name = tool.name
        state.tool_arguments = dict(args)
        state.tool_summary = summarize_loki_response(tool_response)
        return None

    return callback


def build_fixture_model_callback(*, arguments: dict[str, Any], state: SreAgentState):
    def callback(callback_context, llm_request: LlmRequest) -> LlmResponse:
        _ = callback_context, llm_request
        state.model_calls += 1
        if state.model_calls == 1:
            return LlmResponse(
                model_version="deterministic-adk-callback",
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_function_call(
                            name="query_loki_logs",
                            args=arguments,
                        )
                    ],
                ),
            )

        lines = state.tool_summary.get("lines_returned", 0)
        action_id = state.tool_summary.get("action_id", "UNKNOWN")
        final_text = (
            f"Loki 查到 {lines} 筆符合條件的錯誤紀錄，其中一筆可用 action_id={action_id} 繼續追查。"
        )
        return LlmResponse(
            model_version="deterministic-adk-callback",
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=final_text)],
            ),
        )

    return callback


def build_sre_agent(*, endpoint: str, arguments: dict[str, Any], state: SreAgentState) -> Agent:
    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=endpoint,
            timeout=10,
            sse_read_timeout=30,
        ),
        tool_filter=["query_loki_logs"],
    )
    return Agent(
        name="sre_loki_investigator",
        model="gemini-2.5-flash",
        description="Queries bounded Loki evidence through agentgateway and Grafana MCP.",
        instruction=(
            "Investigate the supplied synthetic incident by querying Loki. "
            "Use only the read-only query_loki_logs tool and report correlation identifiers."
        ),
        tools=[toolset],
        before_model_callback=build_fixture_model_callback(arguments=arguments, state=state),
        after_tool_callback=capture_tool_response(state),
        generate_content_config=types.GenerateContentConfig(temperature=0),
    )


async def _run_agent(agent: Agent) -> list[dict[str, Any]]:
    runner = InMemoryRunner(agent=agent, app_name="day25_sre_agent")
    user_id = "synthetic-sre-oncaller"
    session_id = "day25-grafana-mcp"
    await runner.session_service.create_session(
        app_name="day25_sre_agent",
        user_id=user_id,
        session_id=session_id,
    )
    message = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text=(
                    "找出 day25-sre-agent 最近五分鐘的 synthetic checkout timeout，"
                    "並保留 action_id 與 trace_id。"
                )
            )
        ],
    )
    events: list[dict[str, Any]] = []
    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=message,
        ):
            events.append(event.model_dump(mode="json", by_alias=True, exclude_none=True))
    finally:
        await runner.close()
    return events


def run_sre_agent_investigation(
    *,
    artifact_root: Path,
    gateway_url: str,
    loki_url: str,
    grafana_url: str,
    now: datetime | None = None,
) -> SreAgentRunSummary:
    run_time = now or datetime.now(UTC)
    store = ArtifactStore(artifact_root, f"day25-adk-{run_time.strftime('%Y%m%dT%H%M%SZ')}")
    payload = build_loki_push_payload(
        timestamp_ns=int(run_time.timestamp() * 1e9),
        action_id=SRE_AGENT_ACTION_ID,
        trace_id=SRE_AGENT_TRACE_ID,
        service_name=SRE_AGENT_SERVICE,
    )
    _push_loki_log(loki_url, payload, urlopen)
    datasource_uid = _discover_loki_datasource(grafana_url, urlopen)
    start = (run_time - timedelta(minutes=5)).isoformat(timespec="seconds").replace("+00:00", "Z")
    end = (run_time + timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
    arguments = build_query_arguments(
        datasource_uid=datasource_uid,
        start=start,
        end=end,
        action_id=SRE_AGENT_ACTION_ID,
    )
    state = SreAgentState()
    agent = build_sre_agent(endpoint=gateway_url, arguments=arguments, state=state)
    events = asyncio.run(_run_agent(agent))
    if state.tool_name != "query_loki_logs" or state.tool_summary.get("result") != "USABLE":
        raise RuntimeError(f"SRE Agent did not obtain usable Loki evidence: {state.tool_summary}")

    summary = SreAgentRunSummary(
        artifact_dir=str(store.run_dir),
        runtime="google-adk-python/2.7.0",
        configured_path=("Google ADK", "agentgateway", "mcp-grafana", "Grafana", "Loki"),
        tool_name=state.tool_name,
        tool_arguments=state.tool_arguments,
        tool_summary=state.tool_summary,
    )
    store.write_json("sre-agent-summary.json", summary.to_json_dict())
    store.write_json("adk-event-outline.json", {"event_count": len(events)})
    return summary


def _has_expected_correlation(
    item: Any,
    *,
    service_name: str,
    action_id: str,
    trace_id: str,
) -> bool:
    if not isinstance(item, dict):
        return False
    labels = item.get("labels")
    metadata = item.get("structuredMetadata")
    return (
        isinstance(labels, dict)
        and isinstance(metadata, dict)
        and labels.get("service_name") == service_name
        and metadata.get("action_id") == action_id
        and metadata.get("trace_id") == trace_id
    )
