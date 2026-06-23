/**
 * WeChatSenderAgent — MIA 到微信的消息发送 Agent
 *
 * 职责（只负责出站）:
 *   1. 监听 SEND_TEXT / STREAM_* / SEND_VOICE 消息
 *   2. 通过 iLink API 将文本或语音发送给微信用户
 *   3. 发送完成后发布 CONVERSATION_DONE
 *
 * 与 Python 版 channels/wechat/sender.py 保持 1:1 语义映射。
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { BaseAgent } from '../../agents/base.js';
import { MessageBus } from '../../bus/bus.js';
import { Message, MessageType } from '../../bus/message.js';
import { ILinkClient } from './client.js';
import type { MiMoProvider } from '../../providers/mimo.js';

// ─── 常量 ──────────────────────────────────────────────

const DEFAULT_TOKEN_FILE = path.join(os.homedir(), '.mia', 'wechat_bot_token');

// ─── WeChatSenderAgent ─────────────────────────────────

/**
 * WeChatSenderAgent — 微信消息发送 Agent
 *
 * 从 MessageBus 接收输出消息，通过 iLink API 发送到微信用户。
 * 每条消息的 payload 中包含 to_user_id 和 context_token
 * （由 Scheduler 通过消息工厂透传）。
 */
export class WeChatSenderAgent extends BaseAgent {
  private enabled: boolean;
  private botToken: string;
  private baseUrl: string;
  private botTokenFile: string;
  private mimo: MiMoProvider | null;
  private workspaceDir: string;

  private client: ILinkClient | null = null;

  /** 用户 context_token 缓存: to_user_id → context_token */
  private _userContextTokens: Map<string, string> = new Map();
  private _contextTokensFile: string;

  /** 流式回复缓冲: session_id → 累积文本 */
  private _streamBuffers: Map<string, string> = new Map();
  /** 流式元数据缓存: session_id → {to_user_id, context_token} */
  private _streamMeta: Map<string, { to_user_id: string; context_token: string }> = new Map();

  constructor(
    bus: MessageBus,
    opts: {
      botToken?: string;
      botTokenFile?: string;
      baseUrl?: string;
      enabled?: boolean;
      mimo?: MiMoProvider | null;
      workspaceDir?: string;
    } = {},
  ) {
    super('wechat_sender', bus);
    this.enabled = opts.enabled ?? true;
    this.botToken = opts.botToken || '';
    this.baseUrl = opts.baseUrl || 'https://ilinkai.weixin.qq.com';
    this.botTokenFile = opts.botTokenFile || DEFAULT_TOKEN_FILE;
    this.mimo = opts.mimo || null;
    this.workspaceDir = opts.workspaceDir || path.join(os.homedir(), '.mia', 'workspace');

    this._contextTokensFile = path.join(
      path.dirname(this.botTokenFile),
      'wechat_context_tokens.json',
    );

    fs.mkdirSync(this.workspaceDir, { recursive: true });
  }

  // ─── 生命周期 ──────────────────────────────────────

  protected async onStart(): Promise<void> {
    if (!this.enabled) return;

    // 加载 token
    if (!this.botToken) {
      this.botToken = this._loadTokenFromFile();
    }

    // 创建 ILinkClient
    this.client = new ILinkClient(this.botToken, this.baseUrl);

    // 加载 context_tokens 缓存
    this._loadContextTokens();

    console.log('[WeChatSender] 微信发送渠道已就绪 ✓');
  }

  protected async onStop(): Promise<void> {
    this.client = null;
  }

  protected async handle(msg: Message): Promise<void> {
    if (!this.enabled) return;

    switch (msg.msg_type) {
      case MessageType.SEND_TEXT:
        await this._handleOutputText(msg);
        break;
      case MessageType.STREAM_START:
        await this._handleStreamStart(msg);
        break;
      case MessageType.STREAM_CHUNK:
        await this._handleStreamChunk(msg);
        break;
      case MessageType.STREAM_END:
        await this._handleStreamEnd(msg);
        break;
      case MessageType.SEND_VOICE:
        await this._handleOutputVoice(msg);
        break;
    }
  }

  // ─── 文本输出 ────────────────────────────────────

  private async _handleOutputText(msg: Message): Promise<void> {
    const message = (msg.payload['message'] as string) || '';
    const toUserId = (msg.payload['to_user_id'] as string) || '';
    let contextToken = (msg.payload['context_token'] as string) || '';

    // Fallback: 从缓存获取 context_token
    if (!contextToken && toUserId) {
      contextToken = this._userContextTokens.get(toUserId) || '';
    }

    if (message && toUserId) {
      await this._sendTextToUser(toUserId, contextToken, message);
      console.log(`\x1b[32m[WeChatSender]\x1b[0m 文本已发送 (${message.length}字)`);
    }

    await this._publishConversationDone(msg, message);
  }

  // ─── 流式输出 ────────────────────────────────────

  private async _handleStreamStart(msg: Message): Promise<void> {
    const sid = msg.session_id || '';
    this._streamBuffers.set(sid, '');

    const toUserId = (msg.payload['to_user_id'] as string) || '';
    let contextToken = (msg.payload['context_token'] as string) || '';
    if (toUserId) {
      if (!contextToken) contextToken = this._userContextTokens.get(toUserId) || '';
      this._streamMeta.set(sid, { to_user_id: toUserId, context_token: contextToken });
    }
  }

  private async _handleStreamChunk(msg: Message): Promise<void> {
    const sid = msg.session_id || '';
    const delta = (msg.payload['delta'] as string) || '';
    const current = this._streamBuffers.get(sid) || '';
    this._streamBuffers.set(sid, current + delta);
  }

