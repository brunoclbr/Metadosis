"""Application-specific conditional routing for the workflow.

Mental model:
    Nodes do work and return state updates.
    Conditional edges inspect state and choose where execution goes next.

Use a custom edge when routing depends on application state, for example summary,
approval, or retry policy. Do not recreate standard tool-call routing: LangGraph's
``tools_condition`` already inspects the latest ``AIMessage`` and routes either to
``"tools"`` or ``END``. In ``graph.py``, a path map translates that ``END`` result
to the delivery phase rather than ending the whole workflow immediately.
"""

from typing import Literal

from langgraph.graph import END

from .state import AgentState


def route_after_action_planning(
    state: AgentState,
) -> Literal["tools", "request_human_approval_node", END]:
    """
    Example:
        risky/sensitive action -> ask human first
        normal pending action  -> execute tools
        nothing left to do     -> end
    """

    if state["requires_approval"]:
        return "request_human_approval_node"

    if state["pending_tool_calls"]:
        return "tools"

    return END

def should_summarize_conversation(
    state: AgentState,
) -> Literal["summarize", END]:
    """Route long conversations through compact post-response summarization.

    Inheriting from ``MessagesState`` supplies the ``messages`` key and its
    ``add_messages`` reducer without repeating that boilerplate. Summarization runs
    after delivery has been selected and finalized, so it cannot interfere with the
    assistant/tool loop's action and observation messages.
    """
    messages = state["messages"]
    return "summarize" if len(messages) >= 30 else END
