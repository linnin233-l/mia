/**
 * 微信 iLink 渠道工具函数 — AES-128-ECB 加解密 + HTTP 请求头生成
 *
 * iLink Bot API 的媒体文件（图片/文件/视频）存储在微信 CDN 上，
 * 使用 AES-128-ECB + PKCS7 加密。
 *
 * Node.js 原生 crypto 模块替代 Python pycryptodome。
 *
 * 与 Python 版 channels/wechat/utils.py 保持 1:1 语义映射。
 */

import crypto from 'node:crypto';

// ─── HTTP 请求头 ─────────────────────────────────────────

/**
 * 构建 iLink API HTTP 请求头
 *
 * 每个请求包含:
 *   - Content-Type: application/json
 *   - AuthorizationType: ilink_bot_token（固定值）
 *   - X-WECHAT-UIN: base64(random_uint32) — 反重放随机值
 *   - Authorization: Bearer <bot_token>（仅当 token 可用时）
 *
 * @param botToken - QR 码登录后获取的 bearer token
 * @returns HTTP 请求头对象
 */
export function makeHeaders(botToken = ''): Record<string, string> {
  // 生成随机 UIN 作为反重放措施（与官方 SDK 行为一致）
  const uinVal = crypto.randomInt(0, 0xffffffff).toString();
  const uinB64 = Buffer.from(uinVal).toString('base64');

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    AuthorizationType: 'ilink_bot_token',
    'X-WECHAT-UIN': uinB64,
  };

  if (botToken) {
    headers['Authorization'] = `Bearer ${botToken}`;
  }

  return headers;
}

// ─── AES-128-ECB 解密 ────────────────────────────────────

/**
 * AES-128-ECB 解密微信 CDN 媒体文件
 *
 * 自动检测三种密钥格式（与官方 TypeScript SDK 的 parseAesKey 逻辑一致）:
 *   1. 32/48/64 字符 hex 字符串 → Buffer.from(hex, 'hex')
 *   2. Base64 编码（16 字节原始 key 或 32 字符 hex）
 *   3. 其他格式 → 尝试直接使用
 *
 * @param data - 加密的字节数据（从 CDN 下载）
 * @param keyB64 - AES 密钥字符串（三种格式之一）
 * @returns 解密后的字节数据（已去除 PKCS7 padding）
 */
export function aesEcbDecrypt(data: Buffer, keyB64: string): Buffer {
  // ─── 自动检测密钥格式 ──────────────────────────────
  let key: Buffer;
  const raw = keyB64.trim();

  // 格式: 纯 hex 字符串（32/48/64 字符）
  if (
    (raw.length === 32 || raw.length === 48 || raw.length === 64) &&
    /^[0-9a-fA-F]+$/.test(raw)
  ) {
    key = Buffer.from(raw, 'hex');
  } else {
    // 格式: Base64 编码
    let decoded: Buffer;
    try {
      decoded = Buffer.from(raw + '==', 'base64');
    } catch {
      decoded = Buffer.from(raw, 'utf-8');
    }

    if (decoded.length === 16) {
      // Format A: base64(raw 16 bytes) — 图片使用此格式
      key = decoded;
    } else if (
      decoded.length === 32 &&
      /^[0-9a-fA-F]+$/.test(decoded.toString('ascii'))
    ) {
      // Format B: base64(hex string) — 文件/语音/视频使用此格式
      key = Buffer.from(decoded.toString('ascii'), 'hex');
    } else {
      key = decoded;
    }
  }

  if (![16, 24, 32].includes(key.length)) {
    throw new Error(
      `Invalid AES key length: ${key.length} (from keyB64=${raw.slice(0, 20)})`,
    );
  }

  // ─── AES-128-ECB 解密 ──────────────────────────────
  const decipher = crypto.createDecipheriv(
    'aes-128-ecb',
    key.slice(0, 16),
    Buffer.alloc(0),
  );
  decipher.setAutoPadding(false); // 手动处理 PKCS7 padding

  const decrypted = Buffer.concat([decipher.update(data), decipher.final()]);

  // 去除 PKCS7 padding
  return pkcs7Unpad(decrypted);
}

// ─── AES-128-ECB 加密 ────────────────────────────────────

/**
 * AES-128-ECB 加密 + PKCS7 padding — 用于上传媒体到微信 CDN
 *
 * @param data - 原始文件字节
 * @param keyB64 - Base64 编码的 16 字节 AES 密钥
 * @returns 加密后的字节数据
 */
export function aesEcbEncrypt(data: Buffer, keyB64: string): Buffer {
  const key = Buffer.from(keyB64, 'base64');
  const padded = pkcs7Pad(data, 16);

  const cipher = crypto.createCipheriv(
    'aes-128-ecb',
    key.slice(0, 16),
    Buffer.alloc(0),
  );
  cipher.setAutoPadding(false);

  return Buffer.concat([cipher.update(padded), cipher.final()]);
}

/**
 * 生成加密安全的 16 字节随机 AES 密钥
 *
 * @returns Base64 编码的 16 字节 AES 密钥
 */
export function generateAesKeyB64(): string {
  return crypto.randomBytes(16).toString('base64');
}

// ─── PKCS7 Padding ──────────────────────────────────────

/** PKCS7 填充 */
function pkcs7Pad(data: Buffer, blockSize: number): Buffer {
  const padLen = blockSize - (data.length % blockSize);
  const padding = Buffer.alloc(padLen, padLen);
  return Buffer.concat([data, padding]);
}

/** PKCS7 去填充 */
function pkcs7Unpad(data: Buffer): Buffer {
  const padLen = data[data.length - 1]!;
  if (padLen < 1 || padLen > 16) {
    // 不是有效的 PKCS7 padding，返回原数据
    return data;
  }
  return data.subarray(0, data.length - padLen);
}