  private async _handleStreamEnd(msg: Message): Promise<void> {
    const sid = msg.session_id || '';
    let fullText = (msg.payload['message'] as string) || '';

    // 从缓冲获取完整文本
    if (!fullText) {
      fullText = this._streamBuffers.get(sid) || '';
    }
    this._streamBuffers.delete(sid);

    // 获取目标用户
    let toUserId = (msg.payload['to_user_id'] as string) || '';
    let contextToken = (msg.payload['context_token'] as string) || '';

    if (!toUserId) {
      const meta = this._streamMeta.get(sid);
      if (meta) {
        toUserId = meta.to_user_id;
        contextToken = contextToken || meta.context_token;
      }
    }
    this._streamMeta.delete(sid);

    // Fallback: 从缓存获取 context_token
    if (!contextToken && toUserId) {
      contextToken = this._userContextTokens.get(toUserId) || '';
    }

    if (fullText && toUserId) {
      await this._sendTextToUser(toUserId, contextToken, fullText);
      console.log(`\x1b[32m[WeChatSender]\x1b[0m 流式文本已发送 (${fullText.length}字)`);
    }

    await this._publishConversationDone(msg, fullText);
  }

  // ─── 语音输出 ────────────────────────────────────

  private async _handleOutputVoice(msg: Message): Promise<void> {
    const message = (msg.payload['message'] as string) || '';
    const voice = (msg.payload['voice'] as string) || '冰糖';
    const audioFormat = (msg.payload['format'] as string) || 'wav';
    const toUserId = (msg.payload['to_user_id'] as string) || '';
    let contextToken = (msg.payload['context_token'] as string) || '';

    if (!contextToken && toUserId) {
      contextToken = this._userContextTokens.get(toUserId) || '';
    }

    if (!toUserId || !message) {
      console.log(`\x1b[33m[WeChatSender]\x1b[0m SEND_VOICE 缺少必要参数`);
      return;
    }

    let audioSent = false;

    // TTS 合成 + CDN 上传 + 发送
    if (this.mimo && this.client) {
      try {
        const audioBytes = await this.mimo.synthesize(message, voice, audioFormat);
        const filename = `wechat_voice_${msg.msg_id}.${audioFormat}`;
        const audioPath = path.join(this.workspaceDir, filename);
        fs.writeFileSync(audioPath, audioBytes);

        console.log(`   \x1b[90m├─\x1b[0m TTS: ${audioBytes.length} bytes`);

        // 上传 CDN
        const uploadResult = await this.client.uploadMedia(audioPath, 3, toUserId);

        // 发送 file_item
        const fileMsg = {
          to_user_id: toUserId,
          client_id: crypto.randomUUID(),
          message_type: 2,
          message_state: 2,
          context_token: contextToken,
          item_list: [{
            type: 4,
            file_item: {
              media: {
                encrypt_query_param: uploadResult.encrypt_query_param,
                aes_key: uploadResult.aes_key_b64,
                encrypt_type: 1,
              },
              file_name: `mia_voice.${audioFormat}`,
              len: String(uploadResult.rawsize),
            },
          }],
        };
        await this.client.sendmessage(fileMsg);

        audioSent = true;
        console.log(`\x1b[32m   └─\x1b[0m 语音文件已发送 ✓`);

        // 清理临时文件
        try { fs.unlinkSync(audioPath); } catch { /* ignore */ }
      } catch (err) {
        console.error(`\x1b[31m   └─\x1b[0m 语音发送失败:`, err);
      }
    }

    // 文本 fallback
    const prefix = audioSent ? '🎤 ' : '';
    await this._sendTextToUser(toUserId, contextToken, `${prefix}${message}`);

    await this._publishConversationDone(msg, message);
  }

  // ─── CONVERSATION_DONE ─────────────────────────────

  private async _publishConversationDone(msg: Message, message: string): Promise<void> {
    // 通知 main
    await this.bus.publish({
      msg_type: MessageType.CONVERSATION_DONE,
      source: this.name,
      target: 'main',
      payload: { message },
      msg_id: Date.now().toString(16),
      timestamp: Date.now(),
      session_id: msg.session_id,
    });

    // 通知 MemoryAgent
    await this.bus.publish({
      msg_type: MessageType.CONVERSATION_DONE,
      source: this.name,
      target: 'memory_agent',
      payload: { message },
      msg_id: Date.now().toString(16) + 'm',
      timestamp: Date.now(),
      session_id: msg.session_id,
    });
  }

  // ─── 底层发送 ────────────────────────────────────

  private async _sendTextToUser(
    toUserId: string,
    contextToken: string,
    text: string,
  ): Promise<void> {
    if (!this.client || !toUserId || !text) return;
    try {
      await this.client.sendText(toUserId, text, contextToken);
    } catch (err) {
      console.error(`[WeChatSender] 发送文本失败:`, err);
    }
  }

  // ─── Token 持久化 ──────────────────────────────────

  private _loadTokenFromFile(): string {
    try {
      if (fs.existsSync(this.botTokenFile)) {
        return fs.readFileSync(this.botTokenFile, 'utf-8').trim();
      }
    } catch { /* ignore */ }
    return '';
  }

  // ─── Context Token 缓存 ─────────────────────────────

  private _loadContextTokens(): void {
    try {
      if (fs.existsSync(this._contextTokensFile)) {
        const data = JSON.parse(fs.readFileSync(this._contextTokensFile, 'utf-8'));
        for (const [k, v] of Object.entries(data)) {
          if (typeof v === 'string') this._userContextTokens.set(k, v);
        }
      }
    } catch { /* ignore */ }
  }
}
