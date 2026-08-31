import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from agent.tools.agent_tools import (
    check_device_status,
    get_employee_department,
    get_employee_id,
    get_current_month,
    prepare_report_context,
)


def _call_tool(tool, **kwargs):
    """通过 invoke 调用 @tool 装饰后的 StructuredTool 对象"""
    return tool.invoke(kwargs)


class TestDeviceStatusTool:
    def test_returns_string_with_asset_id(self):
        result = _call_tool(check_device_status, asset_id="ASSET-001")
        assert isinstance(result, str)
        assert "ASSET-001" in result

    def test_result_contains_metrics(self):
        result = _call_tool(check_device_status, asset_id="ASSET-001")
        assert "CPU" in result
        assert "内存" in result
        assert "磁盘" in result


class TestEmployeeTools:
    def test_get_employee_department_returns_string(self):
        result = _call_tool(get_employee_department)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_employee_id_returns_emp_format(self):
        result = _call_tool(get_employee_id)
        assert isinstance(result, str)
        assert result.startswith("EMP")
        assert len(result) == 7

    def test_get_current_month_returns_yyyy_mm_format(self):
        result = _call_tool(get_current_month)
        assert isinstance(result, str)
        parts = result.split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 4
        assert len(parts[1]) == 2

    def test_get_employee_id_returns_one_of_valid_ids(self):
        valid_ids = {f"EMP{i:04d}" for i in range(1001, 1011)}
        for _ in range(20):
            assert _call_tool(get_employee_id) in valid_ids


class TestPrepareReportContext:
    def test_returns_confirmation_string(self):
        result = _call_tool(prepare_report_context)
        assert isinstance(result, str)
        assert "prepare_report_context" in result


class TestQueryAssetRecord:
    def test_requires_employee_id_and_month(self):
        from agent.tools.agent_tools import query_asset_record, load_asset_records, external_data
        load_asset_records()
        assert len(external_data) > 0

        result = _call_tool(query_asset_record, employee_id="EMP1001", month="2025-06")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_nonexistent_record_returns_empty(self):
        from agent.tools.agent_tools import query_asset_record, load_asset_records, external_data
        load_asset_records()
        external_data.clear()

        result = _call_tool(query_asset_record, employee_id="EMP9999", month="2025-06")
        assert result == ""
