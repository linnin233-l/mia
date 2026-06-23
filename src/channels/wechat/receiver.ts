/**
 * WeChatReceiverAgent — 微信入站消息接收 Agent（纯接收，不处理输出）
 *
 * 职责（只负责入站）:
 *   1. 后台长轮询 iLink API 获取新消息
 *   2. 消息解析 (text/image/voice/file/video)
 *   3. 发布 RAW_INPUT 到 MessageBus，携带 context_token 和 to_user_id
 *
 * 不处理任何输出/发送 — 发送由 WeChatSenderAgent 负责。
 *
 * 与 Python 版 channels/wechat/receiver.py 保持 1:1 语义映射。
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { BaseAgent } from '../../agents/base.js';
import { MessageBus } from '../../bus/bus.js';
import { Message, makeRawInput } from '../../bus/message.js';
import { ILinkClient } from './client.js';

// ─── 常量 ──────────────────────────────────────────────

/** 去重集合上限 */
const MAX_PROCESSED_IDS = 2000;
/** 内容去重时间窗口（毫秒） */
const TEXT_DEDUP_TTL_MS = 30_000;
/** 默认 token 文件路径 */
const DEFAULT_TOKEN_FILE = path.join(os.homedir(), '.mia', 'wechat_bot_token');

/** 去重条目 */
interface DedupEntry {
  content: string;
  timestamp: number;
}

// ─── WeChatReceiverAgent ────────────────────────────────

/**
 * WeChatReceiverAgent — 微信入站消息接收 Agent
 *
 * 通过后台轮询 iLink Bot API，接收微信消息并发布 RAW_INPUT。
 */
export class WeChatReceiverAgent extends BaseAgent {
  private enabled: boolean;
  private botToken: string;
  private baseUrl: string;
  private botTokenFile: string;
  private mediaDir: string;

  private client: ILinkClient | null = null;
  private _pollTimer: NodeJS.Timeout | null = null;

  /** 已处理消息 ID 去重集合 */
  private _processedIds: Set<string> = new Set();
  /** 文本内容去重缓存 */
  private _textDedup: DedupEntry[] = [];

  /** 用户 context_token 缓存: to_user_id → context_token */
  private _userContextTokens: Map<string, string> = new Map();

  constructor(
    bus: MessageBus,
    opts: {
      botToken?: string;
      botTokenFile?: string;
      baseUrl?: string;
      enabled?: boolean;
      mediaDir?: string;
    } = {},
  ) {
    super('wechat_receiver', bus);
    this.enabled = opts.enabled ?? true;
    this.botToken = opts.botToken || '';
    this.baseUrl = opts.baseUrl || 'https://ilinkai.weixin.qq.com';
    this.botTokenFile = opts.botTokenFile || DEFAULT_TOKEN_FILE;
    this.mediaDir = opts.mediaDir || path.join(os.homedir(), '.mia', 'media');
  }

  // ─── 生命周期 ──────────────────────────────────────

  protected async onStart(): Promise<void> {
    if (!this.enabled) return;

    // 确保媒体目录存在
    fs.mkdirSync(this.mediaDir, { recursive: true });

    // 尝试从文件加载 token
    if (!this.botToken) {
      this.botToken = this._loadTokenFromFile();
    }

    // 创建 ILinkClient
    this.client = new ILinkClient(this.botToken, this.baseUrl);

    // 如果没有 token，尝试 QR 码登录
    if (!this.botToken) {
      console.log('[WeChatReceiver] 未配置 bot_token，尝试 QR 码登录...');
      try {
        await this._qrLogin();
      } catch (err) {
        console.error('[WeChatReceiver] QR 码登录失败:', err);
        console.log('[WeChatReceiver] 微信渠道将禁用（无有效 token）');
        this.enabled = false;
        return;
      }
    }

    // 启动后台轮询
    this._startPolling();
    console.log('[WeChatReceiver] 微信入站渠道已就绪 ✓');
  }

  protected async onStop(): Promise<void> {
    this._stopPolling();
    if (this.client) {
      // ILinkClient doesn't have a stop method (uses fetch), so just null it
      this.client = null;
    }
  }

  protected async handle(_msg: Message): Promise<void> {
    // WeChatReceiverAgent 不处理 MessageBus 消息
    // 它通过 _pollLoop 主动注入 RAW_INPUT 到总线
  }

  // ─── QR 码登录 ────────────────────────────────────

