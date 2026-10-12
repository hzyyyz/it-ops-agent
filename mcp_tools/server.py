"""Standalone Streamable HTTP MCP server for host monitoring."""

import os

from mcp.server.fastmcp import FastMCP

from mcp_tools import metrics


mcp = FastMCP("it-ops-monitor", host=os.getenv("MCP_HOST", "127.0.0.1"),
              port=int(os.getenv("MCP_PORT", "8001")), stateless_http=True)


@mcp.tool()
def get_cpu_usage() -> dict:
    """Read the MCP server host's current CPU usage percentage."""
    return metrics.get_cpu_usage()


@mcp.tool()
def get_memory_usage() -> dict:
    """Read the MCP server host's memory usage and available bytes."""
    return metrics.get_memory_usage()


@mcp.tool()
def get_disk_usage() -> dict:
    """Read disk usage for the MCP server's working volume."""
    return metrics.get_disk_usage()


@mcp.tool()
def get_process_list(limit: int = 10) -> list[dict]:
    """List up to 20 processes with highest memory usage; no command lines."""
    return metrics.get_process_list(limit)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
