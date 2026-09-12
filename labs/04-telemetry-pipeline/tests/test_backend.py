import json
from pathlib import Path

import pytest

from traceability_lab.backend import verify_backend


def write_manifest(path: Path) -> None:
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "action_id": "act-day20-backend",
                "trace_id": "a" * 32,
            }
        )
    )


def test_backend_verification_correlates_tempo_and_loki(tmp_path: Path) -> None:
    write_manifest(tmp_path)

    def fetch_json(url: str) -> dict:
        if "/api/v2/traces/" in url:
            return {"resourceSpans": [{"value": "act-day20-backend"}]}
        return {"data": {"result": [{"values": [["1", "act-day20-backend"]]}]}}

    report = verify_backend(tmp_path, fetch_json=fetch_json)

    assert report == {
        "action_id": "act-day20-backend",
        "trace_id": "a" * 32,
        "tempo_trace": "PASS",
        "loki_governance_event": "PASS",
        "correlation": "PASS",
    }


def test_backend_verification_reports_missing_loki_event(tmp_path: Path) -> None:
    write_manifest(tmp_path)

    def fetch_json(url: str) -> dict:
        if "/api/v2/traces/" in url:
            return {"resourceSpans": [{"value": "act-day20-backend"}]}
        return {"data": {"result": []}}

    report = verify_backend(tmp_path, fetch_json=fetch_json, attempts=1)

    assert report["tempo_trace"] == "PASS"
    assert report["loki_governance_event"] == "FAIL"
    assert report["correlation"] == "FAIL"


def test_backend_verification_retries_eventual_ingestion(tmp_path: Path) -> None:
    write_manifest(tmp_path)
    calls = {"tempo": 0, "loki": 0}

    def fetch_json(url: str) -> dict:
        backend = "tempo" if "/api/v2/traces/" in url else "loki"
        calls[backend] += 1
        if calls[backend] == 1:
            return {"data": {"result": []}}
        return {"value": "act-day20-backend"}

    report = verify_backend(
        tmp_path,
        fetch_json=fetch_json,
        sleep=lambda _: None,
        attempts=2,
    )

    assert report["correlation"] == "PASS"
    assert calls == {"tempo": 2, "loki": 2}


@pytest.mark.parametrize(
    ("tempo_url", "loki_url"),
    [
        ("https://localhost:3200", "http://127.0.0.1:13100"),
        ("http://tempo.example:3200", "http://127.0.0.1:13100"),
        ("http://127.0.0.1:13200", "http://user:pass@localhost:3100"),
        ("http://127.0.0.1:13200", "http://localhost:3100?token=secret"),
    ],
)
def test_backend_verification_rejects_non_local_or_credentialed_urls(
    tmp_path: Path, tempo_url: str, loki_url: str
) -> None:
    write_manifest(tmp_path)

    with pytest.raises(ValueError, match="backend URL"):
        verify_backend(tmp_path, tempo_url=tempo_url, loki_url=loki_url)
