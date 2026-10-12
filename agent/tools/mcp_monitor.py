"""LangChain-facing tools that invoke a separate MCP service."""

import asyncio
import json
import os

from langchain_core.tools import tool
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def _call_mcp_tool(name: str, arguments: dict) -> str:
    url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001/mcp")
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
    if result.isError:
        raise RuntimeError(f"MCP tool {name} failed")
    if result.structuredContent is not None:
        return json.dumps(result.structuredContent, ensure_ascii=False)
    return "\n".join(part.text for part in result.content if part.type == "text")


def call_mcp_tool(name: str, arguments: dict) -> str:
    return asyncio.run(_call_mcp_tool(name, arguments))


@tool(description="通过 MCP 服务查询当前 CPU 使用率；监测的是 MCP 服务所在主机或容器")
def get_cpu_usage() -> str:
    return call_mcp_tool("get_cpu_usage", {})


@tool(description="通过 MCP 服务查询当前内存使用率及容量；监测的是 MCP 服务所在主机或容器")
def get_memory_usage() -> str:
    return call_mcp_tool("get_memory_usage", {})


@tool(description="通过 MCP 服务查询当前工作磁盘使用率；监测的是 MCP 服务所在主机或容器")
def get_disk_usage() -> str:
    return call_mcp_tool("get_disk_usage", {})


@tool(description="通过 MCP 服务列出内存占用最高的进程，最多20条，不返回命令行")
def get_process_list(limit: int = 10) -> str:
    return call_mcp_tool("get_process_list", {"limit": limit})
