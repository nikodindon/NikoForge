"""
Core module pour NikoForge
"""

from .agent import Agent
from .tools import Tools, ToolResult, format_tool_result
from .context import ContextManager
from .prompt import get_system_prompt

__all__ = [
    'Agent',
    'Tools',
    'ToolResult',
    'format_tool_result',
    'ContextManager',
    'get_system_prompt'
]