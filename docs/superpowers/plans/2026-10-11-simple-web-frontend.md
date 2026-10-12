# 简单 Web 前端实施计划

1. 为知识库管理编写 API 测试：列出文件、上传与覆盖、非法名称/类型/过大拒绝、删除和同步失败。实现独立 `KnowledgeService` 和 `backend/api/knowledge.py`，复用现有增量同步。
2. 为 Trace 编写 API 测试：按 ID 返回元数据、非法 ID 拒绝、不暴露正文。实现 `backend/api/traces.py`。
3. 为 `/ui` 静态页面编写入口测试，提供 `web/index.html`、`web/styles.css`、`web/app.js`。页面实现会话、聊天 SSE、知识库和 Trace 四个区域；所有动态文本使用文本节点，不注入 HTML。
4. 接入 `backend/main.py`，更新 README 的启动方式、单用户访问边界和 Docker 页面地址。
5. 跑针对性测试、完整 Python 测试、JavaScript 语法检查以及浏览器交互验证。
