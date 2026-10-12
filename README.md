# IT运维智能助手 — 基于 ReAct Agent 的企业设备管理 Agent

基于 LangChain/LangGraph 构建的 ReAct Agent 智能运维系统，集成 RAG 检索增强生成，为企业员工提供IT设备故障排查、系统配置指导、安全策略咨询及个性化设备健康度报告生成服务。

## 功能特性

- **ReAct Agent 推理**：思考→行动→观察→再思考的自主推理链路，自动判断何时调用哪个工具
- **可对比的 RAG**：保留 Chroma 纯向量基线，并提供 Query Rewrite、BM25 + 向量融合及本地交叉编码器重排
- **增量知识库更新**：按 chunk 对账，只嵌入新增或变化内容，并清除过期向量
- **Agent 评测**：50 条分类样例，记录 Recall@3/@5、工具选择、任务完成代理指标、延迟与 token 用量
- **MCP 监控指标**：独立 MCP Server 通过 psutil 提供 CPU、内存、磁盘及进程列表；指标来自服务所在主机或容器
- **MySQL 会话持久化**：保存完整问答，支持新建、恢复、分页浏览和删除历史会话；Agent 使用最近 100 条消息作为上下文
- **Redis 会话缓存**：缓存最近 100 条上下文 30 分钟；以 MySQL 版本号校验，Redis 故障时自动回源
- **设备健康度报告**：报告请求进入独立 LangGraph 工作流，按员工、月份查询台账，生成有依据的月度报告；缺少记录时明确提示
- **报告专用提示词**：报告图调用模型时使用专用写作约束，避免把历史台账当作实时指标
- **实时回答**：Streamlit 消费 FastAPI 的 SSE 增量事件，并逐步显示模型输出
- **轻量 Web 工作台**：FastAPI 同源提供聊天、历史会话、知识库文档管理和 Agent Trace 页面
- **工具调用监控**：完整的日志记录与中间件链路追踪，便于调试和审计
- **Docker 一键部署**：提供 Dockerfile + docker-compose.yml，支持容器化部署

## 项目结构

```
Agent项目/
├── app.py                      # Streamlit Web 入口
├── web/                        # FastAPI 提供的轻量前端（HTML/CSS/JS）
├── frontend/chat_client.py     # HTTP 客户端、超时与错误提示
├── backend/
│   ├── main.py                 # FastAPI 入口、异常处理
│   ├── api/chat.py             # JSON 与 SSE 聊天接口
│   ├── api/sessions.py         # 会话列表、详情和删除接口
│   ├── api/knowledge.py        # 文档上传、列表、删除及同步接口
│   ├── api/traces.py           # 按 Trace ID 读取安全的执行元数据
│   ├── database.py             # MySQL 连接池和数据库依赖
│   ├── cache.py                # Redis 最近会话上下文缓存
│   ├── init_db.py              # 显式初始化数据库表
│   ├── models/session.py       # sessions / messages ORM 模型
│   ├── schemas/chat.py         # 请求/响应校验
│   ├── schemas/session.py      # 会话与消息响应模型
│   ├── services/session_service.py # 历史读取、事务保存、并发控制
│   ├── services/knowledge_service.py # 文档校验、保存与索引同步
│   └── services/agent_service.py # 调用现有 Agent、聚合回答
├── agent/
│   ├── react_agent.py          # ReAct Agent 核心与模型消息流
│   ├── report_workflow.py      # 设备报告的取数、状态提取、生成与复位图
│   └── tools/
│       ├── agent_tools.py      # 本地工具定义（知识库、资产查询等）
│       ├── mcp_monitor.py      # 通过 MCP 协议调用独立监控服务
│       └── middleware.py       # 中间件（监控、日志、动态提示词）
├── mcp_tools/
│   ├── server.py               # 独立 MCP Server，注册四个监控工具
│   └── metrics.py              # 有界的 psutil 指标采集
├── rag/
│   ├── rag_service.py          # RAG 总结服务
│   ├── retrieval.py            # 基线、BM25、混合检索及融合
│   ├── reranker.py             # 延迟加载的本地交叉编码器
│   ├── vector_store.py         # Chroma 初始化与知识库同步入口
│   └── knowledge_sync.py       # 按 chunk 对账的增量更新
├── evaluation/
│   ├── runner.py               # 离线检索与可选真实 Agent 评测命令
│   ├── metrics.py              # 指标计算
│   ├── dataset.py              # 评测集校验
│   └── agent_trace.py          # 工具、耗时及 token 采集
├── tests/eval_dataset.json     # 50 条人工标注测试问题
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
│   ├── external/records.csv    # 设备资产台账模拟数据（10员工×2025-2026年月度记录）
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
| 检索排序 | BM25 / Reciprocal Rank Fusion / 本地 CrossEncoder |
| 前端 | 原生 HTML/CSS/JavaScript；保留 Streamlit 页面 |
| HTTP 服务 | FastAPI / Uvicorn / Pydantic |
| 工具协议 | MCP Streamable HTTP |
| 会话存储 | MySQL 8 / SQLAlchemy 2 / PyMySQL；Redis 最近上下文缓存 |
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
chat_model_name: deepseek-v4-flash
openai_base_url: https://api.deepseek.com
openai_api_key: "your-api-key"      # 可选，优先级低于环境变量
embedding_model_name: BAAI/bge-small-zh-v1.5
```

