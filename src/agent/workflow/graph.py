"""LangGraph topology for the ReAct agent.

This module returns an uncompiled ``StateGraph`` on purpose. The host decides
whether to compile it with MongoDB, SQLite, an in-memory checkpointer, or no
persistence at all.

The graph keeps the dynamic reasoning loop small and visible::

    assistant -> tools -> assistant
         |
         +-> choose_delivery -> finalize -> optional summary -> END

Delivery and summarization happen only after the assistant stops requesting tools.
"""

from collections.abc import Sequence
from functools import partial

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from .edges import should_summarize_conversation
from .nodes import (
    assistant_node,
    choose_delivery_node,
    finalize_node,
    summarize_conversation_node,
)
from .state import AgentState
from .tools import get_tools


def create_workflow_graph(tools: Sequence[BaseTool] | None = None):
    """Describe the workflow without choosing tool transport or persistence.

    Application hosts may inject an assembled tool set containing their own clients.
    Calling this with no arguments uses the default tools from ``tools.py``.

    ``partial`` used in the first node "binds" graph-construction dependencies lile `graph_tools` while 
    leaving ``state`` as the ONLY positional argument LangGraph supplies to each node at execution time, 
    which would otherwise cause an error (because we are passing 2 positonal arguments instead of one - the "State"). 
    This also binds the tool menu once per graph configuration rather than rebuilding it on every turn.
    """
    graph_tools = list(tools) if tools is not None else get_tools()

    # One assistant and one ToolNode form the MVP ReAct loop. The latest AIMessage
    # carries requested tool calls, and ToolNode appends ToolMessage observations;
    # duplicating either in custom state would create competing sources of truth.
    graph_builder = StateGraph(AgentState)
    graph_builder.add_node(
        "assistant",
        partial(assistant_node, tools=graph_tools),
    )

    # ToolNode may execute independent calls from one AIMessage concurrently. Keep
    # this menu for safe reads; ordered or consequential writes need a higher-level,
    # deterministic tool or a deliberately sequential execution boundary.
    graph_builder.add_node("tools", ToolNode(graph_tools))
    graph_builder.add_node("choose_delivery", choose_delivery_node)

    # Finalization intentionally leaves rendering to the HTTP adapter. Keeping
    # transient audio streams outside graph state makes checkpoints small and lets
    # FastAPI forward chunks as ElevenLabs produces them.
    graph_builder.add_node("finalize", finalize_node)
    graph_builder.add_node("summarize", summarize_conversation_node)

    graph_builder.add_edge(START, "assistant")

    # Use LangGraph's standard router rather than reimplementing tool-call checks.
    # A tool request loops through ToolNode; a normal assistant answer leaves the
    # ReAct loop and enters deterministic delivery processing. Here we HAVE TO 
    # call 'END' on path_map (which will be the key in the graph) to route to the
    # 'choose_delivery' node, because `tools_condition` returns either 'tools' or 'END'
    graph_builder.add_conditional_edges(
        source="assistant",
        path=tools_condition,
        path_map={"tools": "tools", END: "choose_delivery"},
    )

    graph_builder.add_edge("tools", "assistant")
    graph_builder.add_edge("choose_delivery", "finalize")

    # Summarization is post-processing, not another reasoning turn. The edge keeps
    # this application-specific policy separate from standard tool routing.
    graph_builder.add_conditional_edges(
        "finalize",
        should_summarize_conversation,
        path_map={"summarize": "summarize", END: END},
    )
    graph_builder.add_edge("summarize", END)

    # Compilation belongs to the host. See backend/main.py for MongoDB and
    # app/clients/sqlite.py for an alternative checkpointer.
    return graph_builder
