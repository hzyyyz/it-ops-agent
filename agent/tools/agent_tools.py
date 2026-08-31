from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolCallRequest

from rag.rag_service import RagSummarizeService
import random, os, psutil, time
from datetime import datetime
from utils.config_handler import agent_conf
from utils.path_tool import get_abs_path
from utils.logger_handler import logger


rag = RagSummarizeService()

employee_ids = ["EMP1001", "EMP1002", "EMP1003", "EMP1004", "EMP1005",
                "EMP1006", "EMP1007", "EMP1008", "EMP1009", "EMP1010"]

external_data = {}


@tool(description="从IT运维知识库中检索专业技术资料，包括故障处理、系统配置、网络排查、安全策略等")
def search_knowledge_base(query: str) -> str:
    return rag.rag_summarize(query)


@tool(description="查询设备实时运行状态，读取本机真实的CPU、内存、磁盘、开机时长指标。asset_id用于标注设备名称，可选")
def check_device_status(asset_id: str = "LOCAL-HOST") -> str:
    psutil.cpu_percent(interval=None)  # 建立基准采样，避免首次调用返回0
    time.sleep(0.2)
    cpu = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory().percent
    disk = psutil.disk_usage(".").percent
    uptime = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
    if uptime.days > 0:
        uptime_str = f"{uptime.days}天{uptime.seconds // 3600}小时"
    else:
        uptime_str = f"{uptime.seconds // 3600}小时{uptime.seconds % 3600 // 60}分钟"
    return (f"设备[{asset_id}]实时状态 | CPU: {cpu}% | 内存: {memory}% | "
            f"磁盘: {disk}% | 开机时长: {uptime_str}")


@tool(description="获取当前员工所属部门名称，以纯字符形式返回")
def get_employee_department() -> str:
    departments = ["研发部", "运维部", "产品部", "设计部", "市场部", "财务部", "人力资源部"]
    return random.choice(departments)


@tool(description="获取当前员工工号，格式为EMP开头后接数字（如EMP1001），以纯字符形式返回")
def get_employee_id() -> str:
    return random.choice(employee_ids)


@tool(description="获取当前月份，格式为YYYY-MM，以纯字符形式返回")
def get_current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def load_asset_records():
    """从外部数据文件加载设备资产台账"""
    if not external_data:
        if "external_data_path" not in agent_conf:
            raise KeyError("配置中缺少 external_data_path 字段")

        external_data_path = get_abs_path(agent_conf["external_data_path"])

        if not os.path.exists(external_data_path):
            raise FileNotFoundError(f"外部数据文件不存在: {external_data_path}")

        with open(external_data_path, "r", encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                arr = line.strip().split(",")

                employee_id = arr[0].replace('"', "")
                device_config = arr[1].replace('"', "")
                running_status = arr[2].replace('"', "")
                maintenance = arr[3].replace('"', "")
                security_score = arr[4].replace('"', "")
                month = arr[5].replace('"', "")

                if employee_id not in external_data:
                    external_data[employee_id] = {}

                external_data[employee_id][month] = {
                    "设备配置": device_config,
                    "运行状态": running_status,
                    "维保记录": maintenance,
                    "安全评分": security_score,
                }


@tool(description="查询指定员工在指定月份的IT设备资产与维保记录，包含设备配置、运行状态、维保记录和安全评分，以结构化文本返回")
def query_asset_record(employee_id: str, month: str) -> str:
    load_asset_records()
    try:
        return str(external_data[employee_id][month])
    except KeyError:
        logger.warning(f"[query_asset_record]未能查询到员工:{employee_id}在{month}的设备记录。")
        return ""


@tool(description="无入参，无返回值，调用后触发中间件自动为设备报告生成场景动态注入上下文，为后续提示词切换提供上下文支撑")
def prepare_report_context():
    return "prepare_report_context已调用"
