"""MCP Server for mikr.us API."""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mikrus_mcp.api import MikrusAPI

load_dotenv()

API_KEY = os.getenv("MIKRUS_API_KEY", "")
API_URL = os.getenv("MIKRUS_API_URL", "https://api.mikr.us")


@asynccontextmanager
async def app_lifespan(server: Server) -> AsyncIterator[dict]:
    """Manage application lifecycle."""
    async with httpx.AsyncClient() as client:
        api = MikrusAPI(client, API_KEY, API_URL)
        yield {"api": api}


app = Server("mikrus-mcp", lifespan=app_lifespan)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="server_info",
            description="Get information about your mikr.us server",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="server_logs",
            description="Get logs from your mikr.us server",
            input_schema={
                "type": "object",
                "properties": {
                    "lines": {
                        "type": "integer",
                        "description": "Number of lines to fetch",
                        "default": 50,
                    }
                },
            },
        ),
        Tool(
            name="server_restart",
            description="Restart your mikr.us server",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="server_amfetamina",
            description="Enable 'amfetamina' (boost) on your mikr.us server",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="server_port_check",
            description="Check if a port is open on your mikr.us server",
            input_schema={
                "type": "object",
                "properties": {
                    "port": {
                        "type": "integer",
                        "description": "Port number to check",
                    }
                },
                "required": ["port"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Call a tool."""
    ctx = app.request_context
    api: MikrusAPI = ctx.lifespan_context["api"]

    if name == "server_info":
        result = await api.get_server_info()
    elif name == "server_logs":
        lines = arguments.get("lines", 50)
        result = await api.get_server_logs(lines)
    elif name == "server_restart":
        result = await api.restart_server()
    elif name == "server_amfetamina":
        result = await api.enable_amfetamina()
    elif name == "server_port_check":
        port = arguments["port"]
        result = await api.check_port(port)
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return [TextContent(type="text", text=result)]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
