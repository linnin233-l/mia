"""
MemoryRetriever — 知识检索器

设计参考:
  - linninpaw file_memory_manager.py: 4 阶段关键词搜索
  - ReMe: 向量 + BM25 混合检索

检索流程 (两阶段):
  Phase 1: scan_index() → 扫 index.json 的日摘要定位相关日期
  Phase 2: load_day() → 只加载相关日期的 daily 文件 → 关键词匹配 + LLM 重排序
  Phase 3: summarize_for_context() → 生成精炼上下文摘要注入 Scheduler

降级策略:
  - 索引无匹配 → 加载最近 3 天
  - LLM 关键词提取失败 → 简单分词
  - LLM 相关性评分失败 → 仅用关键词排序
  - LLM 摘要生成失败 → 简单拼接
"""

import asyncio
from typing import Optional

from loguru import logger

from mia.memory.store import KnowledgeEntry, MemoryStore
from mia.providers.base import BaseProvider


# ─── 关键词提取 prompt ──────────────────────────────

KEYWORD_EXTRACTION_PROMPT = """从以下用户问题中提取 3-5 个关键词，用于检索相关的历史知识。
关键词应该是名词、动词或短语，覆盖主题、实体、动作等。
只返回 JSON: {{"keywords": ["kw1", "kw2", "kw3"]}}

用户问题: {intent}"""


# ─── 相关性判断 prompt ─────────────────────────────

RELEVANCE_PROMPT = """判断以下历史知识是否与用户当前问题相关。
返回 0.0 到 1.0 之间的相关性分数 (浮点数)。

当前问题: {intent}

历史知识:
- 类别: {category}
- 内容: {content}

只返回数字 (如 0.85):"""



