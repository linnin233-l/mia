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
  // 留一行余量，避免终端自动滚动
  const h = (process.stdout.rows || 24) - 1;
  const iw = w - 2;

  const lines: string[] = [];

  // 顶框
  lines.push(B.tl + B.h.repeat(iw) + B.tr);
  // Header
  const title = ' MIA TUI | ' + w + 'x' + h + ' ';
  lines.push(B.v + title + ' '.repeat(Math.max(0, iw - title.length)) + B.v);
  // 分隔
  lines.push(B.hl + B.h.repeat(iw) + B.hr);
  // 内容
  for (let y = 3; y < h - 2; y++) {
    lines.push(B.v + ' '.repeat(iw) + B.v);
  }
  // Ctrl+C
  const hint = ' Ctrl+C 退出 ';
  lines.push(B.v + ' '.repeat(Math.max(0, iw - hint.length)) + hint + B.v);
  // 底框
  lines.push(B.bl + B.h.repeat(iw) + B.br);

  process.stdout.write('\x1b[H' + lines.join('\n'));
}

function main() {
  readline.emitKeypressEvents(process.stdin);
  if (process.stdin.isTTY) process.stdin.setRawMode(true);

  process.stdout.write('\x1b[?1049h\x1b[?25l');
  draw();
  process.stdout.on('resize', draw);

  process.stdin.on('keypress', (_str, key) => {
    if (key.ctrl && key.name === 'c') { cleanup(); process.exit(0); }
  });
}

function cleanup() {
  process.stdout.write('\x1b[?1049l\x1b[?25h');
  if (process.stdin.isTTY) process.stdin.setRawMode(false);
  process.stdin.removeAllListeners('keypress');
  process.stdout.removeAllListeners('resize');
}

main();
