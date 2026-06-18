"""
MessageBus — 异步消息总线

所有 Agent 通过 MessageBus 进行通信，不直接相互调用。
基于 asyncio.Queue 实现发布-订阅模式。

特性:
  - 支持定向消息 (target 指定) 和广播 (target='broadcast')
  - 每个 Agent 有独立的订阅队列
  - 非阻塞发送，队列满时丢弃旧消息
  - 支持优雅关闭
"""

import asyncio
from collections import defaultdict
from typing import Optional, Set

from loguru import logger

from mia.bus.message import Message, MessageType


class MessageBus:
    """异步消息总线

    用法:
        bus = MessageBus(max_queue_size=100)
        await bus.subscribe("scheduler")
        await bus.publish(message)
        msg = await bus.receive("scheduler", timeout=30)
    """

    def __init__(self, max_queue_size: int = 100):
        """
        Args:
            max_queue_size: 每个订阅者的最大队列长度
        """
        self._queues: dict[str, asyncio.Queue] = {}
        self._subscribers: Set[str] = set()
        self._max_queue_size = max_queue_size
        self._running = False
        logger.info("MessageBus 初始化, max_queue_size={}", max_queue_size)

    async def subscribe(self, name: str) -> None:
        """
        订阅消息

        Args:
            name: 订阅者名称 (如 'scheduler', 'receiver', 'task_agent')
        """
        if name not in self._queues:
            self._queues[name] = asyncio.Queue(maxsize=self._max_queue_size)
            self._subscribers.add(name)
            logger.info("MessageBus: {} 已订阅", name)

    async def unsubscribe(self, name: str) -> None:
        """取消订阅"""
        if name in self._queues:
            del self._queues[name]
            self._subscribers.discard(name)
            logger.info("MessageBus: {} 已取消订阅", name)

    async def publish(self, msg: Message) -> bool:
        """
        发布消息到总线

        定向消息 (target != 'broadcast'): 只投递到目标订阅者
        广播消息 (target == 'broadcast'): 投递到所有订阅者

        Args:
            msg: 要发布的消息

        Returns:
            True 如果至少投递到一个订阅者
        """
        if not self._running:
            logger.warning("MessageBus 未运行，消息丢弃: {}", msg)
            return False

        delivered = False

        if msg.target == "broadcast":
            # 广播到所有订阅者
            for name, queue in self._queues.items():
                if name != msg.source:  # 不发给发送方自己
                    delivered |= await self._put_safe(queue, msg, name)
        else:
            # 定向投递
            queue = self._queues.get(msg.target)
            if queue:
                delivered = await self._put_safe(queue, msg, msg.target)
            else:
                logger.warning(
                    "MessageBus: 目标 '{}' 未订阅，消息丢弃: {}",
                    msg.target, msg,
                )

        return delivered

    async def receive(
        self,
        name: str,
        timeout: Optional[float] = None,
    ) -> Optional[Message]:
        """
        接收消息 (阻塞等待)

        Args:
            name: 接收者名称
            timeout: 超时秒数 (None 表示无限等待)

        Returns:
            收到的消息，超时返回 None
        """
        queue = self._queues.get(name)
        if not queue:
            logger.warning("MessageBus: '{}' 未订阅，无法接收", name)
            return None

        try:
            if timeout is not None:
                return await asyncio.wait_for(queue.get(), timeout=timeout)
            return await queue.get()
        except asyncio.TimeoutError:
            return None

    async def receive_filter(
        self,
        name: str,
        msg_types: set[MessageType],
        timeout: Optional[float] = None,
    ) -> Optional[Message]:
        """
        接收消息 — 只接收指定类型的消息，其他消息放回队列

        Args:
            name: 接收者名称
            msg_types: 要接收的消息类型集合
            timeout: 超时秒数

        Returns:
            匹配的消息，超时返回 None
        """
        queue = self._queues.get(name)
        if not queue:
            return None

        deadline = None if timeout is None else asyncio.get_event_loop().time() + timeout
        skipped: list[Message] = []

        while True:
            remaining = None if deadline is None else deadline - asyncio.get_event_loop().time()
            if remaining is not None and remaining <= 0:
                # 超时，把跳过的消息放回
                for m in skipped:
                    await queue.put(m)
                return None

            try:
                if remaining is not None:
                    msg = await asyncio.wait_for(queue.get(), timeout=remaining)
                else:
                    msg = await queue.get()
            except asyncio.TimeoutError:
                for m in skipped:
                    await queue.put(m)
                return None

            if msg.msg_type in msg_types:
                # 找到匹配的消息，先放回跳过的消息
                for m in skipped:
                    await queue.put(m)
                return msg
            else:
                # 不匹配，暂存
                skipped.append(msg)

    async def start(self) -> None:
        """启动总线"""
        self._running = True
        logger.info("MessageBus 已启动")

    async def stop(self) -> None:
        """停止总线 — 清空所有队列"""
        self._running = False
        for name, queue in self._queues.items():
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        logger.info("MessageBus 已停止")

    async def _put_safe(
        self,
        queue: asyncio.Queue,
        msg: Message,
        subscriber: str,
    ) -> bool:
        """
        安全投递 — 队列满时丢弃旧消息

        Returns:
            True 如果投递成功
        """
        try:
            queue.put_nowait(msg)
            return True
        except asyncio.QueueFull:
            # 丢弃最旧的消息，放入新消息
            try:
                old = queue.get_nowait()
                logger.warning(
                    "MessageBus: {} 队列已满，丢弃旧消息: {}",
                    subscriber, old,
                )
                queue.put_nowait(msg)
                return True
            except (asyncio.QueueFull, asyncio.QueueEmpty):
                logger.error(
                    "MessageBus: {} 队列异常，消息丢失: {}",
                    subscriber, msg,
                )
                return False
