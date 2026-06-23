/**
 * MIA Ink TUI — 主 App 组件（重构版）
 *
 * 修复:
 *   1. Agent 输出通过 bridge → dispatch → Ink 渲染（不再冲破布局）
 *   2. 本地命令 (/help /memory /clear /quit) 在 TUI 内拦截
 *   3. Static key 警告已修复
 */

import React, { useReducer, useCallback, useEffect, useState, useRef } from 'react';
import { Box, Text, useInput } from 'ink';
import { Header } from './components/Header.js';
import { ChatPanel } from './components/ChatPanel.js';
import { ThinkingPanel } from './components/ThinkingPanel.js';
import { ToolsPanel } from './components/ToolsPanel.js';
import { MemoryPanel } from './components/MemoryPanel.js';
import { InputBar } from './components/InputBar.js';
import { tuiReducer, createInitialState } from './store.js';
import type { MemoryAgent } from '../agents/memory.js';
import {
  handleModelCommand,
  handleAgentCommand,
  handleChannelCommand,
} from '../cli/commands.js';
import { getConfig } from '../config.js';
import type { MemoryEntry } from './types.js';

// ─── Bridge 接口 ────────────────────────────────────────

export interface TuiBridge {
  onUserMessage: (text: string) => void;
  onStreamStart: () => void;
  onStreamChunk: (delta: string) => void;
  onStreamEnd: (fullText: string) => void;
  onSendText: (text: string) => void;
  onThought: (agent: string, title: string, detail: string) => void;
}

// ─── Props ──────────────────────────────────────────────

interface AppProps {
  memoryAgent: MemoryAgent | null;
  bridge: TuiBridge;
  onSubmit: (text: string) => void;
  onQuit: () => void;
}

// ─── 本地帮助文本 ───────────────────────────────────────

const HELP_TEXT = `MIA TUI 命令:
  /help, /h     — 显示此帮助
  /quit, /q     — 退出
  /memory       — 全屏记忆浏览器
  /clear        — 清空对话
  /thinking     — 切换思考面板
  /tools        — 切换工具面板
  /verbose      — 切换详细输出

快捷键:
  Tab           — 切换右侧面板焦点
  1/2/3         — 折叠 Thinking/Tools/Memory 面板
  Esc           — 从全屏模式返回
  Ctrl+C        — 退出`;

/** 本地命令列表（不发送给 Agent） */
const ALL_COMMANDS: Record<
  string,
  {
    handler: (ctx: {
      dispatch: React.Dispatch<import('./store.js').TuiAction>;
      memoryAgent: MemoryAgent | null;
      onQuit: () => void;
      text: string;
    }) => void;
    desc: string;
  }
> = {
  '/help': {
    desc: '显示帮助',
    handler: ({ dispatch }) => {
      dispatch({
        type: 'ADD_USER_MESSAGE',
        content: '/help',
        id: Date.now().toString(16),
      });
      dispatch({ type: 'FINISH_STREAMING', content: HELP_TEXT });
    },
  },
  '/h': {
    desc: '显示帮助',
    handler: ({ dispatch }) => {
      dispatch({
        type: 'ADD_USER_MESSAGE',
        content: '/h',
        id: Date.now().toString(16),
      });
      dispatch({ type: 'FINISH_STREAMING', content: HELP_TEXT });
    },
  },
  '/quit': { desc: '退出', handler: ({ onQuit }) => onQuit() },
  '/q': { desc: '退出', handler: ({ onQuit }) => onQuit() },
  '/exit': { desc: '退出', handler: ({ onQuit }) => onQuit() },
  '/memory': {
    desc: '记忆浏览器',
    handler: ({ dispatch }) => {
      dispatch({ type: 'SET_FULLSCREEN', mode: 'memory' });
    },
  },
  '/clear': {
    desc: '清空对话',
    handler: ({ dispatch }) => dispatch({ type: 'CLEAR_CHAT' }),
  },
  '/thinking': {
    desc: '切换思考面板',
    handler: ({ dispatch }) =>
      dispatch({ type: 'TOGGLE_PANEL', panel: 'thinking' }),
  },
  '/tools': {
    desc: '切换工具面板',
    handler: ({ dispatch }) =>
      dispatch({ type: 'TOGGLE_PANEL', panel: 'tools' }),
  },
  '/verbose': {
    desc: '切换详细输出',
    handler: ({ dispatch }) => {
      const cfg = getConfig();
      cfg.agent.verbose = !cfg.agent.verbose;
      dispatch({
        type: 'FINISH_STREAMING',
        content: `Verbose 模式已${cfg.agent.verbose ? '开启' : '关闭'}`,
      });
    },
  },
  '/model': {
    desc: '模型平台配置',
    handler: async ({ dispatch }) => {
      const cfg = getConfig();
      dispatch({
        type: 'ADD_USER_MESSAGE',
        content: '/model',
        id: Date.now().toString(16),
      });
      try {
        await handleModelCommand(cfg.runtime);
        dispatch({
          type: 'FINISH_STREAMING',
          content: '模型配置已更新（/model 命令完成）',
        });
      } catch (err) {
        dispatch({
          type: 'FINISH_STREAMING',
          content: `模型配置失败: ${String(err)}`,
        });
      }
    },
  },
  '/agent': {
    desc: 'Agent 模型分配',
    handler: async ({ dispatch }) => {
      const cfg = getConfig();
      dispatch({
        type: 'ADD_USER_MESSAGE',
        content: '/agent',
        id: Date.now().toString(16),
      });
      try {
        await handleAgentCommand(cfg.runtime);
        dispatch({
          type: 'FINISH_STREAMING',
          content: 'Agent 配置已更新（/agent 命令完成）',
        });
      } catch (err) {
        dispatch({
          type: 'FINISH_STREAMING',
          content: `Agent 配置失败: ${String(err)}`,
        });
      }
    },
  },
  '/channel': {
    desc: '通信渠道配置',
    handler: async ({ dispatch }) => {
      const cfg = getConfig();
      dispatch({
        type: 'ADD_USER_MESSAGE',
        content: '/channel',
        id: Date.now().toString(16),
      });
      try {
        await handleChannelCommand(cfg.runtime);
        dispatch({
          type: 'FINISH_STREAMING',
          content: '渠道配置已更新（/channel 命令完成）',
        });
      } catch (err) {
        dispatch({
          type: 'FINISH_STREAMING',
          content: `渠道配置失败: ${String(err)}`,
        });
      }
    },
  },
  '/compact': {
    desc: '压缩对话历史',
    handler: async ({ memoryAgent, dispatch }) => {
      if (!memoryAgent) {
        dispatch({
          type: 'FINISH_STREAMING',
          content: 'MemoryAgent 未就绪，无法压缩',
        });
        return;
      }
      dispatch({
        type: 'ADD_USER_MESSAGE',
        content: '/compact',
        id: Date.now().toString(16),
      });
      try {
        const summary = await memoryAgent.compact();
        dispatch({
          type: 'FINISH_STREAMING',
          content: `对话历史已压缩:\n${summary.slice(0, 300)}`,
        });
      } catch (err) {
        dispatch({
          type: 'FINISH_STREAMING',
          content: `压缩失败: ${String(err)}`,
        });
      }
    },
  },
};

