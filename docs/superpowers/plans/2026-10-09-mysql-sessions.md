# MySQL 会话持久化实施计划

目标：完成用户选定的第二阶段。后端管理会话及历史，重启后仍能继续对话。

架构：使用同步 SQLAlchemy 2 + PyMySQL，保留 FastAPI 同步路由和原有 Agent。数据库连接延迟创建；通过显式 `python -m backend.init_db` 初始化空库中的表，不在启动时修改结构。MySQL 为实际存储，SQLite 仅用于隔离的自动化测试，不作为隐式回退。

数据：sessions 包含 UUID、标题、UTC 创建/更新时间和版本号；messages 包含自增 ID、session_id 外键、角色、内容、UTC 时间。删除会话级联删除消息。

接口：POST /api/chat 接受 message、可选 session_id，返回 answer、session_id。省略 ID 时成功后创建会话；传入 ID 时读取该会话最后 100 条消息作为上下文。history 字段不再接受，避免客户端覆盖后端历史。GET /api/sessions 支持 limit/offset；GET /api/sessions/{id} 返回会话及有序消息；DELETE /api/sessions/{id} 返回 204。

事务：模型执行期间不持有数据库事务。成功后使用版本比较更新，原子保存问答；并发更新返回 409，已删除/不存在返回 404，数据库故障返回 503。模型失败不新增空会话或半轮消息。暂不实现鉴权；定位为本机单用户应用。

前端：从后端读取会话列表和详情；新建只清空当前选择，不删除历史；删除需明确点击；发送成功保存 session_id。页面不再上传 history。保留现有快捷提问。

实施清单：
- [x] 编写后端持久化、失败回滚、404、409、输入校验测试，确认新增行为失败。
- [x] 实现 backend/database.py、models、session schema/service/router、初始化命令及聊天接入。
- [x] 更新 frontend/chat_client.py、app.py，覆盖历史切换、新建、删除、错误提示。
- [x] 更新 MySQL 依赖、环境示例、Compose 和 README。
- [x] 运行回归和独立审查，记录未验证的边界。
- [ ] 连接信息就绪后初始化专用库并验证真实 MySQL。

验证：使用隔离的临时 SQLite 文件验证跨连接持久化和事务；注入模拟 Agent，不调用远程模型。真实 MySQL 检查只在用户提供明确连接配置后进行。可选集成测试向本项目专用数据库写入自身新建的会话，随后只删除该会话，不清表或更改其他会话。

## 2026-10-09 验证结果

- 完整测试：70 passed、1 skipped、3 个依赖弃用警告；测试使用临时 SQLite 文件和占位模型 Key，无远程模型调用。
- 唯一跳过项为 tests/test_mysql_integration.py，需显式 RUN_MYSQL_INTEGRATION=1 和真实 MYSQL_* 配置。
- MySQL DDL 编译与 Compose 结构检查通过，表使用 InnoDB、utf8mb4、DATETIME(6)，消息删除有外键级联。
- 独立审查发现快捷问题在详情读取失败后可能被带到其他会话；已添加回归测试并修复。
- git diff --check 通过。保留用户原有 model/factory.py 修改。
- 当前缺少项目 .env 和用户级 MYSQL_DATABASE、MYSQL_USER、MYSQL_PASSWORD；没有操作本机 MySQL 数据或启动 Docker 容器。
- 本阶段 API 有约定变更：history 不再接受，调用方必须同步更新为 session_id。当前无用户鉴权，定位为本地单用户使用。
