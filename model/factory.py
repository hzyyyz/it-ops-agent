import os
from abc import ABC, abstractmethod
from typing import Optional
from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI
from langchain_huggingface import HuggingFaceEmbeddings
from utils.config_handler import rag_conf
from utils.path_tool import get_abs_path

# 加载 .env 文件
env_path = os.path.join(get_abs_path(""), ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)

os.environ["HF_HUB_OFFLINE"] = "1"

def _resolve_local_model_path(model_name: str) -> str:
    """将HuggingFace模型名解析为本地缓存snapshot路径，避免任何网络请求。"""
    cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
    dir_name = "models--" + model_name.replace("/", "--")
    snapshots_dir = os.path.join(cache_dir, dir_name, "snapshots")
    if os.path.isdir(snapshots_dir):
        for snapshot in os.listdir(snapshots_dir):
            snapshot_path = os.path.join(snapshots_dir, snapshot)
            if os.path.isdir(snapshot_path):
                return snapshot_path
    return model_name


def _resolve_api_key(base_url: str) -> Optional[str]:
    """按端点选择密钥：DeepSeek 不接受 OpenAI 密钥，反之亦然。

    base_url 指向谁就优先用谁的密钥；对应的密钥缺失时才退回另一个，
    以兼容用 OpenAI 协议、但自建密钥的自定义服务。
    """
    preferred = ("DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    if "deepseek" not in base_url.lower():
        preferred = preferred[::-1]
    return os.getenv(preferred[0]) or os.getenv(preferred[1]) or rag_conf.get("openai_api_key")


class BaseModelFactory(ABC):
    @abstractmethod
    def generator(self) -> Optional[ Embeddings | ChatOpenAI ]:
        pass


class ChatModelFactory(BaseModelFactory):
    def generator(self) -> Optional[Embeddings | ChatOpenAI]:
        base_url = os.getenv("OPENAI_BASE_URL", rag_conf.get("openai_base_url", ""))
        kwargs = {
            "model": os.getenv("CHAT_MODEL_NAME", rag_conf.get("chat_model_name", "")),
            "openai_api_base": base_url,
        }
        api_key = _resolve_api_key(base_url)
        if api_key:
            kwargs["openai_api_key"] = api_key
        return ChatOpenAI(**kwargs)

class EmbeddingsFactory(BaseModelFactory):
    def generator(self) -> Optional[Embeddings | ChatOpenAI]:
        model_name = os.getenv("EMBEDDING_MODEL_NAME", rag_conf.get("embedding_model_name", ""))
        local_path = _resolve_local_model_path(model_name)
        return HuggingFaceEmbeddings(model_name=local_path)


chat_model = ChatModelFactory().generator()
embed_model = EmbeddingsFactory().generator()
