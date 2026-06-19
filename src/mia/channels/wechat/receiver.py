# -*- coding: utf-8 -*-
"""WeChatReceiverAgent — 微信入站消息接收 Agent（纯接收，不处理输出）

职责（只负责入站）:
  1. 后台线程长轮询 iLink API 获取新消息
  2. SILK → WAV 转换（通过 pilk 解码）
  3. 发布 RAW_INPUT 到 MessageBus，payload 中携带 context_token 和 to_user_id

不处理任何输出/发送 — 发送由 WeChatSenderAgent 负责。

架构位置:
  微信用户  →  (iLink API)  →  WeChatReceiverAgent  →  MessageBus  →  MIA Agent 链路
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

from mia.agents.base import BaseAgent
from mia.bus.bus import MessageBus
from mia.bus.message import Message, MessageType

logger = logging.getLogger(__name__)

# ─── 常量 ──────────────────────────────────────────────

# 去重集合上限
_MAX_PROCESSED_IDS = 2000

# 内容去重时间窗口（秒）
_TEXT_DEDUP_TTL = 30.0

# 默认 token 文件路径
_DEFAULT_TOKEN_FILE = Path.home() / ".mia" / "wechat_bot_token"
_DEFAULT_CONTEXT_TOKENS_FILE = Path.home() / ".mia" / "wechat_context_tokens.json"


class WeChatReceiverAgent(BaseAgent):
    """微信入站消息接收 Agent — 纯入站，不处理输出

    通过后台线程长轮询 iLink Bot API，接收微信消息并发布 RAW_INPUT。
    只负责接收，不负责发送回复 — 发送由 WeChatSenderAgent 处理。

    Args:
        bus: MIA 消息总线
        bot_token: iLink Bot token（空字符串表示需要 QR 码登录）
        bot_token_file: Token 持久化文件路径
        base_url: iLink API 基础 URL
        enabled: 是否启用此渠道
        media_dir: 媒体文件下载目录
    """

    def __init__(
        self,
        bus: MessageBus,
        bot_token: str = "",
        bot_token_file: str = "",
        base_url: str = "",
        enabled: bool = True,
        media_dir: str = "",
    ):
        super().__init__(name="wechat_receiver", bus=bus)
        self.enabled = enabled
        self.bot_token = bot_token
        self._base_url = base_url or "https://ilinkai.weixin.qq.com"

        # Token 文件和媒体目录
        self._bot_token_file = (
            Path(bot_token_file).expanduser()
            if bot_token_file
            else _DEFAULT_TOKEN_FILE
        )
        self._context_tokens_file = (
            self._bot_token_file.parent / "wechat_context_tokens.json"
        )
        self._media_dir = (
            Path(media_dir).expanduser()
            if media_dir
            else Path.home() / ".mia" / "media"
        )

        # ILinkClient 实例（延迟创建，在 start() 中初始化）
        self._client = None  # type: Optional[ILinkClient]

        # ─── 长轮询状态 ──────────────────────────────
        self._poll_loop: Optional[asyncio.AbstractEventLoop] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._loop_accepting = threading.Event()

        # 长轮询 cursor（get_updates_buf）
        self._cursor: str = ""

        # ─── 消息去重 ────────────────────────────────
        self._processed_ids: OrderedDict[str, None] = OrderedDict()
        self._processed_ids_lock = threading.Lock()

        # 内容级去重
        self._text_dedup: OrderedDict[str, float] = OrderedDict()

        # ─── 用户状态缓存 ────────────────────────────
        # 缓存每个用户最近一次的 context_token（用于 WeChatSenderAgent 路由回复）
        self._user_context_tokens: Dict[str, str] = {}

        # 当前活跃对话的元数据（session_id → {to_user_id, context_token, ...}）
        # WeChatSenderAgent 会读取此缓存来确定回复路由
        self._active_sessions: Dict[str, Dict[str, Any]] = {}

    # ─── 生命周期 ──────────────────────────────────────

    async def on_start(self) -> None:
        """Agent 启动 — 尝试加载 token，初始化客户端，启动后台轮询"""
        if not self.enabled:
            logger.info("[WeChatReceiverAgent] 渠道已禁用，跳过初始化")
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

        # 4. 如果没有 token，执行 QR 码登录
        if not self.bot_token:
            logger.info("[WeChatReceiverAgent] 无 bot_token，启动 QR 码登录...")
            success = await self._do_qrcode_login()
            if not success:
                logger.error("[WeChatReceiverAgent] QR 码登录失败，微信渠道不可用")
                self.enabled = False
                return

        # 5. 启动后台长轮询线程
        self._start_poll_thread()
        logger.info("[WeChatReceiverAgent] 微信接收渠道已就绪 ✓")

    async def on_stop(self) -> None:
        """Agent 停止 — 关闭轮询线程和 HTTP 客户端"""
        # 通知轮询线程停止
        self._stop_event.set()
        self._loop_accepting.clear()

        # 等待轮询线程结束
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5.0)

        # 关闭 ILinkClient
        if self._client:
            await self._client.stop()
            self._client = None

        logger.info("[WeChatReceiverAgent] 微信接收渠道已停止")

    async def handle(self, msg: Message) -> None:
        """处理消息总线消息 — Receiver 不处理输出消息，仅做日志记录

        WeChatReceiverAgent 是纯入站 Agent，不负责发送回复。
        所有 SEND_TEXT / SEND_VOICE / STREAM_* 输出由 WeChatSenderAgent 处理。
        """
        if not self.enabled:
            return

        logger.debug(
            "[WeChatReceiverAgent] 收到消息但忽略（纯入站 Agent）: "
            "msg_type=%s session=%s",
            msg.msg_type.name,
            msg.session_id,
        )

    # ─── 长轮询（后台线程） ────────────────────────────

    def _start_poll_thread(self) -> None:
        """启动后台长轮询线程"""
        if self._poll_thread and self._poll_thread.is_alive():
            return

        self._stop_event.clear()
        self._loop_accepting.set()

        self._poll_thread = threading.Thread(
            target=self._run_poll_forever,
            name="wechat-poll",
            daemon=True,
        )
        self._poll_thread.start()
        logger.info("[WeChatReceiverAgent] 长轮询线程已启动")

    def _run_poll_forever(self) -> None:
        """后台线程入口：在专用 event loop 中运行长轮询"""
        if sys.platform == "darwin":
            poll_loop = asyncio.SelectorEventLoop()
        else:
            poll_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(poll_loop)
        self._poll_loop = poll_loop

        try:
            self._poll_task = poll_loop.create_task(self._poll_loop_async())
            poll_loop.run_until_complete(self._poll_task)
        except asyncio.CancelledError:
            logger.info("[WeChatReceiverAgent] 轮询任务已取消")
        except Exception:
            logger.exception("[WeChatReceiverAgent] 轮询线程异常")
        finally:
            self._poll_task = None
            try:
                pending = asyncio.all_tasks(poll_loop)
                for task in pending:
                    task.cancel()
                if pending:
                    poll_loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True),
                    )
                poll_loop.run_until_complete(poll_loop.shutdown_asyncgens())
                poll_loop.close()
            except Exception:
                pass
            self._poll_loop = None

    async def _poll_loop_async(self) -> None:
        """异步长轮询循环 — 持续调用 getupdates 获取新消息"""
        from mia.channels.wechat.client import ILinkClient

        # 为此线程创建独立的 HTTP 客户端
        client = ILinkClient(
            bot_token=self.bot_token,
            base_url=self._base_url,
        )
        await client.start()
        cursor = self._cursor

        # 断路器：连续失败指数退避
        consecutive_failures = 0
        max_backoff_seconds = 120

        try:
            while not self._stop_event.is_set():
                try:
                    data = await client.getupdates(cursor)
                    ret = data.get("ret", -1)
                    new_cursor = data.get("get_updates_buf")
                    if new_cursor is not None:
                        cursor = new_cursor
                        self._cursor = cursor

                    msgs: List[Dict[str, Any]] = data.get("msgs") or []
                    for msg in msgs:
                        await self._on_message(msg, client)

                    # 成功后重置断路器
                    consecutive_failures = 0

                    if ret != 0 and not msgs:
                        if ret == -1:
                            logger.debug(
                                "wechat getupdates timeout (ret=-1), "
                                "continue polling"
                            )
                        else:
                            logger.warning(
                                "wechat getupdates non-zero ret=%s, "
                                "retry in 3s",
                                ret,
                            )
                            await asyncio.sleep(3)

                except asyncio.CancelledError:
                    break
                except Exception:
                    consecutive_failures += 1
                    backoff = min(
                        5 * (2 ** (consecutive_failures - 1)),
                        max_backoff_seconds,
                    )
                    logger.exception(
                        "wechat poll error (%d consecutive), "
                        "retry in %ds",
                        consecutive_failures,
                        backoff,
                    )
                    if not self._stop_event.is_set():
                        await asyncio.sleep(backoff)
        finally:
            await client.stop()

    # ─── 入站消息处理 ──────────────────────────────────

    async def _on_message(
        self,
        msg: Dict[str, Any],
        client,  # ILinkClient (from poll thread)
    ) -> None:
        """解析一条微信入站消息并转发到 MIA 消息总线

        Args:
            msg: iLink getupdates 返回的原始消息字典
            client: 当前轮询线程的 ILinkClient 实例
        """
        try:
            from_user_id = msg.get("from_user_id", "")
            to_user_id = msg.get("to_user_id", "")
            context_token = msg.get("context_token", "")
            group_id = msg.get("group_id", "")
            msg_type = msg.get("message_type", 0)

            # 只处理用户→Bot 的消息（message_type == 1）
            if msg_type != 1:
                return

            # ─── 去重 ──────────────────────────────────
            dedup_key = (
                context_token
                or f"{from_user_id}_{msg.get('msg_id', '')}"
            )
            if dedup_key and self._is_duplicate(dedup_key):
                logger.debug(
                    "wechat: duplicate message skipped: %s",
                    dedup_key[:40],
                )
                return

            # 内容级去重
            raw_text = "".join(
                (item.get("text_item") or {}).get("text", "")
                for item in (msg.get("item_list") or [])
                if item.get("type", 0) == 1
            ).strip()
            if raw_text and self._is_text_duplicate(from_user_id, raw_text):
                logger.debug(
                    "wechat: content-duplicate message skipped: "
                    "user=%s text_len=%d",
                    from_user_id[:12],
                    len(raw_text),
                )
                return

            # ─── 解析消息内容 ──────────────────────────
            text_parts: List[str] = []
            image_paths: List[str] = []
            voice_paths: List[str] = []  # 下载的语音文件路径

            item_list: List[Dict[str, Any]] = msg.get("item_list") or []
            for item in item_list:
                item_type = item.get("type", 0)

                if item_type == 1:  # 文本
                    text = (
                        (item.get("text_item") or {})
                        .get("text", "")
                        .strip()
                    )
                    # 过滤掉纯文件名（避免文件消息触发误回复）
                    if text and not self._looks_like_filename(text):
                        text_parts.append(text)

                elif item_type == 2:  # 图片
                    img_item = item.get("image_item") or {}
                    media = img_item.get("media") or {}
                    encrypt_query_param = media.get(
                        "encrypt_query_param", ""
                    )
                    aeskey_hex = img_item.get("aeskey", "")
                    if aeskey_hex:
                        import base64 as _b64
                        aes_key = _b64.b64encode(
                            bytes.fromhex(aeskey_hex)
                        ).decode()
                    else:
                        aes_key = media.get("aes_key", "")

                    if encrypt_query_param:
                        path = await self._download_media(
                            client,
                            aes_key,
                            "image.jpg",
                            encrypt_query_param=encrypt_query_param,
                        )
                        if path:
                            image_paths.append(path)
                        else:
                            text_parts.append("[图片下载失败]")
                    else:
                        text_parts.append("[图片: 无下载链接]")

                elif item_type == 3:  # 语音
                    voice_item = item.get("voice_item") or {}
                    # ─── ASR 转写文本（iLink 自动提供） ──
                    asr_text = (
                        voice_item.get("text_item", {}).get("text", "")
                        .strip()
                        if isinstance(
                            voice_item.get("text_item"), dict
                        )
                        else voice_item.get("text", "").strip()
                    )
                    if asr_text:
                        text_parts.append(asr_text)

                    # ─── 下载原始音频（用于多模态理解） ──
                    media = voice_item.get("media") or {}
                    encrypt_query_param = media.get(
                        "encrypt_query_param", ""
                    )
                    aes_key = media.get("aes_key", "")
                    if encrypt_query_param:
                        audio_path = await self._download_media(
                            client,
                            aes_key,
                            "voice.silk",  # iLink 语音是 SILK 编码
                            encrypt_query_param=encrypt_query_param,
                        )
                        if audio_path:
                            # ─── SILK → WAV 转码 ──────────
                            converted = await self._convert_to_wav(audio_path)
                            if converted:
                                voice_paths.append(converted)
                                logger.info(
                                    "[WeChatReceiverAgent] 语音已转为 WAV: %s",
                                    converted,
                                )
                            else:
                                logger.warning(
                                    "[WeChatReceiverAgent] SILK 转码失败，"
                                    "仅使用 ASR 文本"
                                )
                    if not asr_text and not voice_paths:
                        text_parts.append("[语音: 无转写]")

                elif item_type == 4:  # 文件
                    file_item = item.get("file_item") or {}
                    filename = (
                        file_item.get("file_name", "file.bin")
                        or "file.bin"
                    )
                    text_parts.append(f"[收到文件: {filename}]")

                elif item_type == 5:  # 视频
                    text_parts.append("[收到视频]")

                # 处理引用消息（回复某条消息）
                ref_msg = item.get("ref_msg")
                if ref_msg:
                    quoted_text = self._extract_quoted_text(ref_msg)
                    if quoted_text:
                        text_parts.insert(
                            0, f"[引用消息: {quoted_text}]"
                        )

            # ─── 构建用户输入 ──────────────────────────
            text = "\n".join(text_parts).strip()
            if not text and not image_paths and not voice_paths:
                return

            # 生成 session_id
            is_group = bool(group_id)
            if is_group:
                session_id = f"wechat:group:{group_id}"
            else:
                session_id = f"wechat:{from_user_id}" if from_user_id else ""

            # 保存活跃会话元数据（用于 WeChatSenderAgent 后续回复路由）
            if from_user_id and context_token:
                self._active_sessions[session_id] = {
                    "to_user_id": from_user_id,
                    "context_token": context_token,
                    "is_group": is_group,
                    "group_id": group_id,
                }
                # 同时更新用户级 context_token 缓存
                self._user_context_tokens[from_user_id] = context_token
                self._save_context_tokens()

            # ─── 发布 RAW_INPUT 到消息总线 ─────────────
            if text:
                user_input = text
            elif image_paths:
                user_input = "请分析这张图片"
            elif voice_paths:
                user_input = ""  # 纯语音 — ReceiverAgent 会做多模态理解
            else:
                user_input = ""

            logger.info(
                "wechat recv: from=%s group=%s text_len=%s images=%d voice=%d",
                (from_user_id or "")[:20],
                (group_id or "")[:20],
                len(text),
                len(image_paths),
                len(voice_paths),
            )

            # 将消息转发到主事件循环（跨线程安全）
            self._dispatch_to_main_loop(
                self._publish_raw_input(
                    user_input=user_input,
                    image_paths=image_paths,
                    voice_paths=voice_paths,
                    session_id=session_id,
                    context_token=context_token,
                    to_user_id=from_user_id,
                ),
                description=f"publish RAW_INPUT for {session_id}",
            )

        except Exception:
            logger.exception("[WeChatReceiverAgent] _on_message 失败")

    async def _publish_raw_input(
        self,
        user_input: str,
        image_paths: List[str],
        voice_paths: List[str],
        session_id: str,
        context_token: str,
        to_user_id: str,
    ) -> None:
        """在主事件循环中发布 RAW_INPUT 消息到总线

        payload 中携带 context_token 和 to_user_id，
        供 WeChatSenderAgent 在收到回复时路由到正确的微信用户。

        Args:
            user_input: 用户文本输入
            image_paths: 图片文件路径列表
            voice_paths: 语音文件路径列表
            session_id: MIA 会话 ID
            context_token: iLink API context_token（用于发送回复）
            to_user_id: 发送者微信用户 ID（用于回复路由）
        """
        payload: Dict[str, Any] = {
            "text": user_input,
            "source": "wechat",
            "context_token": context_token,
            "to_user_id": to_user_id,
        }

        if image_paths:
            payload["image"] = image_paths[0]

        if voice_paths:
            payload["voice"] = voice_paths[0]

        raw_msg = Message(
            msg_type=MessageType.RAW_INPUT,
            source="wechat",
            target="receiver",
            payload=payload,
            session_id=session_id,
        )
        await self.bus.publish(raw_msg)

        voice_hint = (
            f" + 语音({voice_paths[0][-30:]})"
            if voice_paths else ""
        )
        print(
            f"\033[32m[WeChat]\033[0m 收到消息 → "
            f"\033[90m{user_input[:80]}{voice_hint}\033[0m"
        )

    # ─── QR 码登录 ─────────────────────────────────────

    async def _do_qrcode_login(self) -> bool:
        """执行 QR 码扫码登录流程"""
        if not self._client:
            return False

        try:
            qr_data = await self._client.get_bot_qrcode()
            qrcode = qr_data.get("qrcode", "")
            qrcode_url = qr_data.get("url") or qr_data.get(
                "qrcode_img_content", ""
            )

            print()
            print(f"\033[1;33m{'='*50}\033[0m")
            print(f"\033[1;33m  MIA 微信登录 — 请扫描下方二维码\033[0m")
            print(f"\033[1;33m{'='*50}\033[0m")
            print()
            print(f"  QR 码 URL: {qrcode_url or '(见 debug 日志)'}")
            print()
            print(f"  \033[90m等待扫码中... (最长 300 秒)\033[0m")

            logger.info(
                "wechat: waiting for QR code scan (up to 300s)…"
            )

            token, base_url = await self._client.wait_for_login(qrcode)
            self.bot_token = token
            self._client.bot_token = token

            if base_url and base_url != self._client.base_url:
                self._client.base_url = base_url.rstrip("/")
                self._base_url = base_url.rstrip("/")

            self._save_token_to_file(token)
            print(f"  \033[32m[OK]\033[0m 微信登录成功！")
            print()

            logger.info("wechat: QR code login succeeded")
            return True

        except Exception:
            logger.exception("wechat: QR code login failed")
            print(f"  \033[31m[FAIL]\033[0m 微信登录失败，请重试")
            print()
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
                        "wechat: loaded bot_token from %s",
                        self._bot_token_file,
                    )
                    return token
        except Exception:
            logger.debug(
                "wechat: failed to read token file", exc_info=True
            )
        return ""

    def _save_token_to_file(self, token: str) -> None:
        """持久化 bot_token 到文件"""
        try:
            self._bot_token_file.parent.mkdir(parents=True, exist_ok=True)
            self._bot_token_file.write_text(token, encoding="utf-8")
            logger.info(
                "wechat: bot_token saved to %s", self._bot_token_file
            )
        except Exception:
            logger.warning(
                "wechat: failed to save token file", exc_info=True
            )

    def _load_context_tokens(self) -> None:
        """从文件加载持久化的 context_tokens"""
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
                        "wechat: loaded %d context_tokens from %s",
                        len(self._user_context_tokens),
                        self._context_tokens_file,
                    )
        except Exception:
            logger.debug(
                "wechat: failed to load context_tokens file",
                exc_info=True,
            )

    def _save_context_tokens(self) -> None:
        """持久化当前 context_tokens 到文件"""
        try:
            self._context_tokens_file.parent.mkdir(
                parents=True, exist_ok=True
            )
            self._context_tokens_file.write_text(
                json.dumps(
                    self._user_context_tokens, ensure_ascii=False
                ),
                encoding="utf-8",
            )
        except Exception:
            logger.debug(
                "wechat: failed to save context_tokens file",
                exc_info=True,
            )

    # ─── 消息去重 ──────────────────────────────────────

    def _is_duplicate(self, msg_id: str) -> bool:
        """ID 级去重 — 防止同一消息被重复处理"""
        with self._processed_ids_lock:
            if msg_id in self._processed_ids:
                return True
            self._processed_ids[msg_id] = None
            while len(self._processed_ids) > _MAX_PROCESSED_IDS:
                self._processed_ids.popitem(last=False)
        return False

    def _is_text_duplicate(
        self, from_user_id: str, text: str
    ) -> bool:
        """内容级去重 — 捕捉跨 poll 的重复消息"""
        import hashlib
        import time

        content_hash = hashlib.md5(text.encode()).hexdigest()[:16]
        key = f"{from_user_id}:{content_hash}"
        now = time.time()
        with self._processed_ids_lock:
            prev_time = self._text_dedup.get(key)
            if (
                prev_time is not None
                and now - prev_time < _TEXT_DEDUP_TTL
            ):
                return True
            self._text_dedup[key] = now
            while len(self._text_dedup) > _MAX_PROCESSED_IDS:
                self._text_dedup.popitem(last=False)
        return False

    # ─── 媒体下载 ──────────────────────────────────────

    async def _download_media(
        self,
        client,  # ILinkClient
        aes_key: str = "",
        filename_hint: str = "file.bin",
        encrypt_query_param: str = "",
    ) -> Optional[str]:
        """下载并解密 CDN 媒体文件"""
        import hashlib

        try:
            data = await client.download_media(
                "", aes_key, encrypt_query_param
            )
            self._media_dir.mkdir(parents=True, exist_ok=True)
            safe_name = (
                "".join(
                    c
                    for c in filename_hint
                    if c.isalnum() or c in "-_."
                )
                or "media"
            )
            url_hash = hashlib.md5(
                encrypt_query_param.encode()
            ).hexdigest()[:8]
            path = self._media_dir / f"wechat_{url_hash}_{safe_name}"
            path.write_bytes(data)
            return str(path)
        except Exception:
            logger.exception(
                "wechat _download_media failed"
            )
            return None

    # ─── SILK → WAV 转码 ────────────────────────────

    async def _convert_to_wav(self, file_path: str) -> Optional[str]:
        """将微信 SILK 音频转为 WAV 格式

        使用 pilk (Python SILK 解码器) 解码为 PCM，再封装 WAV 容器。
        与官方 openclaw-weixin 插件 silk-wasm 方案一致。
        """
        silk_path = Path(file_path)
        if not silk_path.exists():
            return None

        try:
            raw = silk_path.read_bytes()
            head = raw[:16]
            if not (b"SILK" in head or b"#!SILK" in head):
                return file_path  # 非 SILK，直接返回
        except Exception:
            return None

        # 剥离 WeChat 0x02 前缀
        if raw[0:1] == b"\x02" and raw[1:10] == b"#!SILK_V3":
            silk_data = raw[1:]
        else:
            silk_data = raw

        try:
            import pilk

            # pilk.decode(src_path, dst_path) → 写入 PCM
            temp_silk_path = silk_path.with_suffix(".silk.tmp")
            temp_silk_path.write_bytes(silk_data)

            pcm_path = silk_path.with_suffix(".pcm")
            try:
                duration_s = pilk.decode(str(temp_silk_path), str(pcm_path))
            finally:
                try:
                    temp_silk_path.unlink(missing_ok=True)
                except Exception:
                    pass

            pcm = pcm_path.read_bytes()
            pcm_path.unlink(missing_ok=True)

            # 封装 WAV 容器
            sample_rate = 24000; channels = 1; bps = 16
            byte_rate = sample_rate * channels * bps // 8
            block_align = channels * bps // 8
            data_size = len(pcm)

            wav = bytearray(44 + data_size)
            wav[0:4] = b"RIFF"
            wav[4:8] = (36 + data_size).to_bytes(4, "little")
            wav[8:12] = b"WAVE"
            wav[12:16] = b"fmt "
            wav[16:20] = (16).to_bytes(4, "little")
            wav[20:22] = (1).to_bytes(2, "little")
            wav[22:24] = channels.to_bytes(2, "little")
            wav[24:28] = sample_rate.to_bytes(4, "little")
            wav[28:32] = byte_rate.to_bytes(4, "little")
            wav[32:34] = block_align.to_bytes(2, "little")
            wav[34:36] = bps.to_bytes(2, "little")
            wav[36:40] = b"data"
            wav[40:44] = data_size.to_bytes(4, "little")
            wav[44:] = pcm

            wav_path = silk_path.with_suffix(".wav")
            wav_path.write_bytes(bytes(wav))

            logger.info(
                "[WeChatReceiverAgent] SILK→WAV: %s → %s (%d bytes, %.1fs)",
                silk_path.name, wav_path.name,
                len(wav), float(duration_s or 0) / 1000,
            )
            try:
                silk_path.unlink(missing_ok=True)
            except Exception:
                pass
            return str(wav_path)

        except ImportError:
            logger.warning("[WeChatReceiverAgent] pilk 未安装，pip install pilk")
        except Exception as e:
            logger.warning("[WeChatReceiverAgent] pilk 解码失败: %s", e)

        return None

    # ─── 跨线程调度 ────────────────────────────────────

    def _dispatch_to_main_loop(
        self,
        coro,
        *,
        description: str = "",
    ) -> bool:
        """将协程安全地调度到主事件循环（从轮询线程调用）"""
        if not self._loop_accepting.is_set():
            logger.debug(
                "wechat: skipping dispatch (loop not accepting): %s",
                description,
            )
            coro.close()
            return False

        loop = asyncio.get_event_loop()
        if loop.is_closed():
            coro.close()
            return False

        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
            return True
        except RuntimeError:
            logger.debug(
                "wechat: dispatch failed (loop stopped): %s",
                description,
            )
            coro.close()
            return False

    # ─── 辅助方法 ──────────────────────────────────────

    @staticmethod
    def _looks_like_filename(text: str) -> bool:
        """检查文本是否看起来像纯文件名"""
        common_extensions = (
            ".txt", ".doc", ".docx", ".pdf", ".jpg", ".jpeg",
            ".png", ".gif", ".mp4", ".avi", ".mov", ".mp3",
            ".wav", ".zip", ".rar", ".xlsx", ".xls", ".ppt", ".pptx",
        )
        text_lower = text.lower().strip()
        return any(text_lower.endswith(ext) for ext in common_extensions)

    @staticmethod
    def _extract_quoted_text(ref_msg: Dict[str, Any]) -> str:
        """从引用消息中提取文本内容"""
        quoted_item = ref_msg.get("message_item") or {}
        quoted_type = quoted_item.get("type", 0)

        if quoted_type == 1:
            return (
                (quoted_item.get("text_item") or {})
                .get("text", "").strip()
            )
        elif quoted_type == 3:
            voice_item = quoted_item.get("voice_item") or {}
            return (
                voice_item.get("text_item", {}).get("text", "").strip()
                if isinstance(voice_item.get("text_item"), dict)
                else voice_item.get("text", "").strip()
            )
        elif quoted_type == 4:
            file_item = quoted_item.get("file_item") or {}
            filename = file_item.get("file_name", "") or ""
            return f"[文件: {filename}]" if filename else "[文件]"
        elif quoted_type == 2:
            return "[图片]"
        elif quoted_type == 5:
            return "[视频]"

        return ""
