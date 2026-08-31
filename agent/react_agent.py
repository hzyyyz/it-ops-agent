from langchain.agents import create_agent
from agent.tools.middleware import monitor_tool, log_before_model, log_after_model, report_prompt_switch
from agent.tools.agent_tools import (search_knowledge_base, check_device_status, get_employee_department,
                                     get_employee_id, get_current_month, query_asset_record,
                                     prepare_report_context)
from model.factory import chat_model
from utils.prompt_loader import load_system_prompt


class ReactAgent(object):
    def __init__(self):
        self.agent = create_agent(
            model=chat_model,
            system_prompt=load_system_prompt(),
            tools=[search_knowledge_base, check_device_status, get_employee_department,
                   get_employee_id, get_current_month, query_asset_record,
                   prepare_report_context],
            middleware=[monitor_tool, log_before_model, log_after_model, report_prompt_switch],
        )

    def execute_stream(self, query, history=None):
        messages = []
        if history:
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": query})

        input_dict = {"messages": messages}

        for chunk in self.agent.stream(input_dict, stream_mode="values", context={"report": False}):
            latest_message = chunk["messages"][-1]
            if latest_message.content and getattr(latest_message, "type", "") == "ai":
                yield latest_message.content.strip() + "\n"


if __name__ == '__main__':
    agent = ReactAgent()
    for chunk in agent.execute_stream("我的办公电脑运行很卡，帮我查一下设备状态"):
        print(chunk, end="", flush=True)