模型密钥由 `model/factory.py` **按 `openai_base_url` 自动选择**：端点指向 DeepSeek 时用
`DEEPSEEK_API_KEY`，指向 OpenAI 时用 `OPENAI_API_KEY`；两者都没有才回退到上面的
`openai_api_key`。这样机器上同时存在两种密钥时不会把 OpenAI 的 Key 发给 DeepSeek
（反之亦然，服务端会直接返回 401）。`load_dotenv` 不覆盖已有环境变量，所以进程环境变量
优先级高于 `.env`。

### 4. 初始化知识库

将知识文档放入 `Agent项目/data/` 目录（已内置故障排除、维护保养、选购指南、安全策略四个知识库），然后执行：

```bash
cd Agent项目
python -m rag.vector_store
```

### 5. 配置管理员口令、MySQL 和初始化数据表

在 MySQL 中准备本项目专用的空数据库（例如 `it_ops_agent`，字符集 `utf8mb4`），
并创建有该库建表、查询、写入权限的应用账号。不要使用已有其他应用的数据库。
在项目根目录 `.env` 中填写以下配置，或设置同名进程环境变量；已有环境变量优先于 `.env`：

```dotenv
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=it_ops_agent
MYSQL_USER=it_ops_agent
MYSQL_PASSWORD="your-database-password"
AGENT_ADMIN_TOKEN="replace-with-at-least-32-random-characters"
```

把 `AGENT_ADMIN_TOKEN` 换成至少 32 个随机字符。可用 PowerShell 生成：
`[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))`。
它是本地单用户管理员口令，不是模型 API Key；不要提交真实口令到仓库。
数据库账号与模型 API Key 是不同配置，密码不需要 URL 编码。然后在项目根目录运行：

```bash
python -m backend.init_db
```

该命令创建 `users`、`sessions`、`messages`、`documents`、`evaluation_results` 五张表，
并把已有 `sessions` 表增加 `user_id` 列、将旧会话归属到本地管理员。可以重复执行，不会清空消息；
旧库升级需要应用账号具备 `ALTER` 权限。升级前仍建议备份 MySQL 数据库。
`documents` 保存知识文件的大小、更新时间与索引状态；`evaluation_results` 保存评测摘要，
逐题明细仍保存在 JSON 报告中。
API 启动时不会自动建表，也不会在 MySQL 不可用时回退到 SQLite。

### 5.1 Redis 最近会话缓存

Docker Compose 会启动内部 Redis，并自动为 API 设置 `REDIS_URL=redis://redis:6379/0`；
Redis 不向主机公开端口。本地分别启动服务时，可在 `.env` 设置
`REDIS_URL=redis://127.0.0.1:6379/0`；不设置则禁用缓存。
缓存键为 `session:{id}:messages`，保存最近 100 条消息，TTL 为 1800 秒。
MySQL 保存完整历史和版本号，每次请求先用该版本校验缓存；版本变化、缓存过期或 Redis
不可用时会从 MySQL 读取。成功保存新一轮问答或删除会话后会清除缓存。
会话详情仍从 MySQL 返回完整历史。Redis 不存持久数据，无需迁移或备份。
启动 Compose 后可验证 Redis 联通与 TTL：

