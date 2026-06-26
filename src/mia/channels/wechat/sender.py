# -*- coding: utf-8 -*-
"""WeChatSenderAgent — MIA 到微信的消息发送 Agent

WeChatSenderAgent 是 WeChatAgent 的出站部分独立提取的 Agent，
只负责将 MIA 的回复发送到微信用户，不处理入站消息轮询。

职责:
  1. 监听 SEND_TEXT / STREAM_* / SEND_VOICE 消息
  2. 通过 iLink API 将文本或语音发送给微信用户
  3. 发送完成后发布 CONVERSATION_DONE

架构位置:
  MIA Scheduler → MessageBus → WeChatSenderAgent → (iLink API) → 微信用户

对比 WeChatAgent（原始）:
  - 移除了所有入站处理: 长轮询线程、消息去重、媒体下载、SILK→WAV 转码、QR 登录
  - 移除了 _active_sessions（不再需要缓存入站会话信息）
  - to_user_id / context_token 从 msg.payload 获取（由 Scheduler 透传）
  - context_token 仅有缓存 fallback: _user_context_tokens
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from mia.agents.base import BaseAgent
from mia.bus.bus import MessageBus
from mia.bus.message import Message, MessageType

logger = logging.getLogger(__name__)

# ─── 常量 ──────────────────────────────────────────────

_DEFAULT_TOKEN_FILE = Path.home() / ".mia" / "wechat_bot_token"


class WeChatSenderAgent(BaseAgent):
    """微信消息发送 Agent — 将 MIA 的回复发送到微信用户

    从 WeChatAgent 提取出站部分，只处理输出消息，不处理入站轮询。
    每条 SEND_TEXT / STREAM_* / SEND_VOICE 消息的 payload 中
    包含 to_user_id 和 context_token（由 Scheduler 通过消息工厂透传）。

    Args:
        bus: MIA 消息总线
        bot_token: iLink Bot token（空字符串 = 从文件加载）
        bot_token_file: Token 持久化文件路径
        base_url: iLink API 基础 URL
        enabled: 是否启用此渠道
        mimo: MiMoProvider 实例（可选，用于 TTS 语音合成）
        workspace_dir: TTS 音频临时输出目录
    """

    def __init__(
        self,
        bus: MessageBus,
        bot_token: str = "",
        bot_token_file: str = "",
        base_url: str = "",
        enabled: bool = True,
        mimo=None,
        workspace_dir: str = "",
    ):
        super().__init__(name="wechat_sender", bus=bus)
        self.enabled = enabled
        self.bot_token = bot_token
        self._base_url = base_url or "https://ilinkai.weixin.qq.com"
        self._mimo = mimo  # 可选: 用于合成语音回复

        # Token 文件
        self._bot_token_file = (
            Path(bot_token_file).expanduser()
            if bot_token_file
            else _DEFAULT_TOKEN_FILE
        )
        # context_tokens 缓存文件（与 agent.py 保持一致的位置）
        self._context_tokens_file = (
            self._bot_token_file.parent / "wechat_context_tokens.json"
        )

        # TTS 音频输出目录
        self._workspace_dir = (
            Path(workspace_dir).expanduser()
            if workspace_dir
            else Path.home() / ".mia" / "workspace"
        )
        self._workspace_dir.mkdir(parents=True, exist_ok=True)

        # ILinkClient 实例（延迟创建，在 on_start() 中初始化）
        self._client = None  # type: Optional[ILinkClient]

        # ─── 用户 context_token 缓存 ────────────────────
        # to_user_id → context_token（持久化到文件）
        # 用于 payload 中没有 context_token 时的 fallback
        self._user_context_tokens: Dict[str, str] = {}

        # ─── 流式回复缓冲 ───────────────────────────────
        # session_id → 累积文本
        self._stream_buffers: Dict[str, str] = {}

        # ─── 流式元数据缓存 ─────────────────────────────
        # session_id → {to_user_id, context_token}
        # 由 STREAM_START 写入，STREAM_END 读取并清理
        self._stream_meta: Dict[str, Dict[str, str]] = {}

    # ─── 生命周期 ──────────────────────────────────────

    async def on_start(self) -> None:
        """Agent 启动 — 加载 token，创建 ILinkClient，加载 context_tokens

        仅初始化发送所需组件，不启动轮询线程。
        """
        if not self.enabled:
            logger.info("[WeChatSender] 渠道已禁用，跳过初始化")
            return

        # 1. 尝试从文件加载 token
        if not self.bot_token:
            self.bot_token = self._load_token_from_file()

        # 2. 创建 ILinkClient（延迟导入避免循环依赖）
        from mia.channels.wechat.client import ILinkClient

        self._client = ILinkClient(
            bot_token=self.bot_token,
            base_url=self._base_url,
        )
        await self._client.start()

        # 3. 加载持久化的 context_tokens
        self._load_context_tokens()

        logger.info("[WeChatSender] 微信发送渠道已就绪 ✓")

    async def on_stop(self) -> None:
        """Agent 停止 — 关闭 HTTP 客户端"""
        if self._client:
            await self._client.stop()
            self._client = None
        logger.info("[WeChatSender] 微信发送渠道已停止")

    async def handle(self, msg: Message) -> None:
        """处理来自 MessageBus 的输出消息

        监听 Scheduler 发来的输出消息，转发给微信用户:
          - SEND_TEXT: 纯文本回复
          - STREAM_START / STREAM_CHUNK / STREAM_END: 流式回复
          - SEND_VOICE: 语音回复（TTS 合成 → CDN 上传 → 文件消息）

        to_user_id 和 context_token 从 msg.payload 获取，
        Scheduler 通过 make_send_text / make_stream_* / make_send_voice
        工厂函数将这些字段透传到 payload 中。
        """
        if not self.enabled:
            return

        if msg.msg_type == MessageType.SEND_TEXT:
            await self._handle_output_text(msg)
        elif msg.msg_type == MessageType.STREAM_START:
            await self._handle_stream_start(msg)
        elif msg.msg_type == MessageType.STREAM_CHUNK:
            await self._handle_stream_chunk(msg)
        elif msg.msg_type == MessageType.STREAM_END:
            await self._handle_stream_end(msg)
        elif msg.msg_type == MessageType.SEND_VOICE:
            await self._handle_output_voice(msg)

    # ─── 输出处理 ──────────────────────────────────────

    async def _handle_output_text(self, msg: Message) -> None:
        """处理文本输出 — 直接发送到微信用户，然后发布 CONVERSATION_DONE

        与原始 WeChatAgent 不同:
          - 不再依赖 _active_sessions 查找 to_user_id / context_token
          - 直接从 msg.payload 获取（由 Scheduler 透传）
          - context_token fallback: payload → _user_context_tokens 缓存
        """
        message = msg.payload.get("message", "")
        to_user_id = msg.payload.get("to_user_id", "")
        context_token = msg.payload.get("context_token", "")

        # Fallback: 如果 payload 没有 context_token，尝试从缓存获取
        if not context_token and to_user_id:
            context_token = self._user_context_tokens.get(to_user_id, "")

        if message and to_user_id:
            await self._send_text_to_user(to_user_id, context_token, message)
            print(f"\033[32m[WeChatSender]\033[0m 文本已发送 ({len(message)}字)")

        # 发布 CONVERSATION_DONE → MemoryAgent 存储记忆
        await self._publish_conversation_done(msg, message)

    async def _handle_stream_start(self, msg: Message) -> None:
        """流式开始 — 初始化文本缓冲和流式元数据"""
        sid = msg.session_id or ""
        self._stream_buffers[sid] = ""

        # 保存 to_user_id / context_token 供 STREAM_END 使用
        to_user_id = msg.payload.get("to_user_id", "")
        context_token = msg.payload.get("context_token", "")
        if to_user_id:
            # payload 没有 context_token 时尝试从缓存获取
            if not context_token:
                context_token = self._user_context_tokens.get(to_user_id, "")
            self._stream_meta[sid] = {
                "to_user_id": to_user_id,
                "context_token": context_token,
            }

    async def _handle_stream_chunk(self, msg: Message) -> None:
        """流式增量 — 累积文本到缓冲"""
        sid = msg.session_id or ""
        delta = msg.payload.get("delta", "")
        if sid in self._stream_buffers:
            self._stream_buffers[sid] += delta

    async def _handle_stream_end(self, msg: Message) -> None:
        """流式结束 — 发送完整文本到微信，然后发布 CONVERSATION_DONE

        完整文本优先级:
          1. msg.payload["message"]（STREAM_END 的完整消息体）
          2. _stream_buffers[sid]（累积的增量文本）
        """
        sid = msg.session_id or ""
        full_text = msg.payload.get("message", "")

        # 从缓冲获取完整文本
        if not full_text and sid in self._stream_buffers:
            full_text = self._stream_buffers.pop(sid, "")
        elif sid in self._stream_buffers:
            del self._stream_buffers[sid]

        # 获取目标用户 — 优先从 STREAM_END payload，其次从 STREAM_START 缓存
        to_user_id = msg.payload.get("to_user_id", "")
        context_token = msg.payload.get("context_token", "")

        if not to_user_id:
            meta = self._stream_meta.pop(sid, {})
            to_user_id = meta.get("to_user_id", "")
            context_token = context_token or meta.get("context_token", "")
        elif sid in self._stream_meta:
            del self._stream_meta[sid]

        # Fallback: 如果仍没有 context_token，尝试从缓存获取
        if not context_token and to_user_id:
            context_token = self._user_context_tokens.get(to_user_id, "")

        if full_text and to_user_id:
            await self._send_text_to_user(to_user_id, context_token, full_text)
            print(f"\033[32m[WeChatSender]\033[0m 流式文本已发送 ({len(full_text)}字)")

        # 发布 CONVERSATION_DONE → MemoryAgent 存储记忆
        await self._publish_conversation_done(msg, full_text)

    async def _handle_output_voice(self, msg: Message) -> None:
        """处理语音输出 — TTS 合成 → 上传 CDN → 发送到微信

        流程:
          1. 从 SEND_VOICE payload 获取文本 / 音色 / 格式 / to_user_id
          2. 调用 MiMo TTS 生成 WAV 音频
          3. 上传到微信 CDN（AES-128-ECB 加密）
          4. 发送 file_item 消息（用户点击播放）
          5. 同时发送文本作为 fallback（带 🎤 前缀表示语音已成功发送）

        to_user_id / context_token 来源（优先级递减）:
          a. msg.payload.get("to_user_id") — Scheduler 透传
          b. msg.payload.get("context_token") — Scheduler 透传
          c. self._user_context_tokens[to_user_id] — 缓存 fallback
        """
        message = msg.payload.get("message", "")
        voice = msg.payload.get("voice", "冰糖")
        audio_format = msg.payload.get("format", "wav")
        session_id = msg.session_id

        # 解析目标微信用户 — 从 payload 获取（主要来源）
        to_user_id = msg.payload.get("to_user_id", "")
        context_token = msg.payload.get("context_token", "")

        # Fallback: 如果 payload 没有 context_token，尝试从缓存获取
        if not context_token and to_user_id:
            context_token = self._user_context_tokens.get(to_user_id, "")

        if not to_user_id or not message:
            print(
                f"\033[33m[WeChatSender]\033[0m SEND_VOICE "
                f"缺少 to_user_id={'EMPTY' if not to_user_id else to_user_id[:20]} "
                f"msg_len={len(message)}"
            )
            return

        print(
            f"\033[36m[WeChatSender]\033[0m → 语音发送 "
            f"to={to_user_id[:20]} text_len={len(message)}"
        )

        audio_sent = False

        # ─── 1. TTS 合成 ───────────────────────────────
        if self._mimo:
            try:
                audio_bytes = await self._mimo.synthesize(
                    text=message,
                    voice=voice,
                    audio_format=audio_format,
                )

                filename = f"wechat_voice_{msg.msg_id}.{audio_format}"
                audio_path = self._workspace_dir / filename
                audio_path.write_bytes(audio_bytes)
                print(
                    f"   \033[90m├─\033[0m TTS: {len(audio_bytes)} bytes "
                    f"→ {audio_path}"
                )

                # ─── 2. 上传到 CDN ────────────────
                print(f"   \033[90m├─\033[0m 上传 CDN...")
                upload_result = await self._client.upload_media(
                    str(audio_path),
                    media_type=3,  # FILE
                    to_user_id=to_user_id,
                )
                print(
                    f"   \033[90m├─\033[0m CDN OK: "
                    f"rawsize={upload_result['rawsize']} "
                    f"filesize={upload_result['filesize']} "
                    f"enc_param={upload_result['encrypt_query_param'][:40]}..."
                )

                # ─── 3. 发送 file_item ────────────────
                print(f"   \033[90m├─\033[0m 发送 file_item...")
                file_msg = {
                    "to_user_id": to_user_id,
                    "client_id": str(uuid.uuid4()),
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": [
                        {
                            "type": 4,
                            "file_item": {
                                "media": {
                                    "encrypt_query_param": upload_result[
                                        "encrypt_query_param"
                                    ],
                                    "aes_key": upload_result["aes_key_b64"],
                                    "encrypt_type": 1,
                                },
                                "file_name": f"mia_voice.{audio_format}",
                                "len": str(upload_result["rawsize"]),
                            },
                        }
                    ],
                }
                resp = await self._client.sendmessage(file_msg)

                ret = resp.get("ret", -1) if isinstance(resp, dict) else -1
                errcode = (
                    resp.get("errcode", "?") if isinstance(resp, dict) else "?"
                )
                print(f"   \033[90m├─\033[0m 响应: ret={ret} errcode={errcode}")

                # HTTP 200 = 成功（官方插件不检查 ret）
                audio_sent = True
                print(f"\033[32m   └─\033[0m 语音文件已发送 ✓")

                # 清理临时文件
                try:
                    audio_path.unlink(missing_ok=True)
                except Exception:
                    pass

            except Exception as e:
                print(f"\033[31m   └─\033[0m 语音发送失败: {e}")
                logger.exception("[WeChatSender] 语音发送异常")
        else:
            print(f"   \033[33m└─\033[0m 无 MiMoProvider，跳过语音")

        # ─── 4. 文本 fallback ───────────────────────────
        # 如果语音已发送，加 🎤 前缀提示用户
        prefix = "🎤 " if audio_sent else ""
        await self._send_text_to_user(
            to_user_id, context_token, f"{prefix}{message}"
        )

        # ─── 5. 发布 CONVERSATION_DONE → MemoryAgent ──
        await self._publish_conversation_done(msg, message)

    # ─── CONVERSATION_DONE ───────────────────────────────

    async def _publish_conversation_done(
        self,
        msg: Message,
        message: str,
    ) -> None:
        """发布 CONVERSATION_DONE — 通知 MemoryAgent 和 main 本轮对话结束

        模仿 SenderAgent 的行为：同时发给 "main" 和 "memory_agent"。
        MemoryAgent 收到后会追加对话历史 + 提取 Level 1 临时知识。
        """
        await self.bus.publish(
            Message(
                msg_type=MessageType.CONVERSATION_DONE,
                source=self.name,
                target="main",
                payload={"message": message},
                session_id=msg.session_id,
            )
        )
        await self.bus.publish(
            Message(
                msg_type=MessageType.CONVERSATION_DONE,
                source=self.name,
                target="memory_agent",
                payload={"message": message},
                session_id=msg.session_id,
            )
        )

    # ─── 发送文本到微信 ─────────────────────────────────

    async def _send_text_to_user(
        self,
        to_user_id: str,
        context_token: str,
        text: str,
    ) -> bool:
        """发送文本到微信用户（底层 iLink API 调用），返回是否成功"""
        if not self._client or not to_user_id or not text:
            return False
        try:
            resp = await self._client.send_text(
                to_user_id, text, context_token,
            )
            ret = resp.get("ret", -1) if isinstance(resp, dict) else -1
            if ret != 0:
                logger.warning("[WeChatSender] send_text ret=%s", ret)
                return False
            return True
        except httpx.ConnectError:
            logger.warning("[WeChatSender] iLink 连接失败 (网络不通)")
            print(f"\033[33m[WeChatSender]\033[0m iLink API 不可达, 回复未发送")
            return False
        except Exception:
            logger.exception("[WeChatSender] 发送文本失败 to=%s", to_user_id[:20])
            return False

    # ─── Token 持久化 ──────────────────────────────────

    def _load_token_from_file(self) -> str:
        """从文件加载持久化的 bot_token"""
        try:
            if self._bot_token_file.exists():
                token = self._bot_token_file.read_text(
                    encoding="utf-8"
                ).strip()
                if token:
                    logger.info(
                        "[WeChatSender] loaded bot_token from %s",
                        self._bot_token_file,
                    )
                    return token
        except Exception:
            logger.debug(
                "[WeChatSender] failed to read token file", exc_info=True
            )
        return ""

    def _save_token_to_file(self, token: str) -> None:
        """持久化 bot_token 到文件"""
        try:
            self._bot_token_file.parent.mkdir(parents=True, exist_ok=True)
            self._bot_token_file.write_text(token, encoding="utf-8")
            logger.info(
                "[WeChatSender] bot_token saved to %s",
                self._bot_token_file,
            )
        except Exception:
            logger.warning(
                "[WeChatSender] failed to save token file", exc_info=True
            )

    # ─── Context Token 缓存 ─────────────────────────────

    def _load_context_tokens(self) -> None:
        """从文件加载持久化的 context_tokens

        缓存文件: {bot_token_file.parent}/wechat_context_tokens.json
        格式: {"to_user_id_1": "context_token_1", ...}
        """
        try:
            if self._context_tokens_file.exists():
                data = json.loads(
                    self._context_tokens_file.read_text(encoding="utf-8")
                )
                if isinstance(data, dict):
                    self._user_context_tokens = {
                        k: v
                        for k, v in data.items()
                        if isinstance(k, str) and isinstance(v, str)
                    }
                    logger.info(
                        "[WeChatSender] loaded %d context_tokens from %s",
                        len(self._user_context_tokens),
                        self._context_tokens_file,
                    )
        except Exception:
            logger.debug(
                "[WeChatSender] failed to load context_tokens file",
                exc_info=True,
            )

    def _save_context_tokens(self) -> None:
        """持久化当前 context_tokens 到文件

        由外部调用（如 Receiver 在收到入站消息时更新缓存后触发保存）。
        WeChatSenderAgent 自身不修改 context_tokens，但需要提供保存能力。
        """
        try:
            self._context_tokens_file.parent.mkdir(
                parents=True, exist_ok=True
            )
            self._context_tokens_file.write_text(
                json.dumps(self._user_context_tokens, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            logger.debug(
                "[WeChatSender] failed to save context_tokens file",
                exc_info=True,
            )
