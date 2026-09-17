from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class ContractError(ValueError):
    """Raised when a replay report violates the public v1 contract."""


_SCHEMA_PATH = Path(__file__).with_name("schemas") / "replay-event-v1.schema.json"


def validate_replay_report(report: dict[str, Any]) -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(report), key=lambda item: list(item.path)
    )
    if not errors:
        return
    details = "; ".join(
        f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in errors
    )
    raise ContractError(details)