class MemoryRetriever:
    """知识检索器 — 关键词 + LLM 混合检索

    适配 KnowledgeEntry 模型:
      - 检索 content + keywords (无 role/summary 字段)
      - 知识条目数量少、质量高，检索更精准
    """

    MAX_CANDIDATES = 30

    def __init__(
        self,
        provider: Optional[BaseProvider] = None,
        fallback_provider: Optional[BaseProvider] = None,
        enable_llm_rerank: bool = True,
    ):
        """
        Args:
            provider: LLM Provider (用于关键词提取和相关性评分)
            fallback_provider: 备选 Provider
            enable_llm_rerank: 是否启用 LLM 相关性评分
        """
        self.provider = provider
        self.fallback_provider = fallback_provider
        self.enable_llm_rerank = enable_llm_rerank

    # ─── 公开 API ───────────────────────────────────

    async def retrieve(
        self,
        intent: str,
        store: MemoryStore,
        top_k: int = 5,
    ) -> list[KnowledgeEntry]:
        """检索与用户意图最相关的历史知识 — 两阶段检索

        Phase 1: 扫索引 (scan_index) → 定位相关日期
        Phase 2: 按需加载 (load_day) → 关键词匹配 + LLM 重排序

        Args:
            intent: 用户意图描述
            store: 知识存储
            top_k: 返回条数

        Returns:
            相关知识列表 (按相关性排序)
        """
        if store.count == 0:
            return []

        # 阶段 1: 关键词提取
        keywords = await self._extract_keywords(intent)
        if not keywords:
            keywords = self._simple_tokenize(intent)

        logger.debug("[MemoryRetriever] 关键词: {}", keywords)

        # 阶段 2: 扫索引 → 定位相关日期
        relevant_dates = store.scan_index(keywords, limit=7)

        # 阶段 3: 按需加载相关日文件 → 收集候选条目
        candidates = []
        for date in relevant_dates:
            candidates.extend(store.load_day(date))

        if not candidates:
            for date in store.get_recent_dates(3):
                candidates.extend(store.load_day(date))
            logger.debug(
                "[MemoryRetriever] 索引无匹配，降级到最近 {} 天, {} 条",
                len(store.get_recent_dates(3)), len(candidates),
            )

        # 阶段 4: 关键词重叠匹配
        candidates = self._keyword_match(keywords, candidates)

        if not candidates:
            candidates = store.get_recent(top_k * 2)
            logger.debug("[MemoryRetriever] 关键词无匹配，回退到最近 {} 条", len(candidates))

        # 阶段 5: LLM 相关性评分 (可选)
        if self.enable_llm_rerank and len(candidates) > top_k and self.provider:
            try:
                candidates = await self._llm_rerank(intent, candidates, top_k)
            except Exception as e:
                logger.warning("[MemoryRetriever] LLM 重排序失败: {}, 使用关键词排序", e)

        # 阶段 6: Top-K
        results = candidates[:top_k]
        logger.info(
            "[MemoryRetriever] 检索完成: {} 条候选 → {} 条结果",
            len(candidates), len(results),
        )
        return results

    async def summarize_for_context(
        self,
        intent: str,
        retrieved: list[KnowledgeEntry],
    ) -> str:
        """将检索到的知识生成为上下文文本，直接注入 Scheduler LLM

        重要设计决策: 知识条目本身已经是 Level 1/2 LLM 提炼过的原子事实，
        不需要再调用 LLM 做"摘要的摘要"。这避免了:
          - LLM 幻觉导致关键信息被篡改 (如名字截断)
          - 额外的 token 消耗和延迟
          - 信息在多次 LLM 传递中的失真

        Args:
            intent: 用户当前意图 (保留参数用于未来扩展)
            retrieved: 检索到的知识列表

        Returns:
            上下文文本 (直接拼接的条目列表)
        """
        if not retrieved:
            return ""

        return self._simple_summary(retrieved)

    # ─── 关键词提取 ──────────────────────────────────

    async def _extract_keywords(self, intent: str) -> list[str]:
        """调用 LLM 提取关键词 (公开方法, 供 MemoryAgent 合并检索使用)"""
        if not self.provider:
            return self._simple_tokenize(intent)

        prompt = KEYWORD_EXTRACTION_PROMPT.format(intent=intent)

        try:
            response = await self.provider.chat_sync(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=128,
                temperature=0.1,
            )
            import json
            import re

            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    logger.debug("[MemoryRetriever] JSON 解析失败: {}",
                                 json_match.group(0)[:100])
                    raise
                keywords_list = data.get("keywords") or data.get("keyword") or []
                if isinstance(keywords_list, list):
                    return keywords_list
                logger.debug("[MemoryRetriever] keywords 不是列表: {}", type(keywords_list))

        except Exception as e:
            logger.warning("[MemoryRetriever] 关键词提取失败: {}", e)

        return self._simple_tokenize(intent)

    @staticmethod
    def _simple_tokenize(text: str) -> list[str]:
        """简单中文分词 — 降级方案，使用字符二元组 + ASCII 单词

        中文使用二元组拆分:
          "我叫什么" → ["我叫", "叫什", "什么"]
        英文使用单词提取:
          "MIA开发" → ["MIA", "我叫", "叫开", "开发"]

        二元组比整句 token 更细粒度，更容易命中子串匹配。
        """
        import re
        tokens = []
        # ASCII 单词 (3+ 字母/数字)
        ascii_tokens = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]{2,}', text)
        tokens.extend(ascii_tokens)
        # 中文字符二元组
        chinese_chars = re.findall(r'[一-鿿]', text)
        seen = set()
        for i in range(len(chinese_chars) - 1):
            bigram = chinese_chars[i] + chinese_chars[i+1]
            if bigram not in seen:
                seen.add(bigram)
                tokens.append(bigram)
        # 过滤停用词
        stopwords = {"用户问", "用户说", "请问", "帮我", "我想", "可以", "什么", "怎么", "如何", "这是", "那个", "这个"}
        return [t for t in tokens if t not in stopwords][:10]

    # ─── 关键词匹配 ──────────────────────────────────

    def _keyword_match(
        self,
        keywords: list[str],
        entries: list[KnowledgeEntry],
    ) -> list[KnowledgeEntry]:
        """关键词重叠匹配 — 在 content + keywords 中搜索

        适配 KnowledgeEntry: 无 role/summary，直接搜 content + keywords
        """
        if not keywords:
            return list(reversed(entries[-self.MAX_CANDIDATES:]))

        scored = []
        for entry in entries:
            # 在 keywords 和 content 中匹配
            searchable = (
                " ".join(entry.keywords) + " " +
                entry.content
            ).lower()

            overlap = sum(
                1 for kw in keywords
                if kw.lower() in searchable
            )
            if overlap > 0:
                # 评分: 关键词重叠 + 重要性 + 置信度
                score = overlap * 2.0 + entry.importance * 0.5 + entry.confidence * 0.5
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:self.MAX_CANDIDATES]]

    # ─── LLM 重排序 ──────────────────────────────────

    async def _llm_rerank(
        self,
        intent: str,
        candidates: list[KnowledgeEntry],
        top_k: int,
    ) -> list[KnowledgeEntry]:
        """LLM 相关性评分 — 精确过滤"""
        max_to_judge = min(len(candidates), 10)

        async def judge_one(entry: KnowledgeEntry) -> tuple[float, KnowledgeEntry]:
            prompt = RELEVANCE_PROMPT.format(
                intent=intent,
                category=entry.category_label,
                content=entry.content[:300],
            )
            try:
                response = await self.provider.chat_sync(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=16,
                    temperature=0.1,
                )
                score = float(response.strip())
                return (score, entry)
            except Exception:
                return (0.0, entry)

        tasks = [judge_one(entry) for entry in candidates[:max_to_judge]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scored = []
        for result in results:
            if isinstance(result, tuple):
                scored.append(result)
            else:
                logger.debug("[MemoryRetriever] 评分失败: {}", result)

        scored.sort(
            key=lambda x: (x[0], x[1].importance, x[1].confidence),
            reverse=True,
        )
        return [entry for _, entry in scored[:top_k]]

    @staticmethod
    def _simple_summary(retrieved: list[KnowledgeEntry]) -> str:
        """直接拼接知识条目为上下文文本 — 无需 LLM 摘要

        知识条目本身已经是 Level 1/2 提炼过的原子事实，
        直接以列表形式注入 Scheduler LLM 上下文即可。

        Args:
            retrieved: 检索到的知识列表

        Returns:
            格式化的上下文文本
        """
        parts = ["## 相关历史知识"]
        for entry in retrieved:
            # 保留完整内容不截断 — 条目本身就是精炼的原子知识
            parts.append(f"- [{entry.category_label}] {entry.content}")
        return "\n".join(parts)
