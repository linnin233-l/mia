import { useState, useRef, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Input, Button, Card, Space, Spin } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import { sendMessage } from '../api'

export default function ChatPage() {
  const { messages, setMessages } = useOutletContext<any>()
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, loading])

  const handleSend = async () => {
    if (!text.trim()) return
    const userMsg = { role: 'user', content: text }
    setMessages((prev: any[]) => [...prev, userMsg])
    setText('')
    setLoading(true)
    try {
      const res = await sendMessage(text)
      setMessages((prev: any[]) => [...prev, { role: 'assistant', content: res.response }])
    } catch (e: any) {
      setMessages((prev: any[]) => [...prev, { role: 'assistant', content: 'Error: ' + (e?.message || 'failed') }])
    } finally { setLoading(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ flex: 1, overflow: 'auto', padding: 8 }}>
        {messages.map((m: any, i: number) => (
          <div key={i} style={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start', marginBottom: 12 }}>
            <Card size="small" style={{ maxWidth: '70%', background: m.role === 'user' ? '#1677ff' : '#f5f5f5', color: m.role === 'user' ? '#fff' : '#333' }}>
              <div style={{ fontSize: 11, opacity: 0.6, marginBottom: 4 }}>{m.role === 'user' ? 'You' : 'MIA'}</div>
              <div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>
            </Card>
          </div>
        ))}
        {loading && <div style={{ textAlign: 'center', padding: 12 }}><Spin /> 思考中...</div>}
        <div ref={bottomRef} />
      </div>
      <div style={{ borderTop: '1px solid #f0f0f0', padding: '8px 0' }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input.TextArea value={text} onChange={e => setText(e.target.value)} placeholder="输入消息... (Enter 发送)" rows={2} disabled={loading}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }} />
          <Button type="primary" icon={<SendOutlined />} onClick={handleSend} loading={loading} disabled={!text.trim()} />
        </Space.Compact>
      </div>
    </div>
  )
}