// ─── App 组件 ───────────────────────────────────────────

export const App: React.FC<AppProps> = ({
  memoryAgent,
  bridge,
  onSubmit,
  onQuit,
}) => {
  const [state, dispatch] = useReducer(tuiReducer, createInitialState());
  const bridgeRef = useRef(bridge);
  bridgeRef.current = bridge;

  // ─── 连接 Bridge → dispatch ──────────────────────
  useEffect(() => {
    const b = bridgeRef.current;
    b.onUserMessage = (text: string) => {
      dispatch({
        type: 'ADD_USER_MESSAGE',
        content: text,
        id: Date.now().toString(16),
      });
    };
    b.onStreamStart = () => {
      dispatch({ type: 'SET_STREAMING', text: '' });
    };
    b.onStreamChunk = (delta: string) => {
      dispatch({ type: 'APPEND_STREAMING', delta });
    };
    b.onStreamEnd = (fullText: string) => {
      dispatch({ type: 'FINISH_STREAMING', content: fullText });
    };
    b.onSendText = (text: string) => {
      dispatch({ type: 'FINISH_STREAMING', content: text });
    };
    b.onThought = (agent: string, title: string, detail: string) => {
      dispatch({
        type: 'ADD_THOUGHT',
        entry: {
          id: Date.now().toString(16),
          agent,
          title,
          detail,
          timestamp: Date.now(),
        },
      });
    };
  }, []);

  // ─── 快捷键 ─────────────────────────────────────
  useInput((input, key) => {
    if (key.escape) {
      dispatch({ type: 'SET_FULLSCREEN', mode: 'chat' });
      return;
    }
    if (key.ctrl && input === 'c') {
      onQuit();
      return;
    }
    if (key.tab) {
      // Toggle panel cycle
      const panels: Array<'thinking' | 'tools' | 'memory'> = ['thinking', 'tools', 'memory'];
      const current = panels.find(
        (p) => !state.panels[p],
      ) || 'thinking';
      dispatch({ type: 'TOGGLE_PANEL', panel: current });
      return;
    }
    if (input === '1') dispatch({ type: 'TOGGLE_PANEL', panel: 'thinking' });
    if (input === '2') dispatch({ type: 'TOGGLE_PANEL', panel: 'tools' });
    if (input === '3') dispatch({ type: 'TOGGLE_PANEL', panel: 'memory' });
  });

  // ─── 输入处理 ───────────────────────────────────
  const handleSubmit = useCallback(
    (text: string) => {
      // 斜杠命令 → 查表处理
      if (text.startsWith('/')) {
        const cmd = ALL_COMMANDS[text];
        if (cmd) {
          cmd.handler({ dispatch, memoryAgent, onQuit, text });
          return;
        }

        // 未匹配 → 提示用户，不发给 Agent
        const known = Object.keys(ALL_COMMANDS).filter((k) => k.length > 2);
        const suggestions = known
          .filter((k) => k.startsWith(text.slice(0, 3)))
          .slice(0, 3);
        const hint =
          suggestions.length > 0
            ? `你是想输入 ${suggestions.join(' 或 ')} 吗？`
            : '输入 /help 查看可用命令。';

        dispatch({
          type: 'ADD_USER_MESSAGE',
          content: text,
          id: Date.now().toString(16),
        });
        dispatch({
          type: 'FINISH_STREAMING',
          content: `未知命令 '${text}'。${hint}`,
        });
        return;
      }

      // 普通文本 → 转发给 Agent 管道
      onSubmit(text);
    },
    [onSubmit, onQuit, memoryAgent],
  );

  // ─── Memory 全屏模式 ──────────────────────────
  if (state.fullscreenMode === 'memory') {
    return (
      <MemoryFullScreen
        memoryAgent={memoryAgent}
        onBack={() => dispatch({ type: 'SET_FULLSCREEN', mode: 'chat' })}
      />
    );
  }

  // ─── 聊天模式 ──────────────────────────────────
  return (
    <Box flexDirection="column" width="100%" height="100%">
      <Header
        model={state.status.model}
        memoryCount={state.status.memoryCount}
        sessionId={state.status.sessionId}
      />

      <Box flexDirection="row" flexGrow={1}>
        {/* 左侧聊天区 */}
        <ChatPanel
          messages={state.messages}
          streamingText={state.streamingText}
          isProcessing={state.isProcessing}
        />

        {/* 右侧信息面板 */}
        <Box
          flexDirection="column"
          flexGrow={2}
          borderStyle="round"
          borderColor="gray"
          paddingX={1}
        >
          <ThinkingPanel
            thoughts={state.thoughts}
            expanded={state.panels.thinking}
          />
          <ToolsPanel
            toolCalls={state.toolCalls}
            expanded={state.panels.tools}
          />
          <MemoryPanel
            memories={state.memories}
            expanded={state.panels.memory}
          />
        </Box>
      </Box>

      {/* 快捷键提示 */}
      <Box paddingX={1}>
        <Text dimColor>
          Tab切换 | 1/2/3折叠面板 | /help帮助 | /memory记忆 | /clear清屏 | Esc返回 | Ctrl+C退出
        </Text>
      </Box>

      <InputBar onSubmit={handleSubmit} isProcessing={state.isProcessing} />
    </Box>
  );
};

