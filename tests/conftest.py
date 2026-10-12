import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def allow_existing_api_tests_to_focus_on_their_own_behavior():
    """Auth has dedicated tests; older endpoint tests use a known admin identity."""
    from backend.auth import require_admin
    from backend.api.knowledge import get_document_catalog
    from backend.main import app

    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[get_document_catalog] = lambda: type("NoopCatalog", (), {
        "reconcile": lambda self, documents, indexed: None,
    })()
    yield
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_document_catalog, None)


@pytest.fixture
def sample_asset_record():
    return {
        "设备配置": "ThinkPad X1 Carbon | i7-1365U | 16GB | 512GB SSD | Win11",
        "运行状态": "CPU:23% 内存:45% 磁盘:62% | 蓝屏:0次 | 网络延迟:2ms",
        "维保记录": "无故障 | 系统补丁:已更新",
        "安全评分": "95分 | 防火墙:正常 | 杀毒:已更新",
    }
