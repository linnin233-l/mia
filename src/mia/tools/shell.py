"""
Shell 工具 — 执行 Shell 命令

安全约束:
  - 黑名单命令 (rm -rf, sudo, fork bomb 等)
  - 30 秒执行超时
  - 工作目录沙箱
"""

import asyncio
import os
import re
from pathlib import Path
from typing import Optional

from loguru import logger

from mia.tools.base import Tool, ToolResult


# ─── 危险命令黑名单 ────────────────────────────────────

DANGEROUS_PATTERNS = [
    r'rm\s+(-[rRf]+\s+)*[/~]',     # rm -rf / 或 rm -rf ~
    r'sudo\s',                       # sudo
    r'mkfs\.',                       # 格式化磁盘
    r'dd\s+if=',                     # dd 磁盘操作
    r'>\s*/dev/',                    # 写入设备
    r':\(\)\s*\{',                   # fork bomb
    r'chmod\s+(-[Rr]+\s+)?777\s+/', # chmod 777 /
    r'shutdown\s',                   # 关机
    r'reboot\s',                     # 重启
    r'wget\s+.*\|\s*sh',            # 管道下载执行
    r'curl\s+.*\|\s*sh',            # 管道下载执行
]


class ShellTool(Tool):
    """Shell 命令执行工具"""

    name = "shell"
    description = (
        "执行 Shell 命令并返回 stdout/stderr。"
        "适用于: 运行代码、文件操作、系统查询、数据处理。"
        "注意: 命令会在工作目录沙箱中执行，30秒超时。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 Shell 命令",
            },
            "workdir": {
                "type": "string",
                "description": "工作目录 (可选，默认 workspace)",
            },
        },
        "required": ["command"],
    }

    def __init__(self, default_workdir: Optional[str] = None):
        """
        Args:
            default_workdir: 默认工作目录
        """
        self.default_workdir = default_workdir or str(
            Path(__file__).parent.parent.parent.parent / "workspace"
        )
        Path(self.default_workdir).mkdir(parents=True, exist_ok=True)

    async def execute(
        self,
        command: str,
        workdir: Optional[str] = None,
    ) -> ToolResult:
        """
        执行 Shell 命令

        Args:
            command: Shell 命令
            workdir: 工作目录

        Returns:
            ToolResult
        """
        # ─── 安全检查 ───────────────────────────────
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return ToolResult(
                    success=False,
                    error=f"命令被安全策略拦截 (匹配危险模式: {pattern})",
                )

        # ─── 工作目录沙箱 ──────────────────────────
        cwd = workdir or self.default_workdir
        if not Path(cwd).exists():
            return ToolResult(success=False, error=f"工作目录不存在: {cwd}")

        # 确保不能通过 cd ../ 逃逸
        abs_cwd = os.path.abspath(cwd)
        allowed_root = os.path.abspath(self.default_workdir)
        if not abs_cwd.startswith(allowed_root):
            return ToolResult(success=False, error=f"工作目录超出允许范围: {abs_cwd}")

        logger.info("[ShellTool] 执行: {}", command[:100])

        # ─── 执行命令 ──────────────────────────────
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=30,
            )

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode == 0:
                output = stdout_text or "(无输出)"
                return ToolResult(
                    success=True,
                    data=output,
                )
            else:
                return ToolResult(
                    success=False,
                    error=stderr_text or f"命令返回码: {proc.returncode}",
                )

        except asyncio.TimeoutError:
            return ToolResult(success=False, error="命令执行超时 (30秒)")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
