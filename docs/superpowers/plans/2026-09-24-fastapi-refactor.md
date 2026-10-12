# FastAPI 第一步重构

**目标：** 实现计划末尾指定的单一接口 `POST /api/chat`，让 Streamlit 通过 HTTP 调用 Agent。

**设计：** 保留根目录 `app.py` 作为前端，新增 `backend/`，避免同名 Python 包冲突。Router 负责 HTTP，Pydantic schema 校验输入，AgentService 聚合现有 `execute_stream` 输出。每次请求独立构建 Agent，延迟导入模型；前端传递历史，不引入服务器会话状态。沿用现有工具、RAG 和报告中间件。

**接口：** 输入 `message` 和可选 `history`（仅 user/assistant）；输出 `answer`。无效输入 422，初始化失败 503，执行失败 502，不向客户端暴露内部异常。同步路由由 FastAPI 在线程池执行。

**范围：** 不实现 SSE、会话持久化、上传、MCP 或 RAG 算法变更。保留用户已有的 model/factory.py 修改。

## 执行清单

- [x] 新建 tests/test_chat_api.py：测试正常回答、历史透传、请求隔离、非法输入、初始化和执行失败；先运行确认缺少实现。
- [x] 新建 backend/main.py、api/chat.py、schemas/chat.py、services/agent_service.py：实现上述接口及依赖注入。
- [x] 新建客户端及测试：覆盖 HTTP 请求、超时、后端错误；修改 app.py 为 HTTP 调用，成功才保存一轮历史。
- [x] 更新 requirements.txt、.env.example、README.md 和现有 Docker 配置，使前后端可分别启动。
- [x] 运行 API/客户端测试、Streamlit AppTest 和原有测试，检查 git diff，记录实际验证边界。

验证命令：`python -m pytest tests/test_chat_api.py tests/test_chat_client.py -q`，`python -m pytest -q`，`git diff --check`。

## 验证结果（2026-09-26）

完整测试：53 passed，3 个依赖弃用警告；测试进程使用占位 API Key，未调用远程 LLM。git diff --check 通过。独立审查发现的非法 URL 错误提示问题已修复并加入回归测试。

验证边界：真实模型对话仍需有效 API Key 联调；Docker 配置已检查，本机无 Docker 命令，未构建运行容器。
