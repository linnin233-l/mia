/**
 * iLink Bot HTTP 客户端 — 微信个人号 Bot API 异步封装
 *
 * 所有 iLink API 端点都在 https://ilinkai.weixin.qq.com 下。
 * 协议: HTTP/JSON，无需第三方 SDK。
 *
 * 与 Python 版 channels/wechat/client.py 保持 1:1 语义映射。
 */

import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import { makeHeaders, aesEcbDecrypt, aesEcbEncrypt } from './utils.js';

// ─── 常量 ──────────────────────────────────────────────

const DEFAULT_BASE_URL = 'https://ilinkai.weixin.qq.com';
const CHANNEL_VERSION = '2.0.1';
const GETUPDATES_TIMEOUT_MS = 45_000;
const DEFAULT_TIMEOUT_MS = 15_000;
const QRCODE_STATUS_TIMEOUT_MS = 60_000;

// ─── 类型 ──────────────────────────────────────────────

/** iLink API 响应通用类型 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type JsonResponse = Record<string, any>;

/** 二维码状态 */
interface QrCodeResponse extends JsonResponse {
  qrcode?: string;
  qrcode_img_content?: string;
  status?: string;
  bot_token?: string;
  baseurl?: string;
}

/** 上传结果 */
export interface UploadResult {
  encrypt_query_param: string;
  aes_key_b64: string;
  rawsize: number;
  filesize: number;
}

/** 获取上传 URL 的响应 */
interface GetUploadUrlResponse extends JsonResponse {
  upload_full_url?: string;
  upload_param?: string;
}

// ─── ILinkClient ────────────────────────────────────────

/**
 * ILinkClient — 微信 iLink Bot API 异步 HTTP 客户端
 *
 * 封装所有 iLink API 调用，包括认证、消息收发、媒体上传下载。
 */
export class ILinkClient {
  private botToken: string;
  private baseUrl: string;

  constructor(botToken = '', baseUrl = DEFAULT_BASE_URL) {
    this.botToken = botToken;
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  // ─── 内部辅助方法 ──────────────────────────────────

  /** 构建完整 API URL */
  private _url(path: string): string {
    return `${this.baseUrl}/${path.replace(/^\//, '')}`;
  }

  /** 发送 GET 请求 */
  private async _get(
    path: string,
    params?: Record<string, string | number>,
    timeoutMs = DEFAULT_TIMEOUT_MS,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ): Promise<any> {
    const url = new URL(this._url(path));
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        url.searchParams.set(k, String(v));
      }
    }

    const headers = makeHeaders(this.botToken);
    const resp = await fetch(url.toString(), {
      method: 'GET',
      headers,
      signal: AbortSignal.timeout(timeoutMs),
    });

    if (!resp.ok) {
      throw new Error(`iLink GET ${path} failed: HTTP ${resp.status}`);
    }