```bash
docker compose exec redis redis-cli PING
docker compose exec api env RUN_REDIS_INTEGRATION=1 python -m pytest tests/test_redis_integration.py -q
```

### 6. 启动前后端

在项目根目录、同一个 Python 虚拟环境下，打开两个终端即可使用新的 Web 工作台。

终端一启动 MCP 监控服务：

```bash
python -m mcp_tools.server
```

终端二启动 FastAPI：

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

浏览器访问 `http://127.0.0.1:8000/ui/`；API 交互文档为 `http://127.0.0.1:8000/docs`。
进入工作台时输入上述管理员口令，浏览器只在当前标签页的 sessionStorage 中保存口令；
Streamlit 页面也会要求输入同一口令。
Web 工作台由 FastAPI 直接提供，无需安装 Node 或运行单独的前端服务。它支持流式聊天、
切换与删除历史会话、上传/删除 TXT 和 PDF 文档，以及查看最近一次回答的 Agent Trace。
文档上传限制为 10 MB，保存到 `data/` 顶层并立即增量更新索引；如果索引失败，文件可能
已经保存，修复原因后点击“同步索引”即可重试。Trace 只展示执行元数据，不显示问题、回答或工具结果正文。

若要使用原有 Streamlit 页面，可在第三个终端启动：

```bash
python -m streamlit run app.py
```

Streamlit 页面地址为 `http://localhost:8501`。它默认连接 `http://127.0.0.1:8000`，
可在 `.env` 或环境变量中设置 `AGENT_API_URL`。
HTTP 连接超时为 5 秒、读取超时为 120 秒。模型在首个聊天请求中加载，首次回答可能较慢。
Agent 默认连接 `http://127.0.0.1:8001/mcp`，可用 `MCP_SERVER_URL` 修改。MCP 服务
默认只绑定本机地址；Docker Compose 中由内部网络连接，不向主机公开端口。
在 Docker 内运行时，psutil 反映 MCP 容器可见的指标，不等于用户个人电脑的指标。

聊天历史以 MySQL 为准；最近上下文可由 Redis 加速。第一条消息省略 `session_id`，成功后返回新会话 ID；
后续请求传入该 ID 即可继续会话。Streamlit 侧边栏支持新建、选择历史会话和确认删除。
关闭浏览器或重启服务后，可以从列表恢复会话；新建会话不会删除旧记录。
当前为本地单管理员应用，没有多用户隔离。聊天、会话、知识库及 Trace API
均要求 `Authorization: Bearer <AGENT_ADMIN_TOKEN>`，未配置有效口令时拒绝访问；
`GET /api/health` 和静态登录页公开。仍应只在本机或可信内网访问，不要直接暴露到公网。

```http
POST /api/chat
Content-Type: application/json
Authorization: Bearer <AGENT_ADMIN_TOKEN>

{
  "message": "帮我查看当前 CPU 使用率"
}
```

成功返回 `{"answer": "...", "session_id": "返回的 UUID"}`。继续同一会话：

```json
{
  "message": "那内存呢？",
  "session_id": "上一次响应中的 UUID"
}
```

`message` 为非空字符串，最多 10,000 字符；`session_id` 必须为已有会话的 UUID。
相比第一阶段，**不再接受客户端 `history` 字段**（发送会返回 422），前后端需要一起更新。
后端按消息 ID 顺序取最近 100 条消息给 Agent，数据库保留完整问答；不会保存工具中间消息。

| 接口 | 行为 |
|------|------|
| `POST /api/chat` | 新会话或继续聊天，返回回答与会话 ID |
| `POST /api/chat/stream` | 同一请求体，返回 SSE：`delta`、`done` 或 `error` |
| `GET /api/sessions?limit=20&offset=0` | 按更新时间倒序列出会话；limit 为 1–100，默认 50 |
| `GET /api/sessions/{session_id}` | 返回标题、UTC 时间和有序的完整消息历史 |
| `DELETE /api/sessions/{session_id}` | 删除会话及消息，成功返回 204 |
| `GET /api/knowledge` | 列出知识文档及文件更新时间 |
| `POST /api/knowledge/upload` | 兼容的 multipart 文件上传入口 |
| `PUT /api/knowledge/{name}` | 原始文件体上传或覆盖并同步索引 |
| `DELETE /api/knowledge/{name}` | 删除文档并同步索引 |
| `POST /api/knowledge/sync` | 重试增量索引同步 |
| `GET /api/traces/{trace_id}` | 读取本次执行的安全元数据 |
| `GET /api/health` | 检查数据库表、知识目录和可选 Redis；不加载模型 |

