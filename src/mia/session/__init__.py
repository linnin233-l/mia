"""
MIA Session Management — 会话持久化与切换

提供跨重启的会话系统:
  - SessionInfo: 会话元数据（ID、名称、来源、时间戳）
  - SessionState: 会话运行时状态（对话历史、临时记忆）
  - SessionManager: 会话 CRUD + 状态持久化

存储布局:
  data/sessions/
    index.json              # 会话索引（始终加载）
    states/<session_id>.json  # 会话状态（按需加载）
"""

from mia.session.manager import SessionManager, SessionInfo, SessionState

__all__ = ["SessionManager", "SessionInfo", "SessionState"]
