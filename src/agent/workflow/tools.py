"""Example tools that can be kept, replaced, or deleted in inherited projects.

This blueprint intentionally shows different execution boundaries: local PDF work
stays synchronous, URL fetching is native async, and the optional retriever shows
how a vector-store-backed tool can be assembled.
"""

from functools import lru_cache
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from langchain_core.tools import BaseTool, create_retriever_tool, tool
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from pypdf import PdfReader

from src.app.clients.qdrant import get_qdrant_client
from src.config import settings


PDF_PATH = Path(__file__).resolve().parents[4] / ".data/minio"


# PDF parsing is local file/CPU work. Declaring it async would not make pypdf
# non-blocking, so keep it synchronous and cache the static development asset after
# its first read. ToolNode can offload sync-only tools during async graph execution.
@lru_cache(maxsize=1)
def _load_pdf_text() -> str:
    reader = PdfReader(PDF_PATH)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(page.strip() for page in pages if page.strip())


# A @tool docstring becomes part of the description shown to the model. Keep
# model-facing instructions there; keep implementation lessons in comments like this.
@tool
def read_pdf_tool() -> str:
    """Read the local PDF and return its extracted text."""
    return _load_pdf_text()


# The full FastAPI example injects one client from its lifespan for connection
# pooling. Smaller blueprint examples can omit it; the tool then owns a temporary
# client and closes it after the request. This keeps create_workflow_graph() useful
# without forcing every inherited project to adopt FastAPI's lifecycle.
def create_read_url_tool(http_client: httpx.AsyncClient | None = None) -> BaseTool:
    """Create the URL tool with optional application-owned infrastructure."""

    # Only the decorated function's docstring is sent to the model as instructions;
    # the outer factory docstring documents Python code for blueprint maintainers.
    @tool
    async def read_url_tool(url: str) -> str:
        """Read a URL and return its visible text."""
        if http_client is None:
            async with httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20.0,
                follow_redirects=True,
            ) as request_client:
                response = await request_client.get(url)
        else:
            response = await http_client.get(url)

        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)[:30000]

    return read_url_tool


@lru_cache(maxsize=1)
def get_retriever_tool():
    """Build the optional retriever tool once.

    This function is a synchronous object factory; making the factory ``async``
    would add no value. Runtime retrieval is handled through the tool interface and
    ToolNode's async execution path when the selected integration supports it.
    """
    embeddings = GoogleGenerativeAIEmbeddings(
        model="gemini-embedding-2-preview",
        output_dimensionality=512,
        api_key=settings.GEMINI_API_KEY,
    )

    vector_store = QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name="agentic-data-engineer",
        embedding=embeddings,
        vector_name="abstract-dense-vector",
    )

    retriever = vector_store.as_retriever()

    # create_retriever_tool has no decorated function docstring, so this explicit
    # description is the instruction the model sees for deciding when to call it.
    return create_retriever_tool(
        retriever=retriever,
        name="retrieve_agent_information_tool",
        description="Retrieve information about the Agent's background and personality",
    )


def get_tools(http_client: httpx.AsyncClient | None = None) -> list[BaseTool]:
    """Return the tool menu for this example agent.

    ``http_client`` lets an application reuse its pooled client in the URL tool;
    leaving it as ``None`` keeps standalone blueprint usage lifecycle-independent.

    Treat this list as a blueprint decision point: enable the retriever only when
    the inherited application actually needs RAG, and delete unused tools and their
    clients rather than shipping every example integration.
    """
    return [
        # Optional RAG example:
        # get_retriever_tool(),
        read_pdf_tool,
        create_read_url_tool(http_client),
    ]
