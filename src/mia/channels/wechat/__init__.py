"""
微信个人号渠道 — iLink Bot API 集成

基于腾讯 iLink Bot API (https://ilinkai.weixin.qq.com)，
使用长轮询接收消息、HTTP 发送消息、QR 码扫码登录。

组件:
  - receiver.py: WeChatReceiverAgent — 入站长轮询 + SILK 解码
  - sender.py: WeChatSenderAgent — 出站消息发送 (TTS + CDN)
  - client.py: ILinkClient — iLink HTTP API 异步客户端
  - utils.py: AES-128-ECB 加解密 + 请求头生成
"""

from mia.channels.wechat.client import ILinkClient
from mia.channels.wechat.receiver import WeChatReceiverAgent
from mia.channels.wechat.sender import WeChatSenderAgent

__all__ = ["ILinkClient", "WeChatReceiverAgent", "WeChatSenderAgent"]
