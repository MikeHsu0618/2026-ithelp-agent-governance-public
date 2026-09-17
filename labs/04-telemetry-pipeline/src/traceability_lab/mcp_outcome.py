from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from traceability_lab.artifacts import ArtifactStore

MCP_PROTOCOL_VERSION = "2025-06-18"
LAB_ACTION_ID = "act-day25-loki-query"
LAB_TRACE_ID = "25" * 16


@dataclass(frozen=True, slots=True)
class HttpExchange:
    status: int
    content_type: str
    body: bytes
    headers: Mapping[str, str]
    payload: dict[str, Any] | None

    @classmethod
    def from_http(
        cls,
        *,
        status: int,
        content_type: str,
        body: bytes,
        headers: Mapping[str, str],
        expected_response_id: int | str | None = None,
    ) -> HttpExchange:
        return cls(
            status=status,
            content_type=content_type,
            body=body,
            headers={key.casefold(): value for key, value in headers.items()},
            payload=_decode_mcp_payload(
                content_type,
                body,
                expected_response_id=expected_response_id,
            ),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "body_excerpt": self.body.decode("utf-8", errors="replace")[:500],
            "content_type": self.content_type,
            "headers": {
                key: "REDACTED" if key in {"authorization", "mcp-session-id"} else value
                for key, value in self.headers.items()
                if key in {"content-type", "mcp-session-id", "mcp-protocol-version"}
            },
            "http_status": self.status,
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class McpOutcomeSummary:
    artifact_dir: str
    datasource_uid: str
    query_window: Mapping[str, str]
    scenarios: tuple[dict[str, Any], ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "artifact_dir": self.artifact_dir,
            "datasource_uid": self.datasource_uid,
            "query_window": dict(self.query_window),
            "scenarios": list(self.scenarios),
        }


class StreamableMcpClient:
    def __init__(
        self,
        endpoint: str,
        *,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.endpoint = endpoint
        self.opener = opener
        self.session_id: str | None = None
        self.next_id = 1

    def initialize(self) -> HttpExchange:
        exchange = self._request(
            {
                "jsonrpc": "2.0",
                "id": self._id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "ithelp-day25-lab", "version": "1.0.0"},
                },
            }
        )
        self.session_id = exchange.headers.get("mcp-session-id")
        return exchange

    def initialized(self) -> HttpExchange:
        return self._request({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def list_tools(self) -> HttpExchange:
        return self._request(
            {"jsonrpc": "2.0", "id": self._id(), "method": "tools/list", "params": {}}
        )

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> HttpExchange:
        return self._request(
            {
                "jsonrpc": "2.0",
                "id": self._id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": dict(arguments)},
            }
        )

    def close(self) -> HttpExchange | None:
        if not self.session_id:
            return None
        headers = {
            "accept": "application/json, text/event-stream",
            "mcp-protocol-version": MCP_PROTOCOL_VERSION,
            "mcp-session-id": self.session_id,
        }
        request = Request(self.endpoint, headers=headers, method="DELETE")
        try:
            with self.opener(request, timeout=20) as response:
                return HttpExchange.from_http(
                    status=response.status,
                    content_type=response.headers.get("content-type", ""),
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except HTTPError as exc:
            return HttpExchange.from_http(
                status=exc.code,
                content_type=exc.headers.get("content-type", ""),
                body=exc.read(),
                headers=dict(exc.headers.items()),
            )
        finally:
            self.session_id = None

    def _id(self) -> int:
        value = self.next_id
        self.next_id += 1
        return value

    def _request(self, payload: Mapping[str, Any]) -> HttpExchange:
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "mcp-protocol-version": MCP_PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        request = Request(
            self.endpoint,
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with self.opener(request, timeout=20) as response:
                return HttpExchange.from_http(
                    status=response.status,
                    content_type=response.headers.get("content-type", ""),
                    body=response.read(),
                    headers=dict(response.headers.items()),
                    expected_response_id=payload.get("id"),
                )
        except HTTPError as exc:
            return HttpExchange.from_http(
                status=exc.code,
                content_type=exc.headers.get("content-type", ""),
                body=exc.read(),
                headers=dict(exc.headers.items()),
                expected_response_id=payload.get("id"),
            )


def assess_tool_exchange(
    exchange: HttpExchange,
    *,
    expected_service_name: str = "day25-mcp-outcome",
    expected_action_id: str = LAB_ACTION_ID,
    expected_trace_id: str = LAB_TRACE_ID,
) -> dict[str, str]:
    client_http = "PASS" if exchange.status == HTTPStatus.OK else "FAIL"
    if client_http == "FAIL":
        return {
            "client_http": "FAIL",
            "mcp_contract": "NOT_EVALUATED",
            "tool_result": "NOT_REACHED",
            "domain_outcome": "UNKNOWN",
            "classification": "HTTP_ERROR",
        }
    payload = exchange.payload
    if not _is_json_rpc_response(payload):
        return {
            "client_http": client_http,
            "mcp_contract": "FAIL",
            "tool_result": "NOT_REACHED",
            "domain_outcome": "UNKNOWN",
            "classification": "MCP_DECODE_FAILED",
        }

    if "error" in payload:
        return {
            "client_http": client_http,
            "mcp_contract": "ERROR",
            "tool_result": "NOT_REACHED",
            "domain_outcome": "UNKNOWN",
            "classification": "MCP_PROTOCOL_ERROR",
        }

    result = payload.get("result")
    if not isinstance(result, dict):
        return {
            "client_http": client_http,
            "mcp_contract": "FAIL",
            "tool_result": "NOT_REACHED",
            "domain_outcome": "UNKNOWN",
            "classification": "MCP_RESULT_MISSING",
        }
    if result.get("isError") is True:
        return {
            "client_http": client_http,
            "mcp_contract": "PASS",
            "tool_result": "ERROR",
            "domain_outcome": "UNKNOWN",
            "classification": "TOOL_EXECUTION_ERROR",
        }

    tool_payload = _tool_payload(result)
    data = _find_data_list(tool_payload)
    if data is None:
        domain_outcome = "UNKNOWN"
        classification = "TOOL_RESULT_UNCLASSIFIED"
    elif data and _contains_expected_correlation(
        data,
        service_name=expected_service_name,
        action_id=expected_action_id,
        trace_id=expected_trace_id,
    ):
        domain_outcome = "USABLE"
        classification = "USABLE_RESULT"
    elif data:
        domain_outcome = "UNVERIFIED"
        classification = "CORRELATION_MISMATCH"
    else:
        domain_outcome = "NO_MATCH"
        classification = "VALID_BUT_EMPTY"
    return {
        "client_http": client_http,
        "mcp_contract": "PASS",
        "tool_result": "PASS",
        "domain_outcome": domain_outcome,
        "classification": classification,
    }


def find_tool_name(tools: list[dict[str, Any]], wanted: str) -> str:
    matches = [
        str(tool["name"])
        for tool in tools
        if isinstance(tool.get("name"), str)
        and (tool["name"] == wanted or tool["name"].endswith(f"__{wanted}"))
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one MCP tool ending in {wanted!r}, found {matches!r}")
    return matches[0]


def build_loki_push_payload(
    *,
    timestamp_ns: int,
    action_id: str = LAB_ACTION_ID,
    trace_id: str = LAB_TRACE_ID,
    service_name: str = "day25-mcp-outcome",
) -> dict[str, Any]:
    line = f"level=error action_id={action_id} year=2026 msg=synthetic_checkout_timeout"
    return {
        "streams": [
            {
                "stream": {"service_name": service_name},
                "values": [
                    [str(timestamp_ns), line, {"action_id": action_id, "trace_id": trace_id}]
                ],
            }
        ]
    }


def run_mcp_outcome_traffic(
    *,
    artifact_root: Path,
    good_gateway_url: str,
    html_gateway_url: str,
    loki_url: str,
    grafana_url: str,
    html_fixture_url: str,
    opener: Callable[..., Any] = urlopen,
    now: datetime | None = None,
) -> McpOutcomeSummary:
    run_time = now or datetime.now(UTC)
    store = ArtifactStore(artifact_root, f"day25-{run_time.strftime('%Y%m%dT%H%M%SZ')}")
    _push_loki_log(
        loki_url, build_loki_push_payload(timestamp_ns=int(run_time.timestamp() * 1e9)), opener
    )
    datasource_uid = _discover_loki_datasource(grafana_url, opener)
    start = (run_time - timedelta(minutes=5)).isoformat(timespec="seconds").replace("+00:00", "Z")
    end = (run_time + timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
    base_args = {
        "datasourceUid": datasource_uid,
        "startRfc3339": start,
        "endRfc3339": end,
        "limit": 5,
        "format": "full",
    }

    good = StreamableMcpClient(good_gateway_url, opener=opener)
    broken = StreamableMcpClient(html_gateway_url, opener=opener)
    try:
        good_init = good.initialize()
        good.initialized()
        good_tools_exchange = good.list_tools()
        query_tool = find_tool_name(_tools(good_tools_exchange), "query_loki_logs")
        empty = good.call_tool(
            query_tool,
            {**base_args, "logql": '{service_name="day25-mcp-outcome"} |= "year=2025"'},
        )
        usable = good.call_tool(
            query_tool,
            {**base_args, "logql": f'{{service_name="day25-mcp-outcome"}} |= "{LAB_ACTION_ID}"'},
        )

        broken_init = broken.initialize()
        broken.initialized()
        broken_tools_exchange = broken.list_tools()
        broken_query_tool = find_tool_name(_tools(broken_tools_exchange), "query_loki_logs")
        upstream_html = broken.call_tool(
            broken_query_tool,
            {
                **base_args,
                "datasourceUid": "loki",
                "logql": '{service_name="day25-mcp-outcome"}',
            },
        )
        fixture_events = _fetch_json(f"{html_fixture_url.rstrip('/')}/events", opener)["events"]
    finally:
        good.close()
        broken.close()

    scenarios = (
        _scenario("upstream-200-html", upstream_html, fixture_events=fixture_events),
        _scenario("valid-empty-query", empty),
        _scenario("usable-loki-result", usable),
    )
    summary = McpOutcomeSummary(
        artifact_dir=str(store.run_dir),
        datasource_uid=datasource_uid,
        query_window={"start": start, "end": end},
        scenarios=scenarios,
    )
    store.write_json("mcp-outcome-report.json", summary.to_json_dict())
    store.write_json(
        "mcp-handshakes.json",
        {
            "good": good_init.to_json_dict(),
            "html": broken_init.to_json_dict(),
            "tool_name": query_tool,
        },
    )
    (store.run_dir / "terminal.txt").write_text(render_terminal(summary), encoding="utf-8")
    return summary


def render_terminal(summary: McpOutcomeSummary) -> str:
    lines = [
        "DAY 25 / GRAFANA MCP OUTCOME",
        "",
        "scenario                 client-http  mcp      tool     query-outcome",
    ]
    for item in summary.scenarios:
        assessment = item["assessment"]
        lines.append(
            f"{item['scenario']:<24} "
            f"{assessment['client_http']:<12} "
            f"{assessment['mcp_contract']:<8} "
            f"{assessment['tool_result']:<8} "
            f"{assessment['domain_outcome']}"
        )
    http_passes = sum(item["assessment"]["client_http"] == "PASS" for item in summary.scenarios)
    lines.extend(
        ["", f"{http_passes}/{len(summary.scenarios)} client-facing calls returned HTTP 200."]
    )
    return "\n".join(lines) + "\n"


def _scenario(
    name: str,
    exchange: HttpExchange,
    *,
    fixture_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "assessment": assess_tool_exchange(exchange),
        "exchange": exchange.to_json_dict(),
        "scenario": name,
    }
    if fixture_events is not None:
        item["upstream_grafana_api"] = fixture_events
    return item


def _discover_loki_datasource(grafana_url: str, opener: Callable[..., Any]) -> str:
    payload = _fetch_json(f"{grafana_url.rstrip('/')}/api/datasources", opener)
    if not isinstance(payload, list):
        raise ValueError("Grafana datasource response must be a list")
    matches = [item.get("uid") for item in payload if item.get("type") == "loki"]
    if len(matches) != 1 or not isinstance(matches[0], str):
        raise ValueError(f"expected one Loki datasource, found {matches!r}")
    return matches[0]


def _push_loki_log(
    loki_url: str,
    payload: Mapping[str, Any],
    opener: Callable[..., Any],
) -> None:
    request = Request(
        f"{loki_url.rstrip('/')}/loki/api/v1/push",
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with opener(request, timeout=10) as response:
        if response.status != HTTPStatus.NO_CONTENT:
            raise RuntimeError(f"Loki push returned HTTP {response.status}")


def _fetch_json(url: str, opener: Callable[..., Any]) -> Any:
    request = Request(url, headers={"accept": "application/json"})
    with opener(request, timeout=10) as response:
        return json.load(response)


def _tools(exchange: HttpExchange) -> list[dict[str, Any]]:
    if not _is_json_rpc_response(exchange.payload):
        raise ValueError("tools/list did not return a JSON-RPC response")
    result = exchange.payload.get("result")
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        raise ValueError("tools/list response did not contain tools")
    return [item for item in tools if isinstance(item, dict)]


def _is_json_rpc_response(payload: dict[str, Any] | None) -> bool:
    return isinstance(payload, dict) and payload.get("jsonrpc") == "2.0" and "id" in payload


def _decode_mcp_payload(
    content_type: str,
    body: bytes,
    *,
    expected_response_id: int | str | None = None,
) -> dict[str, Any] | None:
    media_type = content_type.partition(";")[0].strip().casefold()
    if media_type == "text/event-stream":
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return None
        payloads: list[dict[str, Any]] = []
        normalized = text.replace("\r\n", "\n")
        for event in normalized.split("\n\n"):
            data_lines = [
                line[5:].lstrip() for line in event.splitlines() if line.startswith("data:")
            ]
            if not data_lines:
                continue
            try:
                payload = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
        if expected_response_id is not None:
            return next(
                (payload for payload in payloads if payload.get("id") == expected_response_id),
                None,
            )
        responses = [payload for payload in payloads if "id" in payload]
        return responses[-1] if responses else (payloads[-1] if payloads else None)
    elif media_type not in {"application/json", "application/json-rpc"}:
        return None
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if expected_response_id is not None and (
        not isinstance(payload, dict) or payload.get("id") != expected_response_id
    ):
        return None
    return payload if isinstance(payload, dict) else None


def _tool_payload(result: Mapping[str, Any]) -> Mapping[str, Any] | None:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = result.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _find_data_list(payload: Mapping[str, Any] | None) -> list[Any] | None:
    if payload is None:
        return None
    data = payload.get("data")
    if isinstance(data, list):
        return data
    for key in ("result", "output"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = _find_data_list(nested)
            if found is not None:
                return found
    return None


def _contains_expected_correlation(
    data: list[Any],
    *,
    service_name: str,
    action_id: str,
    trace_id: str,
) -> bool:
    for item in data:
        if not isinstance(item, dict):
            continue
        labels = item.get("labels")
        metadata = item.get("structuredMetadata")
        if not isinstance(labels, dict) or not isinstance(metadata, dict):
            continue
        if (
            labels.get("service_name") == service_name
            and metadata.get("action_id") == action_id
            and metadata.get("trace_id") == trace_id
        ):
            return True
    return False
