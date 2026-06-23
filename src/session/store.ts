/**
 * SessionStore — 会话持久化存储
 *
 * 存储方案:
 *   每个会话一个 JSON 文件: <workspace>/sessions/<session_id>.json
 *   索引文件: <workspace>/sessions/index.json (快速列出所有会话)
 *
 * 单会话文件格式:
 *   {
 *     id, title, created_at, updated_at,
 *     messages: [{ role, content, ts, thoughts?, tools? }]
 *   }
 *
 * 索引文件格式:
 *   [{ id, title, created_at, updated_at, message_count }]
 */

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { getConfig } from '../config.js';

// ─── 类型定义 ────────────────────────────────────────────

/** 会话中的单条消息 */
export interface SessionMessage {
  /** "user" | "assistant" */
  role: 'user' | 'assistant';
  /** 消息文本 */
  content: string;
  /** 毫秒时间戳 */
  ts: number;
  /** 助手消息关联的思考过程 */
  thoughts?: Array<{
    agent: string;
    title: string;
    detail: string;
    ts: number;
  }>;
  /** 助手消息关联的工具调用 */
  tools?: Array<{
    name: string;
    status: 'running' | 'success' | 'error';
    args: string;
    result: string;
    ts: number;
  }>;
}

/** 完整会话数据 */
export interface SessionData {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: SessionMessage[];
}

/** 会话索引条目 (轻量，仅元数据) */
export interface SessionIndexEntry {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

// ─── SessionStore ─────────────────────────────────────────

export class SessionStore {
  private _sessionsDir: string | null = null;

  /** 获取会话文件目录 */
  private get sessionsDir(): string {
    if (this._sessionsDir) return this._sessionsDir;
    try {
      const ws = getConfig().agent.workspace_dir;
      const dir = path.join(ws, 'sessions');
      fs.mkdirSync(dir, { recursive: true });
      this._sessionsDir = dir;
    } catch {
      this._sessionsDir = path.resolve('sessions');
      fs.mkdirSync(this._sessionsDir, { recursive: true });
    }
    return this._sessionsDir;
  }

  /** 获取单个会话文件路径 */
  private _sessionPath(sessionId: string): string {
    return path.join(this.sessionsDir, `${sessionId}.json`);
  }

  /** 获取索引文件路径 */
  private _indexPath(): string {
    return path.join(this.sessionsDir, 'index.json');
  }

  // ─── CRUD ──────────────────────────────────────────

  /** 创建新会话 — 返回 sessionId */
  create(title?: string): string {
    const id = crypto.randomBytes(6).toString('hex');
    const now = new Date().toISOString();
    const session: SessionData = {
      id,
      title: title || '新会话',
      created_at: now,
      updated_at: now,
      messages: [],
    };
    this._writeSession(session);
    this._updateIndex(session);
    return id;
  }

  /** 保存会话 (追加新消息) */
  save(
    sessionId: string,
    messages: SessionMessage[],
    title?: string,
  ): void {
    const existing = this._readSession(sessionId);
    const session: SessionData = existing || {
      id: sessionId,
      title: title || '会话',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      messages: [],
    };

    // 追加消息（去重: 相同 ts 视为重复）
    const existingTs = new Set(session.messages.map((m) => m.ts));
    for (const msg of messages) {
      if (!existingTs.has(msg.ts)) {
        session.messages.push(msg);
      }
    }

    session.updated_at = new Date().toISOString();
    if (title) session.title = title;

    this._writeSession(session);
    this._updateIndex(session);
  }

  /** 追加单条用户消息 */
  appendUserMsg(sessionId: string, content: string, ts?: number): void {
    this.save(sessionId, [
      { role: 'user', content, ts: ts || Date.now() },
    ]);
  }

  /** 追加单条助手消息 (含 thoughts/tools) */
  appendAssistantMsg(
    sessionId: string,
    content: string,
    thoughts?: SessionMessage['thoughts'],
    tools?: SessionMessage['tools'],
    ts?: number,
  ): void {
    this.save(sessionId, [
      { role: 'assistant', content, ts: ts || Date.now(), thoughts, tools },
    ]);
  }

  /** 加载会话 */
  load(sessionId: string): SessionData | null {
    return this._readSession(sessionId);
  }

  /** 删除会话 */
  delete(sessionId: string): boolean {
    const filePath = this._sessionPath(sessionId);
    if (!fs.existsSync(filePath)) return false;
    fs.unlinkSync(filePath);
    this._removeFromIndex(sessionId);
    return true;
  }

  /** 列出所有会话 (按更新时间倒序) */
  list(): SessionIndexEntry[] {
    return this._readIndex();
  }

  /** 获取会话消息列表 (仅消息) */
  getMessages(sessionId: string): SessionMessage[] {
    const session = this._readSession(sessionId);
    return session?.messages || [];
  }

  // ─── 内部方法 ──────────────────────────────────────

  private _writeSession(session: SessionData): void {
    const filePath = this._sessionPath(session.id);
    fs.writeFileSync(filePath, JSON.stringify(session, null, 2), 'utf-8');
  }

  private _readSession(sessionId: string): SessionData | null {
    const filePath = this._sessionPath(sessionId);
    if (!fs.existsSync(filePath)) return null;
    try {
      const raw = fs.readFileSync(filePath, 'utf-8');
      return JSON.parse(raw) as SessionData;
    } catch {
      return null;
    }
  }

  private _readIndex(): SessionIndexEntry[] {
    const indexPath = this._indexPath();
    if (!fs.existsSync(indexPath)) return [];
    try {
      return JSON.parse(fs.readFileSync(indexPath, 'utf-8')) as SessionIndexEntry[];
    } catch {
      return [];
    }
  }

  private _writeIndex(entries: SessionIndexEntry[]): void {
    const indexPath = this._indexPath();
    fs.writeFileSync(indexPath, JSON.stringify(entries, null, 2), 'utf-8');
  }

  private _updateIndex(session: SessionData): void {
    const entries = this._readIndex();
    const existingIdx = entries.findIndex((e) => e.id === session.id);
    const entry: SessionIndexEntry = {
      id: session.id,
      title: session.title,
      created_at: session.created_at,
      updated_at: session.updated_at,
      message_count: session.messages.length,
    };
    if (existingIdx >= 0) {
      entries[existingIdx] = entry;
    } else {
      entries.push(entry);
    }
    // 按更新时间倒序
    entries.sort(
      (a, b) =>
        new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    );
    this._writeIndex(entries);
  }

  private _removeFromIndex(sessionId: string): void {
    const entries = this._readIndex().filter((e) => e.id !== sessionId);
    this._writeIndex(entries);
  }
}
