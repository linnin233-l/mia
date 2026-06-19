# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test

```bash
pip install -e ".[dev]"        # Install with dev deps (pytest, pytest-asyncio, etc.)

# Run all tests (2 test files, 11 test cases total)
python tests/test_memory_storage.py
python tests/test_memory_browser.py

# Run interactively
python -m mia

# Run with single query
python -m mia --query "你好"

# Start HTTP API server
python -m mia --server --port 8080
```

No linter/formatter configured yet. Python 3.11+ required. Build system: hatchling.

## Architecture

MIA is a **message-bus multi-agent system** with LLM-driven decision loops. Every `python -m mia` invocation boots 5 agents communicating through a single `MessageBus` (async pub-sub on `asyncio.Queue`).

### Message Flow (full pipeline)

```
CLI/API → ReceiverAgent → MemoryAgent → SchedulerAgent ⇄ TaskAgent → SenderAgent → Output
                                  ↑                                              │
                                  └──── CONVERSATION_DONE ───────────────────────┘
```

1. **ReceiverAgent** (`agents/receiver.py`) — accepts `RAW_INPUT`, decodes text/image/voice via MiMo VL/ASR → emits `USER_INTENT` (target="memory_agent").
2. **MemoryAgent** (`agents/memory.py`) — intercepts `USER_INTENT`, retrieves relevant knowledge + conversation history, injects `memory_context` into payload → forwards to Scheduler. Also listens for `CONVERSATION_DONE` to extract memories.
3. **SchedulerAgent** (`agents/scheduler.py`) — the core LLM loop. Receives `USER_INTENT`/`TASK_RESULT`/`TASK_ERROR`, calls LLM to decide: `reply` (emit `SEND_TEXT` or stream reply), `execute_task` (emit `EXECUTE_TASK` to TaskAgent), or `done`. Safety caps: 10 iterations, 3 consecutive tasks, 60s task timeout.
4. **TaskAgent** (`agents/task.py`) — receives `EXECUTE_TASK`, runs its own LLM+tool loop (max 5 iterations), returns `TASK_RESULT`/`TASK_ERROR`. Built-in tools: `web_search` (DuckDuckGo), `weather`, `shell`, `file`.
5. **SenderAgent** (`agents/sender.py`) — receives `SEND_TEXT`/`SEND_VOICE`/stream chunks, prints to terminal, optionally calls MiMo TTS. Emits `CONVERSATION_DONE` to both `main` and `memory_agent`.

### Two-Level Memory System (MemoryAgent)

**Level 1 — Working Memory** (in-memory, `_working_memory`): after each `CONVERSATION_DONE`, calls LLM to extract 1-3 atomic `KnowledgeEntry` items (confidence=0.5). Falls back to local extraction on timeout.

**Level 2 — Persistent Knowledge** (disk, `MemoryStore`): triggered on date change or `/compact`. LLM merges/dedupes Level 1 entries → persists with confidence ≥ 0.7.

**Conversation History** (`_conversation_history`): last N turns of user+assistant raw text injected into LLM context for pronoun resolution. Default 5 turns (`MIA_MEMORY_HISTORY_TURNS`).

### MemoryStore Storage Layout (`memory/store.py`)

Two-tier file architecture under `data/memory/`:
- `index.json` — always loaded (~1-2 KB), one `DaySummary` per day (count, keywords, category distribution, LLM-generated summary). Used for fast scan-based lookup.
- `daily/YYYY-MM-DD.json` — lazily loaded on demand, stores the actual `KnowledgeEntry` list for that day.

Two-phase retrieval: `scan_index(keywords)` → narrow to relevant dates → `load_day(date)` → keyword match + LLM rerank.

### Provider Architecture

`BaseProvider` defines `chat()`, `chat_sync()`, `chat_stream()`. Both `MiMoProvider` and `DeepSeekProvider` use `openai.AsyncOpenAI` client. Every agent with LLM access supports primary + fallback provider chaining (e.g., MiMo → DeepSeek).

### Configuration (`config.py`)

`pydantic-settings` with `.env` auto-load. Three config groups:
- `MiMoConfig` (prefix `MIMO_`) — API key, model names, auto-detects `tp-` (token plan) vs `sk-` (pay-per-use) base URLs.
- `DeepSeekConfig` (prefix `DEEPSEEK_`) — fallback provider.
- `AgentConfig` (prefix `MIA_`) — scheduler limits, memory settings, streaming toggle, verbose mode.

Singleton accessed via `get_config()`.

### Message Format (`bus/message.py`)

`MessageType` enum (19 types) + `Message` dataclass (msg_type, source, target, payload, session_id, parent_id). Factory functions (`make_user_intent`, `make_send_text`, `make_execute_task`, etc.) enforce type-safe payload construction. Streaming uses `STREAM_START` → `STREAM_CHUNK` (N times) → `STREAM_END` sequence.

### Tool Framework (`tools/base.py`)

`Tool` ABC with `name`, `description`, `parameters` (JSON Schema), and `async execute(**kwargs) → ToolResult`. TaskAgent registers tools in a `dict[name, Tool]` and passes their descriptions into the LLM prompt for tool selection.

## Key Patterns

- **Agent lifecycle**: `start()` (subscribes to bus, emits `SYSTEM_READY`) → `run()` message loop (background `asyncio.Task`) → `stop()` (emits `SYSTEM_SHUTDOWN`, unsubscribes).
- **Provider fallback**: Every LLM call tries primary → catches exception → tries fallback. Used consistently across Scheduler, TaskAgent, and MemoryAgent.
- **LLM JSON parsing**: `_parse_decision()` extracts JSON from ```json``` blocks or raw `{...}` via regex — robust to LLM formatting quirks.
- **Streaming**: Scheduler pushes text deltas via bus messages; Sender prints them immediately with `flush=True`.
- **Interactive mode input**: `input()` runs in `loop.run_in_executor(None, input, ...)` to avoid blocking the event loop (so background MemoryAgent can process concurrent messages).
- **Verbose mode**: Controlled by `MIA_VERBOSE`/`/verbose` command. All agents check `get_config().agent.verbose` before printing structured debug output.

## CLI Commands (interactive mode)

| Command | Description |
|---------|-------------|
| `/memory` | TUI knowledge browser (3-level drill-down: date → entry → detail) |
| `/compact` | Compress conversation history into knowledge summary |
| `/verbose` | Toggle detailed agent thought/steps output |
| `/image <path>` | Send image for VL analysis |
| `/help`, `/quit` | Self-explanatory |

## Env Configuration

Required: `MIMO_API_KEY` (tp-... or sk-...). Optional: `DEEPSEEK_API_KEY`, `MIA_MEMORY_HISTORY_TURNS`, `MIA_ENABLE_STREAMING`.
