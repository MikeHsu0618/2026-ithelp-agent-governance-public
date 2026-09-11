import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from gateway_runtime.byo_boundary import (
    ACTOR,
    HttpResult,
    build_decision_request,
    build_message_request,
    extract_task,
    render_terminal,
    run_probe,
)


def _public_makefile_source() -> Path:
    repository_root = Path(__file__).parents[3]
    for candidate in (
        repository_root / "publication/Makefile.public",
        repository_root / "Makefile",
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("public Makefile not found in authoring or exported layout")


def _load_day18_result_parser():
    parser_path = Path(__file__).parents[1] / "fixtures/day-18-byo/day18_byo/result_parser.py"
    spec = importlib.util.spec_from_file_location("day18_result_parser", parser_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _task_response(
    *,
    task_id: str,
    context_id: str,
    state: str,
    text: str = "",
) -> dict:
    task: dict = {
        "id": task_id,
        "contextId": context_id,
        "status": {"state": state},
    }
    if text:
        task["artifacts"] = [
            {
                "artifactId": f"artifact-{task_id}",
                "parts": [{"kind": "text", "text": text}],
            }
        ]
    return {"jsonrpc": "2.0", "id": task_id, "result": task}


def test_message_request_uses_the_direct_a2a_shape() -> None:
    request = build_message_request("message-18", "Change demo/cache")

    assert request["method"] == "message/send"
    assert request["params"]["message"] == {
        "messageId": "message-18",
        "role": "user",
        "parts": [{"kind": "text", "text": "Change demo/cache"}],
    }


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_decision_request_keeps_the_pending_task_context(decision: str) -> None:
    request = build_decision_request(
        request_id=f"day18-{decision}",
        message_id=f"message-{decision}",
        task_id="task-parent-18",
        context_id="context-parent-18",
        decision=decision,
    )

    message = request["params"]["message"]
    assert message["taskId"] == "task-parent-18"
    assert message["contextId"] == "context-parent-18"
    assert message["parts"] == [{"kind": "data", "data": {"decision_type": decision}}]


def test_extract_task_accepts_direct_and_gateway_wrapped_results() -> None:
    direct = _task_response(
        task_id="task-direct",
        context_id="context-direct",
        state="completed",
    )
    wrapped = {"result": {"task": direct["result"]}}

    assert extract_task(direct)["id"] == "task-direct"
    assert extract_task(wrapped)["contextId"] == "context-direct"

    with pytest.raises(RuntimeError, match="does not contain an A2A task"):
        extract_task({"error": {"message": "not found"}})


def test_probe_proves_nested_hitl_and_identity_without_hiding_rejection() -> None:
    parent_url = "http://day18-parent.test"
    byo_url = "http://day18-byo.test"
    calls: list[tuple[str, str, dict[str, str], dict | None]] = []
    pending = iter(
        [
            _task_response(
                task_id="task-approve",
                context_id="context-approve",
                state="input-required",
            ),
            _task_response(
                task_id="task-approve",
                context_id="context-approve",
                state="completed",
                text=("parent-complete ACTION_EXECUTED resource=demo/cache actor=sre-oncaller"),
            ),
            _task_response(
                task_id="task-reject",
                context_id="context-reject",
                state="input-required",
            ),
            _task_response(
                task_id="task-reject",
                context_id="context-reject",
                state="completed",
                text="parent-complete ACTION_SKIPPED decision=rejected",
            ),
        ]
    )

    def transport(
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict | None,
    ) -> HttpResult:
        calls.append((method, url, headers, body))
        if method == "GET":
            return HttpResult(
                200,
                {
                    "name": "day18_byo_agent",
                    "description": "BYO boundary fixture",
                    "url": byo_url,
                    "version": "0.1.0",
                    "capabilities": {"streaming": False},
                    "defaultInputModes": ["text"],
                    "defaultOutputModes": ["text"],
                    "skills": [],
                },
            )
        return HttpResult(200, next(pending))

    report = run_probe(parent_url, byo_url, transport=transport)
    cases = {case["case_id"]: case for case in report["cases"]}

    assert cases["byo-agent-card"]["status"] == "PASS"
    assert cases["agent-as-tool"]["status"] == "PASS"
    assert cases["nested-hitl-approve"]["status"] == "PASS"
    assert cases["nested-hitl-reject"]["status"] == "PASS"
    assert cases["identity-propagation"]["status"] == "PASS"
    assert cases["identity-propagation"]["label"] == "Synthetic actor propagation"
    assert report["summary"] == {"matched": 5, "total": 5}

    post_calls = [call for call in calls if call[0] == "POST"]
    assert len(post_calls) == 4
    assert all(call[2]["x-user-id"] == ACTOR for call in post_calls)
    assert post_calls[1][3]["params"]["message"]["taskId"] == "task-approve"
    assert post_calls[3][3]["params"]["message"]["parts"][0]["data"] == {"decision_type": "reject"}

    terminal = render_terminal(report)
    assert "matched 5/5" in terminal
    assert "actor=sre-oncaller" in terminal
    assert "rejected-without-execution=true" in terminal


def test_probe_fails_if_the_child_loses_the_synthetic_actor() -> None:
    responses = iter(
        [
            _task_response(
                task_id="task-approve",
                context_id="context-approve",
                state="input-required",
            ),
            _task_response(
                task_id="task-approve",
                context_id="context-approve",
                state="completed",
                text="ACTION_EXECUTED resource=demo/cache actor=system:serviceaccount:kagent",
            ),
            _task_response(
                task_id="task-reject",
                context_id="context-reject",
                state="input-required",
            ),
            _task_response(
                task_id="task-reject",
                context_id="context-reject",
                state="completed",
                text="ACTION_SKIPPED decision=rejected",
            ),
        ]
    )

    def transport(
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict | None,
    ) -> HttpResult:
        if method == "GET":
            return HttpResult(200, {"name": "day18_byo_agent", "url": url})
        return HttpResult(200, next(responses))

    report = run_probe("http://parent.test", "http://byo.test", transport=transport)
    identity = next(case for case in report["cases"] if case["case_id"] == "identity-propagation")

    assert identity["status"] == "FAIL"
    assert report["summary"] == {"matched": 4, "total": 5}


@pytest.mark.parametrize(
    ("pending_override", "final_override", "message"),
    [
        ({"contextId": ""}, {}, "missing a contextId"),
        ({"status": {"state": "completed"}}, {}, "input-required"),
        ({}, {"id": "different-task"}, "changed task id"),
        ({}, {"contextId": "different-context"}, "changed contextId"),
        ({}, {"status": {"state": "failed"}}, "completed"),
    ],
)
def test_probe_rejects_broken_hitl_task_continuity(
    pending_override: dict,
    final_override: dict,
    message: str,
) -> None:
    pending = _task_response(
        task_id="task-approve",
        context_id="context-approve",
        state="input-required",
    )
    pending["result"].update(pending_override)
    final = _task_response(
        task_id="task-approve",
        context_id="context-approve",
        state="completed",
        text="ACTION_EXECUTED resource=demo/cache actor=sre-oncaller",
    )
    final["result"].update(final_override)
    responses = iter([pending, final])

    def transport(
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict | None,
    ) -> HttpResult:
        del url, headers, body
        if method == "GET":
            return HttpResult(200, {"name": "day18_byo_agent"})
        return HttpResult(200, next(responses))

    with pytest.raises(RuntimeError, match=message):
        run_probe("http://parent.test", "http://byo.test", transport=transport)


def test_day18_tool_result_parser_requires_a_non_empty_result() -> None:
    parser = _load_day18_result_parser()

    assert parser.tool_result_text({"result": "ACTION_EXECUTED"}) == "ACTION_EXECUTED"
    assert parser.tool_result_text({"result": 0}) == "0"

    with pytest.raises(ValueError, match="mapping"):
        parser.tool_result_text(None)
    with pytest.raises(ValueError, match="result"):
        parser.tool_result_text({})
    with pytest.raises(ValueError, match="result"):
        parser.tool_result_text({"result": None})
    with pytest.raises(ValueError, match="empty"):
        parser.tool_result_text({"result": "  "})


def test_report_is_json_serializable_for_public_evidence() -> None:
    report = {
        "schema": "ithelp.byo-boundary-report.v1",
        "actor": ACTOR,
        "cases": [],
        "summary": {"matched": 0, "total": 0},
    }

    assert json.loads(json.dumps(report))["actor"] == ACTOR


def test_day18_manifest_keeps_platform_registration_and_runtime_ownership_distinct() -> None:
    manifest = Path(__file__).parents[1] / "configs/day-18/kagent-resources.yaml"
    resources = [item for item in yaml.safe_load_all(manifest.read_text()) if item]
    agents = {item["metadata"]["name"]: item for item in resources if item.get("kind") == "Agent"}
    routes = [item for item in resources if item.get("kind") == "HTTPRoute"]
    backends = [item for item in resources if item.get("kind") == "AgentgatewayBackend"]

    byo = agents["day18-byo"]["spec"]
    assert byo["type"] == "BYO"
    assert byo["byo"]["deployment"]["imagePullPolicy"] == "Never"
    deployment = byo["byo"]["deployment"]
    assert deployment["serviceAccountName"] == "day18-byo"
    assert deployment["securityContext"]["readOnlyRootFilesystem"] is True
    assert deployment["volumeMounts"] == [{"name": "tmp", "mountPath": "/tmp"}]
    assert deployment["volumes"][0]["emptyDir"]["sizeLimit"] == "64Mi"
    assert "declarative" not in byo
    assert "memory" not in byo["byo"]
    service_accounts = {
        item["metadata"]["name"]: item for item in resources if item.get("kind") == "ServiceAccount"
    }
    assert service_accounts["day18-byo"]["automountServiceAccountToken"] is False
    assert service_accounts["day18-parent"]["automountServiceAccountToken"] is False
    assert service_accounts["day18-synthetic-llm"]["automountServiceAccountToken"] is False
    synthetic = next(
        item
        for item in resources
        if item.get("kind") == "Deployment" and item["metadata"]["name"] == "day18-synthetic-llm"
    )
    assert synthetic["spec"]["template"]["spec"]["serviceAccountName"] == ("day18-synthetic-llm")
    assert backends[0]["spec"]["a2a"]["host"] == ("day18-byo.day18-lab.svc.cluster.local")
    assert routes[0]["spec"]["rules"][0]["matches"][0]["headers"] == [
        {
            "name": "x-kagent-host",
            "type": "Exact",
            "value": "day18-byo.day18-lab",
        }
    ]

    parent = agents["day18-parent"]["spec"]
    assert parent["type"] == "Declarative"
    assert parent["declarative"]["runtime"] == "python"
    assert parent["declarative"]["deployment"]["serviceAccountName"] == ("day18-parent")
    assert parent["declarative"]["tools"] == [
        {
            "type": "Agent",
            "agent": {
                "apiGroup": "kagent.dev",
                "kind": "Agent",
                "name": "day18-byo",
            },
        }
    ]


def test_day18_bootstrap_uses_the_pinned_kagent_version_from_the_start() -> None:
    source = _public_makefile_source().read_text()
    day18_target = source.split("lab-03-runtime-byo-up:", maxsplit=1)[1].split(
        "\nlab-03-runtime-byo-run:", maxsplit=1
    )[0]

    assert 'lab-03-runtime-kagent-up KAGENT_VERSION="$(DAY18_KAGENT_VERSION)"' in day18_target
    assert "helm upgrade --install kagent" not in day18_target

    containerfile = (Path(__file__).parents[1] / "fixtures/day-18-byo/Containerfile").read_text()
    assert (
        "kagent-adk:0.10.1@sha256:"
        "f7f45b693177792c9e51f3cf944887d085a4957a67388a43d70a3632d17ff98d" in containerfile
    )


def test_exported_root_makefile_can_plan_day18_without_private_paths(tmp_path: Path) -> None:
    exported = tmp_path / "Makefile"
    exported.write_text(_public_makefile_source().read_text())

    result = subprocess.run(
        ["make", "-n", "lab-03-runtime-byo-up"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "publication/Makefile.public" not in result.stderr


def test_day18_composite_target_is_serial_even_with_parallel_make(tmp_path: Path) -> None:
    exported = tmp_path / "Makefile"
    exported.write_text(_public_makefile_source().read_text())

    result = subprocess.run(
        ["make", "-n", "-j2", "lab-03-runtime-byo"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert output.index("lab-03-runtime-byo-up") < output.index("lab-03-runtime-byo-run")
