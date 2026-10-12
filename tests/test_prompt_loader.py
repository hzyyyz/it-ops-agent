import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from utils.prompt_loader import load_system_prompt, load_rag_prompts, load_report_prompts


class TestPromptLoader:
    def test_load_system_prompt_returns_non_empty_string(self):
        prompt = load_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "ReAct" in prompt

    def test_load_system_prompt_contains_tool_references(self):
        prompt = load_system_prompt()
        assert "search_knowledge_base" in prompt
        assert "get_cpu_usage" in prompt
        assert "get_memory_usage" in prompt
        assert "get_disk_usage" in prompt
        assert "get_process_list" in prompt
        assert "prepare_report_context" in prompt

    def test_load_rag_prompts_returns_non_empty_string(self):
        prompt = load_rag_prompts()
        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "{input}" in prompt
        assert "{context}" in prompt

    def test_load_report_prompts_returns_non_empty_string(self):
        prompt = load_report_prompts()
        assert isinstance(prompt, str)
        assert len(prompt) > 0
