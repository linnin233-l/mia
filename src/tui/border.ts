/**
 * TUI 边框测试 — 交替屏幕，原地刷新
 */

import readline from 'node:readline';

const B = {
  tl: '┌', tr: '┐', bl: '└', br: '┘',
  h: '─', v: '│',
  hl: '├', hr: '┤',
};

function draw() {
  const w = process.stdout.columns || 80;
  const h = (process.stdout.rows || 24) - 1;
  const iw = w - 2;

  const lines: string[] = [];

  lines.push(B.tl + B.h.repeat(iw) + B.tr);
  const title = ' MIA TUI | ' + w + 'x' + h + ' ';
  lines.push(B.v + title + ' '.repeat(Math.max(0, iw - title.length)) + B.v);
  lines.push(B.hl + B.h.repeat(iw) + B.hr);

  for (let y = 3; y < h - 2; y++) {
    lines.push(B.v + ' '.repeat(iw) + B.v);
  }

  // 纯 ASCII hint，避免 CJK 双列宽导致溢出
  const hint = ' Ctrl+C quit ';
  const pad = Math.max(0, iw - hint.length);
  lines.push(B.v + ' '.repeat(pad) + hint + B.v);
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
    if (key.ctrl && key.name === 'c') {
      // 先退出交替屏幕，再 exit（不留残影）
      process.stdout.write('\x1b[?1049l\x1b[?25h');
      if (process.stdin.isTTY) process.stdin.setRawMode(false);
      process.exit(0);
    }
  });
}

main();