  /** QR 码登录流程 */
  private async _qrLogin(): Promise<void> {
    if (!this.client) return;

    const qrData = await this.client.getBotQrcode();
    const qrcode = qrData.qrcode || '';

    if (!qrcode) {
      throw new Error('获取二维码失败');
    }

    // 保存二维码图片
    if (qrData.qrcode_img_content) {
      const qrPath = path.join(this.mediaDir, 'wechat_qrcode.png');
      fs.writeFileSync(qrPath, Buffer.from(qrData.qrcode_img_content, 'base64'));
      console.log(`[WeChatReceiver] 二维码已保存: ${qrPath}`);
      console.log('[WeChatReceiver] 请用微信扫描二维码登录...');
    }

    // 等待扫码确认
    const [token, baseUrl] = await this.client.waitForLogin(qrcode);

    this.botToken = token;
    this.baseUrl = baseUrl;
    this.client = new ILinkClient(token, baseUrl);

    // 持久化 token
    this._saveTokenToFile(token);
    console.log('[WeChatReceiver] QR 码登录成功 ✓');
  }

  // ─── 后台轮询 ────────────────────────────────────

  /** 启动后台轮询 */
  private _startPolling(): void {
    let cursor = '';

    const poll = async () => {
      if (!this.client || !this.enabled) return;

      try {
        const data = await this.client.getupdates(cursor);

        if (data.ret === 0 && data.msgs) {
          for (const msg of data.msgs as Array<Record<string, unknown>>) {
            await this._onMessage(msg);
          }
        }

        cursor = (data.get_updates_buf as string) || cursor;
      } catch (err) {
        console.error('[WeChatReceiver] 轮询错误:', err);
      }
    };

    // 递归轮询: 每次完成后立即发起下一次
    const loop = () => {
      poll().finally(() => {
        if (this._pollTimer !== null) {
          this._pollTimer = setTimeout(loop, 100); // 100ms 间隔避免过载
        }
      });
    };

    this._pollTimer = setTimeout(loop, 0);
  }

  /** 停止后台轮询 */
  private _stopPolling(): void {
    if (this._pollTimer) {
      clearTimeout(this._pollTimer);
      this._pollTimer = null;
    }
  }

  // ─── 消息处理 ────────────────────────────────────

  /** 处理入站微信消息 */
  private async _onMessage(msg: Record<string, unknown>): Promise<void> {
    // 去重: 消息 ID
    const msgId = msg['msg_id'] as string;
    if (msgId && this._processedIds.has(msgId)) return;
    if (msgId) {
      this._processedIds.add(msgId);
      // 限制去重集合大小
      if (this._processedIds.size > MAX_PROCESSED_IDS) {
        const toDelete = [...this._processedIds].slice(0, MAX_PROCESSED_IDS / 2);
        for (const id of toDelete) this._processedIds.delete(id);
      }
    }

    const fromUserId = (msg['from_user_id'] as string) || '';
    const toUserId = (msg['to_user_id'] as string) || '';
    const contextToken = (msg['context_token'] as string) || '';

    // 缓存 context_token
    if (fromUserId && contextToken) {
      this._userContextTokens.set(fromUserId, contextToken);
    }

    // 解析消息内容
    const itemList = msg['item_list'] as Array<Record<string, unknown>> || [];
    for (const item of itemList) {
      const itemType = item['type'] as number;

      switch (itemType) {
        case 1: // 文本
          await this._handleTextItem(item, fromUserId, toUserId, contextToken);
          break;
        case 2: // 图片
          await this._handleImageItem(item, fromUserId, toUserId, contextToken);
          break;
        case 3: // 语音 (SILK)
          await this._handleVoiceItem(item, fromUserId, toUserId, contextToken);
          break;
        case 4: // 文件
          await this._handleFileItem(item, fromUserId, toUserId, contextToken);
          break;
        case 5: // 视频
          await this._handleVideoItem(item, fromUserId, toUserId, contextToken);
          break;
      }
    }
  }

  // ─── 各类型消息处理 ──────────────────────────────

  /** 处理文本消息 */
  private async _handleTextItem(
    item: Record<string, unknown>,
    fromUserId: string,
    _toUserId: string,
    contextToken: string,
  ): Promise<void> {
    const textItem = item['text_item'] as Record<string, unknown> || {};
    const text = (textItem['text'] as string) || '';

    if (!text) return;

    // 内容去重
    if (this._isTextDuplicate(text)) return;

    // 构建 session_id (wechat:<user_id>)
    const sessionId = `wechat:${fromUserId}`;

    const rawMsg = makeRawInput(text, [], sessionId, contextToken, fromUserId);
    await this.send(rawMsg);
  }

