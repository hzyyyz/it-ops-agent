import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture
def sample_asset_record():
    return {
        "设备配置": "ThinkPad X1 Carbon | i7-1365U | 16GB | 512GB SSD | Win11",
        "运行状态": "CPU:23% 内存:45% 磁盘:62% | 蓝屏:0次 | 网络延迟:2ms",
        "维保记录": "无故障 | 系统补丁:已更新",
        "安全评分": "95分 | 防火墙:正常 | 杀毒:已更新",
    }