参数错误返回 422，不存在的会话返回 404，并发更新冲突返回 409，
模型初始化或数据库不可用返回 503，Agent 执行失败返回 502。
流式接口在开始响应前仍可返回输入、会话或数据库错误；开始后通过 `error` 事件报告失败。
`delta` 携带 `{"text":"..."}`，数据库提交成功后 `done` 才携带完整回答与会话 ID。
中途失败不会保存半条问答，客户端应刷新历史后再重试。
API 文档可打开只表示 HTTP 服务启动成功，不代表模型和数据库已就绪。

模型执行期间不持有数据库事务。回答生成后在同一事务中保存问题与回答，失败会回滚；
通过版本号检查防止同一会话的并发回答交错写入。客户端超时不代表服务端任务已取消：
重新发送前应刷新会话列表/详情，检查上一条是否已保存。本阶段没有自动重试或幂等请求 ID。

本地管理员口令由环境变量校验，`users` 表记录本地管理员身份；它不提供多用户注册或权限分级。
知识文件与索引状态写入 `documents`，评测运行可通过 `--save-db` 把摘要写入
`evaluation_results`。数据库初始化和迁移是显式命令，API 启动不会自动改表。
升级旧数据库时，初始化命令会登记已有知识文件为 `pending`；随后运行
`POST /api/knowledge/sync` 才会核对索引并把状态更新为 `ready`。

运行测试（API/客户端测试不需要模型或 API Key）：

```bash
python -m pytest tests/test_chat_api.py tests/test_chat_stream_api.py tests/test_sessions_api.py tests/test_chat_client.py tests/test_streamlit_app.py tests/test_mcp_monitoring.py -q
python -m pytest -q
```

完整测试中的原有工具测试会加载本地 Embedding 模型，需要准备原项目运行环境。
会话测试使用临时 SQLite 文件验证事务和跨连接持久化，不连接本机 MySQL，也不替代真实 MySQL 联调。
真实 MySQL 验证可在配置并初始化专用数据库后，显式设置 `RUN_MYSQL_INTEGRATION=1`，
运行 `python -m pytest tests/test_mysql_integration.py -q`。它通过真实 MySQL 创建会话、
在新 Python 进程恢复历史、继续聊天并删除自己的测试会话；模型仍为模拟实现。
未启用该变量时此项测试跳过。它不会清空已有会话或删除表。
这些工具测试不调用远程 LLM，但模型工厂在导入时仍检查 API Key；没有真实 Key 时，
可仅在测试进程设置当前端点对应的占位值，例如 `openai_base_url` 指向 DeepSeek 时用
`DEEPSEEK_API_KEY=test-placeholder-not-a-real-key`。该占位值不能用于聊天。

### RAG 基线与评测

`config/chroma.yml` 中的 `retrieval_mode: advanced` 是聊天默认路径：原问题先由模型改写，
从现有 Chroma 库分别检索向量候选和 BM25 关键词候选，使用 Reciprocal Rank Fusion 合并
前 10 条，再由本地交叉编码器重排成前 3 条交给回答模型。设置环境变量
`RAG_RETRIEVAL_MODE=baseline` 可以切回原来的纯向量 Top‑3，便于同一知识库对比。
BM25 首次检索时读取已入库文档并建立进程内词法索引，之后复用；不需要再建持久索引。
修改、新增或删除 `data/` 顶层的 `.txt`、`.pdf` 后运行 `python -m rag.vector_store`：
系统按来源和 chunk 内容对账，只对新增或变化的 chunk 做 Embedding，移除过期 chunk，
并打印新增、保留、删除、失败数量。原样重跑不会重复嵌入。旧版整文件 MD5 导入的记录会在
首次同步时迁移，可能重新嵌入一次；`md5.text` 不再作为索引状态依据。
如果更新命令运行在 API 之外的进程，重启 API 以刷新其进程内 BM25 索引；在同一 RAG 服务进程
调用 `sync_knowledge()` 会自动使缓存失效。详见 [增量知识库更新说明](docs/knowledge-sync.md)。

