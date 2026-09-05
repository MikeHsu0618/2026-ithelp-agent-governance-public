from pathlib import Path

import pytest

from gateway_runtime.demo import run_lab


@pytest.mark.integration
def test_pinned_agentgateway_exposes_the_nine_expected_outcomes(tmp_path: Path) -> None:
    report = run_lab(tmp_path / "artifacts")

    assert [item["case_id"] for item in report["cases"]] == [
        "human-key-active",
        "human-key-after-offboarding",
        "workload-key",
        "retired-workload-key",
        "jwt-human",
        "jwt-wrong-issuer",
        "jwt-wrong-audience",
        "jwt-missing-issuer",
        "jwt-missing-audience",
    ]
    results = {item["case_id"]: item for item in report["cases"]}
    assert set(results) == {
        "human-key-active",
        "human-key-after-offboarding",
        "workload-key",
        "retired-workload-key",
        "jwt-human",
        "jwt-wrong-issuer",
        "jwt-wrong-audience",
        "jwt-missing-issuer",
        "jwt-missing-audience",
    }
    assert all(item["matched"] for item in results.values())
    assert results["human-key-after-offboarding"]["code"] == "STALE_MAPPING_ALLOWED"
    assert (
        results["human-key-active"]["credential_fingerprint"]
        == results["human-key-after-offboarding"]["credential_fingerprint"]
    )
    assert results["workload-key"]["code"] == "WORKLOAD_KEY_ISOLATED"
    assert results["jwt-human"]["human"] == "user/sre-oncaller"
    assert all(not item["incoming_credential_forwarded"] for item in results.values())
    assert all(
        results[case_id]["provider_auth"] == "MATCHED"
        for case_id in [
            "human-key-active",
            "human-key-after-offboarding",
            "workload-key",
            "jwt-human",
        ]
    )
    assert results["retired-workload-key"]["http_status"] == 401
    assert results["jwt-wrong-issuer"]["http_status"] == 401
    assert results["jwt-wrong-audience"]["http_status"] == 401
    assert results["jwt-missing-issuer"]["http_status"] == 401
    assert results["jwt-missing-audience"]["http_status"] == 401
    assert report["summary"] == {"matched": 9, "total": 9}
