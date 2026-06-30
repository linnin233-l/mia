import { useEffect, useState } from 'react'
import { Tabs, Table, Button, Switch, Tag, Select, Input, Card, Modal, message } from 'antd'
import { fetchConfig, fetchModels, toggleModel, updateAgent, fetchChannels, toggleChannel, fetchInterfaceDetail, updateInterfaceToken, getQrCode, pollQrCode } from '../api'

function ModelPanel() {
  const [models, setModels] = useState<any[]>([]); const [loading, setLoading] = useState(false)
  useEffect(() => { (async () => { setLoading(true); const d = await fetchModels(); setModels(d.models || []); setLoading(false) })() }, [])
  return (
    <Table rowKey="id" dataSource={models} loading={loading} size="small" pagination={false}
      columns={[
        { title: '模型 ID', dataIndex: 'id', width: 160 },
        { title: '平台', dataIndex: 'provider', width: 90 },
        { title: '描述', dataIndex: 'desc', ellipsis: true },
        { title: '能力', dataIndex: 'capabilities', width: 260, render: (caps: string[]) => caps.map(c => <Tag key={c} style={{ marginBottom: 2 }}>{c}</Tag>) },
        { title: '启用', width: 80, align: 'center' as const,
          render: (_: any, row: any) => (
            <Switch size="small" checked={row.enabled} disabled={!row.has_key}
              onChange={async (v) => { await toggleModel(row.id, v); const m = models.find(x => x.id === row.id); if (m) m.enabled = v; setModels([...models]) }} />
          ),
        },
      ]} />
  )
}

function AgentPanel() {
  const [cfg, setCfg] = useState<any>({}); const [loading, setLoading] = useState(true)
  useEffect(() => { (async () => { setCfg(await fetchConfig()); setLoading(false) })() }, [])
  if (loading) return <div>Loading...</div>
  const list = [
    { k: 'scheduler', l: 'Scheduler' }, { k: 'task', l: 'TaskAgent' }, { k: 'memory', l: 'MemoryAgent' },
  ]
  const opts = ['mimo-v2.5-pro', 'mimo-v2.5', 'deepseek-v4-pro', 'deepseek-v4-flash']
  return (
    <Table rowKey="k" dataSource={list} size="small" pagination={false}
      columns={[
        { title: 'Agent', dataIndex: 'l', width: 120 },
        { title: '主模型', width: 220, render: (_: any, r: any) => (
          <Select value={cfg[r.k]?.model} size="small" style={{ width: 200 }}
            onChange={async (v) => { await updateAgent(r.k, { model: v }); setCfg({ ...cfg, [r.k]: { ...cfg[r.k], model: v } }) }}>
            {opts.map(m => <Select.Option key={m} value={m}>{m}</Select.Option>)}
          </Select>
        )},
        { title: '备选', width: 220, render: (_: any, r: any) => (
          <Select value={cfg[r.k]?.fallback} size="small" style={{ width: 200 }} allowClear placeholder="None"
            onChange={async (v) => { await updateAgent(r.k, { fallback: v || '' }); setCfg({ ...cfg, [r.k]: { ...cfg[r.k], fallback: v || '' } }) }}>
            {opts.map(m => <Select.Option key={m} value={m}>{m}</Select.Option>)}
          </Select>
        )},
      ]} />
  )
}

