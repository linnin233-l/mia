/**
 * Audio Recorder — 麦克风录音工具
 *
 * 用于 CLI 交互场景的键盘控制录音。
 * 需要可选依赖: naudiodon + node-wave (跨平台 PortAudio 方案)
 * 或 sox / arecord (系统级方案)
 *
 * 与 Python 版 audio/recorder.py 保持 1:1 语义映射。
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { execSync, spawn, type ChildProcess } from 'node:child_process';

/**
 * 键盘控制的麦克风录音 — 阻塞式
 *
 * 流程:
 *   1. 调用后立即开始录音
 *   2. 等待用户按 Enter 停止
 *   3. 保存为临时 WAV 文件并返回路径
 *
 * 支持的回退策略:
 *   1. 尝试 sox (Linux/macOS)
 *   2. 尝试 arecord (Linux ALSA)
 *   3. 无可用录音工具时返回 null
 *
 * @param sampleRate - 采样率 (Hz)，默认 16000
 * @param channels - 声道数，默认 1
 * @returns 临时 WAV 文件路径，录音为空或失败返回 null
 */
export async function recordUntilKeypress(
  sampleRate = 16000,
  channels = 1,
): Promise<string | null> {
  // 创建临时目录
  const tmpDir = path.join(os.tmpdir(), 'mia_recordings');
  fs.mkdirSync(tmpDir, { recursive: true });

  const tmpFile = path.join(tmpDir, `mia_rec_${Date.now()}.wav`);

  // 检测可用录音工具
  const recorder = detectRecorder();

  if (!recorder) {
    console.error(
      '  \x1b[33m[警告]\x1b[0m 未检测到可用的录音工具。\n' +
      '  \x1b[90m请安装 sox (推荐):\n' +
      '    macOS: brew install sox\n' +
      '    Linux: apt-get install sox\n' +
      '    Windows: choco install sox.portable\x1b[0m',
    );
    return null;
  }

  console.log(`  \x1b[33m[录音]\x1b[0m 使用 ${recorder} 录制... 按 Enter 停止`);

  try {
    // 启动录音进程
    const child = spawnRecorder(recorder, tmpFile, sampleRate, channels);

    // 等待用户按 Enter
    await waitForEnter();

    // 停止录音
    child.kill('SIGTERM');

    // 等待进程退出
    await new Promise<void>((resolve) => {
      child.on('exit', () => resolve());
      setTimeout(resolve, 500);
    });

    // 检查文件
    if (fs.existsSync(tmpFile) && fs.statSync(tmpFile).size > 44) {
      console.log(`  \x1b[32m[OK]\x1b[0m 录音完成 (${tmpFile})`);
      return tmpFile;
    } else {
      console.log('  \x1b[33m[警告]\x1b[0m 未录制到有效音频数据');
      try { fs.unlinkSync(tmpFile); } catch { /* ignore */ }
      return null;
    }
  } catch (err) {
    console.error(`  \x1b[31m[错误]\x1b[0m 录音失败:`, err);
    try { fs.unlinkSync(tmpFile); } catch { /* ignore */ }
    return null;
  }
}

/** 检测可用的录音工具 */
function detectRecorder(): string | null {
  // 尝试 sox
  try {
    execSync('sox --version', { stdio: 'ignore' });
    return 'sox';
  } catch { /* not found */ }

  // 尝试 arecord (Linux)
  try {
    execSync('arecord --version', { stdio: 'ignore' });
    return 'arecord';
  } catch { /* not found */ }

  return null;
}

/** 启动录音子进程 */
function spawnRecorder(
  tool: string,
  outputFile: string,
  sampleRate: number,
  channels: number,
): ChildProcess {

  if (tool === 'sox') {
    // sox -d -r 16000 -c 1 output.wav
    return spawn('sox', [
      '-d',
      '-r', String(sampleRate),
      '-c', String(channels),
      '-b', '16',
      outputFile,
    ]);
  }

  if (tool === 'arecord') {
    // arecord -r 16000 -c 1 -f S16_LE output.wav
    return spawn('arecord', [
      '-r', String(sampleRate),
      '-c', String(channels),
      '-f', 'S16_LE',
      outputFile,
    ]);
  }

  throw new Error(`Unknown recorder: ${tool}`);
}

/** 等待用户按 Enter */
function waitForEnter(): Promise<void> {
  return new Promise((resolve) => {
    const { stdin } = process;
    if (!stdin.isTTY) {
      resolve();
      return;
    }

    const onData = () => {
      stdin.removeListener('data', onData);
      stdin.setRawMode(false);
      resolve();
    };

    stdin.setRawMode(true);
    stdin.resume();
    stdin.once('data', onData);

    // 30 秒超时
    setTimeout(() => {
      stdin.removeListener('data', onData);
      stdin.setRawMode(false);
      resolve();
    }, 30_000);
  });
}
