import { useEffect, useState } from 'react'
import { Table, Button, Tag, Progress } from 'antd'
import { fetchMemory, compactMemory } from '../api'

export default function MemoryPage() {
  const [entries, setEntries] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  const load = async (p = 1) => { setLoading(true); const d = await fetchMemory(p, 20); setEntries(d.entries || []); setTotal(d.total); setPage(d.page); setLoading(false) }
  useEffect(() => { load(1) }, [])

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3>记忆浏览 ({total} 条)</h3>
        <Button danger onClick={async () => { await compactMemory(); load(1) }}>压缩</Button>
      </div>
      <Table rowKey="id" columns={[
        { title: '内容', dataIndex: 'content', ellipsis: true },
        { title: '分类', dataIndex: 'category', width: 100, render: (v: string) => <Tag>{v}</Tag> },
        { title: '置信度', dataIndex: 'confidence', width: 130, render: (v: number) => <Progress percent={Math.round(v * 100)} size="small" /> },
        { title: '日期', dataIndex: 'created_at', width: 120, render: (v: string) => v?.slice(0, 10) },
      ]} dataSource={entries} loading={loading} size="small"
        expandable={{ expandedRowRender: (row: any) => <div style={{ padding: 12 }}><p>{row.content}</p><p>Key: {row.keywords?.join(', ')}</p><p>Src: {row.source_sessions?.join(', ')}</p></div> }}
        pagination={{ current: page, total, pageSize: 20, onChange: load, showTotal: (t: number) => t + ' entries' }} />
    </div>
  )
}