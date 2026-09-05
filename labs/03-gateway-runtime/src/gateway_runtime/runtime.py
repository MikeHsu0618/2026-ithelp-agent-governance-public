"""Lifecycle wrapper for the pinned agentgateway container."""

import json
import socket
import subprocess
import time
from collections.abc import Mapping
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

AGENTGATEWAY_IMAGE = (
    "cr.agentgateway.dev/agentgateway@"
    "sha256:bf2f339ef326d32def2aaeb44b1b4549801293c19b89e764a4228667d97d9896"
)


class GatewayStartupError(RuntimeError):
    """Raised when the pinned gateway cannot start with the generated config."""


class DockerGateway:
    """Run one short-lived gateway and remove it when the context exits."""

    def __init__(self, config_dir: Path, *, timeout_seconds: float = 15) -> None:
        self.config_dir = config_dir
        self.timeout_seconds = timeout_seconds
        self.port = _free_port()
        self.container_name = f"ithelp-lab03-{self.port}"
        self.process: subprocess.Popen[str] | None = None
        self._log_stream = None
        self.log_path = config_dir / "agentgateway-runtime.log"

    def __enter__(self) -> "DockerGateway":
        self._log_stream = self.log_path.open("w", encoding="utf-8")
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            self.container_name,
            "--add-host",
            "host.docker.internal:host-gateway",
            "-p",
            f"127.0.0.1:{self.port}:3000",
            "-v",
            f"{self.config_dir.resolve()}:/config:ro",
            AGENTGATEWAY_IMAGE,
            "--file",
            "/config/agentgateway.json",
        ]
        self.process = subprocess.Popen(
            command,
            stdout=self._log_stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            self._wait_until_ready()
        except Exception:
            self._stop()
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._stop()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            if self.process and self.process.poll() is not None:
                break
            try:
                urlopen(self.url + "/__lab_ready__", timeout=0.5)
            except HTTPError:
                return
            except (ConnectionResetError, RemoteDisconnected, URLError):
                time.sleep(0.1)
            else:
                return
        log = self._read_log()
        raise GatewayStartupError(f"agentgateway did not become ready:\n{log}")

    def _stop(self) -> None:
        if self.process and self.process.poll() is None:
            subprocess.run(
                ["docker", "stop", "--time", "1", self.container_name],
                check=False,
                capture_output=True,
                text=True,
            )
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=2)
        if self._log_stream and not self._log_stream.closed:
            self._log_stream.close()

    def _read_log(self) -> str:
        if self._log_stream and not self._log_stream.closed:
            self._log_stream.flush()
        if not self.log_path.exists():
            return "<no runtime log>"
        return self.log_path.read_text(encoding="utf-8", errors="replace")[-4000:]


def validate_config(config_path: Path) -> None:
    """Ask the pinned binary to validate a config without starting listeners."""

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{config_path.parent.resolve()}:/config:ro",
            AGENTGATEWAY_IMAGE,
            "--file",
            f"/config/{config_path.name}",
            "--validate-only",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        details = (result.stdout + result.stderr).strip()
        raise GatewayStartupError(f"agentgateway rejected the config:\n{details}")


def write_runtime_files(
    config_dir: Path,
    config: Mapping[str, object],
    jwks: Mapping[str, object],
) -> None:
    """Write runtime-only JSON files inside a temporary directory."""

    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "agentgateway.json").write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (config_dir / "jwks.json").write_text(
        json.dumps(jwks, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])
