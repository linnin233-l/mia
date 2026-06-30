import { useEffect, useState } from 'react'
import { Table, Button, Input, Modal, Tag, Space, message } from 'antd'
import { fetchSessions, createSession, renameSession, deleteSession, activateSession } from '../api'

export default function SessionsPage() {
  const [sessions, setSessions] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [createVisible, setCreateVisible] = useState(false)
  const [renameVisible, setRenameVisible] = useState(false)
  const [newName, setNewName] = useState('')
  const [target, setTarget] = useState<any>(null)

  const load = async () => { setLoading(true); const s = await fetchSessions(); setSessions(s.sessions || []); setLoading(false) }
  useEffect(() => { load() }, [])

  const cols = [
    { title: '名称', dataIndex: 'name' },
    { title: '来源', dataIndex: 'source', width: 100, render: (v: string) => <Tag>{v}</Tag> },
    { title: '轮次', dataIndex: 'turn_count', width: 80 },
    { title: '创建时间', dataIndex: 'created_at', width: 170, render: (v: string) => v?.slice(0, 16) },
    { title: '操作', key: 'action', width: 280,
      render: (_: any, row: any) => (
        <Space>
          <Button size="small" type="primary" onClick={() => { activateSession(row.session_id); load() }}>切换</Button>
          <Button size="small" onClick={() => { setTarget(row); setNewName(row.name); setRenameVisible(true) }}>重命名</Button>
          <Button size="small" danger disabled={sessions.length <= 1} onClick={() => { deleteSession(row.session_id); load() }}>删除</Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3>会话管理</h3>
        <Button type="primary" onClick={() => { setNewName(''); setCreateVisible(true) }}>新建会话</Button>
      </div>
      <Table rowKey="session_id" columns={cols} dataSource={sessions} loading={loading} size="small" />
      <Modal title="新建会话" open={createVisible} onCancel={() => setCreateVisible(false)} onOk={async () => {
        if (!newName.trim()) return; await createSession(newName.trim()); setNewName(''); setCreateVisible(false); load()
      }}><Input placeholder="会话名称" value={newName} onChange={e => setNewName(e.target.value)} /></Modal>
      <Modal title="重命名" open={renameVisible} onCancel={() => setRenameVisible(false)} onOk={async () => {
        if (!newName.trim() || !target) return; await renameSession(target.session_id, newName.trim()); setRenameVisible(false); load()
      }}><Input value={newName} onChange={e => setNewName(e.target.value)} /></Modal>
    </div>
  )
}