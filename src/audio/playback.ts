/**
 * Audio Playback — 音频播放工具
 *
 * 跨平台音频播放。
 * 需要可选依赖: sound-play (npm) 或系统级播放器 (ffplay/aplay/afplay)
 *
 * 与 Python 版 audio/playback.py 保持 1:1 语义映射。
 */

import { execSync, spawn } from 'node:child_process';

/**
 * 播放音频文件 (WAV/FLAC/OGG/MP3 等)
 *
 * 支持的回退策略:
 *   1. 尝试 ffplay (ffmpeg 套件)
 *   2. 尝试 aplay (Linux ALSA)
 *   3. 尝试 afplay (macOS)
 *
 * @param filepath - 音频文件路径
 * @param blocking - true = 阻塞等待播放完成, false = 后台播放
 * @returns true 如果开始播放
 */
export function playAudio(filepath: string, blocking = false): boolean {
  const player = detectPlayer();

  if (!player) {
    console.error(
      '  \x1b[33m[警告]\x1b[0m 未检测到可用的音频播放器。\n' +
      '  \x1b[90m请安装 ffmpeg (推荐):\n' +
      '    macOS: brew install ffmpeg\n' +
      '    Linux: apt-get install ffmpeg\n' +
      '    Windows: choco install ffmpeg\x1b[0m',
    );
    return false;
  }

  try {
    const args = buildPlayerArgs(player, filepath);
    const child = spawn(player, args, {
      stdio: 'ignore',
      detached: !blocking,
    });

    if (blocking) {
      // 阻塞等待
      return new Promise<boolean>((resolve) => {
        child.on('exit', (code) => resolve(code === 0));
        child.on('error', () => resolve(false));
        setTimeout(() => resolve(false), 30_000);
      }) as unknown as boolean;
    } else {
      // 后台播放，不等待
      child.unref();
      return true;
    }
  } catch (err) {
    console.error(`  \x1b[33m[警告]\x1b[0m 音频播放失败:`, err);
    return false;
  }
}

/** 检测可用的音频播放器 */
function detectPlayer(): string | null {
  // ffplay (ffmpeg)
  try {
    execSync('ffplay -version', { stdio: 'ignore' });
    return 'ffplay';
  } catch { /* not found */ }

  // aplay (Linux)
  try {
    execSync('aplay --version', { stdio: 'ignore' });
    return 'aplay';
  } catch { /* not found */ }

  // afplay (macOS)
  try {
    execSync('which afplay', { stdio: 'ignore' });
    return 'afplay';
  } catch { /* not found */ }

  return null;
}

/** 构建播放器命令行参数 */
function buildPlayerArgs(player: string, filepath: string): string[] {
  switch (player) {
    case 'ffplay':
      return ['-nodisp', '-autoexit', '-loglevel', 'quiet', filepath];
    case 'aplay':
      return ['-q', filepath];
    case 'afplay':
      return [filepath];
    default:
      return [filepath];
  }
}
