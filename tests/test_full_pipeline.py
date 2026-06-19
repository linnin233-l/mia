"""
MIA 全流程测试用例

涵盖: CLI文本/语音、记忆持久化、工具调用(天气/搜索)、流式输出、语音回复
用法: python tests/test_full_pipeline.py
"""

import asyncio
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root / "src"))

from mia.config import get_config, Config
from mia.bus.bus import MessageBus
from mia.bus.message import Message, MessageType
from mia.providers.mimo import MiMoProvider
from mia.providers.deepseek import DeepSeekProvider
from mia.agents.receiver import ReceiverAgent
from mia.agents.scheduler import SchedulerAgent
from mia.agents.sender import SenderAgent
from mia.agents.task import TaskAgent
from mia.agents.memory import MemoryAgent

# ─── 测试结果收集 ──────────────────────────────────────

results: list[dict] = []


def record(test_name: str, passed: bool, detail: str = ""):
    status = "\033[32mPASS\033[0m" if passed else "\033[31mFAIL\033[0m"
    print(f"  [{status}] {test_name}")
    if detail and not passed:
        print(f"         \033[90m{detail}\033[0m")
    results.append({"name": test_name, "passed": passed, "detail": detail})


async def run_pipeline_query(
    bus: MessageBus,
    agents: dict,
    query: str,
    image_path: str = "",
    voice_path: str = "",
    timeout: float = 120.0,
) -> str:
    """运行一次完整的 Agent 链路并返回回复文本"""
    import uuid
    session_id = uuid.uuid4().hex[:12]

    # 注入 RAW_INPUT
    payload: dict = {"text": query}
    if image_path:
        payload["image"] = image_path
    if voice_path:
        payload["voice"] = voice_path

    raw_msg = Message(
        msg_type=MessageType.RAW_INPUT,
        source="test",
        target="receiver",
        payload=payload,
        session_id=session_id,
    )
    await bus.publish(raw_msg)

    # 等待 CONVERSATION_DONE
    await bus.subscribe("test")
    final_response = ""
    remaining = timeout

    while remaining > 0:
        msg = await bus.receive("test", timeout=1.0)
        remaining -= 1.0
        if msg is None:
            continue
        if msg.msg_type == MessageType.CONVERSATION_DONE:
            final_response = msg.payload.get("message", "")
            break
        if msg.msg_type == MessageType.TASK_ERROR:
            print(f"         \033[33m[TaskError]\033[0m {msg.payload.get('error', '')[:100]}")

    await bus.unsubscribe("test")
    return final_response


