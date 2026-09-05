"""A tiny OpenAI-compatible backend that records only safe boundary observations."""

import hashlib
import json
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class MockProvider:
    """Serve a synthetic provider on a random local port."""

    def __init__(
        self,
        *,
        provider_key: str,
        incoming_credentials: set[str],
        synchronize_stream: bool = False,
    ) -> None:
        self.provider_key = provider_key
        self.incoming_credentials = incoming_credentials
        self.synchronize_stream = synchronize_stream
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._request_counts: Counter[str] = Counter()
        self._request_counts_lock = threading.Lock()
        self._stream_release = threading.Event()
        self._stream_release_observed = False

    def __enter__(self) -> "MockProvider":
        provider_key = self.provider_key
        incoming_credentials = self.incoming_credentials
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = ""
            sys_version = ""

            def do_GET(self) -> None:  # noqa: N802
                self._write(404, {"error": "not_found"})

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/v1/chat/completions":
                    self._write(404, {"error": "not_found"})
                    return

                content_length = int(self.headers.get("content-length", "0"))
                payload = json.loads(self.rfile.read(content_length))
                authorization = self.headers.get("authorization", "")
                supplied = _bearer_value(authorization)
                forwarded = supplied in incoming_credentials
                matched = supplied == provider_key
                scenario = _scenario(payload)
                with owner._request_counts_lock:
                    owner._request_counts[scenario] += 1
                safe = {
                    "provider_auth": "MATCHED" if matched else "MISMATCH",
                    "provider_credential_fingerprint": _fingerprint(supplied),
                    "incoming_credential_forwarded": forwarded,
                    "audit_kind": self.headers.get("x-audit-kind"),
                    "audit_human": self.headers.get("x-audit-human"),
                    "audit_workload": self.headers.get("x-audit-workload"),
                    "audit_consumer": self.headers.get("x-audit-consumer"),
                }
                if not matched:
                    self._write(401, safe)
                    return
                if scenario == "rate-limit":
                    self._write(
                        429,
                        {
                            "error": {
                                "code": "synthetic_rate_limit",
                                "message": "synthetic provider capacity reached",
                            }
                        },
                        headers={"retry-after": "7"},
                    )
                    return
                if scenario == "stream":
                    self._write_sse()
                    return
                self._write(
                    200,
                    {
                        "id": "chatcmpl-lab",
                        "object": "chat.completion",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": "lab-ok"},
                                "finish_reason": "stop",
                            }
                        ],
                        **safe,
                    },
                )

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _write(
                self,
                status: int,
                payload: dict[str, Any],
                *,
                headers: dict[str, str] | None = None,
            ) -> None:
                body = json.dumps(payload, sort_keys=True).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def _write_sse(self) -> None:
                if owner.synchronize_stream:
                    owner._stream_release.clear()
                    owner._stream_release_observed = False
                chunks = [
                    {
                        "id": "chatcmpl-lab",
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": {"content": "lab-"}}],
                    },
                    {
                        "id": "chatcmpl-lab",
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": {"content": "ok"}}],
                    },
                ]
                records = [f"data: {json.dumps(chunk, sort_keys=True)}\n\n" for chunk in chunks]
                records.append("data: [DONE]\n\n")
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.end_headers()
                for index, record in enumerate(records):
                    self.wfile.write(record.encode())
                    self.wfile.flush()
                    if index == 0 and owner.synchronize_stream:
                        owner._stream_release_observed = owner._stream_release.wait(timeout=2)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)

    @property
    def port(self) -> int:
        if not self._server:
            raise RuntimeError("mock provider has not started")
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def request_count(self, scenario: str) -> int:
        with self._request_counts_lock:
            return self._request_counts[scenario]

    def total_request_count(self) -> int:
        with self._request_counts_lock:
            return self._request_counts.total()

    def release_stream(self) -> None:
        self._stream_release.set()

    @property
    def stream_release_observed(self) -> bool:
        return self._stream_release_observed


def _scenario(payload: dict[str, Any]) -> str:
    if payload.get("model") == "lab-rate-limited":
        return "rate-limit"
    if payload.get("stream") is True:
        return "stream"
    return "normal"


def _bearer_value(authorization: str) -> str:
    prefix = "Bearer "
    return authorization[len(prefix) :] if authorization.startswith(prefix) else authorization


def _fingerprint(value: str) -> str:
    if not value:
        return "NOT_PRESENT"
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()[:16]}"
