"""Day 19 Agent Registry catalog, deployment, and trust-boundary probe."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REGISTRY_NAMESPACE = "day19-lab"
RUNTIME_NAMESPACE = "day19-runtime"
AGENT_NAME = "day19byo"
AGENT_TAG = "approved"
DEPLOYMENT_NAME = "day19-agent"
MANAGED_LABEL = f"aregistry.ai/deployment-id={DEPLOYMENT_NAME}"


@dataclass(frozen=True)
class HttpResult:
    """Minimal HTTP response used by the live client and unit tests."""

    status: int
    body: dict[str, Any]


Transport = Callable[[str, str, dict[str, str], bytes | None], HttpResult]


class RegistryClient:
    """Small client for the Agent Registry v0 declarative API."""

    def __init__(self, base_url: str, transport: Transport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport or _http_transport

    def apply_yaml(self, manifest: str) -> dict[str, Any]:
        result = self.transport(
            "POST",
            f"{self.base_url}/v0/apply",
            {"Accept": "application/json", "Content-Type": "application/yaml"},
            manifest.encode(),
        )
        return _require_success(result)

    def get_agent(self, name: str, tag: str, *, namespace: str) -> dict[str, Any]:
        path = f"/v0/agents/{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}"
        return self._get(path, namespace)

    def get_deployment(self, name: str, *, namespace: str) -> dict[str, Any]:
        path = f"/v0/deployments/{urllib.parse.quote(name)}"
        return self._get(path, namespace)

    def _get(self, path: str, namespace: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"namespace": namespace})
        result = self.transport(
            "GET",
            f"{self.base_url}{path}?{query}",
            {"Accept": "application/json"},
            None,
        )
        return _require_success(result)


class KubectlClient:
    """Read only the Day 19 kagent resources through an explicit context."""

    def __init__(self, executable: str, kubeconfig: Path, context: str) -> None:
        self.prefix = [
            executable,
            "--kubeconfig",
            str(kubeconfig),
            "--context",
            context,
        ]
        current = self._run("config", "current-context").strip()
        if current != context:
            raise RuntimeError(f"refusing context {current!r}; expected {context!r}")

    def managed_agents(self) -> list[dict[str, Any]]:
        output = self._run(
            "-n",
            RUNTIME_NAMESPACE,
            "get",
            "agents.kagent.dev",
            "-l",
            MANAGED_LABEL,
            "-o",
            "json",
        )
        return json.loads(output).get("items", [])

    def _run(self, *arguments: str) -> str:
        result = subprocess.run(
            [*self.prefix, *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout


def condition_is_true(resource: dict[str, Any], condition_type: str) -> bool:
    """Return true only for an explicit Kubernetes-style True condition."""

    conditions = resource.get("status", {}).get("conditions", [])
    return any(
        condition.get("type") == condition_type and condition.get("status") == "True"
        for condition in conditions
    )


def build_report(observations: dict[str, Any]) -> dict[str, Any]:
    """Classify working mechanics separately from missing trust controls."""

    anonymous_apply = bool(observations.get("anonymous_apply"))
    catalog_tag = str(observations.get("catalog_tag", ""))
    deployment_ready = bool(observations.get("deployment_ready"))
    image_before = str(observations.get("image_before", ""))
    image_after = str(observations.get("image_after", ""))
    removed = bool(observations.get("runtime_resource_removed"))
    image_changed = bool(image_before and image_after and image_before != image_after)

    cases = [
        {
            "case_id": "anonymous-write",
            "layer": "authorization",
            "label": "Anonymous catalog write",
            "status": "RISK_EXPOSED" if anonymous_apply else "CONTROL_PRESENT",
        },
        {
            "case_id": "catalog-discovery",
            "layer": "catalog",
            "label": "Tagged Agent readable",
            "status": "PASS" if catalog_tag == AGENT_TAG else "FAIL",
            "tag": catalog_tag or "NOT_AVAILABLE",
        },
        {
            "case_id": "deployment-reconcile",
            "layer": "control-plane",
            "label": "Deployment reached kagent",
            "status": "PASS" if deployment_ready and bool(image_before) else "FAIL",
            "image": image_before or "NOT_AVAILABLE",
        },
        {
            "case_id": "mutable-approved-tag",
            "layer": "provenance",
            "label": "Same approved tag changed image",
            "status": "RISK_EXPOSED" if image_changed else "FAIL",
            "tag": AGENT_TAG,
            "image_before": image_before or "NOT_AVAILABLE",
            "image_after": image_after or "NOT_AVAILABLE",
        },
        {
            "case_id": "declarative-undeploy",
            "layer": "lifecycle",
            "label": "Declarative undeploy removed Agent",
            "status": "PASS" if removed else "FAIL",
        },
    ]
    observed = sum(case["status"] != "FAIL" for case in cases)
    passed = sum(case["status"] == "PASS" for case in cases)
    risks = sum(case["status"] == "RISK_EXPOSED" for case in cases)
    return {
        "schema": "ithelp.agent-registry-boundary-report.v1",
        "registry_namespace": REGISTRY_NAMESPACE,
        "runtime_namespace": RUNTIME_NAMESPACE,
        "cases": cases,
        "summary": {
            "observed": observed,
            "total": len(cases),
            "pass": passed,
            "risk_findings": risks,
        },
    }


def render_terminal(report: dict[str, Any]) -> str:
    """Render compact terminal evidence without raw API or cluster payloads."""

    cases = {case["case_id"]: case for case in report["cases"]}
    rows = ["DAY 19 / AGENT REGISTRY BOUNDARY", ""]
    rows.extend(f"{case['label']:<40} {case['status']}" for case in report["cases"])
    rows.extend(
        [
            "",
            f"catalog-tag={cases['catalog-discovery']['tag']}",
            f"image-before={cases['mutable-approved-tag']['image_before']}",
            f"image-after={cases['mutable-approved-tag']['image_after']}",
            f"observed={report['summary']['observed']}/{report['summary']['total']}",
            f"risk-findings={report['summary']['risk_findings']}",
        ]
    )
    return "\n".join(rows)


def run_live_probe(
    *,
    registry_url: str,
    config_dir: Path,
    artifact_root: Path,
    kubectl: KubectlClient,
    timeout: float = 180,
) -> dict[str, Any]:
    """Run the catalog-to-runtime lifecycle against the disposable cluster."""

    client = RegistryClient(registry_url)
    agent_v1 = (config_dir / "agent-v1.yaml").read_text()
    agent_v2 = (config_dir / "agent-v2.yaml").read_text()
    runtime = (config_dir / "runtime.yaml").read_text()
    deployment = (config_dir / "deployment.yaml").read_text()
    undeployed = (config_dir / "deployment-undeployed.yaml").read_text()

    first_apply = client.apply_yaml(agent_v1)
    anonymous_apply = _apply_succeeded(first_apply)
    catalog = client.get_agent(AGENT_NAME, AGENT_TAG, namespace=REGISTRY_NAMESPACE)

    client.apply_yaml(runtime)
    client.apply_yaml(deployment)
    registry_deployment = _wait_for(
        lambda: client.get_deployment(DEPLOYMENT_NAME, namespace=REGISTRY_NAMESPACE),
        lambda resource: condition_is_true(resource, "RuntimeConfigured"),
        timeout=timeout,
        description="Agent Registry Deployment RuntimeConfigured=True",
    )
    runtime_agent = _wait_for(
        kubectl.managed_agents,
        _one_ready_agent,
        timeout=timeout,
        description="one ready kagent Agent managed by the Registry",
    )[0]
    image_before = _agent_image(runtime_agent)

    client.apply_yaml(agent_v2)
    runtime_agent_v2 = _wait_for(
        kubectl.managed_agents,
        lambda items: len(items) == 1 and _agent_image(items[0]).endswith(":1.0.1"),
        timeout=timeout,
        description="kagent Agent image update to 1.0.1",
    )[0]
    image_after = _agent_image(runtime_agent_v2)

    client.apply_yaml(undeployed)
    _wait_for(
        kubectl.managed_agents,
        lambda items: not items,
        timeout=timeout,
        description="managed kagent Agent removal",
    )

    observations = {
        "anonymous_apply": anonymous_apply,
        "catalog_tag": catalog.get("metadata", {}).get("tag", ""),
        "deployment_ready": condition_is_true(registry_deployment, "RuntimeConfigured"),
        "image_before": image_before,
        "image_after": image_after,
        "runtime_resource_removed": not kubectl.managed_agents(),
    }
    report = build_report(observations)
    terminal = render_terminal(report)

    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "registry-boundary-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    (artifact_root / "terminal.txt").write_text(terminal + "\n")
    (artifact_root / "catalog-agent.redacted.json").write_text(
        json.dumps(_public_resource(catalog), indent=2, ensure_ascii=False) + "\n"
    )
    (artifact_root / "deployment-status.redacted.json").write_text(
        json.dumps(_public_resource(registry_deployment), indent=2, ensure_ascii=False) + "\n"
    )
    return report


def _apply_succeeded(result: dict[str, Any]) -> bool:
    results = result.get("results", [])
    return bool(results) and all(item.get("status") != "failed" for item in results)


def _one_ready_agent(items: list[dict[str, Any]]) -> bool:
    return len(items) == 1 and condition_is_true(items[0], "Ready")


def _agent_image(resource: dict[str, Any]) -> str:
    return str(resource.get("spec", {}).get("byo", {}).get("deployment", {}).get("image", ""))


def _wait_for(
    fetch: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    timeout: float,
    description: str,
) -> Any:
    deadline = time.monotonic() + timeout
    last_value: Any = None
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            last_value = fetch()
            if predicate(last_value):
                return last_value
            last_error = None
        except (RuntimeError, urllib.error.URLError) as error:
            last_error = error
        time.sleep(1)
    detail = f"; last error: {last_error}" if last_error else f"; last value: {last_value}"
    raise RuntimeError(f"timed out waiting for {description}{detail}")


def _public_resource(resource: dict[str, Any]) -> dict[str, Any]:
    metadata = resource.get("metadata", {})
    return {
        "apiVersion": resource.get("apiVersion"),
        "kind": resource.get("kind"),
        "metadata": {
            key: metadata.get(key)
            for key in ("namespace", "name", "tag")
            if metadata.get(key) is not None
        },
        "spec": resource.get("spec", {}),
        "status": resource.get("status", {}),
    }


def _require_success(result: HttpResult) -> dict[str, Any]:
    if 200 <= result.status < 300:
        return result.body
    raise RuntimeError(f"Agent Registry returned HTTP {result.status}: {result.body}")


def _http_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
) -> HttpResult:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return HttpResult(response.status, json.loads(raw or b"{}"))
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            decoded = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            decoded = {"detail": raw.decode(errors="replace")}
        return HttpResult(error.code, decoded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-url", default="http://127.0.0.1:18121")
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--kubeconfig", type=Path, required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--kubectl-bin", default="kubectl")
    arguments = parser.parse_args(argv)

    report = run_live_probe(
        registry_url=arguments.registry_url,
        config_dir=arguments.config_dir,
        artifact_root=arguments.artifact_root,
        kubectl=KubectlClient(arguments.kubectl_bin, arguments.kubeconfig, arguments.context),
    )
    print(render_terminal(report))
    return 1 if any(case["status"] == "FAIL" for case in report["cases"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
