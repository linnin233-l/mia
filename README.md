# MIA — Modular Intelligent Agent

基于 **LLM 决策循环** 的多 Agent 对话系统，模拟人类"理解 → 检索 → 规划 → 执行 → 回复"的思考链路。

> **MIA** 不是某个特定模型的产品名，而是 **Agent 架构框架**。当前默认接入 MiMo API，支持任意 OpenAI 兼容 Provider 可插拔替换。

## 架构

```
User Input
  │
  ▼
ReceiverAgent          ── 多模态理解 (文本/图片/语音)
  │
  ▼
MemoryAgent            ── 两级知识记忆 + 对话历史注入
  │  ├─ Level 1: 每轮实时提取原子知识 (内存)
  │  └─ Level 2: 换日/compact 合并去重持久化 (磁盘)
  │
  ▼
SchedulerAgent         ── LLM 决策循环 (plan → execute → observe → reply)
  │
  ├── TaskAgent        ── 工具调用 (天气/搜索/代码执行...)
  │
  └── SenderAgent      ── 多模态输出 (文本/图片/语音)
```

## 特性

- **LLM 决策循环** — Scheduler 不断分析状态 → 派发任务 → 观察结果 → 决定回复，而非一次性生成
- **两级知识记忆** — 临时记忆 (Level 1) + 持久知识 (Level 2)，从对话中自动提炼知识点，支持跨轮关联
- **对话历史注入** — 每轮自动将最近 N 轮对话原文注入 LLM 上下文，解决指代和连续对话问题
- **可插拔 Provider** — 支持 OpenAI / MiMo / DeepSeek 或任意兼容 API，通过 `.env` 配置切换
- **消息总线架构** — Agent 间通过 MessageBus 松耦合通信，每个 Agent 独立运行在事件循环中
- **多模态输入** — 支持文本、图片 (VL)、语音 (ASR)
- **工具调用** — TaskAgent 支持天气查询、DuckDuckGo 搜索、代码执行等
- **TUI 记忆浏览器** — `/memory` 命令提供交互式知识浏览 (3 级钻取)
- **持久化存储** — 知识条目按日期分片存储，index + daily JSON 文件架构

## 快速开始

### 环境要求

- Python 3.11+
- Windows / Linux / macOS

### 安装

```bash
git clone https://github.com/linnin233/mia.git
cd mia
pip install -e ".[dev]"
```

### 配置

创建 `.env` 文件 (项目根目录):

```bash
# 主 Provider
MIMO_API_KEY=your_api_key_here

# 可选: 备选 Provider
DEEPSEEK_API_KEY=your_deepseek_key

# 可选: Agent 行为配置
MIA_MEMORY_HISTORY_TURNS=5       # 对话历史保留轮数
MIA_MEMORY_EXTRACTION_TIMEOUT=8.0 # 知识提取超时秒数
```

### 运行

```bash
# 交互模式 (推荐)
python -m mia

# 单次查询
python -m mia --query "你好，我叫linnin"

# HTTP API 服务器
python -m mia --server --port 8080

# 运行测试
python tests/test_memory_storage.py
python tests/test_memory_browser.py
```

### 交互命令

| 命令 | 说明 |
|------|------|
| 直接输入文本 | 开始一轮对话 |
| `/memory` | 打开 TUI 知识浏览器 (临时记忆 + 持久知识) |
| `/compact` | 压缩对话历史为知识摘要 |
| `/image <path>` | 发送图片 |
| `/help` | 显示帮助 |
| `/quit` | 退出 |

## 项目结构

```
mia/
├── src/mia/
│   ├── agents/           # Agent 实现
│   │   ├── receiver.py   # 多模态理解
│   │   ├── memory.py     # 两级记忆 + 对话历史
│   │   ├── scheduler.py  # LLM 决策循环
│   │   ├── task.py       # 工具调用
│   │   └── sender.py     # 多模态输出
│   ├── memory/           # 记忆子系统
│   │   ├── store.py      # 知识存储 (index + daily JSON)
│   │   ├── retriever.py  # 关键词 + LLM 混合检索
│   │   └── browser.py    # TUI 记忆浏览器
│   ├── bus/              # 消息总线
│   ├── providers/        # LLM Provider (OpenAI/MiMo/DeepSeek)
│   ├── tools/            # 工具实现 (天气/搜索/代码)
│   ├── config.py         # 配置管理 (pydantic-settings)
│   └── main.py           # 入口: CLI 交互 + HTTP 服务
├── tests/                # 测试 (11 个)
├── workspace/            # TaskAgent 工作目录
└── pyproject.toml
```

## License

MIT
