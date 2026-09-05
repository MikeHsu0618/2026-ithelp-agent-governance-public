"""Execute the Day 14 credential cases through one live agentgateway."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from gateway_runtime.artifacts import ArtifactStore, assert_values_absent
from gateway_runtime.config import build_agentgateway_config, redacted_config
from gateway_runtime.contract import CredentialCase, GatewayObservation, assess
from gateway_runtime.credentials import EphemeralCredentials
from gateway_runtime.provider import MockProvider
from gateway_runtime.runtime import (
    AGENTGATEWAY_IMAGE,
    DockerGateway,
    validate_config,
    write_runtime_files,
)


def run_lab(artifact_root: Path) -> dict[str, Any]:
    """Run nine cases and persist only redacted, reproducible evidence."""

    material = EphemeralCredentials.create()
    valid_jwt = material.issue_human_jwt()
    wrong_issuer_jwt = material.issue_human_jwt(issuer="https://other-issuer.lab.example/")
    wrong_audience_jwt = material.issue_human_jwt(audience="some-other-service")
    missing_issuer_jwt = material.issue_human_jwt(omit_claims={"iss"})
    missing_audience_jwt = material.issue_human_jwt(omit_claims={"aud"})
    incoming_credentials = {
        material.human_virtual_key,
        material.workload_consumer_key,
        material.retired_workload_key,
        valid_jwt,
        wrong_issuer_jwt,
        wrong_audience_jwt,
        missing_issuer_jwt,
        missing_audience_jwt,
    }
    raw_credentials = incoming_credentials | {material.provider_key}

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    store = ArtifactStore(artifact_root, run_id)
    with MockProvider(
        provider_key=material.provider_key,
        incoming_credentials=incoming_credentials,
    ) as provider:
        provider_host = f"host.docker.internal:{provider.port}"
        config = build_agentgateway_config(
            material,
            provider_host=provider_host,
            jwks_path="/config/jwks.json",
        )
        with tempfile.TemporaryDirectory(prefix="ithelp-lab03-") as runtime_directory:
            runtime_dir = Path(runtime_directory)
            write_runtime_files(runtime_dir, config, material.public_jwks())
            validate_config(runtime_dir / "agentgateway.json")
            with DockerGateway(runtime_dir) as gateway:
                requests = _cases(
                    material,
                    valid_jwt,
                    wrong_issuer_jwt,
                    wrong_audience_jwt,
                    missing_issuer_jwt,
                    missing_audience_jwt,
                )
                results = [
                    _execute_case(gateway.url, case, credential, route_kind, material)
                    for case, credential, route_kind in requests
                ]

    report: dict[str, Any] = {
        "schema": "ithelp.gateway-runtime.report.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "runtime": {
            "gateway_count": 1,
            "gateway_image": AGENTGATEWAY_IMAGE,
            "backend": "synthetic-openai-compatible-provider",
        },
        "cases": results,
        "summary": {
            "matched": sum(1 for result in results if result["matched"]),
            "total": len(results),
        },
    }
    store.write_json("evidence/report.json", report)
    store.write_json("evidence/agentgateway-config.redacted.json", redacted_config(config))
    store.write_json("evidence/jwks.public.json", material.public_jwks())
    store.write_text("evidence/decision-table.md", _decision_table(results))
    store.write_text("evidence/terminal.txt", _terminal_output(results, report["summary"]))
    store.write_json(
        "manifest.json",
        {
            "files": [
                "evidence/agentgateway-config.redacted.json",
                "evidence/decision-table.md",
                "evidence/jwks.public.json",
                "evidence/report.json",
                "evidence/terminal.txt",
            ],
            "raw_credentials_persisted": False,
            "run_id": run_id,
        },
    )
    assert_values_absent(store.run_dir, raw_credentials)
    report["artifact_dir"] = str(store.run_dir)
    return report


def _cases(
    material: EphemeralCredentials,
    valid_jwt: str,
    wrong_issuer_jwt: str,
    wrong_audience_jwt: str,
    missing_issuer_jwt: str,
    missing_audience_jwt: str,
) -> list[tuple[CredentialCase, str, str]]:
    return [
        (
            CredentialCase("human-key-active", "HUMAN_VIRTUAL_KEY", "ACTIVE", "KEY_MAPPING_ACTIVE"),
            material.human_virtual_key,
            "api-key",
        ),
        (
            CredentialCase(
                "human-key-after-offboarding",
                "HUMAN_VIRTUAL_KEY",
                "DISABLED",
                "STALE_MAPPING_ALLOWED",
            ),
            material.human_virtual_key,
            "api-key",
        ),
        (
            CredentialCase(
                "workload-key",
                "WORKLOAD_CONSUMER_KEY",
                "NOT_APPLICABLE",
                "WORKLOAD_KEY_ISOLATED",
            ),
            material.workload_consumer_key,
            "api-key",
        ),
        (
            CredentialCase(
                "retired-workload-key",
                "RETIRED_WORKLOAD_CONSUMER_KEY",
                "NOT_APPLICABLE",
                "OLD_KEY_REJECTED",
            ),
            material.retired_workload_key,
            "api-key",
        ),
        (
            CredentialCase("jwt-human", "JWT_PRINCIPAL", "ACTIVE", "JWT_PRINCIPAL_VERIFIED"),
            valid_jwt,
            "jwt",
        ),
        (
            CredentialCase(
                "jwt-wrong-issuer",
                "JWT_WRONG_ISSUER",
                "ACTIVE",
                "JWT_ISSUER_REJECTED",
            ),
            wrong_issuer_jwt,
            "jwt",
        ),
        (
            CredentialCase(
                "jwt-wrong-audience",
                "JWT_WRONG_AUDIENCE",
                "ACTIVE",
                "JWT_AUDIENCE_REJECTED",
            ),
            wrong_audience_jwt,
            "jwt",
        ),
        (
            CredentialCase(
                "jwt-missing-issuer",
                "JWT_MISSING_ISSUER",
                "ACTIVE",
                "JWT_ISSUER_REQUIRED",
            ),
            missing_issuer_jwt,
            "jwt",
        ),
        (
            CredentialCase(
                "jwt-missing-audience",
                "JWT_MISSING_AUDIENCE",
                "ACTIVE",
                "JWT_AUDIENCE_REQUIRED",
            ),
            missing_audience_jwt,
            "jwt",
        ),
    ]


def _execute_case(
    gateway_url: str,
    case: CredentialCase,
    credential: str,
    route_kind: str,
    material: EphemeralCredentials,
) -> dict[str, Any]:
    request = Request(
        gateway_url + "/v1/chat/completions",
        data=json.dumps(
            {"model": "lab-model", "messages": [{"role": "user", "content": "ping"}]}
        ).encode(),
        headers={
            "authorization": f"Bearer {credential}",
            "content-type": "application/json",
            "x-demo-credential": route_kind,
        },
        method="POST",
    )
    body: dict[str, Any] = {}
    status_code: int
    try:
        with urlopen(request, timeout=3) as response:
            status_code = int(response.status)
            body = json.loads(response.read())
    except HTTPError as error:
        status_code = int(error.code)
        if error.headers.get_content_type() == "application/json":
            body = json.loads(error.read())

    observation = GatewayObservation(
        status_code=status_code,
        audit_kind=body.get("audit_kind"),
        human=body.get("audit_human"),
        workload=body.get("audit_workload"),
        consumer=body.get("audit_consumer"),
        provider_auth=body.get("provider_auth", "NOT_REACHED"),
        incoming_credential_forwarded=body.get("incoming_credential_forwarded", False),
    )
    event: dict[str, Any] = dict(assess(case, observation).to_event())
    event["credential_fingerprint"] = material.fingerprint(credential)
    event["http_status"] = status_code
    return event


def _decision_table(results: list[dict[str, Any]]) -> str:
    lines = [
        "| Case | Gateway | Control | Code | Human | Workload | Upstream |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        lines.append(
            "| {case_id} | {gateway_decision} | {control_result} | {code} | "
            "{human} | {workload} | {provider_auth} |".format(**result)
        )
    return "\n".join(lines) + "\n"


def _terminal_output(results: list[dict[str, Any]], summary: dict[str, int]) -> str:
    lines = ["DAY 14 / CREDENTIAL BOUNDARY", ""]
    for result in results:
        lines.append(f"{result['case_id']:<31} {result['gateway_decision']:<5}  {result['code']}")
    lines.extend(["", f"matched {summary['matched']}/{summary['total']}"])
    return "\n".join(lines) + "\n"