    return resp.json();
  }

  /** 发送 POST 请求 */
  private async _post(
    path: string,
    body: Record<string, unknown>,
    timeoutMs = DEFAULT_TIMEOUT_MS,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ): Promise<any> {
    const headers = makeHeaders(this.botToken);
    const resp = await fetch(this._url(path), {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    });

    if (!resp.ok) {
      throw new Error(`iLink POST ${path} failed: HTTP ${resp.status}`);
    }

    return resp.json();
  }

  // ─── 认证 API ──────────────────────────────────────

  /** 获取登录二维码 */
  async getBotQrcode(): Promise<QrCodeResponse> {
    return this._get('ilink/bot/get_bot_qrcode', { bot_type: 3 });
  }

  /** 轮询二维码扫码状态 */
  async getQrcodeStatus(qrcode: string): Promise<QrCodeResponse> {
    return this._get(
      'ilink/bot/get_qrcode_status',
      { qrcode },
      QRCODE_STATUS_TIMEOUT_MS,
    );
  }

  /**
   * 阻塞等待二维码被扫码确认（最长 300 秒）
   *
   * @returns [botToken, baseUrl]
   */
  async waitForLogin(
    qrcode: string,
    pollIntervalMs = 1500,
    maxWaitMs = 300_000,
  ): Promise<[string, string]> {
    const deadline = Date.now() + maxWaitMs;

    while (Date.now() < deadline) {
      let data: QrCodeResponse;
      try {
        data = await this.getQrcodeStatus(qrcode);
      } catch {
        await sleep(pollIntervalMs);
        continue;
      }

      const status = data.status || '';
      if (status === 'confirmed') {
        const token = data.bot_token || '';
        const baseUrl = data.baseurl || this.baseUrl;
        return [token, baseUrl];
      }
      if (status === 'expired') {
        throw new Error('WeChat QR code expired, please retry login');
      }

      await sleep(pollIntervalMs);
    }

    throw new Error(`WeChat QR code not scanned within ${maxWaitMs}ms`);
  }

  // ─── 消息收发 API ──────────────────────────────────

  /** 长轮询获取新消息（hold 最多 35 秒） */
  async getupdates(cursor = ''): Promise<JsonResponse> {
    const body: Record<string, unknown> = {
      get_updates_buf: cursor,
      base_info: { channel_version: CHANNEL_VERSION },
    };
    return this._post('ilink/bot/getupdates', body, GETUPDATES_TIMEOUT_MS);
  }

  /** 发送消息到微信用户 */
  async sendmessage(msg: Record<string, unknown>): Promise<JsonResponse> {
    return this._post('ilink/bot/sendmessage', {
      msg,
      base_info: { channel_version: CHANNEL_VERSION },
    });
  }

  /** 便捷方法：发送纯文本消息 */
  async sendText(
    toUserId: string,
    text: string,
    contextToken: string,
  ): Promise<JsonResponse> {
    return this.sendmessage({
      from_user_id: '',
      to_user_id: toUserId,
      client_id: crypto.randomUUID(),
      message_type: 2,   // BOT
      message_state: 2,  // FINISH
      context_token: contextToken,
      item_list: [{ type: 1, text_item: { text } }],
    });
  }

  // ─── 媒体辅助方法 ──────────────────────────────────

  /**
   * 下载 CDN 媒体文件并可选解密
   */
  async downloadMedia(
    url: string,
    aesKeyB64 = '',
    encryptQueryParam = '',
  ): Promise<Buffer> {
    let downloadUrl: string;

    if (encryptQueryParam) {
      const cdnBase = 'https://novac2c.cdn.weixin.qq.com/c2c';
      const enc = encodeURIComponent(encryptQueryParam);
      downloadUrl = `${cdnBase}/download?encrypted_query_param=${enc}`;
    } else if (url.startsWith('http')) {
      downloadUrl = url;
    } else {
      throw new Error(
        `Cannot download media: no valid HTTP URL. url=${url.slice(0, 40)}`,
      );
    }

    const resp = await fetch(downloadUrl, {
      signal: AbortSignal.timeout(60_000),
    });

    if (!resp.ok) {
      throw new Error(`CDN download failed: HTTP ${resp.status}`);
    }

    const arrayBuf = await resp.arrayBuffer();
    let data: Buffer = Buffer.from(new Uint8Array(arrayBuf));
    if (aesKeyB64) {
      data = aesEcbDecrypt(data, aesKeyB64);
    }
    return data;
  }

  /** 获取媒体文件上传 URL 和参数 */
  async getUploadUrl(
    filekey: string,
    mediaType: number,
    toUserId: string,
    rawsize: number,
    rawfilemd5: string,
    filesize: number,
    aeskey: string,
    noNeedThumb = true,
  ): Promise<GetUploadUrlResponse> {
    return this._post('ilink/bot/getuploadurl', {
      filekey,
      media_type: mediaType,
      to_user_id: toUserId,
      rawsize,
      rawfilemd5,
      filesize,
      aeskey,
      no_need_thumb: noNeedThumb,
      base_info: { channel_version: CHANNEL_VERSION },
    });
  }

  /**
   * 上传并加密媒体文件到微信 CDN（完整流程）
   */
  async uploadMedia(
    filePath: string,
    mediaType: number,
    toUserId: string,
  ): Promise<UploadResult> {
    // 读取原始文件
    const rawData = await fs.readFile(filePath);
    const rawsize = rawData.length;
    const rawfilemd5 = crypto.createHash('md5').update(rawData).digest('hex');

    // 生成 AES 密钥和 filekey
    const aesKeyRawBytes = crypto.randomBytes(16);
    const aesKeyHex = aesKeyRawBytes.toString('hex');              // 32 hex chars
    const aesKeyForMsg = Buffer.from(aesKeyHex).toString('base64'); // base64(hex_string)
    const aesKeyB64ForEncrypt = aesKeyRawBytes.toString('base64');  // base64(raw bytes)
    const filekey = crypto.randomBytes(16).toString('hex');

    // AES-128-ECB 加密 + PKCS7 padding
    const encryptedData = aesEcbEncrypt(rawData, aesKeyB64ForEncrypt);
    const filesize = encryptedData.length;

    // 获取上传 URL
    const uploadResp = await this.getUploadUrl(
      filekey,
      mediaType,
      toUserId,
      rawsize,
      rawfilemd5,
      filesize,
      aesKeyHex,
    );

    let uploadUrl = uploadResp.upload_full_url || '';
    if (!uploadUrl) {
      const uploadParam = uploadResp.upload_param || '';
      if (uploadParam) {
        const cdnBase = 'https://novac2c.cdn.weixin.qq.com/c2c';
        const encParam = encodeURIComponent(uploadParam);
        uploadUrl = `${cdnBase}/upload?encrypted_query_param=${encParam}&filekey=${filekey}`;
      } else {
        throw new Error(
          `No upload_full_url or upload_param in getuploadurl response`,
        );
      }
    }

    // 上传加密文件到 CDN
    const resp = await fetch(uploadUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: encryptedData,
      signal: AbortSignal.timeout(120_000),
    });

    if (!resp.ok) {
      throw new Error(`CDN upload failed: HTTP ${resp.status}`);
    }

    // 从响应头获取下载参数
    const encryptQueryParam =
      resp.headers.get('x-encrypted-param') ||
      resp.headers.get('X-Encrypted-Param') ||
      '';

    if (!encryptQueryParam) {
      throw new Error(
        'upload_media failed: CDN did not return encrypt_query_param',
      );
    }

    return {
      encrypt_query_param: encryptQueryParam,
      aes_key_b64: aesKeyForMsg,
      rawsize,
      filesize,
    };
  }

  /** 发送图片消息 */
  async sendImage(
    toUserId: string,
    imagePath: string,
    contextToken: string,
  ): Promise<JsonResponse> {
    const uploadResult = await this.uploadMedia(imagePath, 1, toUserId);

    return this.sendmessage({
      to_user_id: toUserId,
      client_id: crypto.randomUUID(),
      message_type: 2,
      message_state: 2,
      context_token: contextToken,
      item_list: [{
        type: 2,
        image_item: {
          media: {
            encrypt_query_param: uploadResult.encrypt_query_param,
            aes_key: uploadResult.aes_key_b64,
            encrypt_type: 1,
          },
          mid_size: uploadResult.filesize,
        },
      }],
    });
  }

  /** 发送文件消息 */
  async sendFile(
    toUserId: string,
    filePath: string,
    filename: string,
    contextToken: string,
  ): Promise<JsonResponse> {
    const uploadResult = await this.uploadMedia(filePath, 3, toUserId);

    return this.sendmessage({
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
          file_name: filename,
          len: String(uploadResult.rawsize),
        },
      }],
    });
  }
}

// ─── 工具函数 ──────────────────────────────────────────

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
