import logging
from typing import AsyncIterator

import litellm
from canary_framework import service, after_config

logger = logging.getLogger(__name__)


@service(name="LLMClient")
class LLMClient:
    @after_config
    def setup(self):
        self._api_base = self.config.litellm_url
        self._api_key = self.config.litellm_api_key
        self._embedding_model = self.config.embedding_model

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
