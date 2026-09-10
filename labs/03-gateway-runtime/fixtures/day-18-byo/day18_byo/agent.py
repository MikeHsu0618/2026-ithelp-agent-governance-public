"""Google ADK Agent that exposes one approval-gated, side-effect-free tool."""

from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from .result_parser import tool_result_text


def change_demo_resource(resource: str, tool_context: ToolContext) -> str:
    """Return an action receipt without touching Kubernetes or an external service."""

    actor = tool_context.session.user_id
    return f"ACTION_EXECUTED resource={resource} actor={actor}"


def require_approval(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
) -> str | dict[str, str] | None:
    """Pause the ADK tool call and resume only after an explicit decision."""

    if tool.name != "change_demo_resource":
        return None
    confirmation = tool_context.tool_confirmation
    if confirmation is None:
        tool_context.request_confirmation(
            hint=f"Approve changing {args.get('resource', 'the requested resource')}?"
        )
        return {"status": "confirmation_requested"}
    if confirmation.confirmed:
        return None
    return "ACTION_SKIPPED decision=rejected"


class BoundaryModel(BaseLlm):
    """A deterministic model keeps the experiment about the runtime boundary."""

    model: str = "day18-fixture-model"

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        del stream
        result = _latest_tool_result(llm_request)
        if result is None:
            parts = [
                types.Part(
                    function_call=types.FunctionCall(
                        id="day18-change",
                        name="change_demo_resource",
                        args={"resource": "demo/cache"},
                    )
                )
            ]
        else:
            parts = [types.Part(text=result)]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


def _latest_tool_result(llm_request: LlmRequest) -> str | None:
    for content in reversed(llm_request.contents or []):
        for part in reversed(content.parts or []):
            response = part.function_response
            if response and response.name == "change_demo_resource":
                return tool_result_text(response.response)
    return None


root_agent = Agent(
    name="day18_byo_agent",
    description="Tests what a BYO Agent does and does not inherit from kagent.",
    instruction="Always call change_demo_resource and return its exact result.",
    model=BoundaryModel(),
    tools=[change_demo_resource],
    before_tool_callback=require_approval,
)
