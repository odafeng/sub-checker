"""Tools for agents to search the web and fetch pages."""

from __future__ import annotations

from sub_checker.services.web import WebService


async def web_search(service: WebService, query: str) -> str:
    """Search the web and return summarized results."""
    results = await service.search(query)
    if not results:
        return f"No web results found for '{query}'."
    lines = [f"Found {len(results)} result(s):"]
    for r in results[:5]:
        lines.append(f"  - {r['title']}: {r['snippet'][:150]}...")
        lines.append(f"    URL: {r['url']}")
    return "\n".join(lines)


async def fetch_page(service: WebService, url: str) -> str:
    """Fetch and extract text content from a URL."""
    content = await service.fetch_page(url)
    if not content:
        return f"Could not fetch content from {url}."
    # Truncate to avoid overwhelming the agent
    if len(content) > 8000:
        content = content[:8000] + "\n\n[... truncated, content too long]"
    return content


TOOL_WEB_SEARCH = {
    "name": "web_search",
    "description": "Search the web for information. Useful for finding journal submission guidelines, citation format requirements, etc.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query",
            }
        },
        "required": ["query"],
    },
}

TOOL_FETCH_PAGE = {
    "name": "fetch_page",
    "description": "Fetch and extract text content from a URL. Useful for reading journal 'Instructions for Authors' pages.",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to fetch",
            }
        },
        "required": ["url"],
    },
}
