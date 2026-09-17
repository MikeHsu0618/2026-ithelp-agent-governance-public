import tomllib
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]


def test_adk_runtime_is_a_package_dependency_for_the_published_cli() -> None:
    project = tomllib.loads((LAB_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert "google-adk[mcp]==2.7.0" in project["dependencies"]
