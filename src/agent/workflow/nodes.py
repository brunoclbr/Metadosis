"""LangGraph nodes and the reasoning behind their execution style.

Rule of thumb: make network I/O async, but keep cheap deterministic or local
CPU/file work synchronous. ``graph.ainvoke()`` does not require every node and
tool to be declared with ``async def``.
"""

from collections.abc import Sequence
from typing import Literal

from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from src.agent.prompts import ROUTER_SYSTEM_PROMPT, SYSTEM_PROMPT
from src.app.clients.model_providers import ModelProvider
from src.config import settings

from .state import AgentState


# ModelProvider caches the selected LangChain chat model, so graph executions share
# one client object instead of rebuilding it for every node call. That is the normal
# LangChain pattern: request-specific messages and config are passed to invoke(), not
# stored on the model instance.
#
# Two reminders when changing the model provider:
# 1. with_structured_output() is implemented differently by each provider/model
#    (tool calling, JSON schema, JSON mode, etc.). Re-test RouterResponse whenever
#    the selected provider or model changes.
# 2. Shared model instances are safe while callbacks/middleware remain request-local.
#    If custom middleware stores mutable request state on the model object, this
#    concurrency assumption no longer holds.
llm = ModelProvider(
    model_provider=settings.MODEL_PROVIDER,
    model_name=settings.MODEL_NAME,
).get_llm_client()


class RouterResponse(BaseModel):
    """Structured decision returned by the response-format router.

    Pydantic field metadata is not only documentation here. LangChain turns this
    model into the schema shown to the LLM, so the field description helps instruct
    the model and also appears in generated JSON/OpenAPI-style schemas.
    """

    response_type: Literal["text", "audio"] = Field(
        description="For the response choose either 'text' or 'audio'"
    )


async def assistant_node(
    state: AgentState,
    *,
    tools: Sequence[BaseTool],
):
    """Run one assistant turn in the ReAct loop through async model transport.

    Tools are injected by ``create_workflow_graph`` so the exact tool set can
    contain application-owned clients. The returned ``AIMessage`` is the loop's
    source of truth: ``tools_condition`` inspects its tool calls, and ``ToolNode``
    appends observations before this node runs again. No separate planner or
    private scratchpad state is needed for the MVP.
    """
    llm_with_tools = llm.bind_tools(tools)

    # Reuse a previous compact summary when one exists; otherwise send the normal
    # system prompt plus the conversation currently held in graph state.
    summary = state.get("summary", "")

    if summary:
        system_content = (
            f"{SYSTEM_PROMPT.prompt} \n Summary of conversation earlier: {summary}"
        )
        messages = [SystemMessage(content=system_content), *state["messages"]]
    else:
        messages = [SystemMessage(content=SYSTEM_PROMPT.prompt), *state["messages"]]

    response = await llm_with_tools.ainvoke(messages)
    return {"messages": response}


async def choose_delivery_node(state: AgentState):
    """Choose text or audio only after the assistant has produced a final answer.

    Keeping delivery outside the ReAct cycle prevents an audio/text decision from
    running before every tool round. ``with_structured_output(RouterResponse)`` asks
    the provider for a validated object such as
    ``RouterResponse(response_type="audio")``.

    The classifier request deliberately ends with a new ``HumanMessage``. Sending
    ``SystemMessage`` followed directly by the completed ``AIMessage`` looks like
    model-response prefilling, which providers such as Gemini reject because the
    final request turn must come from a user or a tool response.
    """
    final_answer = state["messages"][-1].text
    latest_user_request = next(
        message.text
        for message in reversed(state["messages"])
        if isinstance(message, HumanMessage)
    )
    classification_request = HumanMessage(
        content=(
            "Choose the delivery format for the completed answer below. Consider "
            "the user's original request, but do not rewrite or answer it.\n\n"
            f"User request:\n{latest_user_request}\n\n"
            f"Completed assistant answer:\n{final_answer}"
        )
    )

    system_message = SystemMessage(content=ROUTER_SYSTEM_PROMPT.prompt)
    structured_llm = llm.with_structured_output(
        RouterResponse,
        method="json_schema",
    )
    response = await structured_llm.ainvoke([system_message, classification_request])

    return {"response_type": response.response_type}


async def summarize_conversation_node(state: AgentState):
    """Summarize older messages using native async model I/O.

    The summary is kept in state while ``RemoveMessage`` updates delete older chat
    messages from the message reducer. The latest two messages remain verbatim so
    the agent keeps recent detail instead of relying only on a lossy summary.
    """
    summary = state.get("summary", "")

    if summary:
        summary_message = (
            f"This is a summary of the conversation so far: {summary}\n\n"
            "Extend the summary by taking into account the new messages above:"
        )
    else:
        summary_message = "Create a summary of the conversation above:"

    messages = [*state["messages"], HumanMessage(content=summary_message)]
    response = await llm.ainvoke(messages)
    delete_messages = [
        RemoveMessage(id=message.id) for message in state["messages"][:-2]
    ]

    return {"summary": response.text, "messages": delete_messages}


def finalize_node(_state: AgentState):
    """Finish graph-owned work without rendering the selected transport.

    This node remains explicit because it is a useful extension seam for cheap,
    deterministic final-state work. Audio synthesis does not belong here: joining
    the provider's async chunks would delay playback, hold the whole file in memory,
    and place binary transport data in the checkpointer. The FastAPI adapter instead
    reads the durable text and ``response_type`` after the graph completes, then
    streams transient audio directly to the caller.

    Returning an empty update is intentional. LangGraph already carries the final
    assistant message and delivery choice forward in state.
    """
    return {}
