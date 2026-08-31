import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import tempfile
from utils.file_handler import get_file_hex, listdir_with_allowed_type


class TestFileHandler:
    def test_get_file_hex_returns_32_char_hex(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content")
            path = f.name

        try:
            result = get_file_hex(path)
            assert isinstance(result, str)
            assert len(result) == 32
            for char in result:
                assert char in "0123456789abcdef"
        finally:
            os.unlink(path)

    def test_get_file_hex_same_content_same_hash(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            path_a = f.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            path_b = f.name

        try:
            assert get_file_hex(path_a) == get_file_hex(path_b)
        finally:
            os.unlink(path_a)
            os.unlink(path_b)

    def test_get_file_hex_different_content_different_hash(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("content A")
            path_a = f.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("content B")
            path_b = f.name

        try:
            assert get_file_hex(path_a) != get_file_hex(path_b)
        finally:
            os.unlink(path_a)
            os.unlink(path_b)

    def test_get_file_hex_nonexistent_returns_none(self):
        result = get_file_hex("/nonexistent/path/file.txt")
        assert result is None

    def test_listdir_with_allowed_type_returns_tuple(self):
        data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data"
        )
        result = listdir_with_allowed_type(data_dir, ("txt",))
        assert isinstance(result, tuple)
        for path in result:
            assert path.endswith(".txt")
