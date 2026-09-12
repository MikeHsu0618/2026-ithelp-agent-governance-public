from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen


def fetch_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:  # noqa: S310 - URL is validated before use
        return json.load(response)


def validate_backend_url(url: str) -> str:
    parsed = urlsplit(url.rstrip("/"))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("backend URL must use http on localhost or 127.0.0.1")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("backend URL must not include credentials, query, or fragment")
    return url.rstrip("/")


def verify_backend(
    artifact_dir: Path,
    *,
    tempo_url: str = "http://127.0.0.1:13200",
    loki_url: str = "http://127.0.0.1:13100",
    fetch_json: Callable[[str], dict[str, Any]] = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 10,
) -> dict[str, str]:
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    action_id = str(manifest["action_id"])
    trace_id = str(manifest["trace_id"])
    tempo_base = validate_backend_url(tempo_url)
    loki_base = validate_backend_url(loki_url)
    tempo_endpoint = f"{tempo_base}/api/v2/traces/{trace_id}"
    query = '{service_name="ithelp-traceability-lab"} |= "' + action_id + '"'
    loki_endpoint = f"{loki_base}/loki/api/v1/query_range?{urlencode({'query': query})}"
    tempo_found = False
    loki_found = False
    for attempt in range(attempts):
        tempo_payload = fetch_json(tempo_endpoint)
        loki_payload = fetch_json(loki_endpoint)
        tempo_found = action_id in json.dumps(tempo_payload, sort_keys=True)
        loki_found = action_id in json.dumps(loki_payload, sort_keys=True)
        if tempo_found and loki_found:
            break
        if attempt + 1 < attempts:
            sleep(1)
    return {
        "action_id": action_id,
        "trace_id": trace_id,
        "tempo_trace": "PASS" if tempo_found else "FAIL",
        "loki_governance_event": "PASS" if loki_found else "FAIL",
        "correlation": "PASS" if tempo_found and loki_found else "FAIL",
    }
