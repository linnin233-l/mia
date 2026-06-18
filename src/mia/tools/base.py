"""
Tool 抽象类 — 所有工具的基类

TaskAgent 通过调用 Tool.execute() 来完成具体操作。
每个 Tool 需要定义 name、description、parameters(JSON Schema)。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolResult:
    """工具执行结果"""

    success: bool
    """是否执行成功"""

    data: Any = None
    """执行结果数据 (成功时)"""

    error: Optional[str] = None
    """错误信息 (失败时)"""


class Tool(ABC):
    """工具抽象基类

    子类必须定义:
      - name: 工具名称
      - description: 工具描述 (给 LLM 看)
      - parameters: JSON Schema 参数定义
      - execute(): 执行逻辑

    示例:
        class CalculatorTool(Tool):
            name = "calculator"
            description = "执行数学计算"
            parameters = {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "数学表达式"}
                },
                "required": ["expression"],
            }

            async def execute(self, expression: str) -> ToolResult:
                try:
                    result = eval(expression)
                    return ToolResult(success=True, data=result)
                except Exception as e:
                    return ToolResult(success=False, error=str(e))
    """

    name: str = ""
    description: str = ""
    parameters: dict = field(default_factory=dict)

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        执行工具操作

        Args:
            **kwargs: 根据 parameters JSON Schema 定义的参数

        Returns:
            ToolResult — 执行结果
        """
        ...
