from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import jwt

from traceability_lab.cardinality import (
    build_traffic_cases,
    issue_access_token,
    prepare_identity_material,
    run_cardinality_traffic,
)

LAB_ROOT = Path(__file__).resolve().parents[1]


class FakeResponse(BytesIO):
    def __init__(self, body: bytes = b"", *, status: int = 200) -> None:
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def test_prepare_identity_material_keeps_private_key_local_and_jwks_public(tmp_path: Path) -> None:
    material = prepare_identity_material(tmp_path, now=datetime(2026, 9, 14, tzinfo=UTC))

    private_mode = stat.S_IMODE(material.private_key_path.stat().st_mode)
    jwks = json.loads(material.jwks_path.read_text(encoding="utf-8"))

    assert private_mode == 0o600
    assert material.private_key_path.parent == tmp_path
    assert material.jwks_path.parent == tmp_path
    assert jwks["keys"][0]["kid"] == material.key_id
    assert jwks["keys"][0]["kty"] == "RSA"
    assert not {"d", "p", "q", "dp", "dq", "qi"}.intersection(jwks["keys"][0])


def test_access_token_contains_the_bounded_team_and_synthetic_principal(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    material = prepare_identity_material(tmp_path, now=now)
    traffic_case = build_traffic_cases(user_count=3, conversations_per_user=1)[0]

    token = issue_access_token(material, traffic_case, now=now)
    public_key = jwt.PyJWK.from_dict(
        json.loads(material.jwks_path.read_text(encoding="utf-8"))["keys"][0]
    ).key
    claims = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        audience=material.audience,
        issuer=material.issuer,
    )

    assert claims["sub"] == "user/sre-oncaller-000"
    assert claims["team"] == "platform"
    assert claims["token_use"] == "access"


def test_traffic_matrix_reuses_the_same_requests_for_all_three_gateway_variants() -> None:
    cases = build_traffic_cases(user_count=6, conversations_per_user=2)

    assert len(cases) == 12
    assert len({item.subject for item in cases}) == 6
    assert len({item.conversation_id for item in cases}) == 12
    assert {item.team for item in cases} == {"observability", "platform", "security"}


def test_cardinality_run_sends_signed_requests_without_persisting_tokens(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    artifact_root = tmp_path / "artifacts"
    prepare_identity_material(runtime_dir, now=datetime(2026, 9, 14, tzinfo=UTC))
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout))
        status = 401 if len(requests) <= 2 else 200
        return FakeResponse(b'{"status":"ok"}', status=status)

    summary = run_cardinality_traffic(
        runtime_dir=runtime_dir,
        artifact_root=artifact_root,
        gateway_urls={
            "bounded": "http://127.0.0.1:28081",
            "user": "http://127.0.0.1:28082",
            "conversation": "http://127.0.0.1:28083",
        },
        user_count=3,
        conversations_per_user=2,
        opener=opener,
        now=datetime(2026, 9, 14, 8, 0, tzinfo=UTC),
    )

    assert summary.requests_per_variant == 6
    assert summary.successful_requests == 18
    assert summary.missing_token_status == 401
    assert summary.wrong_audience_status == 401
    assert len(requests) == 20
    assert requests[0][0].headers.get("Authorization") is None
    assert requests[1][0].headers["Authorization"].startswith("Bearer ey")
    assert all(item[0].headers["Authorization"].startswith("Bearer ey") for item in requests[2:])
    assert all(item[0].headers["X-conversation-id"].startswith("conv-") for item in requests)
    traceparents = [item[0].headers["Traceparent"] for item in requests[2:]]
    assert all(value.startswith("00-") and value.endswith("-01") for value in traceparents)
    assert len(set(traceparents)) == 18
    assert all(item[1] == 5 for item in requests)

    report_path = Path(summary.artifact_dir) / "cardinality-run.json"
    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["sample_principal"] == "user/sre-oncaller-000"
    assert report["sample_conversation_id"] == "conv-000-00"
    assert report["sample_trace_id"] == traceparents[0].split("-")[1]
    assert "Bearer " not in report_text
    assert ".private.pem" not in report_text


def test_day23_alloy_scrape_timeout_is_shorter_than_the_two_second_interval() -> None:
    config = (LAB_ROOT / "config.day23.alloy").read_text(encoding="utf-8")

    assert config.count('scrape_interval = "2s"') == 3
    assert config.count('scrape_timeout  = "1s"') == 3


def test_day23_dashboard_uses_real_prometheus_and_loki_queries() -> None:
    payload = json.loads(
        (LAB_ROOT / "configs/day-23/grafana-dashboard.json").read_text(encoding="utf-8")
    )
    dashboard = payload["dashboard"]
    expressions = [
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
        if "expr" in target
    ]

    assert dashboard["uid"] == "day23-agentgateway-cardinality"
    assert any('job="agentgateway-bounded"' in expression for expression in expressions)
    assert any('job="agentgateway-user"' in expression for expression in expressions)
    assert any('job="agentgateway-conversation"' in expression for expression in expressions)
    assert any("identity_user_id" in expression for expression in expressions)