async def main():
    print("\033[1m" + "=" * 60 + "\033[0m")
    print("\033[1m  MIA 全流程测试\033[0m")
    print("\033[1m" + "=" * 60 + "\033[0m")
    print()

    config = get_config()
    if not config.mimo.api_key:
        print("\033[33m跳过: 未配置 MIMO_API_KEY\033[0m")
        return

    # ─── 1. 启动系统 ───────────────────────────────────
    print("\033[36m── 初始化系统 ──\033[0m")
    bus = MessageBus(max_queue_size=100)
    await bus.start()

    # 总线记忆镜像
    mirror_types = [
        MessageType.USER_INTENT,
        MessageType.SEND_TEXT,
        MessageType.STREAM_END,
        MessageType.EXECUTE_TASK,
        MessageType.TASK_RESULT,
        MessageType.TASK_ERROR,
        MessageType.CONVERSATION_DONE,
    ]
    for mt in mirror_types:
        bus.subscribe_mirror(mt, "memory_agent")

    mimo = MiMoProvider(api_key=config.mimo.api_key)
    deepseek = DeepSeekProvider(api_key=config.deepseek.api_key)

    agents = {
        "receiver": ReceiverAgent(bus=bus, mimo=mimo),
        "memory": MemoryAgent(
            bus=bus, provider=mimo, model=config.mimo.chat_model,
            fallback_provider=deepseek, fallback_model=config.deepseek.chat_model,
        ),
        "scheduler": SchedulerAgent(
            bus=bus, provider=mimo, model=config.mimo.chat_model,
            fallback_provider=deepseek, fallback_model=config.deepseek.chat_model,
            enable_streaming=config.agent.enable_streaming,
        ),
        "sender": SenderAgent(bus=bus, mimo=mimo, output_dir=config.agent.workspace_dir),
        "task": TaskAgent(
            bus=bus, provider=mimo, model=config.mimo.chat_model,
            fallback_provider=deepseek, fallback_model=config.deepseek.chat_model,
        ),
    }

    for agent in agents.values():
        await agent.start()

    tasks = [asyncio.create_task(a.run()) for a in agents.values()]
    await asyncio.sleep(0.3)
    print("  \033[32m系统就绪\033[0m")
    print()

    try:
        # ═══════════════════════════════════════════════════
        # 测试 1: 基础文本对话
        # ═══════════════════════════════════════════════════
        print("\033[1;33m── 测试 1: 基础文本对话 ──\033[0m")
        resp = await run_pipeline_query(bus, agents, "你好，我是linnin233，请记住我的名字")
        record("1.1 收到回复", len(resp) > 10, f"回复长度: {len(resp)}")
        record("1.2 包含用户名字", "linnin233" in resp, resp[:100])
        print(f"     \033[90m回复: {resp[:120]}...\033[0m")

        # ═══════════════════════════════════════════════════
        # 测试 2: 记忆功能 — 跨轮对话
        # ═══════════════════════════════════════════════════
        print()
        print("\033[1;33m── 测试 2: 跨轮记忆 ──\033[0m")
        resp2 = await run_pipeline_query(bus, agents, "我叫什么名字？")
        record("2.1 收到回复", len(resp2) > 5, f"回复长度: {len(resp2)}")
        record("2.2 回忆出用户名", "linnin233" in resp2 or "linnin" in resp2.lower(), resp2[:120])
        print(f"     \033[90m回复: {resp2[:120]}...\033[0m")

        # ═══════════════════════════════════════════════════
        # 测试 3: 工具调用 — 天气查询
        # ═══════════════════════════════════════════════════
        print()
        print("\033[1;33m── 测试 3: 天气查询 (TaskAgent) ──\033[0m")
        resp3 = await run_pipeline_query(bus, agents, "查询一下北京明天的天气")
        record("3.1 收到回复", len(resp3) > 10, f"回复长度: {len(resp3)}")
        has_weather = any(kw in resp3 for kw in ["温度", "天气", "度", "°", "风", "雨", "晴", "℃"])
        record("3.2 包含天气信息", has_weather, resp3[:120])
        print(f"     \033[90m回复: {resp3[:150]}...\033[0m")

        # ═══════════════════════════════════════════════════
        # 测试 4: 工具调用 — 网络搜索
        # ═══════════════════════════════════════════════════
        print()
        print("\033[1;33m── 测试 4: 网络搜索 (TaskAgent) ──\033[0m")
        resp4 = await run_pipeline_query(bus, agents, "搜索一下今天的Python最新新闻")
        record("4.1 收到回复", len(resp4) > 20, f"回复长度: {len(resp4)}")
        has_content = len(resp4) > 30  # 搜索结果应该有些内容
        record("4.2 回复有实质内容", has_content, resp4[:120])
        print(f"     \033[90m回复: {resp4[:150]}...\033[0m")

        # ═══════════════════════════════════════════════════
        # 测试 5: 对话历史 — 再问天气验证记忆
        # ═══════════════════════════════════════════════════
        print()
        print("\033[1;33m── 测试 5: 对话历史注入 ──\033[0m")
        resp5 = await run_pipeline_query(bus, agents, "刚才我查过哪两个城市的天气？如果只有一个，告诉我是哪个")
        record("5.1 收到回复", len(resp5) > 10, f"回复长度: {len(resp5)}")
        # 应该提到北京(第一轮查的)
        record("5.2 提及北京", "北京" in resp5, resp5[:120])
        print(f"     \033[90m回复: {resp5[:150]}...\033[0m")

        # ═══════════════════════════════════════════════════
        # 测试 6: 文字回复
        # ═══════════════════════════════════════════════════
        print()
        print("\033[1;33m── 测试 6: 闲聊 ──\033[0m")
        resp6 = await run_pipeline_query(bus, agents, "讲个简短的笑话")
        record("6.1 收到回复", len(resp6) > 10, f"回复长度: {len(resp6)}")
        print(f"     \033[90m回复: {resp6[:120]}...\033[0m")

        # 等待 MemoryAgent 处理所有 CONVERSATION_DONE
        await asyncio.sleep(2)

    finally:
        # ─── 清理 ─────────────────────────────────────
        print()
        print("\033[36m── 清理系统 ──\033[0m")
        for agent in agents.values():
            await agent.stop()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await bus.stop()

    # ─── 汇总 ─────────────────────────────────────────
    print()
    print("\033[1m" + "=" * 60 + "\033[0m")
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    color = "\033[32m" if passed == total else "\033[31m"
    print(f"\033[1m  结果: {color}{passed}/{total} 通过\033[0m")
    print("\033[1m" + "=" * 60 + "\033[0m")

    if passed < total:
        print()
        print("\033[33m失败用例:\033[0m")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail'][:100]}")

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
