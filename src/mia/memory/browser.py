"""
MemoryBrowser — 交互式 TUI 记忆浏览器

3 级钻取式浏览:
  Level 1: questionary.select 展示日期列表 (方向键选择)
  Level 2: questionary.select 展示条目列表 (方向键选择)
  Level 3: rich.Table 展示完整条目详情

支持降级: 当终端不支持 prompt_toolkit (如 Git Bash) 时自动降级为 flat print 模式。

用法:
    from mia.memory.browser import MemoryBrowser
    browser = MemoryBrowser(store)
    await browser.browse()
"""

import asyncio
import sys
from typing import Optional

from loguru import logger

from mia.memory.store import MemoryEntry, MemoryStore

# ─── 检测终端是否支持交互输入 ──────────────────────

def _is_interactive() -> bool:
    """检测当前终端是否支持交互式输入 (非管道/非 pytest 捕获)"""
    return sys.stdin.isatty()


# ─── 角色图标 (纯文本，兼容所有终端) ──────────────────

_ROLE_LABELS = {
    "user":    "[用户]",
    "assistant": "[助手]",
    "system":  "[系统]",
}


class MemoryBrowser:
    """3 级钻取式记忆浏览器 TUI

    Level 1: 日期列表 (条目数 + 日摘要预览)
    Level 2: 条目列表 (角色 + 内容预览)
    Level 3: 详情表格 (全部 8 个字段)

    纯只读，不修改 MemoryStore。
    """

    DISPLAY_DAYS = 30  # Level 1 最多展示的天数

    def __init__(self, store: MemoryStore):
        """
        Args:
            store: MemoryStore 实例 (只读访问)
        """
        self.store = store
        self._use_tui = True  # 启动时检测终端是否支持 questionary

    # ═══════════════════════════════════════════════════════
    # 公开 API
    # ═══════════════════════════════════════════════════════

    async def browse(self) -> None:
        """主入口 — 启动交互式记忆浏览

        记忆为空时打印提示并立即返回。
        """
        if self.store.count == 0:
            print("  \033[90m对话记忆为空。\033[0m")
            return

        # 尝试导入 questionary, 失败则降级为 flat 模式
        try:
            import questionary
            self._use_tui = True
        except ImportError:
            logger.info("[MemoryBrowser] questionary 未安装，降级为 flat 模式")
            self._use_tui = False
        except Exception:
            # prompt_toolkit 在某些终端 (Git Bash) 无法初始化
            logger.info("[MemoryBrowser] 终端不支持 prompt_toolkit，降级为 flat 模式")
            self._use_tui = False

        if not self._use_tui:
            await self._browse_flat()
            return

        # ─── TUI 模式: 3 级钻取 ─────────────────────
        try:
            await self._browse_tui()
        except Exception as e:
            # 运行时终端错误 (如 NoConsoleScreenBufferError)
            logger.warning("[MemoryBrowser] TUI 失败: {}，降级为 flat", e)
            self._use_tui = False
            await self._browse_flat()

    # ═══════════════════════════════════════════════════════
    # TUI 模式 — 3 级钻取
    # ═══════════════════════════════════════════════════════

    async def _browse_tui(self) -> None:
        """TUI 模式: 日期列表 → 条目列表 → 详情 (循环)"""
        import questionary

        # 获取索引快照
        index = self.store.get_index_summaries()
        if not index:
            print("  \033[90m对话记忆为空。\033[0m")
            return

        # 只有 1 天: 跳过日期选择，直接进条目列表
        if len(index) == 1:
            date = list(index.keys())[0]
            await self._browse_entries_tui(date)
            return

        # 正常流程: 日期 → 条目 → 详情
        while True:
            date = await self._select_date_tui(index)
            if date is None:
                break  # 用户选择 [返回] 退出
            await self._browse_entries_tui(date)

    async def _select_date_tui(self, index: dict) -> Optional[str]:
        """Level 1 — questionary.select 日期候选框"""
        import questionary

        choices = []
        for date, ds in list(index.items())[:self.DISPLAY_DAYS]:
            # 构造选择项: "2026-06-19 (6条) — 日摘要..."
            label = f"{date}  ({ds.entry_count}条)"
            if ds.daily_summary:
                summary_preview = ds.daily_summary[:50]
                label += f" — {summary_preview}"
            choices.append(questionary.Choice(title=label, value=date))

        # 末尾 [返回] 选项
        choices.append(questionary.Choice(
            title="[返回] 退出浏览器",
            value=None,
        ))

        total = self.store.get_total_count()
        message = f"记忆浏览 — {len(index)} 天, {total} 条记录  选择日期:"

        try:
            result = await questionary.select(
                message,
                choices=choices,
                use_indicator=True,
                qmark=">",
                instruction="(↑↓ 移动, Enter 选择, Esc 退出)",
            ).ask_async()
        except KeyboardInterrupt:
            return None

        return result

    async def _browse_entries_tui(self, date: str) -> None:
        """浏览某天的条目 — 条目列表 + 详情循环"""
        entries = self.store.load_day(date)
        if not entries:
            print(f"  \033[90m{date} 无记录。\033[0m")
            return

        while True:
            entry = await self._select_entry_tui(date, entries)
            if entry is None:
                break  # 用户选择 [返回]
            await self._show_detail_tui(entry)

    async def _select_entry_tui(
        self, date: str, entries: list[MemoryEntry],
    ) -> Optional[MemoryEntry]:
        """Level 2 — questionary.select 条目候选框"""
        import questionary

        choices = []
        for entry in entries:
            role_label = _ROLE_LABELS.get(entry.role, "[?]")
            # 内容预览: 单行，截断到 70 字
            preview = entry.content.replace("\n", " ")[:70]
            if len(entry.content) > 70:
                preview += "..."
            label = f"{role_label} {preview}"
            choices.append(questionary.Choice(title=label, value=entry))

        # 末尾 [返回] 选项
        choices.append(questionary.Choice(
            title="[返回] 上一级",
            value=None,
        ))

        try:
            result = await questionary.select(
                f"{date} — {len(entries)} 条记录  选择条目:",
                choices=choices,
                use_indicator=True,
                qmark=">",
                instruction="(↑↓ 移动, Enter 查看详情, Esc 返回)",
            ).ask_async()
        except KeyboardInterrupt:
            return None

        return result

    async def _show_detail_tui(self, entry: MemoryEntry) -> None:
        """Level 3 — rich.Table 展示完整条目详情"""
        try:
            from rich.console import Console
            from rich.table import Table
            from rich.box import ROUNDED
            console = Console()
            table = Table(
                title=f"记忆详情 [{entry.id[:8]}...]",
                box=ROUNDED,
                show_header=True,
                title_style="bold cyan",
            )
            table.add_column("字段", style="bold cyan", no_wrap=True, width=10)
            table.add_column("值", style="")

            role_label = _ROLE_LABELS.get(entry.role, entry.role)
            table.add_row("ID", entry.id)
            table.add_row("角色", role_label)
            table.add_row("时间", entry.timestamp)
            table.add_row("重要性", f"{entry.importance:.2f}")
            table.add_row("会话ID", entry.session_id)
            table.add_row("摘要", entry.summary or "(无)")
            table.add_row("关键词", ", ".join(entry.keywords) if entry.keywords else "(无)")
            table.add_row("内容", entry.content)

            console.print()
            console.print(table)
            console.print()

            # 等待用户按 Enter 返回 (仅在交互式终端暂停)
            if _is_interactive():
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, input, "  按 Enter 返回...")

        except ImportError:
            # rich 未安装，降级为纯文本打印
            self._show_detail_plain(entry)

    # ═══════════════════════════════════════════════════════
    # Flat 模式 — 降级方案 (不支持 TUI 的终端)
    # ═══════════════════════════════════════════════════════

    async def _browse_flat(self) -> None:
        """Flat 模式: 依次打印日期 → 条目，用 input 分页"""
        index = self.store.get_index_summaries()
        if not index:
            print("  \033[90m对话记忆为空。\033[0m")
            return

        total = self.store.get_total_count()
        print(f"\n  \033[90m对话记忆: {len(index)} 天, {total} 条记录\033[0m")
        print()

        interactive = _is_interactive()

        for date, ds in list(index.items())[:self.DISPLAY_DAYS]:
            summary_hint = f" — {ds.daily_summary}" if ds.daily_summary else ""
            print(f"  \033[33m{date}\033[0m ({ds.entry_count}条){summary_hint}")

            entries = self.store.load_day(date)
            for i, entry in enumerate(entries):
                role_label = _ROLE_LABELS.get(entry.role, "[?]")
                preview = entry.content.replace("\n", " ")[:80]
                if len(entry.content) > 80:
                    preview += "..."
                print(f"    \033[90m[{i+1}]\033[0m {role_label} {preview}")

            # 只在交互式终端暂停 (pytest/管道跳过)
            if interactive and len(entries) > 0:
                print()
                await asyncio.get_event_loop().run_in_executor(
                    None, input,
                    f"  \033[90m按 Enter 继续...\033[0m",
                )

        print()

    # ═══════════════════════════════════════════════════════
    # 纯文本详情 (无 rich 时的降级)
    # ═══════════════════════════════════════════════════════

    def _show_detail_plain(self, entry: MemoryEntry) -> None:
        """纯文本打印 MemoryEntry 全部字段"""
        role_label = _ROLE_LABELS.get(entry.role, entry.role)
        print()
        print(f"  \033[1m{'─' * 50}\033[0m")
        print(f"  \033[36mID:\033[0m       {entry.id}")
        print(f"  \033[36m角色:\033[0m     {role_label}")
        print(f"  \033[36m时间:\033[0m     {entry.timestamp}")
        print(f"  \033[36m重要性:\033[0m   {entry.importance:.2f}")
        print(f"  \033[36m会话ID:\033[0m   {entry.session_id}")
        print(f"  \033[36m摘要:\033[0m     {entry.summary or '(无)'}")
        print(f"  \033[36m关键词:\033[0m   {', '.join(entry.keywords) if entry.keywords else '(无)'}")
        print(f"  \033[1m{'─' * 50}\033[0m")
        print(f"  \033[36m内容:\033[0m")
        print(f"  {entry.content}")
        print(f"  \033[1m{'─' * 50}\033[0m")
        print()
