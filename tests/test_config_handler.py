import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from utils.config_handler import load_rag_config, load_chroma_config, load_prompts_config, load_agent_config


class TestConfigHandler:
    def test_load_rag_config_returns_dict(self):
        cfg = load_rag_config()
        assert isinstance(cfg, dict)
        assert "chat_model_name" in cfg
        assert "openai_base_url" in cfg

    def test_load_chroma_config_returns_dict(self):
        cfg = load_chroma_config()
        assert isinstance(cfg, dict)
        assert "collection_name" in cfg
        assert "chunk_size" in cfg
        assert isinstance(cfg["chunk_size"], int)
        assert cfg["chunk_size"] > 0

    def test_load_prompts_config_returns_dict(self):
        cfg = load_prompts_config()
        assert isinstance(cfg, dict)
        assert "main_prompt_path" in cfg
        assert "rag_summarize_prompt_path" in cfg
        assert "report_prompt_path" in cfg

    def test_load_agent_config_returns_dict(self):
        cfg = load_agent_config()
        assert isinstance(cfg, dict)
        assert "external_data_path" in cfg

    def test_chroma_config_separators_are_list(self):
        cfg = load_chroma_config()
        assert isinstance(cfg["separators"], list)
        assert len(cfg["separators"]) > 0

    def test_chroma_config_k_is_positive(self):
        cfg = load_chroma_config()
        assert cfg["k"] > 0
