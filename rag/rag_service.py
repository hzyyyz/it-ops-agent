"""
总结服务类：用户提问，搜索参考资料，将提问和参考资料提交给模型，让模型总结回复
"""

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

from rag.vector_store import  VectorStoreService
from rag.retrieval import RetrievalPipeline
from rag.reranker import LocalCrossEncoder
from utils.prompt_loader import load_rag_prompts
from utils.config_handler import chroma_conf
from langchain_core.prompts import PromptTemplate
from model.factory import chat_model
from observability.tracing import record, span
import os


class RagSummarizeService(object):
    def __init__(self, *, mode: str | None = None, rewriter=None, reranker=None):
        self.vector_store = VectorStoreService()
        self.retriever = self.vector_store.get_retriever()
        self.prompt_text = load_rag_prompts()
        self.prompt_template = PromptTemplate.from_template(self.prompt_text)
        self.model = chat_model
        selected_mode = mode or os.getenv("RAG_RETRIEVAL_MODE", chroma_conf.get("retrieval_mode", "advanced"))
        self.pipeline = RetrievalPipeline(
            self.vector_store.vector_store, mode=selected_mode,
            rewriter=rewriter or self._rewrite_query,
            reranker=reranker or LocalCrossEncoder(),
            candidate_k=chroma_conf.get("candidate_k", 10), final_k=chroma_conf["k"],
        )
        self.chain = self._init_chain()


    def _init_chain(self):
        chain = self.prompt_template | self.model
        return chain

    def retriever_docs(self,query: str) -> list[Document]:
        return self.pipeline.retrieve(query)

    def sync_knowledge(self) -> dict[str, int]:
        """Refresh local documents and this process's cached BM25 corpus."""
        return self.vector_store.load_document(invalidate=self.pipeline.invalidate_lexical_index)

    def _rewrite_query(self, query: str) -> str:
        response = self.model.invoke([
            ("system", "将用户问题改写为适合 IT 运维知识库检索的一句具体查询。保留产品名、错误码和技术术语；只输出查询，不回答问题。"),
            ("human", query),
        ])
        content = response.content
        usage = getattr(response, "usage_metadata", None) or {}
        record("rag.rewrite.usage", input_tokens=usage.get("input_tokens", 0),
               output_tokens=usage.get("output_tokens", 0))
        return content[:300] if isinstance(content, str) else query

    def rag_summarize(self,query: str) -> str:

        context_docs = self.retriever_docs(query)

        context = ""
        counter = 0
        for doc in context_docs:
            counter += 1
            context += f"【参考资料{counter}】:参考资料:{doc.page_content} | 参考元数据:{doc.metadata}\n"

        with span("rag.answer", doc_count=len(context_docs)):
            response = self.chain.invoke({"input": query, "context": context})
            usage = getattr(response, "usage_metadata", None) or {}
            record("rag.answer.usage", input_tokens=usage.get("input_tokens", 0),
                   output_tokens=usage.get("output_tokens", 0))
            return StrOutputParser().invoke(response)

if __name__ == '__main__':
    rag = RagSummarizeService()

    print(rag.rag_summarize("办公电脑运行卡顿怎么排查"))
