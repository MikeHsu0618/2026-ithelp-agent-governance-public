import json
from pathlib import Path
from typing import Any


class TraceNotFoundError(LookupError):
    """Raised when no structured Lab event matches a trace ID."""


def replay_trace(artifact_root: Path, trace_id: str) -> list[dict[str, Any]]:
    """Read custom Lab events and return one trace in timestamp order."""

    timeline: list[dict[str, Any]] = []
    if artifact_root.is_dir():
        for events_path in sorted(artifact_root.glob("*/events.jsonl")):
            for line in events_path.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event.get("trace_id") == trace_id:
                    timeline.append(event)

    if not timeline:
        raise TraceNotFoundError(f"trace ID was not found: {trace_id}")
    return sorted(timeline, key=lambda event: str(event["timestamp"]))
