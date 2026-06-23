/**
 * TUI 边框测试 — 交替屏幕，原地刷新
 *
 * npm run tui
 */

import readline from 'node:readline';

const B = {
  tl: '┌', tr: '┐', bl: '└', br: '┘',
  h: '─', v: '│',
  hl: '├', hr: '┤',
};

function draw() {
  const w = process.stdout.columns || 80;
  const h = process.stdout.rows || 24;
  const iw = w - 2;

  const lines: string[] = [];
  lines.push(B.tl + B.h.repeat(iw) + B.tr);

  // Header
  const title = ' MIA TUI | ' + w + 'x' + h + ' ';
  const tp = Math.max(0, iw - title.length);
  lines.push(B.v + title + ' '.repeat(tp) + B.v);

  // Divider
  lines.push(B.hl + B.h.repeat(iw) + B.hr);

  // Content
  for (let y = 3; y < h - 1; y++) {
    if (y === h - 2) {
      const hint = ' Ctrl+C 退出 ';
      lines.push(B.v + ' '.repeat(Math.max(0, iw - hint.length)) + hint + B.v);
    } else {
      lines.push(B.v + ' '.repeat(iw) + B.v);
    }
  }

  lines.push(B.bl + B.h.repeat(iw) + B.br);

  // 仅归位，不清屏（交替屏幕本身就是干净的，清屏反而可能吞首行）
  process.stdout.write('\x1b[H' + lines.join('\n'));
}

function main() {
  readline.emitKeypressEvents(process.stdin);
  if (process.stdin.isTTY) {
    process.stdin.setRawMode(true);
  }

  // 交替屏幕 + 隐藏光标
  process.stdout.write('\x1b[?1049h\x1b[?25l');
  draw();

  process.stdout.on('resize', draw);

  process.stdin.on('keypress', (_str, key) => {
    if (key.ctrl && key.name === 'c') {
      cleanup();
      process.exit(0);
    }
  });
}

function cleanup() {
  process.stdout.write('\x1b[?1049l\x1b[?25h');
  if (process.stdin.isTTY) {
    process.stdin.setRawMode(false);
  }
  process.stdin.removeAllListeners('keypress');
  process.stdout.removeAllListeners('resize');
}

main();
