"""
MIA TUI Application — 基于 Textual RichLog 的交互式终端界面

参照 OpenCode TUI 的界面模式:
  - Header: 标题 + 时钟
  - RichLog: 聊天历史 (Rich markup 格式化)
  - Input + Button: 底部输入区
  - 思考过程/工具调用: 内联 dim 彩色文本
  - 流式输出: 逐 chunk 写入 RichLog

用法:
    from mia.tui.app import MiaTuiApp
    app = MiaTuiApp()
    await app.run_async()
"""

import asyncio
import uuid
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Header, RichLog, Input, Button

from loguru import logger

from mia.config import get_config
from mia.bus.bus import MessageBus
from mia.bus.message import (
    Message,
    MessageType,
)
from mia.providers.mimo import MiMoProvider
from mia.providers.deepseek import DeepSeekProvider
from mia.agents.receiver import ReceiverAgent
from mia.agents.scheduler import SchedulerAgent
from mia.agents.sender import SenderAgent
from mia.agents.task import TaskAgent
from mia.agents.memory import MemoryAgent


class MiaTuiApp(App):
    """MIA 主 TUI 应用 — RichLog 聊天界面"""

    CSS = """
    Screen { background: #1a1b26; }

    Header { dock: top; }

    #chat-history {
        height: 1fr;
        border: none;
        background: #1a1b26;
        padding: 0 1;
    }

    #input-container {
        dock: bottom;
        height: 3;
        background: #16161e;
        padding: 0 1;
        border-top: solid #3b4261;
    }

    #user-input {
        width: 1fr;
        background: #1a1b26;
        color: #c0caf5;
        border: solid #3b4261;
        margin: 0 1 0 0;
    }
    #user-input:focus { border: solid #7aa2f7; }

    #send-button {
        width: 8;
        background: #7aa2f7;
        color: #1a1b26;
        text-style: bold;
    }
    #send-button:hover { background: #9ece6a; }
    """

    BINDINGS = [
        ("ctrl+c", "quit_app", "退出"),
        ("ctrl+q", "quit_app", "退出"),
        ("escape", "focus_input", "聚焦输入"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config = get_config()

        # Agent 系统
        self.bus: MessageBus | None = None
        self.mimo: MiMoProvider | None = None
        self.deepseek: DeepSeekProvider | None = None
        self.receiver: ReceiverAgent | None = None
        self.memory_agent: MemoryAgent | None = None
        self.scheduler: SchedulerAgent | None = None
        self.sender: SenderAgent | None = None
        self.task_agent: TaskAgent | None = None
        self._agent_tasks: list[asyncio.Task] = []
        self._running = False

        # 流式状态
        self._streaming = False

    # ─── Compose ────────────────────────────────────────

    def compose(self) -> ComposeResult:
        """构建布局: Header + RichLog + Input/Button"""
        yield Header(show_clock=True)
        yield RichLog(
            id="chat-history",
            highlight=True,
            markup=True,
            wrap=True,
            max_lines=5000,
        )
        with Horizontal(id="input-container"):
            yield Input(
                placeholder="输入消息... (/help 查看命令)",
                id="user-input",
            )
            yield Button("发送", id="send-button", variant="primary")

    # ─── 生命周期 ──────────────────────────────────────

    async def on_mount(self) -> None:
        """启动 Agent 系统"""
        # 抑制 loguru stderr 输出
        logger.remove()
        log_dir = Path(__file__).parent.parent.parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "mia-tui.log",
            rotation="10 MB", retention="3 days", level="DEBUG",
            format="{time} | {level} | {name}:{function}:{line} - {message}",
        )

        # Header 标题
        try:
            self.query_one(Header).title = "MIA — Modular Intelligent Agent"
        except Exception:
            pass

        # 启动 Agent 系统
        await self._start_agent_system()

        # 订阅消息
        await self.bus.subscribe("tui")
        await self.bus.subscribe("sender")

        # 消息处理 worker
        self._running = True
        self.run_worker(self._process_bus_messages(), exclusive=False)

        # 欢迎消息
        self._write_system(
            f"MIA v0.2.0 已就绪  |  模型: {self.config.mimo.chat_model}  "
            f"|  /help 查看命令  |  /quit 退出"
        )

        # 聚焦输入
        self._focus_input()

    async def on_unmount(self) -> None:
        """清理"""
        self._running = False
        await self._stop_agent_system()

    # ─── 用户输入 ──────────────────────────────────────

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """发送按钮"""
        if event.button.id == "send-button":
            await self._submit_input()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """回车提交"""
        await self._submit_input()

    async def _submit_input(self) -> None:
        """获取输入文本并处理"""
        try:
            inp = self.query_one("#user-input", Input)
            text = inp.value.strip()
            if not text:
                return
            inp.value = ""  # 清空

            if text.startswith("/"):
                self._handle_command(text.lower())
            else:
                self._send_message(text)
        except Exception:
            pass

    def _send_message(self, text: str) -> None:
        """发送用户消息到 Agent 系统"""
        session_id = uuid.uuid4().hex[:12]

        # 显示用户消息
        chat = self.query_one("#chat-history", RichLog)
        chat.write(f"[bold #7aa2f7]You[/] {text}")

        # 发布到 MessageBus
        if self.bus:
            asyncio.create_task(self.bus.publish(Message(
                msg_type=MessageType.RAW_INPUT,
                source="tui", target="receiver",
                payload={"text": text, "image": None, "voice": None},
                session_id=session_id,
            )))

    # ─── 命令处理 ──────────────────────────────────────

    def _handle_command(self, command: str) -> None:
        """处理 / 命令"""
        if command in ("/quit", "/exit", "/q"):
            self._write_system("再见~")
            asyncio.create_task(self._delayed_quit())

        elif command in ("/help", "/h"):
            self._write_system(
                "[bold]MIA 命令列表[/]\n"
                "  /quit, /exit, /q  — 退出\n"
                "  /help, /h         — 帮助\n"
                "  /compact          — 压缩对话历史\n"
                "  /memory           — 查看记忆状态\n"
                "  Ctrl+C            — 退出\n"
                "  Esc               — 聚焦输入框"
            )

        elif command == "/compact":
            if self.memory_agent:
                self._write_system("[dim]正在压缩对话历史...[/]")
                asyncio.create_task(self._do_compact())
            else:
                self._write_system("[bold red]记忆系统未就绪[/]")

        elif command == "/memory":
            if self.memory_agent:
                w = len(self.memory_agent._working_memory)
                p = self.memory_agent.store.count
                h = len(self.memory_agent._conversation_history)
                parts = [
                    f"[bold]记忆状态[/]  临时: {w} 条  持久: {p} 条  历史: {h} 轮"
                ]
                for i, entry in enumerate(self.memory_agent._working_memory):
                    parts.append(
                        f"  [dim][{entry.category_label}][/] {entry.content[:100]} "
                        f"[dim]({entry.confidence:.1f})[/]"
                    )
                self._write_system("\n".join(parts))
            else:
                self._write_system("[bold red]记忆系统未就绪[/]")

        elif command.startswith("/image "):
            self._write_system("[dim yellow]图片输入功能开发中...[/]")

        else:
            known = ["/quit", "/exit", "/q", "/help", "/h",
                     "/compact", "/memory", "/image"]
            suggestions = [c for c in known if c.startswith(command[:3])]
            if suggestions:
                self._write_system(
                    f"[dim yellow]未知命令 '{command}'，"
                    f"你是想输入 {' / '.join(suggestions[:3])} 吗？[/]"
                )
            else:
                self._write_system(
                    f"[dim yellow]未知命令 '{command}'，输入 /help 查看[/]"
                )

    async def _do_compact(self) -> None:
        """执行 /compact"""
        try:
            summary = await self.memory_agent.compact()
            new_count = self.memory_agent.store.count
            self._write_system(
                f"[bold green]对话历史已压缩[/]\n"
                f"  持久知识: {new_count} 条\n"
                f"  摘要: {summary[:200]}..."
            )
        except Exception as e:
            self._write_system(f"[bold red]压缩失败: {e}[/]")

    async def _delayed_quit(self) -> None:
        """延迟退出"""
        await asyncio.sleep(0.5)
        await self.action_quit_app()

    # ─── Agent 系统生命周期 ────────────────────────────

    async def _start_agent_system(self) -> None:
        """启动 MessageBus + 全部 Agent"""
        config = self.config

        self.bus = MessageBus(max_queue_size=100)
        await self.bus.start()

        self.mimo = MiMoProvider(api_key=config.mimo.api_key)
        self.deepseek = DeepSeekProvider(api_key=config.deepseek.api_key)

        self.receiver = ReceiverAgent(bus=self.bus, mimo=self.mimo)
        self.scheduler = SchedulerAgent(
            bus=self.bus, provider=self.mimo,
            model=config.mimo.chat_model,
            fallback_provider=self.deepseek,
            fallback_model=config.deepseek.chat_model,
            enable_streaming=config.agent.enable_streaming,
        )
        self.sender = SenderAgent(
            bus=self.bus, mimo=self.mimo,
            output_dir=config.agent.workspace_dir,
        )
        self.task_agent = TaskAgent(
            bus=self.bus, provider=self.mimo,
            model=config.mimo.chat_model,
            fallback_provider=self.deepseek,
            fallback_model=config.deepseek.chat_model,
        )
        self.memory_agent = MemoryAgent(
            bus=self.bus, provider=self.mimo,
            model=config.mimo.chat_model,
            fallback_provider=self.deepseek,
            fallback_model=config.deepseek.chat_model,
        )

        for agent in [self.receiver, self.memory_agent,
                       self.scheduler, self.sender, self.task_agent]:
            await agent.start()

        for agent in [self.receiver, self.memory_agent,
                       self.scheduler, self.sender, self.task_agent]:
            self._agent_tasks.append(asyncio.create_task(agent.run()))

        await asyncio.sleep(0.3)
        logger.info("[TUI] Agent 系统启动完成")

    async def _stop_agent_system(self) -> None:
        """关闭 Agent 系统"""
        logger.info("[TUI] 正在关闭 Agent 系统...")
        for agent in [self.receiver, self.memory_agent,
                       self.scheduler, self.sender, self.task_agent]:
            if agent:
                try:
                    await agent.stop()
                except Exception:
                    pass
        for task in self._agent_tasks:
            task.cancel()
        if self._agent_tasks:
            await asyncio.gather(*self._agent_tasks, return_exceptions=True)
        if self.bus:
            await self.bus.stop()
        logger.info("[TUI] Agent 系统已关闭")

    # ─── 消息处理 Worker ───────────────────────────────

    async def _process_bus_messages(self) -> None:
        """后台: 处理 MessageBus 消息 → RichLog 显示"""
        while self._running:
            try:
                msg = await self.bus.receive("tui", timeout=0.05)
                if msg:
                    await self._handle_tui_message(msg)

                msg = await self.bus.receive("sender", timeout=0.05)
                if msg:
                    await self._handle_sender_message(msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[TUI] 消息异常: {}", e)

    async def _handle_tui_message(self, msg: Message) -> None:
        """TUI 专用消息 → RichLog"""
        mt = msg.msg_type

        if mt == MessageType.TUI_THOUGHT:
            agent = msg.payload.get("agent", "?")
            title = msg.payload.get("title", "")
            detail = msg.payload.get("detail", "")
            # 思考过程: dim cyan
            color_map = {
                "scheduler": "#7dcfff",
                "task": "#e0af68",
                "memory": "#bb9af7",
                "receiver": "#f7768e",
            }
            c = color_map.get(agent, "#565f89")
            chat = self.query_one("#chat-history", RichLog)
            chat.write(f"[dim {c}]▶ {agent}: {title}[/]")
            if detail:
                chat.write(f"[dim]{detail}[/]")

        elif mt == MessageType.TUI_TOOL:
            tool_name = msg.payload.get("tool_name", "?")
            tool_args = msg.payload.get("tool_args", "")
            result = msg.payload.get("result", "")
            status = msg.payload.get("status", "running")
            chat = self.query_one("#chat-history", RichLog)
            if status == "running":
                chat.write(f"[dim #e0af68]🔧 {tool_name}({tool_args})[/]")
            elif status == "success":
                chat.write(f"[dim #9ece6a]  ✓ {tool_name}[/]")
                if result:
                    chat.write(f"[dim]{result[:200]}[/]")
            else:
                chat.write(f"[bold #f7768e]  ✖ {tool_name}: {result[:200]}[/]")

        elif mt == MessageType.TUI_TOAST:
            level = msg.payload.get("level", "info")
            message = msg.payload.get("message", "")
            try:
                sev = "information"
                if level in ("warning", "error"):
                    sev = level
                self.notify(message, severity=sev, timeout=5)
            except Exception:
                pass

        elif mt == MessageType.TUI_STATUS:
            # 状态更新 → Header subtitle
            key = msg.payload.get("key", "")
            value = msg.payload.get("value", "")
            try:
                if key == "memory":
                    self.query_one(Header).sub_title = f"记忆: {value}"
            except Exception:
                pass

    async def _handle_sender_message(self, msg: Message) -> None:
        """Sender 消息 (流式/文本) → RichLog"""
        mt = msg.msg_type

        if mt == MessageType.STREAM_START:
            self._streaming = True
            chat = self.query_one("#chat-history", RichLog)
            chat.write("[bold #9ece6a]MIA[/] ")

        elif mt == MessageType.STREAM_CHUNK:
            if self._streaming:
                delta = msg.payload.get("delta", "")
                if delta:
                    chat = self.query_one("#chat-history", RichLog)
                    chat.write(delta)

        elif mt == MessageType.STREAM_END:
            self._streaming = False
            chat = self.query_one("#chat-history", RichLog)
            chat.write("")  # 换行

        elif mt == MessageType.SEND_TEXT:
            message = msg.payload.get("message", "")
            chat = self.query_one("#chat-history", RichLog)
            chat.write(f"[bold #9ece6a]MIA[/] {message}")
            chat.write("")

        elif mt == MessageType.CONVERSATION_DONE:
            pass  # main 处理

        elif mt == MessageType.TASK_ERROR:
            error = msg.payload.get("error", "")
            chat = self.query_one("#chat-history", RichLog)
            chat.write(f"[bold #f7768e]✖ 任务错误: {error}[/]")

    # ─── 辅助方法 ──────────────────────────────────────

    def _write_system(self, text: str) -> None:
        """写入系统消息 (dim italic)"""
        try:
            chat = self.query_one("#chat-history", RichLog)
            chat.write(f"[dim italic]{text}[/]")
        except Exception:
            pass

    def _focus_input(self) -> None:
        """聚焦输入框"""
        try:
            self.query_one("#user-input", Input).focus()
        except Exception:
            pass

    async def action_quit_app(self) -> None:
        """退出"""
        self._write_system("正在退出...")
        await asyncio.sleep(0.3)
        await self._stop_agent_system()
        self.exit()