function ChannelPanel() {
  const [channels, setChannels] = useState<any>({})
  const [details, setDetails] = useState<any>({})
  const [tokenInput, setTokenInput] = useState<Record<string, string>>({})
  const [editing, setEditing] = useState<Record<string, boolean>>({})
  const [qrVisible, setQrVisible] = useState(false)
  const [qrImage, setQrImage] = useState('')
  const [qrCode, setQrCode] = useState('')
  const [qrStatus, setQrStatus] = useState('')

  const load = async () => {
    setChannels(await fetchChannels())
    setDetails({ wechat: await fetchInterfaceDetail('wechat'), telegram: await fetchInterfaceDetail('telegram') })
  }
  useEffect(() => { load() }, [])

  const save = async (name: string) => {
    const t = tokenInput[name]; if (!t?.trim()) return
    await updateInterfaceToken(name, t.trim())
    setEditing({ ...editing, [name]: false }); load()
    message.success('Token saved')
  }

  const startQr = async () => {
    setQrVisible(true)
    try {
      const d = await getQrCode()
      setQrImage(d.image); setQrCode(d.qrcode); setQrStatus('waiting')
      const timer = setInterval(async () => {
        try {
          const s = await pollQrCode(d.qrcode); setQrStatus(s.status)
          if (s.status === 'confirmed') { clearInterval(timer); load(); setQrVisible(false); message.success('Done') }
          if (s.status === 'expired') { clearInterval(timer); setQrStatus('expired') }
        } catch { }
      }, 2000)
    } catch { }
  }

  return (
    <div>
      <Card title="微信 (iLink Bot)" size="small" style={{ marginBottom: 16 }}
        extra={<Switch checked={channels?.wechat?.enabled} onChange={v => { toggleChannel('wechat', v); load() }} />}>
        <div style={{ fontSize: 13, lineHeight: 2 }}>
          <div>Token: <code>{details?.wechat?.token_masked || 'none'}</code></div>
          {details?.wechat?.file_size > 0 && <div style={{ color: '#999', fontSize: 12 }}>{details.wechat.token_file} | {(details.wechat.file_size / 1024).toFixed(1)}KB | {details.wechat.file_mtime}</div>}
          {editing['wechat'] ? (
            <div style={{ marginTop: 8 }}>
              <Input.Password size="small" placeholder="Token" value={tokenInput['wechat'] || ''} onChange={e => setTokenInput({ ...tokenInput, wechat: e.target.value })} style={{ marginBottom: 4 }} />
              <Button size="small" type="primary" onClick={() => save('wechat')}>Save</Button>
              <Button size="small" onClick={() => setEditing({ ...editing, wechat: false })} style={{ marginLeft: 4 }}>Cancel</Button>
            </div>
          ) : (
            <div style={{ marginTop: 8 }}>
              <Button size="small" onClick={() => { setEditing({ ...editing, wechat: true }); setTokenInput({ ...tokenInput, wechat: '' }) }}>{details?.wechat?.has_token ? 'Update' : 'Set'} Token</Button>
              <Button size="small" style={{ marginLeft: 8 }} onClick={startQr}>扫码登录</Button>
            </div>
          )}
        </div>
      </Card>

      <Card title="Telegram (Bot API)" size="small"
        extra={<Switch checked={channels?.telegram?.enabled} onChange={v => { toggleChannel('telegram', v); load() }} />}>
        <div style={{ fontSize: 13, lineHeight: 2 }}>
          <div>Token: <code>{details?.telegram?.token_masked || 'none'}</code></div>
          {details?.telegram?.file_size > 0 && <div style={{ color: '#999', fontSize: 12 }}>{details.telegram.token_file} | {(details.telegram.file_size / 1024).toFixed(1)}KB | {details.telegram.file_mtime}</div>}
          {editing['telegram'] ? (
            <div style={{ marginTop: 8 }}>
              <Input.Password size="small" placeholder="Token" value={tokenInput['telegram'] || ''} onChange={e => setTokenInput({ ...tokenInput, telegram: e.target.value })} style={{ marginBottom: 4 }} />
              <Button size="small" type="primary" onClick={() => save('telegram')}>Save</Button>
              <Button size="small" onClick={() => setEditing({ ...editing, telegram: false })} style={{ marginLeft: 4 }}>Cancel</Button>
            </div>
          ) : (
            <div style={{ marginTop: 8 }}>
              <Button size="small" onClick={() => { setEditing({ ...editing, telegram: true }); setTokenInput({ ...tokenInput, telegram: '' }) }}>{details?.telegram?.has_token ? 'Update' : 'Set'} Token</Button>
            </div>
          )}
        </div>
      </Card>

      <Modal title="微信扫码登录" open={qrVisible} onCancel={() => setQrVisible(false)} footer={null} width={380}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ marginBottom: 12, fontSize: 13, color: qrStatus === 'confirmed' ? '#52c41a' : qrStatus === 'expired' ? '#ff4d4f' : '#666' }}>
            {qrStatus === 'waiting' ? '请用微信扫描' : qrStatus === 'scanned' ? '已扫描，请确认' : qrStatus === 'confirmed' ? 'OK' : qrStatus === 'expired' ? '已过期' : '获取中...'}
          </div>
          {qrImage && <img src={qrImage} style={{ maxWidth: 250, borderRadius: 8, border: '1px solid #eee' }} />}
          {qrStatus === 'expired' && <div style={{ marginTop: 12 }}><Button size="small" onClick={startQr}>Retry</Button></div>}
        </div>
      </Modal>
    </div>
  )
}

export default function SettingsPage() {
  return (
    <div>
      <h3>系统设置</h3>
      <Tabs defaultActiveKey="models" items={[
        { key: 'models', label: '模型注册表', children: <ModelPanel /> },
        { key: 'agents', label: 'Agent 分配', children: <AgentPanel /> },
        { key: 'channels', label: '渠道配置', children: <ChannelPanel /> },
      ]} />
    </div>
  )
}