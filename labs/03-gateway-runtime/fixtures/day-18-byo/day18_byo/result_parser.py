"""Validate the ADK function-response shape used by the Day 18 fixture."""

from collections.abc import Mapping


def tool_result_text(response: object) -> str:
    """Return a Tool receipt, rejecting absent or malformed results."""

    if not isinstance(response, Mapping):
        raise ValueError("function response must be a mapping")
    if "result" not in response or response["result"] is None:
        raise ValueError("function response is missing result")
    result = str(response["result"])
    if not result.strip():
        raise ValueError("function response result must not be empty")
    return result
