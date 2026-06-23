/**
 * ChatPanel — 左侧对话区（简化版，不用 Static）
 */

import React from 'react';
import { Box, Text } from 'ink';
import type { ChatMessage } from '../types.js';

interface ChatPanelProps {
  messages: ChatMessage[];
  streamingText: string;
  isProcessing: boolean;
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

export const ChatPanel: React.FC<ChatPanelProps> = ({
  messages,
  streamingText,
  isProcessing,
}) => {
  // 取最近 20 条消息（避免渲染太多）
  const recentMessages = messages.slice(-20);

  return (
    <Box
      flexDirection="column"
      flexGrow={3}
      borderStyle="round"
      borderColor="gray"
      paddingX={1}
    >
      {/* 空状态 */}
      {recentMessages.length === 0 && !streamingText && !isProcessing && (
        <Box marginY={1}>
          <Text dimColor>
            欢迎使用 MIA Ink TUI! /help 查看命令，直接输入开始对话。
          </Text>
        </Box>
      )}

      {/* 历史消息 */}
      {recentMessages.map((msg) => (
        <Box key={msg.id} flexDirection="column" marginY={1}>
          <Box>
            <Text color={msg.role === 'user' ? 'green' : 'cyan'} bold>
              {msg.role === 'user' ? 'You' : 'MIA'} {'> '}
            </Text>
            <Text dimColor>{formatTime(msg.timestamp)}</Text>
          </Box>
          <Box paddingLeft={2}>
            <Text>{msg.content}</Text>
          </Box>
        </Box>
      ))}

      {/* 流式输出 */}
      {streamingText && (
        <Box flexDirection="column" marginY={1}>
          <Box>
            <Text color="cyan" bold>MIA {'> '}</Text>
          </Box>
          <Box paddingLeft={2}>
            <Text>{streamingText}</Text>
            {isProcessing && <Text color="yellow">▊</Text>}
          </Box>
        </Box>
      )}

      {/* 等待中 */}
      {isProcessing && !streamingText && recentMessages.length === 0 && (
        <Box marginY={1}>
          <Text color="yellow">MIA 思考中...</Text>
        </Box>
      )}
    </Box>
  );
};
