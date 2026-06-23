/**
 * 会话管理 CLI 命令
 *
 * 命令:
 *   /sessions               — 列出所有会话
 *   /sessions new           — 开始新会话 (生成新 sessionId)
 *   /sessions switch <id>   — 切换到已有会话 (加载历史)
 *   /sessions delete <id>   — 删除会话
 *   /sessions info          — 显示当前会话详情
 */

import chalk from 'chalk';
import { SessionStore, type SessionMessage } from '../session/store.js';

// ─── 辅助 ────────────────────────────────────────────────

/** 格式化时间戳为可读字符串 */
function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false });
}

/** 格式化 ISO 时间为简短日期时间 */
function fmtIso(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** 截断文本 */
function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 3) + '...';
}

// ─── 命令处理 ────────────────────────────────────────────

export interface SessionCommandResult {
  /** 是否切换了会话 */
  switched: boolean;
  /** 新 sessionId (如果切换/new) */
  newSessionId?: string;
  /** 要注入的历史消息 (如果加载了会话) */
  historyMessages?: SessionMessage[];
}

const store = new SessionStore();

/**
 * 处理 /sessions 命令族
 *
 * @param args — 空格分隔的参数 (第一个是子命令，后续是参数)
 * @param currentSessionId — 当前活跃的 sessionId
 * @returns 命令结果
 */
export async function handleSessionCommand(
  args: string[],
  currentSessionId?: string,
): Promise<SessionCommandResult> {
  const subCmd = args[0]?.toLowerCase() || 'list';

  switch (subCmd) {
    case 'list':
    case 'ls':
      return cmdList();

    case 'new':
    case 'n':
      return cmdNew();

    case 'switch':
    case 'sw':
      return cmdSwitch(args[1]);

    case 'delete':
    case 'rm':
    case 'del':
      return cmdDelete(args[1]);

    case 'info':
    case 'i':
      return cmdInfo(currentSessionId);

    default:
      console.log(chalk.red(`  未知子命令: ${subCmd}`));
      console.log(chalk.dim('  用法: /sessions [list|new|switch <id>|delete <id>|info]'));
      return { switched: false };
  }
}

// ─── 子命令实现 ──────────────────────────────────────────

function cmdList(): SessionCommandResult {
  const sessions = store.list();

  if (sessions.length === 0) {
    console.log(chalk.dim('  暂无保存的会话。开始对话后会自动创建。'));
    return { switched: false };
  }

  console.log(chalk.cyan(`\n  📂 会话列表 (${sessions.length} 个)`));
  console.log(chalk.dim('  ─────────────────────────────────────────────'));

  for (const s of sessions) {
    const time = fmtIso(s.updated_at);
    const title = truncate(s.title, 30);
    const count = `${s.message_count} 条消息`;
    console.log(
      `  ${chalk.yellow(s.id.slice(0, 8))}  ${chalk.white(title)}  ${chalk.dim(`${count} · ${time}`)}`,
    );
  }

  console.log(chalk.dim('  ─────────────────────────────────────────────'));
  console.log(chalk.dim('  使用 /sessions switch <id> 切换会话'));
  return { switched: false };
}

function cmdNew(): SessionCommandResult {
  const id = store.create();
  console.log(chalk.green(`\n  ✨ 新会话已创建: ${chalk.yellow(id)}`));
  return { switched: true, newSessionId: id };
}

function cmdSwitch(id?: string): SessionCommandResult {
  if (!id) {
    console.log(chalk.red('  请指定会话 ID: /sessions switch <id>'));
    console.log(chalk.dim('  使用 /sessions list 查看所有会话'));
    return { switched: false };
  }

  // 支持模糊匹配: 只要前缀匹配即可
  const sessions = store.list();
  const match = sessions.find(
    (s) => s.id === id || s.id.startsWith(id),
  );

  if (!match) {
    console.log(chalk.red(`  未找到会话: ${id}`));
    return { switched: false };
  }

  const session = store.load(match.id);
  if (!session) {
    console.log(chalk.red(`  会话文件读取失败: ${match.id}`));
    return { switched: false };
  }

  const historyMsgs = session.messages;
  console.log(
    chalk.green(`\n  📂 已切换到会话: ${chalk.yellow(match.title)}`),
  );
  console.log(
    chalk.dim(`  ${historyMsgs.length} 条历史消息 · 创建于 ${fmtIso(match.created_at)}`),
  );

  // 显示最近 3 条消息
  const recent = historyMsgs.slice(-3);
  for (const msg of recent) {
    const role = msg.role === 'user' ? chalk.blue('You') : chalk.green('MIA');
    console.log(
      chalk.dim(`  ${fmtTime(msg.ts)} ${role}: ${truncate(msg.content, 60)}`),
    );
  }

  return {
    switched: true,
    newSessionId: match.id,
    historyMessages: historyMsgs,
  };
}

function cmdDelete(id?: string): SessionCommandResult {
  if (!id) {
    console.log(chalk.red('  请指定会话 ID: /sessions delete <id>'));
    return { switched: false };
  }

  const sessions = store.list();
  const match = sessions.find(
    (s) => s.id === id || s.id.startsWith(id),
  );

  if (!match) {
    console.log(chalk.red(`  未找到会话: ${id}`));
    return { switched: false };
  }

  const ok = store.delete(match.id);
  if (ok) {
    console.log(chalk.green(`  🗑 已删除会话: ${match.title} (${match.id})`));
  } else {
    console.log(chalk.red(`  删除失败: ${match.id}`));
  }

  return { switched: false };
}

function cmdInfo(currentSessionId?: string): SessionCommandResult {
  if (!currentSessionId) {
    console.log(chalk.dim('  当前无活跃会话'));
    return { switched: false };
  }

  const session = store.load(currentSessionId);
  if (!session) {
    console.log(chalk.dim(`  当前会话 ${currentSessionId} 尚未保存到磁盘`));
    console.log(chalk.dim('  对话完成后会自动保存'));
    return { switched: false };
  }

  console.log(chalk.cyan(`\n  📋 会话详情`));
  console.log(chalk.dim('  ──────────────────────────'));
  console.log(`  ID:      ${chalk.yellow(session.id)}`);
  console.log(`  标题:    ${chalk.white(session.title)}`);
  console.log(`  消息数:  ${session.messages.length}`);
  console.log(`  创建:    ${fmtIso(session.created_at)}`);
  console.log(`  更新:    ${fmtIso(session.updated_at)}`);

  return { switched: false };
}
