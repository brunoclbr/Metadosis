import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

import httpx
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from src.agent.workflow import graph, nodes
from src.agent.workflow.tools import create_read_url_tool, read_pdf_tool


class FakeChatModel:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.await_count = 0
        self.bound_tools = None
        self.last_messages = None

    def with_structured_output(
        self,
        _schema: Any,
        **_kwargs: Any,
    ) -> "FakeChatModel":
        return self

    def bind_tools(self, tools: Any) -> "FakeChatModel":
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages: Any) -> Any:
        self.await_count += 1
        self.last_messages = messages
        await asyncio.sleep(0)
        return self.response

    def invoke(self, _messages: Any) -> Any:
        raise AssertionError("workflow LLM nodes must use ainvoke")


def test_llm_nodes_use_native_async_invocation(monkeypatch) -> None:
    async def exercise_nodes() -> None:
        response = AIMessage(content="answer")
        response_model = FakeChatModel(response)
        monkeypatch.setattr(nodes, "llm", response_model)
        generated = await nodes.assistant_node(
            {"messages": [HumanMessage(content="hello")]},
            tools=[read_pdf_tool],
        )
        assert generated == {"messages": response}
        assert response_model.await_count == 1
        assert response_model.bound_tools == [read_pdf_tool]

        router_model = FakeChatModel(SimpleNamespace(response_type="text"))
        monkeypatch.setattr(nodes, "llm", router_model)
        routed = await nodes.choose_delivery_node(
            {
                "messages": [
                    HumanMessage(content="reply with audio"),
                    AIMessage(content="completed answer"),
                ]
            }
        )
        assert routed == {"response_type": "text"}
        assert router_model.await_count == 1
        assert isinstance(router_model.last_messages[-1], HumanMessage)
        assert "reply with audio" in router_model.last_messages[-1].content
        assert "completed answer" in router_model.last_messages[-1].content

        summary_model = FakeChatModel(AIMessage(content="summary"))
        monkeypatch.setattr(nodes, "llm", summary_model)
        summarized = await nodes.summarize_conversation_node(
            {"messages": [HumanMessage(content="hello")], "summary": ""}
        )
        assert summarized["summary"] == "summary"
        assert summary_model.await_count == 1

    asyncio.run(exercise_nodes())


def test_url_tool_is_async_while_pdf_tool_remains_sync() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.test"
        return httpx.Response(
            200,
            text="<html><script>ignore()</script><body>Useful text</body></html>",
        )

    async def exercise_tool() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            url_tool = create_read_url_tool(client)
            assert url_tool.coroutine is not None
            assert (
                await url_tool.ainvoke({"url": "https://example.test"}) == "Useful text"
            )

    asyncio.run(exercise_tool())
    assert read_pdf_tool.coroutine is None
    assert not inspect.iscoroutinefunction(read_pdf_tool.func)


def test_finalize_keeps_transient_audio_out_of_graph_state() -> None:
    result = nodes.finalize_node(
        {
            "messages": [AIMessage(content="speak")],
            "response_type": "audio",
        }
    )

    assert result == {}


def test_react_graph_answers_after_one_tool_round_trip(monkeypatch) -> None:
    """Exercise observable loop behavior without testing ToolNode internals."""

    @tool
    def lookup_fact(topic: str) -> str:
        """Look up one fact for a topic."""
        return f"fact about {topic}"

    class ReActModel:
        def __init__(self) -> None:
            self.calls = 0

        def bind_tools(self, _tools: Any) -> "ReActModel":
            return self

        async def ainvoke(self, messages: Any) -> AIMessage:
            self.calls += 1
            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "lookup_fact",
                            "args": {"topic": "graphs"},
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                )
            assert messages[-1].content == "fact about graphs"
            return AIMessage(content="final answer")

    model = ReActModel()
    monkeypatch.setattr(nodes, "llm", model)
    monkeypatch.setattr(
        graph,
        "choose_delivery_node",
        lambda _state: {"response_type": "text"},
    )
    workflow = graph.create_workflow_graph([lookup_fact]).compile()
    result = asyncio.run(
        workflow.ainvoke(
            {"messages": [("user", "help")]},
            config={"recursion_limit": 10},
        )
    )

    assert model.calls == 2
    assert result["messages"][-1].content == "final answer"
    assert result["response_type"] == "text"
