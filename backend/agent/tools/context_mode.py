"""Context Mode sandbox tool backed by the mksglu/context-mode MCP server."""

from langchain_core.tools import tool

from agent.mcp.context_mode_tools import run_tool as context_mode_run


@tool
def context_mode(
    action: str,
    language: str = "",
    code: str = "",
    content: str = "",
    query: str = "",
    url: str = "",
    source: str = "",
    title: str = "",
    content_type: str = "",
    timeout: int | None = None,
    force: bool = False,
    confirm: bool = False,
) -> str:
    """Sandbox tool output and indexed retrieval via the Context Mode MCP server.

    Actions:
      - execute: language=<python|javascript|bash|typescript|ruby|go|rust|php|perl|r|elixir|csharp>, code=<...>
        Runs the script in a sandboxed subprocess; only stdout is returned. Use this
        instead of pulling many files into context when an answer can be computed.
      - index: content=<markdown>, source=<id>, title=<...>
        Chunks markdown into a local FTS5/BM25 store for later retrieval.
      - search: query=<string or list>, content_type=<code|prose>, source=<filter>
        Returns BM25-ranked snippets from previously indexed content.
      - fetch_and_index: url=<http(s)>, source=<id>, force=<bool>
        Fetches a URL, converts to markdown, indexes it. 24h cache; force=true bypasses.
      - stats / doctor: operational info about the local sandbox + index.
      - purge: confirm=true required. Deletes all indexed content irreversibly.

    Output from fetch_and_index is external content that has NOT passed through
    Vellum's privacy gate — summarize or scrub before quoting in user-visible text.
    """

    return context_mode_run(
        {
            "action": action,
            "language": language,
            "code": code,
            "content": content,
            "query": query,
            "url": url,
            "source": source,
            "title": title,
            "content_type": content_type,
            "timeout": timeout,
            "force": force,
            "confirm": confirm,
        }
    )
