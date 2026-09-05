import json
from pathlib import Path

import pytest

from gateway_runtime.traffic import run_traffic_lab


@pytest.mark.integration
def test_single_agentgateway_preserves_the_day_15_traffic_contract(tmp_path: Path) -> None:
    report = run_traffic_lab(tmp_path / "artifacts")

    results = {item["case_id"]: item for item in report["cases"]}
    assert set(results) == {
        "normal-json",
        "sse-stream",
        "missing-caller-credential",
        "invalid-caller-credential",
        "upstream-rate-limit",
        "backend-credential-isolation",
    }
    assert all(item["matched"] for item in results.values())
    assert results["normal-json"]["http_status"] == 200
    assert results["sse-stream"]["content_type"] == "text/event-stream"
    assert results["sse-stream"]["events"] == ["lab-", "ok", "[DONE]"]
    assert results["sse-stream"]["first_event_before_upstream_complete"] is True
    assert results["missing-caller-credential"]["http_status"] == 401
    assert results["missing-caller-credential"]["upstream_requests"] == 0
    assert results["invalid-caller-credential"]["http_status"] == 401
    assert results["invalid-caller-credential"]["upstream_requests"] == 0
    assert results["upstream-rate-limit"]["http_status"] == 429
    assert results["upstream-rate-limit"]["retry_after"] == "7"
    assert results["upstream-rate-limit"]["upstream_requests"] == 1
    assert results["backend-credential-isolation"]["provider_auth"] == "MATCHED"
    assert results["backend-credential-isolation"]["incoming_credential_forwarded"] is False
    assert report["runtime"]["gateway_count"] == 1
    assert report["summary"] == {"matched": 6, "total": 6}

    artifact_dir = Path(report["artifact_dir"])
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in artifact_dir.rglob("*") if path.is_file()
    )
    assert "provider-secret" not in serialized
    evidence = json.loads((artifact_dir / "evidence" / "traffic-report.json").read_text())
    assert evidence["runtime"]["gateway_count"] == 1
