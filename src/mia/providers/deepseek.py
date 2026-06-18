"""
DeepSeek Provider — 备选 LLM Provider

当 MiMo API 不可用时作为 fallback。
走标准 OpenAI 兼容协议。
"""

from typing import AsyncIterator, Optional

from loguru import logger
from openai import AsyncOpenAI

from mia.providers.base import BaseProvider


class DeepSeekProvider(BaseProvider):
    """DeepSeek API 封装 — OpenAI 兼容协议

    用于 Scheduler 和 TaskAgent 的备选 Provider。
    """

    BASE_URL = "https://api.deepseek.com/v1"
    CHAT_MODEL = "deepseek-chat"

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
    ):
        """
        Args:
            api_key: DeepSeek API Key (sk-xxxxx)
            base_url: 自定义 base URL
        """
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or self.BASE_URL,
        )
        logger.info("DeepSeekProvider 初始化完成, base_url={}", base_url or self.BASE_URL)

    async def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        stream: bool = True,
        tools: Optional[list[dict]] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ):
        """流式/非流式对话 — OpenAI 兼容"""
        kwargs = {
            "model": model or self.CHAT_MODEL,
            "messages": messages,
            "stream": stream,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        logger.debug(
            "DeepSeek chat: model={}, stream={}, msg_count={}",
            kwargs["model"], stream, len(messages),
        )
        return await self.client.chat.completions.create(**kwargs)

    async def chat_sync(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """非流式对话 — 返回完整文本"""
        response = await self.chat(
            messages=messages,
            model=model,
            stream=False,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
