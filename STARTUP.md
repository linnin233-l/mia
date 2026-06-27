# MIA 启动指南

## 环境要求

- Python 3.11+ (推荐 `D:/CodeNeed/Python311_64/python.exe`)
- Node.js 22+ (Web 前端)
- 依赖安装: `pip install -e ".[dev,audio,wechat]"`

## 配置 (.env)

```
MIMO_API_KEY=your_key_here        # 必填, MiMo API Key
DEEPSEEK_API_KEY=your_key_here    # 可选, 备选 Provider
MIA_TELEGRAM_BOT_TOKEN=xxx        # 可选, Telegram Bot Token
MIA_WECHAT_BOT_TOKEN=xxx          # 可选, 微信 iLink Token
MIA_WECHAT_ENABLED=false          # 可选, 启动时自动启用微信
MIA_TELEGRAM_ENABLED=false        # 可选, 启动时自动启用 Telegram
```

---

## 一、CLI 交互模式

```bash
python -m mia
```

进入交互终端, 直接输入文字开始对话。

### 斜杠命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/quit` | 退出 |
| `/model` | TUI 模型平台配置 (API Key + 模型开关) |
| `/agent` | TUI Agent 模型分配 + 功能开关 |
| `/channel` | TUI 渠道开关 (微信/Telegram) |
| `/interface` | TUI 消息接口管理 (查看Token/扫码/删除) |
| `/session` | TUI 会话管理 (列表/切换/新建/重命名/删除) |
| `/memory` | TUI 记忆浏览器 (分页 + 详情) |
| `/compact` | 压缩对话历史 |
| `/verbose` | 切换详细日志 |
| `/image <path>` | 发送图片 (VL 理解) |
| `/voice <path>` | 发送音频 (多模态理解) |
| `/record` | 麦克风录音 |

---

## 二、单次查询模式

```bash
python -m mia --query "你好"
python -m mia -q "搜索Python新闻"
python -m mia -q "分析图片" --image screenshot.png
python -m mia -q "总结" --voice meeting.mp3
```

| 参数 | 简写 | 说明 |
|------|------|------|
| `--query` | `-q` | 查询文本 |
| `--image` | `-i` | 图片路径 |
| `--voice` | `-v` | 语音文件路径 |

---

## 三、HTTP API 服务模式

```bash
python -m mia --server --port 8080
```

启动后访问:
- API: `http://127.0.0.1:8080`
- 文档: `http://127.0.0.1:8080/docs`

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/api/chat` | 发送消息 |
| `POST` | `/api/chat/stream` | SSE 流式对话 |
| `GET` | `/api/sessions` | 会话列表 |
| `POST` | `/api/sessions` | 新建会话 |
| `PUT` | `/api/sessions/{id}` | 重命名会话 |
| `DELETE` | `/api/sessions/{id}` | 删除会话 |
| `POST` | `/api/sessions/{id}/activate` | 切换会话 |
| `GET` | `/api/sessions/current` | 当前会话 |
| `GET` | `/api/sessions/{id}/history` | 会话历史消息 |
| `GET` | `/api/channels` | 渠道状态 |
| `PUT` | `/api/channels/{name}` | 开关渠道 |
| `GET` | `/api/config` | RuntimeConfig 摘要 |
| `GET` | `/api/models` | 模型列表 |
| `PUT` | `/api/models/{id}` | 开关模型 |
| `PUT` | `/api/agents/{name}` | Agent 模型分配 |
| `GET` | `/api/agents/capabilities` | 能力要求映射 |
| `GET` | `/api/memory` | 分页记忆 (参数: page, page_size) |
| `POST` | `/api/compact` | 压缩记忆 |
| `GET` | `/api/interface/{name}` | 接口绑定详情 |
| `PUT` | `/api/interface/{name}/token` | 更新 Token |
| `POST` | `/api/interface/wechat/qrcode` | 微信扫码登录 |
| `GET` | `/api/interface/wechat/qrcode/{qrcode}` | 轮询扫码状态 |

---

## 四、Web 前端

```bash
cd mia-web
npm install
npm run dev
```

访问 `http://localhost:5173`

### 页面路由

| 路由 | 页面 | 功能 |
|------|------|------|
| `/chat` | 聊天 | 消息收发 + 会话切换 |
| `/sessions` | 会话管理 | 新建/重命名/删除/切换 |
| `/memory` | 记忆浏览 | 分页 + 详情 + 压缩 |
| `/settings` | 设置 | 模型/Agent/渠道 配置 |

### 渠道消息

Server 模式启动后, 微信和 Telegram 渠道 Agent 会在后台常驻运行:
- 微信: iLink Bot 长轮询 (需 token)
- Telegram: Bot API 长轮询 (需 token)
- 渠道消息自动路由到对应 Sender

---

## 五、渠道开关持久化

通过 Web 或 CLI 开启渠道后, 状态自动保存到 `data/config.json`。
下次启动时自动恢复, 无需重复配置。

```json
{
  "wechat_enabled": true,
  "telegram_enabled": true,
  "scheduler_model": "mimo-v2.5-pro",
  "receiver_vision_enabled": true,
  ...
}
```
