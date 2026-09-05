import json
from email.message import Message
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from gateway_runtime.provider import MockProvider


def post(
    url: str,
    *,
    authorization: str,
    payload: dict[str, object] | None = None,
) -> tuple[int, Message, bytes]:
    request = Request(
        url,
        data=json.dumps(payload or {"model": "lab-model", "messages": []}).encode(),
        headers={
            "authorization": authorization,
            "content-type": "application/json",
            "x-audit-kind": "WORKLOAD_CONSUMER_KEY",
            "x-audit-human": "NOT_APPLICABLE",
            "x-audit-workload": "workload/runtime-a",
            "x-audit-consumer": "key/runtime-a",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=2) as response:
            return response.status, response.headers, response.read()
    except HTTPError as error:
        return error.code, error.headers, error.read()


def test_mock_provider_reports_only_safe_upstream_observations() -> None:
    with MockProvider(
        provider_key="provider-secret",
        incoming_credentials={"consumer-secret"},
    ) as provider:
        status, _, raw_body = post(
            provider.url + "/v1/chat/completions",
            authorization="Bearer provider-secret",
        )
        body = json.loads(raw_body)

    assert status == 200
    assert body["provider_auth"] == "MATCHED"
    assert body["incoming_credential_forwarded"] is False
    assert body["audit_human"] == "NOT_APPLICABLE"
    assert "provider-secret" not in json.dumps(body)


def test_mock_provider_rejects_a_consumer_key_as_backend_auth() -> None:
    with MockProvider(
        provider_key="provider-secret",
        incoming_credentials={"consumer-secret"},
    ) as provider:
        status, _, raw_body = post(
            provider.url + "/v1/chat/completions",
            authorization="Bearer consumer-secret",
        )
        body = json.loads(raw_body)

    assert status == 401
    assert body["provider_auth"] == "MISMATCH"
    assert body["incoming_credential_forwarded"] is True


def test_mock_provider_requires_the_openai_compatible_path() -> None:
    with MockProvider(provider_key="provider-secret", incoming_credentials=set()) as provider:
        with pytest.raises(HTTPError) as error:
            urlopen(provider.url + "/wrong", timeout=2)

    assert error.value.code == 404


def test_mock_provider_emits_openai_compatible_sse() -> None:
    with MockProvider(provider_key="provider-secret", incoming_credentials=set()) as provider:
        status, headers, body = post(
            provider.url + "/v1/chat/completions",
            authorization="Bearer provider-secret",
            payload={"model": "lab-model", "messages": [], "stream": True},
        )

    records = [line for line in body.decode().splitlines() if line]
    assert status == 200
    assert headers.get_content_type() == "text/event-stream"
    assert records[-1] == "data: [DONE]"
    assert json.loads(records[0].removeprefix("data: "))["choices"][0]["delta"]["content"] == "lab-"
    assert json.loads(records[1].removeprefix("data: "))["choices"][0]["delta"]["content"] == "ok"


def test_mock_provider_exposes_rate_limit_without_retrying_itself() -> None:
    with MockProvider(provider_key="provider-secret", incoming_credentials=set()) as provider:
        status, headers, raw_body = post(
            provider.url + "/v1/chat/completions",
            authorization="Bearer provider-secret",
            payload={"model": "lab-rate-limited", "messages": []},
        )
        request_count = provider.request_count("rate-limit")

    body = json.loads(raw_body)
    assert status == 429
    assert headers["retry-after"] == "7"
    assert body["error"]["code"] == "synthetic_rate_limit"
    assert request_count == 1
