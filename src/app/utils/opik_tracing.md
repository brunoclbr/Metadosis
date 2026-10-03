# Opik tracing in this application

`OpikTracer` is a LangChain callback that observes graph execution; it does not execute the graph itself. `track_langgraph()` attaches that tracer to the compiled graph's default callback configuration, allowing LangGraph/LangChain to propagate tracing through graph nodes, LLM calls, and tool calls.

The backend prepares tracing once during FastAPI lifespan startup:

```text
compiled LangGraph
       ↓
OpikTracer(project_name=settings.COMET_PROJECT)
       ↓
track_langgraph(compiled_graph, tracer)
       ↓
tracked reusable graph
```

Requests invoke the prepared graph with only request-specific input and `thread_id`:

```python
result = await workflow.ainvoke(
    message,
    config={"configurable": {"thread_id": thread_id}},
)
```

A call made outside this callback tree, or in another process without propagated trace context, is not automatically included. Prompt registration through `client.create_prompt(...)` versions prompts and is separate from tracing a chat request.

During shutdown, FastAPI lifespan flushes the shared tracer before closing MongoDB. Each Uvicorn worker process owns its own tracer and tracked graph.

See [`docs/LANGGRAPH_ARCHITECTURE.md`](../../../docs/LANGGRAPH_ARCHITECTURE.md) for the complete lifecycle, checkpointing, concurrency, and production notes.
