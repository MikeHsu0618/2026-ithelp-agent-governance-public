import json
from pathlib import Path

import pytest
import yaml

import gateway_runtime.registry_boundary as registry_boundary
from gateway_runtime.registry_boundary import (
    HttpResult,
    KubectlClient,
    RegistryClient,
    build_report,
    condition_is_true,
    render_terminal,
    run_live_probe,
)

CONFIG_DIR = Path(__file__).parents[1] / "configs/day-19"


def _load_resource(filename: str) -> dict:
    documents = [
        document for document in yaml.safe_load_all((CONFIG_DIR / filename).read_text()) if document
    ]
    assert len(documents) == 1
    return documents[0]


def test_registry_client_uses_anonymous_apply_and_namespace_scoped_reads() -> None:
    calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def transport(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> HttpResult:
        calls.append((method, url, headers, body))
        if method == "POST":
            return HttpResult(200, {"results": [{"status": "created"}]})
        return HttpResult(
            200,
            {
                "apiVersion": "ar.dev/v1alpha1",
                "kind": "Agent",
                "metadata": {"name": "day19byo", "tag": "approved"},
            },
        )

    client = RegistryClient("http://registry.test", transport=transport)
    apply_result = client.apply_yaml("kind: Agent\n")
    agent = client.get_agent("day19byo", "approved", namespace="day19-lab")

    assert apply_result["results"][0]["status"] == "created"
    assert agent["metadata"]["tag"] == "approved"
    assert calls == [
        (
            "POST",
            "http://registry.test/v0/apply",
            {"Accept": "application/json", "Content-Type": "application/yaml"},
            b"kind: Agent\n",
        ),
        (
            "GET",
            "http://registry.test/v0/agents/day19byo/approved?namespace=day19-lab",
            {"Accept": "application/json"},
            None,
        ),
    ]


def test_registry_client_rejects_non_success_responses() -> None:
    def transport(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> HttpResult:
        del method, url, headers, body
        return HttpResult(403, {"title": "Forbidden"})

    client = RegistryClient("http://registry.test/", transport=transport)

    with pytest.raises(RuntimeError, match="HTTP 403"):
        client.apply_yaml("kind: Agent\n")


def test_condition_parser_only_accepts_explicit_true() -> None:
    resource = {
        "status": {
            "conditions": [
                {"type": "Progressing", "status": "False"},
                {"type": "RuntimeConfigured", "status": "True"},
            ]
        }
    }

    assert condition_is_true(resource, "RuntimeConfigured") is True
    assert condition_is_true(resource, "Progressing") is False
    assert condition_is_true({}, "RuntimeConfigured") is False


def test_report_separates_working_reconciliation_from_registry_trust() -> None:
    report = build_report(
        {
            "anonymous_apply": True,
            "catalog_tag": "approved",
            "deployment_ready": True,
            "image_before": "ithelp/day19-byo:1.0.0",
            "image_after": "ithelp/day19-byo:1.0.1",
            "runtime_resource_removed": True,
        }
    )
    cases = {case["case_id"]: case for case in report["cases"]}

    assert cases["anonymous-write"]["status"] == "RISK_EXPOSED"
    assert cases["catalog-discovery"]["status"] == "PASS"
    assert cases["deployment-reconcile"]["status"] == "PASS"
    assert cases["mutable-approved-tag"]["status"] == "RISK_EXPOSED"
    assert cases["declarative-undeploy"]["status"] == "PASS"
    assert report["summary"] == {
        "observed": 5,
        "total": 5,
        "pass": 3,
        "risk_findings": 2,
    }

    terminal = render_terminal(report)
    assert "Anonymous catalog write" in terminal
    assert "RISK_EXPOSED" in terminal
    assert "image-before=ithelp/day19-byo:1.0.0" in terminal
    assert "image-after=ithelp/day19-byo:1.0.1" in terminal
    assert "risk-findings=2" in terminal


def test_report_marks_missing_runtime_evidence_as_fail() -> None:
    report = build_report(
        {
            "anonymous_apply": False,
            "catalog_tag": "",
            "deployment_ready": False,
            "image_before": "",
            "image_after": "",
            "runtime_resource_removed": False,
        }
    )
    cases = {case["case_id"]: case for case in report["cases"]}

    assert cases["anonymous-write"]["status"] == "CONTROL_PRESENT"
    assert cases["catalog-discovery"]["status"] == "FAIL"
    assert cases["deployment-reconcile"]["status"] == "FAIL"
    assert cases["mutable-approved-tag"]["status"] == "FAIL"
    assert cases["declarative-undeploy"]["status"] == "FAIL"
    assert report["summary"]["observed"] == 1


def test_day19_manifests_keep_catalog_tag_and_image_identity_separate() -> None:
    agent_v1 = _load_resource("agent-v1.yaml")
    agent_v2 = _load_resource("agent-v2.yaml")
    runtime = _load_resource("runtime.yaml")
    deployment = _load_resource("deployment.yaml")
    undeployed = _load_resource("deployment-undeployed.yaml")

    assert agent_v1["apiVersion"] == "ar.dev/v1alpha1"
    assert agent_v1["kind"] == "Agent"
    assert agent_v1["metadata"] == {
        "namespace": "day19-lab",
        "name": "day19byo",
        "tag": "approved",
    }
    assert agent_v2["metadata"] == agent_v1["metadata"]
    assert agent_v1["spec"]["source"]["image"] == "ithelp/day19-byo:1.0.0"
    assert agent_v2["spec"]["source"]["image"] == "ithelp/day19-byo:1.0.1"

    assert runtime["kind"] == "Runtime"
    assert runtime["metadata"]["namespace"] == "day19-lab"
    assert runtime["spec"] == {
        "type": "Kubernetes",
        "config": {"namespace": "day19-runtime"},
    }

    assert deployment["kind"] == "Deployment"
    assert deployment["metadata"] == {
        "namespace": "day19-lab",
        "name": "day19-agent",
    }
    assert deployment["spec"]["targetRef"] == {
        "kind": "Agent",
        "name": "day19byo",
        "tag": "approved",
    }
    assert deployment["spec"]["runtimeRef"] == {
        "kind": "Runtime",
        "name": "day19-kubernetes",
    }
    assert undeployed["metadata"] == deployment["metadata"]
    assert undeployed["spec"]["desiredState"] == "undeployed"


def test_day19_manifests_contain_no_credentials_or_private_environment_names() -> None:
    public_text = "\n".join(path.read_text() for path in sorted(CONFIG_DIR.glob("*.yaml")))

    assert "kind: Secret" not in public_text
    assert "apiKey" not in public_text
    assert "Authorization" not in public_text
    assert "sporty" not in public_text.lower()
    assert "uat" not in public_text.lower()
    assert "prod" not in public_text.lower()
    assert json.dumps(yaml.safe_load(public_text.split("---")[0]))


def test_live_probe_records_catalog_reconcile_mutation_and_teardown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRegistry:
        phase = "initial"

        def apply_yaml(self, manifest: str) -> dict:
            if "image: ithelp/day19-byo:1.0.1" in manifest:
                self.phase = "updated"
            elif "desiredState: undeployed" in manifest:
                self.phase = "removed"
            return {"results": [{"status": "created"}]}

        def get_agent(self, name: str, tag: str, *, namespace: str) -> dict:
            assert (name, tag, namespace) == ("day19byo", "approved", "day19-lab")
            return {
                "apiVersion": "ar.dev/v1alpha1",
                "kind": "Agent",
                "metadata": {
                    "namespace": namespace,
                    "name": name,
                    "tag": tag,
                    "uid": "private-row-id",
                },
                "spec": {"source": {"image": "ithelp/day19-byo:1.0.0"}},
            }

        def get_deployment(self, name: str, *, namespace: str) -> dict:
            assert (name, namespace) == ("day19-agent", "day19-lab")
            return {
                "apiVersion": "ar.dev/v1alpha1",
                "kind": "Deployment",
                "metadata": {"namespace": namespace, "name": name, "uid": "private-row-id"},
                "spec": {"desiredState": "deployed"},
                "status": {"conditions": [{"type": "RuntimeConfigured", "status": "True"}]},
            }

    fake_registry = FakeRegistry()

    class FakeKubectl:
        def managed_agents(self) -> list[dict]:
            if fake_registry.phase == "removed":
                return []
            image = (
                "ithelp/day19-byo:1.0.1"
                if fake_registry.phase == "updated"
                else "ithelp/day19-byo:1.0.0"
            )
            return [
                {
                    "metadata": {"name": "day19byo-approved-day19-agent"},
                    "spec": {"byo": {"deployment": {"image": image}}},
                    "status": {"conditions": [{"type": "Ready", "status": "True"}]},
                }
            ]

    monkeypatch.setattr(registry_boundary, "RegistryClient", lambda url: fake_registry)
    artifact_root = tmp_path / "evidence"
    report = run_live_probe(
        registry_url="http://registry.test",
        config_dir=CONFIG_DIR,
        artifact_root=artifact_root,
        kubectl=FakeKubectl(),
        timeout=0.1,
    )

    assert report["summary"] == {
        "observed": 5,
        "total": 5,
        "pass": 3,
        "risk_findings": 2,
    }
    assert "RISK_EXPOSED" in (artifact_root / "terminal.txt").read_text()
    assert json.loads((artifact_root / "registry-boundary-report.json").read_text()) == report
    public_agent = json.loads((artifact_root / "catalog-agent.redacted.json").read_text())
    assert "uid" not in public_agent["metadata"]
    public_deployment = json.loads((artifact_root / "deployment-status.redacted.json").read_text())
    assert public_deployment["status"]["conditions"][0]["type"] == "RuntimeConfigured"


def test_kubectl_client_refuses_an_unexpected_context(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        returncode = 0
        stdout = "kind-other\n"
        stderr = ""

    monkeypatch.setattr(registry_boundary.subprocess, "run", lambda *args, **kwargs: Result())

    with pytest.raises(RuntimeError, match="expected 'kind-ithelp-day19'"):
        KubectlClient("kubectl", Path("/tmp/day19-kubeconfig"), "kind-ithelp-day19")
