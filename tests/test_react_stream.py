from langchain_core.messages import AIMessageChunk, ToolMessage


def test_react_agent_yields_model_text_chunks_only():
    from agent.react_agent import ReactAgent

    class FakeGraph:
        def stream(self, *args, **kwargs):
            assert kwargs["stream_mode"] == "messages"
            yield AIMessageChunk(content="你"), {"langgraph_node": "model"}
            yield AIMessageChunk(content="好"), {"langgraph_node": "model"}
            yield ToolMessage(content="secret-tool-result", tool_call_id="1"), {"langgraph_node": "tools"}
            yield AIMessageChunk(content="", tool_call_chunks=[{"name": "get_cpu_usage", "args": "{}", "id": "1", "index": 0}]), {"langgraph_node": "model"}

    agent = object.__new__(ReactAgent)
    agent.agent = FakeGraph()
    assert list(agent.execute_stream("hi")) == ["你", "好"]