  /** 处理图片消息 */
  private async _handleImageItem(
    item: Record<string, unknown>,
    fromUserId: string,
    _toUserId: string,
    contextToken: string,
  ): Promise<void> {
    const imageItem = item['image_item'] as Record<string, unknown> || {};
    const media = imageItem['media'] as Record<string, unknown> || {};

    // 尝试下载图片
    try {
      if (this.client) {
        const url = (media['url'] as string) || '';
        const aesKey = (media['aes_key'] as string) || '';
        const encParam = (media['encrypt_query_param'] as string) || '';

        const imageData = await this.client.downloadMedia(url, aesKey, encParam);
        const imagePath = path.join(this.mediaDir, `wechat_image_${Date.now()}.jpg`);
        fs.writeFileSync(imagePath, imageData);

        const sessionId = `wechat:${fromUserId}`;
        const rawMsg = makeRawInput(
          '[图片消息]',
          [imagePath],
          sessionId,
          contextToken,
          fromUserId,
        );
        await this.send(rawMsg);
      }
    } catch (err) {
      console.error('[WeChatReceiver] 图片下载失败:', err);
    }
  }

  /** 处理语音消息 (SILK 格式) */
  private async _handleVoiceItem(
    item: Record<string, unknown>,
    fromUserId: string,
    _toUserId: string,
    contextToken: string,
  ): Promise<void> {
    const voiceItem = item['voice_item'] as Record<string, unknown> || {};
    const media = voiceItem['media'] as Record<string, unknown> || {};

    try {
      if (this.client) {
        const url = (media['url'] as string) || '';
        const aesKey = (media['aes_key'] as string) || '';
        const encParam = (media['encrypt_query_param'] as string) || '';

        // 下载 SILK 音频
        const silkData = await this.client.downloadMedia(url, aesKey, encParam);
        const silkPath = path.join(this.mediaDir, `wechat_voice_${Date.now()}.silk`);
        fs.writeFileSync(silkPath, silkData);

        // TODO: SILK → WAV 转换（需要外部工具如 ffmpeg 或 silk-v3-decoder）
        // 当前直接传递 SILK 文件路径，由 ReceiverAgent 的音频理解处理
        const sessionId = `wechat:${fromUserId}`;
        const rawMsg = makeRawInput(
          '[语音消息]',
          [silkPath],
          sessionId,
          contextToken,
          fromUserId,
        );
        await this.send(rawMsg);
      }
    } catch (err) {
      console.error('[WeChatReceiver] 语音下载失败:', err);
    }
  }

  /** 处理文件消息 */
  private async _handleFileItem(
    item: Record<string, unknown>,
    fromUserId: string,
    _toUserId: string,
    contextToken: string,
  ): Promise<void> {
    const fileItem = item['file_item'] as Record<string, unknown> || {};
    const media = fileItem['media'] as Record<string, unknown> || {};
    const fileName = (fileItem['file_name'] as string) || 'unknown';

    try {
      if (this.client) {
        const url = (media['url'] as string) || '';
        const aesKey = (media['aes_key'] as string) || '';
        const encParam = (media['encrypt_query_param'] as string) || '';

        const fileData = await this.client.downloadMedia(url, aesKey, encParam);
        const filePath = path.join(this.mediaDir, `wechat_file_${Date.now()}_${fileName}`);
        fs.writeFileSync(filePath, fileData);

        const sessionId = `wechat:${fromUserId}`;
        const rawMsg = makeRawInput(
          `[文件: ${fileName}]`,
          [filePath],
          sessionId,
          contextToken,
          fromUserId,
        );
        await this.send(rawMsg);
      }
    } catch (err) {
      console.error('[WeChatReceiver] 文件下载失败:', err);
    }
  }

  /** 处理视频消息 */
  private async _handleVideoItem(
    item: Record<string, unknown>,
    _fromUserId: string,
    _toUserId: string,
    _contextToken: string,
  ): Promise<void> {
    // 视频消息暂不处理（太重量级），仅记录
    const videoItem = item['video_item'] as Record<string, unknown> || {};
    const duration = videoItem['duration'] || 0;
    console.log(`[WeChatReceiver] 收到视频消息 (${duration}s)，暂不处理`);
  }

  // ─── 去重逻辑 ────────────────────────────────────

  /** 检查文本内容是否重复 */
  private _isTextDuplicate(text: string): boolean {
    const now = Date.now();
    // 清理过期条目
    this._textDedup = this._textDedup.filter(
      (e) => now - e.timestamp < TEXT_DEDUP_TTL_MS,
    );

    // 检查是否有相同内容
    if (this._textDedup.some((e) => e.content === text)) {
      return true;
    }

    this._textDedup.push({ content: text, timestamp: now });
    return false;
  }

  // ─── Token 持久化 ──────────────────────────────────

  private _loadTokenFromFile(): string {
    try {
      if (fs.existsSync(this.botTokenFile)) {
        return fs.readFileSync(this.botTokenFile, 'utf-8').trim();
      }
    } catch {
      // 忽略
    }
    return '';
  }

  private _saveTokenToFile(token: string): void {
    try {
      const dir = path.dirname(this.botTokenFile);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(this.botTokenFile, token, 'utf-8');
    } catch {
      // 忽略
    }
  }
}
