import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class TestReportPromptSwitch:
    @classmethod
    def setup_class(cls):
        from utils.prompt_loader import load_system_prompt, load_report_prompts
        cls.normal_prompt = load_system_prompt()
        cls.report_prompt = load_report_prompts()

    def test_normal_prompt_contains_react(self):
        assert "ReAct" in self.normal_prompt

    def test_report_prompt_is_non_empty(self):
        assert isinstance(self.report_prompt, str)
        assert len(self.report_prompt) > 0

    def test_two_prompts_have_different_content(self):
        assert self.normal_prompt != self.report_prompt

    def test_normal_prompt_contains_search_knowledge_base(self):
        assert "search_knowledge_base" in self.normal_prompt

    def test_report_prompt_contains_report_context(self):
        assert "资产" in self.report_prompt or "报告" in self.report_prompt