// ─── Memory 全屏浏览器 ──────────────────────────────────

interface MemoryFullScreenProps {
  memoryAgent: MemoryAgent | null;
  onBack: () => void;
}

const MemoryFullScreen: React.FC<MemoryFullScreenProps> = ({
  memoryAgent,
  onBack,
}) => {
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 10;

  useEffect(() => {
    if (!memoryAgent) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const store = (memoryAgent as any).store;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const working = (memoryAgent as any)._workingMemory || [];
    const all = [...store.get_all(), ...working].map(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (e: any) => ({
        id: e.id,
        content: e.content,
        category: e.category,
        confidence: e.confidence,
        importance: e.importance,
        categoryLabel: e.category_label || e.category,
      }),
    ) as MemoryEntry[];
    setEntries(all);
  }, [memoryAgent]);

  const totalPages = Math.max(1, Math.ceil(entries.length / PAGE_SIZE));
  const currentEntries = entries.slice(
    page * PAGE_SIZE,
    (page + 1) * PAGE_SIZE,
  );

  useInput((_input, key) => {
    if (key.escape) onBack();
    if (key.upArrow || key.leftArrow) setPage((p) => Math.max(0, p - 1));
    if (key.downArrow || key.rightArrow)
      setPage((p) => Math.min(totalPages - 1, p + 1));
  });

  return (
    <Box flexDirection="column" padding={1}>
      <Box marginBottom={1}>
        <Text bold color="blue">
          🧠 MIA 记忆浏览器
        </Text>
        <Text dimColor>
          {' '}
          — 共 {entries.length} 条 | 第 {page + 1}/{totalPages} 页 | ↑↓翻页 |
          Esc返回
        </Text>
      </Box>

      <Box flexDirection="column" borderStyle="round" borderColor="blue" paddingX={1}>
        {currentEntries.length === 0 ? (
          <Text dimColor>记忆库为空</Text>
        ) : (
          currentEntries.map((entry) => (
            <Box key={entry.id} flexDirection="column" marginY={1}>
              <Box>
                <Text color="cyan">[{entry.categoryLabel}]</Text>
                <Text> {entry.content}</Text>
              </Box>
              <Text dimColor>
                置信度: {(entry.confidence * 100).toFixed(0)}% | 重要度:{' '}
                {(entry.importance * 100).toFixed(0)}%
              </Text>
            </Box>
          ))
        )}
      </Box>
    </Box>
  );
};
