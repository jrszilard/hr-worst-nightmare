"""Shared MCP utilities for Chrome MCP-based agents."""

from __future__ import annotations

from typing import Any


async def get_anthropic_tools(mcp_client: Any) -> list[dict]:
    """Discover MCP tools and mirror schemas for Anthropic API.

    Parameters
    ----------
    mcp_client:
        An MCP client with a ``list_tools()`` coroutine that returns a list
        of tool definition dicts.

    Returns
    -------
    list[dict]
        Tool definitions ready to pass to the Anthropic ``messages.create``
        ``tools`` parameter.
    """
    mcp_tools = await mcp_client.list_tools()
    return [
        {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "input_schema": tool.get("input_schema", tool.get("inputSchema", {"type": "object"})),
        }
        for tool in mcp_tools
    ]
