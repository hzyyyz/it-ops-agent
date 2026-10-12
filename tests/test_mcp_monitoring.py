import asyncio
import os
import socket
import subprocess
import sys
import time

import pytest


def test_monitor_metrics_are_real_and_bounded():
    from mcp_tools.metrics import get_cpu_usage, get_memory_usage, get_disk_usage, get_process_list

    assert 0 <= get_cpu_usage()["percent"] <= 100
    assert 0 <= get_memory_usage()["percent"] <= 100
    assert 0 <= get_disk_usage()["percent"] <= 100
    processes = get_process_list(limit=5)
    assert len(processes) <= 5
    assert all(set(item) == {"pid", "name", "memory_percent"} for item in processes)


def test_mcp_server_exposes_four_monitor_tools():
    from mcp_tools.server import mcp

    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "get_cpu_usage", "get_memory_usage", "get_disk_usage", "get_process_list"
    }


def test_agent_monitor_tools_use_mcp_proxy():
    from agent.tools import mcp_monitor

    seen = []
    original = mcp_monitor.call_mcp_tool

    def fake_call(name, arguments):
        seen.append((name, arguments))
        return "healthy"

    mcp_monitor.call_mcp_tool = fake_call
    try:
        assert mcp_monitor.get_cpu_usage.invoke({}) == "healthy"
        assert mcp_monitor.get_process_list.invoke({"limit": 3}) == "healthy"
    finally:
        mcp_monitor.call_mcp_tool = original
    assert seen == [("get_cpu_usage", {}), ("get_process_list", {"limit": 3})]


def test_react_agent_registers_mcp_tools(monkeypatch):
    import agent.react_agent as module

    captured = {}
    monkeypatch.setattr(module, "create_agent", lambda **kwargs: captured.update(kwargs))
    module.ReactAgent()
    names = {tool.name for tool in captured["tools"]}
    assert {"get_cpu_usage", "get_memory_usage", "get_disk_usage", "get_process_list"} <= names
    assert "check_device_status" not in names


def test_mcp_client_calls_separate_server(monkeypatch):
    from agent.tools.mcp_monitor import call_mcp_tool

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = dict(os.environ, MCP_HOST="127.0.0.1", MCP_PORT=str(port))
    process = subprocess.Popen([sys.executable, "-m", "mcp_tools.server"], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if process.poll() is not None:
                pytest.fail("MCP server exited before accepting connections")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("MCP server did not start")
        monkeypatch.setenv("MCP_SERVER_URL", f"http://127.0.0.1:{port}/mcp")
        assert "percent" in call_mcp_tool("get_cpu_usage", {})
    finally:
        process.terminate()
        process.wait(timeout=5)
