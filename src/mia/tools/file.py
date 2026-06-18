"""
File 工具 — 读写工作目录下的文件

安全约束:
  - 路径沙箱: 只能访问工作目录内的文件
  - 不能访问 ../
"""

from pathlib import Path
from typing import Optional

from loguru import logger

from mia.tools.base import Tool, ToolResult


class FileTool(Tool):
    """文件读写工具 — 受沙箱保护"""

    name = "file"
    description = (
        "读写工作目录下的文件。支持: 读取文件内容、写入文件、列出目录。"
        "注意: 只能访问工作目录内的文件，不能访问系统文件。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "write", "list"],
                "description": "操作类型: read(读), write(写), list(列目录)",
            },
            "path": {
                "type": "string",
                "description": "相对于工作目录的文件路径",
            },
            "content": {
                "type": "string",
                "description": "要写入的内容 (仅 write 操作需要)",
            },
        },
        "required": ["operation", "path"],
    }

    def __init__(self, workspace_dir: Optional[str] = None):
        """
        Args:
            workspace_dir: 工作目录根路径
        """
        self.workspace = Path(workspace_dir or str(
            Path(__file__).parent.parent.parent.parent / "workspace"
        ))
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def execute(
        self,
        operation: str,
        path: str,
        content: Optional[str] = None,
    ) -> ToolResult:
        """
        执行文件操作

        Args:
            operation: read / write / list
            path: 文件路径 (相对于 workspace)
            content: 写入内容

        Returns:
            ToolResult
        """
        # ─── 路径沙箱检查 ──────────────────────────
        try:
            resolved = (self.workspace / path).resolve()
            if not str(resolved).startswith(str(self.workspace.resolve())):
                return ToolResult(
                    success=False,
                    error=f"路径越界: {path} (只允许访问工作目录内的文件)",
                )
        except (ValueError, OSError) as e:
            return ToolResult(success=False, error=f"路径无效: {e}")

        logger.info("[FileTool] {} {}", operation, path)

        try:
            if operation == "read":
                return await self._read(resolved)
            elif operation == "write":
                return await self._write(resolved, content or "")
            elif operation == "list":
                return await self._list(resolved)
            else:
                return ToolResult(success=False, error=f"未知操作: {operation}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _read(self, filepath: Path) -> ToolResult:
        """读取文件内容"""
        if not filepath.exists():
            return ToolResult(success=False, error=f"文件不存在: {filepath.name}")
        if not filepath.is_file():
            return ToolResult(success=False, error=f"不是文件: {filepath.name}")

        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
            # 限制读取长度
            if len(content) > 5000:
                content = content[:5000] + f"\n...(截断，共 {len(content)} 字符)"
            return ToolResult(success=True, data=content)
        except Exception as e:
            return ToolResult(success=False, error=f"读取失败: {e}")

    async def _write(self, filepath: Path, content: str) -> ToolResult:
        """写入文件内容"""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        size = len(content)
        return ToolResult(
            success=True,
            data=f"文件已写入: {filepath.name} ({size} 字符)",
        )

    async def _list(self, dirpath: Path) -> ToolResult:
        """列出目录内容"""
        if not dirpath.exists():
            return ToolResult(success=False, error=f"目录不存在: {dirpath.name}")
        if not dirpath.is_dir():
            return ToolResult(success=False, error=f"不是目录: {dirpath.name}")

        items = []
        for p in sorted(dirpath.iterdir()):
            prefix = "[DIR]" if p.is_dir() else "[FILE]"
            items.append(f"  {prefix} {p.name}")

        if not items:
            return ToolResult(success=True, data="(空目录)")
        return ToolResult(success=True, data="\n".join(items[:50]))
