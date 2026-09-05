import json
from pathlib import Path

import pytest

from gateway_runtime.artifacts import ArtifactStore, UnsafeCleanupError, cleanup_artifacts
from gateway_runtime.credentials import EphemeralCredentials


def test_artifact_store_writes_safe_json_and_blocks_path_escape(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts", "run-001")
    path = store.write_json("evidence/results.json", {"provider_auth": "MATCHED"})

    assert json.loads(path.read_text()) == {"provider_auth": "MATCHED"}
    with pytest.raises(ValueError):
        store.write_json("../outside.json", {})


def test_artifacts_never_contain_raw_credentials(tmp_path: Path) -> None:
    material = EphemeralCredentials.create()
    store = ArtifactStore(tmp_path / "artifacts", "run-001")
    store.write_json(
        "evidence/results.json",
        {
            "cases": [
                {
                    "case_id": "workload-key",
                    "credential_fingerprint": material.fingerprint(material.workload_consumer_key),
                }
            ]
        },
    )

    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in store.run_dir.rglob("*") if path.is_file()
    )
    for secret in material.raw_secrets():
        assert secret not in serialized


def test_cleanup_refuses_an_unmarked_directory(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    (artifact_root / "keep.txt").write_text("keep\n", encoding="utf-8")

    with pytest.raises(UnsafeCleanupError):
        cleanup_artifacts(tmp_path)

    assert (artifact_root / "keep.txt").is_file()


@pytest.mark.parametrize("run_id", ["../escaped", "/tmp/escaped"])
def test_artifact_store_rejects_a_run_id_outside_the_artifact_root(
    tmp_path: Path,
    run_id: str,
) -> None:
    with pytest.raises(ValueError):
        ArtifactStore(tmp_path / "artifacts", run_id)

    assert not (tmp_path / "escaped").exists()
