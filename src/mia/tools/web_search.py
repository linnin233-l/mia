"""
Web Search 工具 — DuckDuckGo 搜索

返回前 5 条搜索结果 (标题 + 摘要 + URL)。
"""

import asyncio
from typing import Optional

from loguru import logger

from mia.tools.base import Tool, ToolResult


class WebSearchTool(Tool):
    """网页搜索工具 — DuckDuckGo"""

    name = "web_search"
    description = (
        "搜索互联网信息，返回相关结果的标题、摘要和URL。"
        "适用于: 查找最新信息、事实查询、资料收集。"
        "注意: 返回摘要而非完整网页内容。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词",
            },
            "max_results": {
                "type": "integer",
                "description": "最大返回结果数 (默认5, 最多10)",
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        query: str,
        max_results: int = 5,
    ) -> ToolResult:
        """
        执行网页搜索

        Args:
            query: 搜索关键词
            max_results: 最大返回结果数

        Returns:
            ToolResult
        """
        max_results = min(max_results, 10)

        logger.info("[WebSearchTool] 搜索: {}", query)

        try:
            # DuckDuckGo 搜索 (在线程池中运行，因为它是同步API)
            # 优先尝试新版包名 ddgs，降级到旧版 duckduckgo_search
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS  # type: ignore[no-retyped]

            results = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: list(DDGS().text(query, max_results=max_results)),
            )

            if not results:
                return ToolResult(
                    success=True,
                    data="未找到相关搜索结果。",
                )

            # 格式化结果
            formatted = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "无标题")
                href = r.get("href", "")
                body = r.get("body", "")
                # 截断过长摘要
                body = body[:200] + "..." if len(body) > 200 else body
                formatted.append(f"{i}. {title}\n   URL: {href}\n   摘要: {body}")

            output = "\n\n".join(formatted)
            return ToolResult(success=True, data=output)

        except ImportError:
            return ToolResult(
                success=False,
                error="duckduckgo-search 库未安装。请运行: pip install duckduckgo-search",
            )
        except Exception as e:
            logger.error("[WebSearchTool] 搜索失败: {}", e)
            return ToolResult(success=False, error=f"搜索失败: {e}")
