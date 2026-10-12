# MySQL + Redis 实施计划

1. 在 `tests/test_session_cache.py` 写失败测试：缓存命中避免再次读取消息、版本不符回源、Redis 故障回源、提交和删除后失效。
2. 新建 `backend/cache.py`：懒加载 Redis 客户端，封装 JSON 序列化和 1800 秒 TTL；所有缓存故障只记录异常类型并回源。
3. 修改 `backend/services/session_service.py`：仅缓存最近 100 条上下文，MySQL 版本校验成功后才使用；提交和删除后失效。
4. 增加 API 测试：普通和 SSE 继续会话均使用同一缓存策略，失败时不影响 MySQL 数据。
5. 更新 `requirements.txt`、`docker-compose.yml`、`.env.example` 与 `README.md`，加入 Redis 服务、健康检查、配置与使用说明。
6. 运行针对性测试、全量测试、编译与配置校验；环境允许时运行真实 Redis 联调。
