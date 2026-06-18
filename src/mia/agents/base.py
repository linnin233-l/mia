"""
BaseAgent 抽象类 — 所有 Agent 的基类

每个 Agent 都是独立的异步协程，通过 MessageBus 进行通信。
Agent 的生命周期: start() → run() 消息处理循环 → stop()
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Optional, Set

from loguru import logger

from mia.bus.bus import MessageBus
from mia.bus.message import Message, MessageType


class BaseAgent(ABC):
    """Agent 基类

    子类需要实现:
      - handle(): 处理收到的消息

    可选覆盖:
      - on_start(): 启动时的初始化逻辑
      - on_stop(): 停止时的清理逻辑
    """

    def __init__(
        self,
        name: str,
        bus: MessageBus,
    ):
        """
        Args:
            name: Agent 唯一名称 (如 'scheduler', 'receiver', 'sender', 'task_agent')
            bus: 共享的消息总线实例
        """
        self.name = name
        self.bus = bus
        self._running = False

    @property
    def running(self) -> bool:
        """是否正在运行"""
        return self._running

    async def start(self) -> None:
        """
        启动 Agent

        1. 订阅消息总线
        2. 调用 on_start() 钩子
        3. 发送 SYSTEM_READY 消息
        4. 进入消息处理循环
        """
        await self.bus.subscribe(self.name)
        self._running = True

        await self.on_start()

        # 通知其他 Agent 自己已就绪
        await self.bus.publish(Message(
            msg_type=MessageType.SYSTEM_READY,
            source=self.name,
            target="broadcast",
            payload={"agent": self.name},
        ))

        logger.info("[{}] Agent 已启动", self.name)

    async def stop(self) -> None:
        """
        停止 Agent

        1. 发送 SYSTEM_SHUTDOWN 消息
        2. 调用 on_stop() 钩子
        3. 取消订阅
        """
        if not self._running:
            return

        self._running = False

        # 通知其他 Agent
        await self.bus.publish(Message(
            msg_type=MessageType.SYSTEM_SHUTDOWN,
            source=self.name,
            target="broadcast",
            payload={"agent": self.name},
        ))

        await self.on_stop()
        await self.bus.unsubscribe(self.name)
        logger.info("[{}] Agent 已停止", self.name)

    async def send(self, msg: Message) -> bool:
        """
        发送消息到总线

        Args:
            msg: 要发送的消息 (自动设置 source 为当前 Agent)

        Returns:
            True 如果发送成功
        """
        msg.source = self.name
        return await self.bus.publish(msg)

    async def run(
        self,
        msg_types: Optional[Set[MessageType]] = None,
        poll_interval: float = 0.1,
    ) -> None:
        """
        消息处理主循环 — 不断从总线接收消息并调用 handle()

        在后台 asyncio.Task 中运行此方法即可让 Agent 持续工作。

        Args:
            msg_types: 只处理这些类型的消息 (None = 处理所有)
            poll_interval: 轮询间隔 (秒)
        """
        logger.info("[{}] 进入消息处理循环", self.name)

        while self._running:
            try:
                if msg_types:
                    msg = await self.bus.receive_filter(
                        self.name,
                        msg_types,
                        timeout=1.0,
                    )
                else:
                    msg = await self.bus.receive(self.name, timeout=1.0)

                if msg is not None:
                    await self.handle(msg)

            except asyncio.CancelledError:
                logger.info("[{}] 消息循环被取消", self.name)
                break
            except Exception as e:
                logger.error("[{}] 消息处理异常: {}", self.name, e)
                await asyncio.sleep(0.5)

        logger.info("[{}] 消息处理循环已退出", self.name)

    async def on_start(self) -> None:
        """启动钩子 — 子类可覆盖，用于初始化资源"""
        pass

    async def on_stop(self) -> None:
        """停止钩子 — 子类可覆盖，用于清理资源"""
        pass

    @abstractmethod
    async def handle(self, msg: Message) -> None:
        """
        处理收到的消息 — 子类必须实现

        Args:
            msg: 收到的消息
        """
        ...
