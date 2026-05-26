import logging
from typing import AsyncIterator

import litellm
from canary_framework import service, on_init, Context, config

logger = logging.getLogger(__name__)


@config
class LLMConfig:
    litellm_api_base: str = ""
    litellm_port: int = 0
    litellm_api_key: str = ""
    embedding_model: str = "qwen-embedding"

    @property
    def litellm_url(self) -> str:
        return f"{self.litellm_api_base}:{self.litellm_port}"


@service(name="LLMClient", config=LLMConfig)
class LLMClient:
    @on_init
    def init(self, ctx: Context):
        cfg = ctx.get_config(LLMConfig)
        self._api_base = cfg.litellm_url
        self._api_key = cfg.litellm_api_key
        self._embedding_model = cfg.embedding_model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await litellm.aembedding(
            model=self._embedding_model,
            input=texts,
            api_base=self._api_base,
            api_key=self._api_key,
        )
        return [d["embedding"] for d in response.data]

    async def chat(
            self,
            messages: list[dict],
            model: str = "qwen-plus",
            stream: bool = False,
            **kwargs,
    ):
        return await litellm.acompletion(
            model=model,
            messages=messages,
            stream=stream,
            api_base=self._api_base,
            api_key=self._api_key,
            **kwargs,
        )

    async def chat_stream(
            self,
            messages: list[dict],
            model: str = "qwen-plus",
            **kwargs,
    ) -> AsyncIterator[dict]:
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            stream=True,
            api_base=self._api_base,
            api_key=self._api_key,
            **kwargs,
        )
        async for chunk in response:
            yield chunk
