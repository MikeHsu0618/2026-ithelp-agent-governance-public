"""Day 16 ownership checks for kagent and agentgateway.

The checks are intentionally narrower than a product scorecard. They verify that
the checked-in Kubernetes resources put runtime lifecycle in kagent and shared
LLM/MCP traffic policy in one agentgateway, while keeping unsupported workflow
and credential-lifecycle claims visible as partial results.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from gateway_runtime.artifacts import ArtifactStore

KAGENT_VERSION = "0.10.0"
AGENTGATEWAY_VERSION = "1.5.0"
LAB_CONTEXT = "kind-ithelp-day16"
OWNED_LAB_CONTEXTS = frozenset({LAB_CONTEXT, "kind-ithelp-day19"})
AGENTGATEWAY_HOST = "agentgateway-proxy.agentgateway-system.svc.cluster.local"


class UnsafeKubeContextError(RuntimeError):
    """Raised when a cluster command is not pinned to a repository-owned Lab cluster."""


def validate_kind_context(
    kubeconfig: Path,
    context: str,
    *,
    expected_context: str = LAB_CONTEXT,
) -> None:
    """Refuse the default kubeconfig and contexts outside the repository-owned allowlist."""

    default_kubeconfig = (Path.home() / ".kube" / "config").resolve()
    candidate = kubeconfig.expanduser().resolve()
    if candidate == default_kubeconfig:
        raise UnsafeKubeContextError("the Lab must not use ~/.kube/config")
    if expected_context not in OWNED_LAB_CONTEXTS:
        raise UnsafeKubeContextError(
            f"expected context {expected_context!r} is not an owned Lab context"
        )
    if context != expected_context:
        raise UnsafeKubeContextError(
            f"expected context {expected_context!r}, received {context!r}; refusing cluster access"
        )


def assess_boundary(values: dict[str, Any], resources: list[dict[str, Any]]) -> dict[str, Any]:
    """Assess the ownership boundary expressed by kagent values and CRs."""

    model = _one(resources, "ModelConfig")
    remote_mcp = _one(resources, "RemoteMCPServer")
    agent = _one(resources, "Agent")

    declarative = agent.get("spec", {}).get("declarative", {})
    model_spec = model.get("spec", {})
    openai = model_spec.get("openAI", {})
    remote_spec = remote_mcp.get("spec", {})
    proxy_url = values.get("proxy", {}).get("url", "")

    runtime_ok = (
        agent.get("spec", {}).get("type") == "Declarative"
        and declarative.get("runtime") in {"go", "python"}
        and declarative.get("modelConfig") == model.get("metadata", {}).get("name")
    )
    llm_gateway_ok = _host(openai.get("baseUrl", "")) == AGENTGATEWAY_HOST
    mcp_gateway_ok = _host(proxy_url) == AGENTGATEWAY_HOST and _host(
        remote_spec.get("url", "")
    ).endswith(".svc.cluster.local")
    reasoning_ok = openai.get("reasoningEffort") in {
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }
    headers = remote_spec.get("headersFrom", [])
    secret_backed_headers = bool(headers) and all(
        item.get("valueFrom", {}).get("type") == "Secret" for item in headers
    )

    checks = [
        _check(
            "declarative-runtime",
            "runtime/control-plane",
            "PASS" if runtime_ok else "FAIL",
            "Agent CR selects a declarative runtime and a namespaced ModelConfig.",
        ),
        _check(
            "llm-through-agentgateway",
            "traffic-path",
            "PASS" if llm_gateway_ok else "FAIL",
            "ModelConfig sends LLM calls to the single agentgateway service.",
        ),
        _check(
            "mcp-proxy-rewrite",
            "traffic-path",
            "PASS" if mcp_gateway_ok else "FAIL",
            "An internal RemoteMCPServer URL is paired with kagent proxy.url.",
        ),
        _check(
            "reasoning-effort",
            "runtime-surface",
            "PASS" if reasoning_ok else "PARTIAL",
            "The current OpenAI ModelConfig exposes reasoningEffort.",
        ),
        _check(
            "mcp-credential-lifecycle",
            "identity",
            "PARTIAL" if secret_backed_headers else "FAIL",
            (
                "headersFrom reads a Secret, but does not define autonomous token acquisition "
                "or refresh."
            ),
        ),
        _check(
            "advanced-workflow",
            "runtime-surface",
            "PARTIAL",
            (
                "This declarative Agent proves prompt/model/tool wiring, not an arbitrary "
                "multi-step workflow."
            ),
        ),
    ]
    counts = {
        status.lower(): sum(1 for item in checks if item["status"] == status)
        for status in (
            "PASS",
            "PARTIAL",
            "FAIL",
        )
    }
    return {
        "schema": "ithelp.gateway-runtime.kagent-boundary-report.v1",
        "versions": {"kagent": KAGENT_VERSION, "agentgateway": AGENTGATEWAY_VERSION},
        "checks": checks,
        "summary": {**counts, "total": len(checks)},
        "ownership": ownership_matrix(),
    }


def run_boundary_lab(config_dir: Path, artifact_root: Path) -> dict[str, Any]:
    """Assess checked-in Day 16 YAML and preserve a reviewable evidence bundle."""

    values_path = config_dir / "kagent-values.yaml"
    resources_path = config_dir / "kagent-resources.yaml"
    values = yaml.safe_load(values_path.read_text(encoding="utf-8"))
    resources = [
        item
        for item in yaml.safe_load_all(resources_path.read_text(encoding="utf-8"))
        if item is not None
    ]
    report = assess_boundary(values, resources)
    run_id = datetime.now(UTC).strftime("day16-%Y%m%dT%H%M%SZ")
    store = ArtifactStore(artifact_root, run_id)
    store.write_json("evidence/kagent-boundary-report.json", report)
    store.write_text("evidence/ownership-matrix.md", _ownership_markdown(report["ownership"]))
    store.write_text("evidence/kagent-terminal.txt", render_terminal(report))
    store.write_json(
        "manifest.json",
        {
            "files": [
                "evidence/kagent-boundary-report.json",
                "evidence/kagent-terminal.txt",
                "evidence/ownership-matrix.md",
            ],
            "run_id": run_id,
        },
    )
    report["artifact_dir"] = str(store.run_dir)
    return report


def ownership_matrix() -> list[dict[str, str]]:
    """Return the eight source-of-truth decisions used in the article and Lab."""

    return [
        {
            "responsibility": "agent-runtime",
            "owner": "application-team",
            "source_of_truth": "agent source and runtime tests",
        },
        {
            "responsibility": "agent-deployment",
            "owner": "kagent",
            "source_of_truth": "Agent CR and generated Deployment",
        },
        {
            "responsibility": "agent-discovery",
            "owner": "kagent",
            "source_of_truth": "Agent CR status and Agent Card",
        },
        {
            "responsibility": "llm-traffic-policy",
            "owner": "agentgateway",
            "source_of_truth": "Gateway route and policy",
        },
        {
            "responsibility": "mcp-traffic-policy",
            "owner": "agentgateway",
            "source_of_truth": "Gateway MCP backend and policy",
        },
        {
            "responsibility": "credential-acquisition",
            "owner": "identity-platform/application-team",
            "source_of_truth": "workload identity and token lifecycle",
        },
        {
            "responsibility": "runtime-telemetry",
            "owner": "kagent/application-team",
            "source_of_truth": "runtime spans and action events",
        },
        {
            "responsibility": "traffic-telemetry",
            "owner": "agentgateway",
            "source_of_truth": "gateway access log, metrics, and traces",
        },
    ]


def render_terminal(report: dict[str, Any]) -> str:
    """Render a compact, copyable evidence view."""

    lines = [
        "DAY 16 / KAGENT BOUNDARY",
        "",
        (
            f"kagent {report['versions']['kagent']} / "
            f"agentgateway {report['versions']['agentgateway']}"
        ),
        "",
    ]
    for item in report["checks"]:
        lines.append(f"{item['check_id']:<32} {item['status']}")
    summary = report["summary"]
    lines.extend(
        [
            "",
            (f"PASS {summary['pass']} / PARTIAL {summary['partial']} / FAIL {summary['fail']}"),
            "",
        ]
    )
    return "\n".join(lines)


def _ownership_markdown(rows: list[dict[str, str]]) -> str:
    lines = [
        "| Responsibility | Owner | Source of truth |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| `{row['responsibility']}` | `{row['owner']}` | {row['source_of_truth']} |"
        for row in rows
    )
    return "\n".join(lines) + "\n"


def _one(resources: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = [item for item in resources if item.get("kind") == kind]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {kind}, found {len(matches)}")
    return matches[0]


def _host(value: str) -> str:
    return urlparse(value).hostname or ""


def _check(check_id: str, layer: str, status: str, evidence: str) -> dict[str, str]:
    return {"check_id": check_id, "layer": layer, "status": status, "evidence": evidence}
