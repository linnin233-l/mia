/**
 * SessionStore 测试
 *
 * 覆盖:
 *   - 创建会话 (create)
 *   - 保存/追加消息 (save, appendUserMsg, appendAssistantMsg)
 *   - 加载会话 (load)
 *   - 列出所有会话 (list)
 *   - 删除会话 (delete)
 *   - 索引文件持久化 (index.json)
 *   - 消息去重 (相同 ts 不重复追加)
 *   - 边界: 空会话, 大量消息, 不存在的会话
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { SessionStore, type SessionMessage } from '../src/session/store.js';

// ─── 辅助 ────────────────────────────────────────────────

let tmpDir: string;
let store: SessionStore;

function hackPath(s: SessionStore, dir: string): void {
  (s as any)._sessionsDir = dir;
  fs.mkdirSync(dir, { recursive: true });
}

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mia_sess_'));
  store = new SessionStore();
  hackPath(store, tmpDir);
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

// ═══════════════════════════════════════════════════════════

describe('SessionStore', () => {
  // ─── 创建 ──────────────────────────────────────────

  it('create 返回 12 字符 hex id', () => {
    const id = store.create();
    expect(id).toHaveLength(12);
    expect(/^[0-9a-f]+$/.test(id)).toBe(true);
  });

  it('create 后会话文件存在', () => {
    const id = store.create();
    const f = path.join(tmpDir, `${id}.json`);
    expect(fs.existsSync(f)).toBe(true);
  });

  it('create 后 list 包含该会话', () => {
    const id = store.create();
    const list = store.list();
    expect(list.some((e) => e.id === id)).toBe(true);
  });

  it('create 后会话初始消息数为 0', () => {
    const id = store.create();
    const session = store.load(id);
    expect(session).not.toBeNull();
    expect(session!.messages).toHaveLength(0);
    expect(session!.title).toBe('新会话');
  });

  // ─── 保存/追加 ─────────────────────────────────────

  it('appendUserMsg 后消息数 = 1', () => {
    const id = store.create();
    store.appendUserMsg(id, '你好');
    const session = store.load(id);
    expect(session?.messages).toHaveLength(1);
    expect(session?.messages[0]?.role).toBe('user');
    expect(session?.messages[0]?.content).toBe('你好');
  });

  it('appendAssistantMsg 后消息数 = 2', () => {
    const id = store.create();
    store.appendUserMsg(id, '你好');
    store.appendAssistantMsg(id, '你好呀！', [{ agent: 'scheduler', title: '决策', detail: '...', ts: 1 }]);
    const session = store.load(id);
    expect(session?.messages).toHaveLength(2);
    expect(session?.messages[1]?.role).toBe('assistant');
    expect(session?.messages[1]?.thoughts).toHaveLength(1);
  });

  it('save 批量追加消息', () => {
    const id = store.create();
    const msgs: SessionMessage[] = [
      { role: 'user', content: 'Q1', ts: 1000 },
      { role: 'assistant', content: 'A1', ts: 1001 },
      { role: 'user', content: 'Q2', ts: 2000 },
      { role: 'assistant', content: 'A2', ts: 2001 },
    ];
    store.save(id, msgs);
    const session = store.load(id);
    expect(session?.messages).toHaveLength(4);
  });

  it('相同 ts 消息去重', () => {
    const id = store.create();
    store.appendUserMsg(id, '你好', 1000);
    store.appendUserMsg(id, '你好', 1000); // same ts
    const session = store.load(id);
    expect(session?.messages).toHaveLength(1); // 去重
  });

  it('save 更新标题', () => {
    const id = store.create('旧标题');
    store.save(id, [], '新标题');
    const session = store.load(id);
    expect(session?.title).toBe('新标题');
  });

  // ─── 加载 ──────────────────────────────────────────

  it('load 不存在的会话返回 null', () => {
    expect(store.load('nonexistent')).toBeNull();
  });

  it('load 返回完整会话数据', () => {
    const id = store.create('测试会话');
    store.appendUserMsg(id, '测试消息', 5000);
    store.appendAssistantMsg(id, '回复内容', undefined, [{ name: 'weather', status: 'success', args: '', result: '26°C', ts: 5001 }], 5001);

    const session = store.load(id)!;
    expect(session.id).toBe(id);
    expect(session.title).toBe('测试会话');
    expect(session.messages[1]?.tools).toBeDefined();
    expect(session.messages[1]?.tools![0]?.name).toBe('weather');
  });

  // ─── 列表 ──────────────────────────────────────────

  it('空 store list 返回 []', () => {
    expect(store.list()).toEqual([]);
  });

  it('list 返回按更新时间倒序', () => {
    const id1 = store.create('A');
    const id2 = store.create('B');
    // B 是后创建的，应该在前面
    const list = store.list();
    expect(list[0]?.id).toBe(id2);
    expect(list[1]?.id).toBe(id1);
  });

  it('更新后排序变化', () => {
    const id1 = store.create('First');
    const id2 = store.create('Second');
    // 更新 id1
    store.appendUserMsg(id1, '新消息');
    const list = store.list();
    // id1 应该在前面（最新更新）
    expect(list[0]?.id).toBe(id1);
    expect(list[0]?.message_count).toBe(1);
  });

  // ─── 删除 ──────────────────────────────────────────

  it('delete 后文件不存在', () => {
    const id = store.create();
    store.delete(id);
    expect(fs.existsSync(path.join(tmpDir, `${id}.json`))).toBe(false);
  });

  it('delete 后 list 不包含', () => {
    const id = store.create();
    store.delete(id);
    expect(store.list().some((e) => e.id === id)).toBe(false);
  });

  it('delete 不存在的会话返回 false', () => {
    expect(store.delete('noexist')).toBe(false);
  });

  // ─── 索引文件 ──────────────────────────────────────

  it('index.json 在创建后存在', () => {
    store.create();
    expect(fs.existsSync(path.join(tmpDir, 'index.json'))).toBe(true);
  });

  it('index.json 数据正确', () => {
    const id = store.create('测试');
    store.appendUserMsg(id, 'hello');
    store.appendAssistantMsg(id, 'world');

    const indexPath = path.join(tmpDir, 'index.json');
    const raw = JSON.parse(fs.readFileSync(indexPath, 'utf-8'));
    const entry = raw.find((e: any) => e.id === id);
    expect(entry).toBeDefined();
    expect(entry.title).toBe('测试');
    expect(entry.message_count).toBe(2);
  });

  // ─── 边界 ──────────────────────────────────────────

  it('不存在的 session 调用 append 自动创建', () => {
    const id = 'abc123def456';
    store.appendUserMsg(id, '自动创建测试');
    const session = store.load(id);
    expect(session).not.toBeNull();
    expect(session?.messages).toHaveLength(1);
  });

  it('加载空消息的会话', () => {
    const id = store.create();
    const session = store.load(id)!;
    expect(session.messages).toHaveLength(0);
    expect(session.created_at).toBeTruthy();
    expect(session.updated_at).toBeTruthy();
  });

  it('getMessages 空会话返回 []', () => {
    const msgs = store.getMessages('nonexistent');
    expect(msgs).toEqual([]);
  });

  it('thoughts 和 tools 保存与加载', () => {
    const id = store.create();
    store.appendAssistantMsg(
      id,
      '完成',
      [
        { agent: 'scheduler', title: '分析意图', detail: '用户询问天气', ts: 10 },
        { agent: 'scheduler', title: '决策', detail: '调用天气工具', ts: 11 },
      ],
      [
        { name: 'weather', status: 'running', args: '金华', result: '', ts: 12 },
        { name: 'weather', status: 'success', args: '', result: '26°C', ts: 13 },
      ],
    );

    const session = store.load(id)!;
    const msg = session.messages[0]!;
    expect(msg.thoughts).toHaveLength(2);
    expect(msg.thoughts![0]?.title).toBe('分析意图');
    expect(msg.tools).toHaveLength(2);
    expect(msg.tools![1]?.status).toBe('success');
    expect(msg.tools![1]?.result).toBe('26°C');
  });
});
