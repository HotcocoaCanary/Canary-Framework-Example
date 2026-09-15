"""The model layer — embeddings and chat completion, one class per implementation.

选哪个实现，最终版把决定权交还给了**单元自己**：`provide=` 被删除后，运行时没有任何
入口能把另一个对象放到某个单元的位置上（框架的理由是"图上的实例全部由框架无参构造"，
一条来源比两条清楚）。于是这里回到 0.9.2 的形状——单元读配置、自己挑后端：

``EmbeddingModel`` / ``ChatModel``
    图上的单元。默认用离线确定性实现（哈希 n-gram 向量 + 抽取式回答），
    整套系统因此零外部依赖就能启动；``AppConfig`` 说要 ``openai`` 时，
    它们在 ``@on_start`` 里换上远端后端并把调用转过去。
``RemoteEmbeddingBackend`` / ``RemoteChatBackend``
    OpenAI 兼容端点（litellm、DashScope 兼容模式、vLLM …）。它们**不在图上**，
    由上面的单元构造并持有，生命周期也由上面的单元转发——图外的对象没有钩子。

代价记在 doc/verification-final.md：这个 `if provider == ...` 分支是 0.9.3 的
`overrides=` 曾经删掉过的东西，最终版把它请了回来。
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import httpx

from canary_framework import cocoa, on_start, on_stop
from config import AppConfig

_TOKEN = re.compile(r"[a-zA-Z0-9_]+|[一-鿿]")

NO_ANSWER = "馆藏资料中没有检索到与该问题相关的内容，无法回答。"


def tokenize(text: str) -> list[str]:
    """Split *text* into ASCII words and individual CJK characters."""
    return [t.lower() for t in _TOKEN.findall(text or "")]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; ``0.0`` when either vector is empty or degenerate."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@cocoa(deps=[AppConfig])
class EmbeddingModel:
    """Turns text into vectors — a hashed bag-of-n-grams, L2-normalised.

    Deterministic and lexical: passages sharing terms with the query land close
    together, which is all the retrieval tests need — and it never touches the
    network.
    """

    app_config: AppConfig

    _remote: RemoteEmbeddingBackend | None = None

    @on_start
    async def choose_backend(self) -> None:
        if self.app_config.embedding_provider == "openai":
            self._remote = RemoteEmbeddingBackend(self.app_config)
            await self._remote.open()

    @on_stop
    async def close_backend(self) -> None:
        if self._remote is not None:
            await self._remote.aclose()
            self._remote = None

    @property
    def dim(self) -> int:
        return self.app_config.embedding_dim

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if self._remote is not None:
            return await self._remote.embed_many(texts)
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        dim = self.dim
        vec = [0.0] * dim
        tokens = tokenize(text)
        grams = tokens + ["".join(pair) for pair in zip(tokens, tokens[1:], strict=False)]
        for gram in grams:
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec


@cocoa(deps=[AppConfig])
class ChatModel:
    """Generates an answer from a system prompt and a conversation.

    Extractive rather than generative: it quotes the retrieved passage closest
    to the question.  Not a language model — but deterministic, so the RAG
    pipeline can be asserted end-to-end with no network call, and the *shape* of
    the answer (grounded in retrieved context, or an explicit "not found")
    matches what the remote model is instructed to produce.
    """

    app_config: AppConfig

    _remote: RemoteChatBackend | None = None

    @on_start
    async def choose_backend(self) -> None:
        if self.app_config.chat_provider == "openai":
            self._remote = RemoteChatBackend(self.app_config)
            await self._remote.open()

    @on_stop
    async def close_backend(self) -> None:
        if self._remote is not None:
            await self._remote.aclose()
            self._remote = None

    async def complete(
        self,
        *,
        instruction: str,
        context: list[str],
        history: list[dict[str, str]],
        question: str,
    ) -> str:
        if self._remote is not None:
            return await self._remote.complete(
                instruction=instruction, context=context, history=history, question=question
            )
        passages = [p.strip() for p in context if p.strip()]
        if not passages:
            return NO_ANSWER
        query_terms = set(tokenize(question))
        best = max(passages, key=lambda p: len(query_terms & set(tokenize(p))))
        if not query_terms & set(tokenize(best)):
            return NO_ANSWER
        return f"根据馆藏资料：{best[:400]}"


class _RemoteBackend:
    """Shared plumbing for the OpenAI-compatible implementations.

    不是 ``@cocoa``，也不在图上：它由持有它的单元构造，因此**没有**生命周期钩子——
    ``@on_start`` / ``@on_stop`` 只对图上的节点有效。开关连接由持有者转发。
    """

    _client: httpx.AsyncClient | None = None

    def __init__(self, app_config: AppConfig) -> None:
        self.app_config = app_config

    async def open(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.app_config.llm_api_base.rstrip("/"),
            headers={"Authorization": f"Bearer {self.app_config.llm_api_key}"},
            timeout=self.app_config.llm_timeout_seconds,
        )

    async def aclose(self) -> None:
        # 容忍「open() 只跑了一半」的自己：启动失败时这个方法照样会被调用。
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        assert self._client is not None, f"{type(self).__name__} 尚未 start()"
        return self._client


class RemoteEmbeddingBackend(_RemoteBackend):
    """``EmbeddingModel`` 的远端后端：OpenAI 兼容的 ``/v1/embeddings``。"""

    @property
    def dim(self) -> int:
        return self.app_config.embedding_dim

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = await self.client.post(
            "/v1/embeddings",
            json={"model": self.app_config.embedding_model_name, "input": texts},
        )
        resp.raise_for_status()
        payload = resp.json()
        ordered = sorted(payload["data"], key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in ordered]


class RemoteChatBackend(_RemoteBackend):
    """``ChatModel`` 的远端后端：OpenAI 兼容的 ``/v1/chat/completions``。"""

    async def complete(
        self,
        *,
        instruction: str,
        context: list[str],
        history: list[dict[str, str]],
        question: str,
    ) -> str:
        messages: list[dict[str, str]] = [{"role": "system", "content": instruction}]
        if context:
            joined = "\n\n".join(f"[资料 {i + 1}]\n{passage}" for i, passage in enumerate(context))
            messages.append({"role": "system", "content": f"可用馆藏资料：\n{joined}"})
        messages.extend(history)
        messages.append({"role": "user", "content": question})

        resp = await self.client.post(
            "/v1/chat/completions",
            json={
                "model": self.app_config.chat_model_name,
                "messages": messages,
                "temperature": 0.2,
            },
        )
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
        return payload["choices"][0]["message"]["content"]
