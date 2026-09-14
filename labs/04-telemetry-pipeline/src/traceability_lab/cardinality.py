from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from traceability_lab.artifacts import ArtifactStore

ISSUER = "https://identity.invalid/day23"
AUDIENCE = "agentgateway-cardinality-lab"
KEY_ID = "day23-ephemeral-key"
TEAM_NAMES = ("platform", "observability", "security")
VARIANT_NAMES = ("bounded", "user", "conversation")


@dataclass(frozen=True, slots=True)
class IdentityMaterial:
    private_key_path: Path
    jwks_path: Path
    issuer: str = ISSUER
    audience: str = AUDIENCE
    key_id: str = KEY_ID

    def to_json_dict(self) -> dict[str, str]:
        return {
            "audience": self.audience,
            "issuer": self.issuer,
            "jwks_path": str(self.jwks_path),
            "key_id": self.key_id,
            "private_key": "LOCAL_RUNTIME_ONLY",
        }


@dataclass(frozen=True, slots=True)
class TrafficCase:
    subject: str
    team: str
    conversation_id: str


@dataclass(frozen=True, slots=True)
class CardinalityRunSummary:
    run_id: str
    artifact_dir: str
    team_count: int
    user_count: int
    conversation_count: int
    requests_per_variant: int
    successful_requests: int
    missing_token_status: int
    wrong_audience_status: int
    sample_principal: str
    sample_conversation_id: str
    sample_trace_id: str
    started_at: str
    finished_at: str

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def prepare_identity_material(
    runtime_dir: Path, *, now: datetime | None = None
) -> IdentityMaterial:
    """Create a fresh signing key locally and expose only its public JWK to agentgateway."""

    runtime_dir.mkdir(parents=True, exist_ok=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = runtime_dir / "day23.private.pem"
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    descriptor = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as private_file:
        os.fchmod(private_file.fileno(), 0o600)
        private_file.write(private_bytes)

    encoded = RSAAlgorithm.to_jwk(private_key.public_key())
    public_jwk = json.loads(encoded) if isinstance(encoded, str) else encoded
    public_jwk.update({"alg": "RS256", "kid": KEY_ID, "use": "sig"})
    jwks_path = runtime_dir / "jwks.json"
    jwks_path.write_text(
        json.dumps({"keys": [public_jwk]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    material = IdentityMaterial(private_key_path=private_path, jwks_path=jwks_path)
    generated_at = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    (runtime_dir / "identity-material.json").write_text(
        json.dumps(
            {**material.to_json_dict(), "generated_at": generated_at},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return material


def load_identity_material(runtime_dir: Path) -> IdentityMaterial:
    material = IdentityMaterial(
        private_key_path=runtime_dir / "day23.private.pem",
        jwks_path=runtime_dir / "jwks.json",
    )
    if not material.private_key_path.is_file() or not material.jwks_path.is_file():
        raise FileNotFoundError("run cardinality-prepare before cardinality-run")
    return material


def build_traffic_cases(
    *, user_count: int = 30, conversations_per_user: int = 3
) -> tuple[TrafficCase, ...]:
    if user_count < len(TEAM_NAMES):
        raise ValueError(f"user_count must be at least {len(TEAM_NAMES)}")
    if conversations_per_user < 1:
        raise ValueError("conversations_per_user must be positive")
    return tuple(
        TrafficCase(
            subject=f"user/sre-oncaller-{user_index:03d}",
            team=TEAM_NAMES[user_index % len(TEAM_NAMES)],
            conversation_id=f"conv-{user_index:03d}-{conversation_index:02d}",
        )
        for user_index in range(user_count)
        for conversation_index in range(conversations_per_user)
    )


def issue_access_token(
    material: IdentityMaterial,
    traffic_case: TrafficCase,
    *,
    now: datetime | None = None,
    audience: str | None = None,
) -> str:
    issued_at = (now or datetime.now(UTC)).astimezone(UTC)
    claims = {
        "aud": audience or material.audience,
        "exp": issued_at + timedelta(minutes=15),
        "iat": issued_at,
        "iss": material.issuer,
        "jti": uuid.uuid4().hex,
        "nbf": issued_at - timedelta(seconds=5),
        "scope": "agent.invoke",
        "sub": traffic_case.subject,
        "team": traffic_case.team,
        "token_use": "access",
    }
    return jwt.encode(
        claims,
        material.private_key_path.read_bytes(),
        algorithm="RS256",
        headers={"kid": material.key_id, "typ": "JWT"},
    )


def _validate_gateway_url(value: str) -> str:
    parsed = urlsplit(value.rstrip("/"))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("gateway URL must use http on localhost or 127.0.0.1")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("gateway URL must not include credentials, query, or fragment")
    return value.rstrip("/")


def _request_status(request: Request, opener: Callable[..., Any]) -> int:
    try:
        with opener(request, timeout=5) as response:
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)


def run_cardinality_traffic(
    *,
    runtime_dir: Path,
    artifact_root: Path,
    gateway_urls: Mapping[str, str],
    user_count: int = 30,
    conversations_per_user: int = 3,
    opener: Callable[..., Any] = urlopen,
    now: datetime | None = None,
) -> CardinalityRunSummary:
    """Send the same authenticated request matrix through three real gateway variants."""

    if set(gateway_urls) != set(VARIANT_NAMES):
        raise ValueError(f"gateway variants must be {', '.join(VARIANT_NAMES)}")
    endpoints = {name: _validate_gateway_url(url) for name, url in gateway_urls.items()}
    material = load_identity_material(runtime_dir)
    cases = build_traffic_cases(
        user_count=user_count,
        conversations_per_user=conversations_per_user,
    )
    started = (now or datetime.now(UTC)).astimezone(UTC)
    successful = 0
    sample_trace_id = ""
    guard_headers = {
        "content-type": "application/json",
        "x-conversation-id": cases[0].conversation_id,
    }
    missing_token_status = _request_status(
        Request(
            endpoints["bounded"] + "/cardinality/run",
            data=b'{"experiment":"day23-auth-guard"}',
            headers=guard_headers,
            method="POST",
        ),
        opener,
    )
    wrong_audience_token = issue_access_token(
        material,
        cases[0],
        now=started,
        audience="another-agentgateway-audience",
    )
    wrong_audience_status = _request_status(
        Request(
            endpoints["bounded"] + "/cardinality/run",
            data=b'{"experiment":"day23-auth-guard"}',
            headers={
                **guard_headers,
                "authorization": f"Bearer {wrong_audience_token}",
            },
            method="POST",
        ),
        opener,
    )
    expected_guards = {"missing token": 401, "wrong audience": 401}
    observed_guards = {
        "missing token": missing_token_status,
        "wrong audience": wrong_audience_status,
    }
    if observed_guards != expected_guards:
        raise RuntimeError(f"agentgateway authentication guards did not match: {observed_guards}")
    tokens = {
        subject: issue_access_token(material, case, now=started)
        for subject, case in {item.subject: item for item in cases}.items()
    }
    for variant in VARIANT_NAMES:
        for traffic_case in cases:
            trace_id = uuid.uuid4().hex
            span_id = uuid.uuid4().hex[:16]
            request = Request(
                endpoints[variant] + "/cardinality/run",
                data=b'{"experiment":"day23"}',
                headers={
                    "authorization": f"Bearer {tokens[traffic_case.subject]}",
                    "content-type": "application/json",
                    "traceparent": f"00-{trace_id}-{span_id}-01",
                    "x-conversation-id": traffic_case.conversation_id,
                },
                method="POST",
            )
            status = _request_status(request, opener)
            if status != 200:
                raise RuntimeError(f"{variant} gateway returned unexpected HTTP {status}")
            if variant == "bounded" and traffic_case == cases[0]:
                sample_trace_id = trace_id
            successful += 1

    finished = datetime.now(UTC) if now is None else started + timedelta(seconds=1)
    run_id = f"day23-{uuid.uuid4().hex[:12]}"
    store = ArtifactStore(artifact_root, run_id)
    summary = CardinalityRunSummary(
        run_id=run_id,
        artifact_dir=str(store.run_dir),
        team_count=len({item.team for item in cases}),
        user_count=len({item.subject for item in cases}),
        conversation_count=len({item.conversation_id for item in cases}),
        requests_per_variant=len(cases),
        successful_requests=successful,
        missing_token_status=missing_token_status,
        wrong_audience_status=wrong_audience_status,
        sample_principal=cases[0].subject,
        sample_conversation_id=cases[0].conversation_id,
        sample_trace_id=sample_trace_id,
        started_at=started.isoformat(),
        finished_at=finished.astimezone(UTC).isoformat(),
    )
    store.write_json(
        "cardinality-run.json",
        {
            **summary.to_json_dict(),
            "gateway_variants": list(VARIANT_NAMES),
            "metric_under_test": "agentgateway_requests_total",
            "source_of_identity": "agentgateway-validated-jwt",
            "traffic_generator_role": "signed-request-client-only",
        },
    )
    return summary