重排模型默认 `BAAI/bge-reranker-base`，可用 `RAG_RERANKER_MODEL` 修改。它只从本地缓存加载；
若机器尚未缓存该模型，检索会使用融合排序继续回答，评测报告的 `reranked` 为 `false`。
Query Rewrite 失败也会回退原问题，并在 `rewrite_failed` 标记。需要完整重排时，请先按
[Sentence Transformers 的 CrossEncoder 文档](https://www.sbert.net/docs/package_reference/cross_encoder/model.html)
准备模型缓存。Docker 镜像目前也没有内置该权重。

在项目根目录运行检索评测，输出 JSON 中包含每题来源及汇总 Recall@3/@5：

```bash
python -m evaluation.runner --mode retrieval --rag-mode baseline --output reports/baseline.json
python -m evaluation.runner --mode retrieval --rag-mode advanced --output reports/advanced.json
python -m evaluation.compare reports/baseline.json reports/advanced.json
```

新报告会记录评测集内容和 Chroma 索引指纹；比较命令仅在两份报告的指纹一致时计算差值。
旧报告没有指纹，需要按上述命令重新生成后再比较。

默认检索评测不请求在线 LLM 改写，便于离线重复；要连同 Query Rewrite 一起测，加 `--rewrite`。
对真实 Agent 进行评测需模型 API、MySQL 和 MCP 服务已配置且可用；这会产生模型调用：

```bash
python -m evaluation.runner --mode agent --limit 5 --output reports/agent-sample.json
python -m evaluation.runner --mode all --output reports/full.json
```

加 `--save-db` 会把本次评测的汇总指标存入 MySQL 的 `evaluation_results`；
完整逐题输出仍写入 `--output` 指定的 JSON 文件。该选项要求先执行 `python -m backend.init_db`。

评测集为 `tests/eval_dataset.json`，共 50 条，分为工具、RAG、混合任务、健康报告和非运维问题。
RAG 样例用相对来源路径和目标段落短语标注，避免同名文件或仅命中文件中无关段落造成虚高。
可用 `--category rag` 单独运行一类。报告包含工具选择召回/精度、检索 Recall@3/@5、
首字与总延迟，以及输入/输出 token 数；如提供 `--input-usd-per-million` 和
`--output-usd-per-million`，才按你填写的价格估算费用。`task_success_proxy_rate` 检查
必要工具是否调用且回答非空；健康报告题还要求实际生成报告，缺少台账时的说明不算完成任务。
这仍不能代替人工判断建议是否正确。健康报告评测现走与聊天相同的 LangGraph 工作流，
报告模型的 token 会计入；RAG 工具内部的模型调用可能未计入，因此费用估算仍可能是下界。
2026-10-12 在相同数据集和 Chroma 索引上复测 20 道检索题：纯向量基线的段落
Recall@3 为 100%；仅启用 DeepSeek 改写时为 95%；改写与本地 BGE 重排全部启用时为
100%，20 题均完成改写和重排。完整路径与基线持平，题集已出现天花板效应，不能据此
宣称高级路径整体提升了准确率；后续应增加更难的反例和人工答案质量评分。
评测命令生成的逐题 JSON 可能包含用户输入、模型回答或本机信息，默认留在本地
`reports/`，不提交到公开仓库。

升级工作流之前的 50 题 DeepSeek 在线 Agent 评测汇总、指标边界和数据缺失案例见
[评测记录](reports/eval-deepseek-summary.md)。该次评测通过本地 MCP 服务执行监控工具；
规则代理成功率不等于答案正确率，逐题 JSON 同样只保存在本地。

### Agent 可观测性

每个 API 请求返回 `X-Trace-Id`；聊天 JSON 和流式 `done` / `error` 事件也包含该 ID。
后端将请求、模型、工具及 RAG 各阶段的结构化事件写入 `logs/traces.jsonl`，
可按 `trace_id` 还原一次请求的执行链路、耗时、token 与错误类型。
配置、查看命令、隐私边界及流式耗时解释见 [可观测性说明](docs/observability.md)。

### 7. Docker 部署（可选）

```bash
cd Agent项目
cp .env.example .env           # 已有 .env 时请勿覆盖；填入模型 Key、数据库密码和随机管理员口令
docker compose up -d --build
```

浏览器访问 `http://127.0.0.1:8000/ui/` 使用新 Web 工作台；
`http://localhost:8501` 仍提供 Streamlit 页面。

Compose 启动 `mysql`、`redis`、一次性的 `api-init`、`mcp`、`api` 和 `app`。MySQL 通过健康检查后初始化表，
初始化成功后才启动 API。数据库使用 `mysql_data` 命名卷保存；停止容器不会清空会话。
容器内 MYSQL_HOST 固定为 `mysql`，不连接本机的 MySQL80 服务，也不占用宿主机 3306 端口。
Redis 仅存有 TTL 的临时上下文，不挂载数据卷；Redis 中断时 API 仍从 MySQL 读取。
必须设置 `MYSQL_PASSWORD`、独立的 `MYSQL_ROOT_PASSWORD` 和随机的 `AGENT_ADMIN_TOKEN`；
应用账号 `MYSQL_USER` 不应设为 root。
MySQL 容器首次初始化后，修改 `.env` 中密码不会自动修改已有数据库账号密码。

Compose 中前端通过 `http://api:8000` 访问后端。API 健康检查验证 MySQL 表和知识目录，
报告 Redis 状态，但不加载模型或检验模型 Key；
后端通过内部地址 `http://mcp:8001/mcp` 调用监控工具。MCP 容器的指标只代表该容器可见的环境。
后端仍需已有的本地 Embedding 缓存。当前 Docker 镜像不包含模型，且模型加载为离线模式。
在 `.env` 中设置 `HF_CACHE_HOST_PATH` 为宿主机 HuggingFace 缓存目录（Windows 可用
`C:/Users/用户名/.cache/huggingface`）；Compose 将其只读挂载到后端
`/root/.cache/huggingface`。未设置时默认挂载项目下 `hf_cache`，需先把模型缓存放入该目录。
高级路径的重排模型也须在该缓存中，否则会自动回退融合排序。

## 工具说明

| 工具名称 | 功能 | 入参 | 可扩展方向 |
|---------|------|------|-----------|
| `search_knowledge_base` | 从IT运维知识库检索专业技术资料 | query: str | 接入 Confluence/Jira Wiki API |
| `get_cpu_usage`（MCP） | 读取 MCP 服务所在环境的 CPU 使用率 | 无 | 接入 Prometheus/Zabbix API |
| `get_memory_usage`（MCP） | 读取内存用量 | 无 | 接入监控平台 |
| `get_disk_usage`（MCP） | 读取工作磁盘用量 | 无 | 接入监控平台 |
| `get_process_list`（MCP） | 返回内存占用最高的进程，最多 20 条 | limit: int | 接入监控平台 |
| `get_employee_department` | 获取当前员工所属部门 | 无 | 接入 LDAP/AD |
| `get_employee_id` | 随机获取演示员工号（尚无登录身份） | 无 | 接入 SSO 系统 |
| `get_current_month` | 获取当前月份 | 无 | — |
| `query_asset_record` | 查询员工设备资产与维保记录 | employee_id, month | 接入 CMDB/资产管理系统 |
| `prepare_report_context` | 旧版 ReAct 报告提示词切换兼容工具 | 无 | 新报告请求改走 LangGraph 工作流 |

## 中间件说明

| 中间件 | 类型 | 功能 |
|--------|------|------|
| `monitor_tool` | `@wrap_tool_call` | 记录工具名称、结果类型与耗时，并兼容旧版报告状态切换；不记录参数和结果正文 |
| `log_before_model` | `@before_model` | 在 LLM 调用前记录消息摘要，便于排查推理异常 |
| `report_prompt_switch` | `@dynamic_prompt` | 检测报告生成场景，动态切换为报告专用提示词 |

## 提示词策略

项目采用双提示词架构：

- **主提示词**：处理日常IT运维咨询——故障排查、系统配置、网络诊断、安全事件处置、设备选型建议等
- **报告提示词**：设备资产健康报告进入独立工作流；查询到台账后才调用模型，生成标题为「IT设备资产健康度报告与运维建议」的 Markdown 报告

工作流节点、数据边界和缺失记录行为见 [健康报告说明](docs/health-report-workflow.md)。

## 有待扩展的接口

部分工具返回模拟数据（Mock），以下接口预留了真实 API 接入点：

| 工具 | 当前实现 | 可替换为 |
|------|---------|---------|
| 四个 MCP 监控工具 | MCP 服务通过 psutil 读取所在环境指标 | Prometheus API / Zabbix API / 云厂商监控 API |
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
