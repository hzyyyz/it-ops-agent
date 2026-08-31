# IT运维智能助手 — 基于 ReAct Agent 的企业设备管理 Agent

基于 LangChain/LangGraph 构建的 ReAct Agent 智能运维系统，集成 RAG 检索增强生成，为企业员工提供IT设备故障排查、系统配置指导、安全策略咨询及个性化设备健康度报告生成服务。

## 功能特性

- **ReAct Agent 推理**：思考→行动→观察→再思考的自主推理链路，自动判断何时调用哪个工具
- **RAG 检索增强**：基于 Chroma 向量库的IT运维知识检索，覆盖故障排除、安全策略、选购配置指南等场景
- **多轮对话记忆**：Agent 携带完整对话历史进行推理，支持上下文连续的追问和补充
- **设备健康度报告**：结合员工设备台账自动生成月度/年度设备资产健康度报告与运维建议
- **动态提示词切换**：通过中间件自动识别报告生成场景，切换专用提示词模板
- **流式输出**：Streamlit 前端实时渲染 Agent 思考与回复过程
- **工具调用监控**：完整的日志记录与中间件链路追踪，便于调试和审计
- **Docker 一键部署**：提供 Dockerfile + docker-compose.yml，支持容器化部署

## 项目结构

```
Agent项目/
├── app.py                      # Streamlit Web 入口
├── agent/
│   ├── react_agent.py          # ReAct Agent 核心
│   └── tools/
│       ├── agent_tools.py      # 工具定义（知识库检索、设备状态、资产查询等）
│       └── middleware.py       # 中间件（监控、日志、动态提示词）
├── rag/
│   ├── rag_service.py          # RAG 总结服务
│   └── vector_store.py         # Chroma 向量库管理（文档加载、分片、MD5去重）
├── model/
│   └── factory.py              # 模型工厂（LLM + Embedding）
├── utils/
│   ├── config_handler.py       # YAML 配置加载
│   ├── file_handler.py         # 文件处理（PDF/TXT加载、MD5去重）
│   ├── logger_handler.py       # 日志系统（控制台+文件双通道）
│   ├── path_tool.py            # 路径工具
│   └── prompt_loader.py        # 提示词加载
├── config/
│   ├── agent.yml               # Agent 配置（外部数据路径）
│   ├── chroma.yml              # 向量库配置（分片参数、检索参数）
│   ├── prompts.yml             # 提示词路径配置
│   └── rag.yml                 # 模型配置（LLM + Embedding）
├── prompts/
│   ├── mian_prompts.txt        # 主系统提示词（IT运维助手人设+ReAct规则）
│   ├── rag_summarize.txt       # RAG 总结提示词
│   └── report_prompt.txt       # 报告生成提示词
├── data/
│   ├── external/records.csv    # 设备资产台账模拟数据（10员工×12月）
│   ├── 故障排除.txt             # IT设备故障排查知识库
│   ├── 维护保养.txt             # IT设备维护保养规范
│   ├── 选购指南.txt             # 企业IT设备采购配置指南
│   └── 安全策略.txt             # 网络安全策略与最佳实践
└── logs/                       # 运行日志
```

## 技术栈

| 层级 | 技术 |
|------|------|
| Agent 框架 | LangChain / LangGraph |
| LLM | DeepSeek（兼容 OpenAI API，可替换为任意兼容模型） |
| Embedding | BAAI/bge-small-zh-v1.5（HuggingFace 本地离线加载） |
| 向量数据库 | Chroma |
| 前端 | Streamlit |
| 文档加载 | PyPDF / LangChain TextLoader |
| 配置管理 | YAML |

## 快速开始

### 1. 环境准备

- Python 3.10+
- 首次运行前需下载 Embedding 模型至本地缓存（运行 HuggingFaceEmbeddings 时自动缓存）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置

编辑 `Agent项目/config/rag.yml`：

```yaml
chat_model_name: deepseek-v4-pro
openai_base_url: https://api.deepseek.com
openai_api_key: "your-api-key"      # 可选，也可通过环境变量设置
embedding_model_name: BAAI/bge-small-zh-v1.5
```

### 4. 初始化知识库

将知识文档放入 `Agent项目/data/` 目录（已内置故障排除、维护保养、选购指南、安全策略四个知识库），然后执行：

```bash
cd Agent项目
python rag/vector_store.py
```

### 5. 启动应用

```bash
cd Agent项目
streamlit run app.py
```

浏览器访问 `http://localhost:8501`。

### 6. Docker 部署（可选）

```bash
cd Agent项目
cp .env.example .env           # 编辑 .env 填入真实 API Key
docker-compose up -d           # 构建并启动
```

浏览器访问 `http://localhost:8501`。

## 工具说明

| 工具名称 | 功能 | 入参 | 可扩展方向 |
|---------|------|------|-----------|
| `search_knowledge_base` | 从IT运维知识库检索专业技术资料 | query: str | 接入 Confluence/Jira Wiki API |
| `check_device_status` | 查询设备实时运行状态（CPU/内存/磁盘/网络） | asset_id: str | 接入 Prometheus/Zabbix API |
| `get_employee_department` | 获取当前员工所属部门 | 无 | 接入 LDAP/AD |
| `get_employee_id` | 获取当前员工工号 | 无 | 接入 SSO 系统 |
| `get_current_month` | 获取当前月份 | 无 | — |
| `query_asset_record` | 查询员工设备资产与维保记录 | employee_id, month | 接入 CMDB/资产管理系统 |
| `prepare_report_context` | 触发设备报告生成上下文 | 无 | — |

## 中间件说明

| 中间件 | 类型 | 功能 |
|--------|------|------|
| `monitor_tool` | `@wrap_tool_call` | 记录每次工具调用的名称、参数与结果，检测报告场景 |
| `log_before_model` | `@before_model` | 在 LLM 调用前记录消息摘要，便于排查推理异常 |
| `report_prompt_switch` | `@dynamic_prompt` | 检测报告生成场景，动态切换为报告专用提示词 |

## 提示词策略

项目采用双提示词架构，通过中间件自动切换：

- **主提示词**：处理日常IT运维咨询——故障排查、系统配置、网络诊断、安全事件处置、设备选型建议等
- **报告提示词**：当 Agent 检测到用户意图为"生成设备健康度报告"时，通过 `prepare_report_context` 工具触发中间件自动切换，引导模型生成结构化的 Markdown 报告，标题为"IT设备资产健康度报告与运维建议"

## 有待扩展的接口

当前工具返回模拟数据（Mock），以下接口预留了真实 API 接入点：

| 工具 | 当前实现 | 可替换为 |
|------|---------|---------|
| `check_device_status` | 随机返回预设状态 | Prometheus API / Zabbix API / 云厂商监控 API |
| `get_employee_department` | 随机返回部门 | LDAP/AD 查询 / HR 系统 API |
| `get_employee_id` | 随机返回工号 | SSO/OIDC 用户信息接口 |
| `query_asset_record` | 本地 CSV 文件 | CMDB API / 资产管理系统数据库 |
| `search_knowledge_base` | 本地 Chroma 向量库 | Confluence API / 企业 Wiki / Notion API |

## 子项目

| 目录 | 说明 |
|------|------|
| `Agent/` | LangChain Agent 入门示例（4个） |
| `LangChainRAG/` | LangChain RAG 渐进教程（24个示例） |
| `RAG项目案例/` | 简版 RAG 知识库问答 + 文件上传 |
| `提示词优化/` | OpenAI API 提示词工程示例（8个） |

## License

MIT
