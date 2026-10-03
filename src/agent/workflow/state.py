from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """Durable conversational state stored by the selected checkpointer.

    ``MessagesState`` supplies ``messages`` with LangGraph's ``add_messages``
    reducer, so assistant and tool observations append correctly across ReAct turns.
    Keep transient delivery payloads out of this schema: audio chunks belong to the
    HTTP response stream, not MongoDB/SQLite checkpoints.
    """

    summary: str
    response_type: str
