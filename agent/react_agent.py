from langchain.agents import create_agent
from agent.tools.middleware import monitor_tool, trace_model_call, log_before_model, log_after_model, report_prompt_switch
from agent.tools.agent_tools import (search_knowledge_base, get_employee_department,
                                     get_employee_id, get_current_month, query_asset_record,
                                     prepare_report_context)
from agent.tools.mcp_monitor import get_cpu_usage, get_memory_usage, get_disk_usage, get_process_list
from model.factory import chat_model
from utils.prompt_loader import load_system_prompt
from agent.report_workflow import ReportWorkflow, is_report_request, is_report_followup
from observability.tracing import record


class ReactAgent(object):
    def __init__(self):
        self.report_workflow = ReportWorkflow()
        self.agent = create_agent(
            model=chat_model,
            system_prompt=load_system_prompt(),
            tools=[search_knowledge_base, get_cpu_usage, get_memory_usage, get_disk_usage,
                   get_process_list, get_employee_department,
                   get_employee_id, get_current_month, query_asset_record,
                   prepare_report_context],
            middleware=[monitor_tool, trace_model_call, log_before_model, log_after_model, report_prompt_switch],
        )

    def execute_stream(self, query, history=None):
        if is_report_request(query) or is_report_followup(query, history):
            record("report.route")
            yield from self.report_workflow.stream(query, history=history)
            return
        messages = []
        if history:
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": query})

        input_dict = {"messages": messages}

        for chunk, metadata in self.agent.stream(input_dict, stream_mode="messages", context={"report": False}):
            if (metadata.get("langgraph_node") == "model"
                    and getattr(chunk, "type", "") == "AIMessageChunk"
                    and not getattr(chunk, "tool_call_chunks", None)):
                content = chunk.content
                if isinstance(content, str) and content:
                    yield content


if __name__ == '__main__':
    agent = ReactAgent()
    for chunk in agent.execute_stream("我的办公电脑运行很卡，帮我查一下设备状态"):
        print(chunk, end="", flush=True)
