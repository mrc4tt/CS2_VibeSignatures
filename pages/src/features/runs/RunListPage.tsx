import { ReloadOutlined } from '@ant-design/icons'
import { useInfiniteQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Input, Progress, Select, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, listRuns } from '../../api/client'
import type { RunStatus, RunView } from '../../api/types'
import { useApiConfig } from '../../app/apiContext'
import { StatusTag } from '../../components/StatusTag'
import { statusLabel } from '../../components/status'

const STATUS_OPTIONS: RunStatus[] = [
  'queued',
  'starting',
  'running',
  'succeeded',
  'failed',
  'aborted',
  'stale',
]

function formatTime(value: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '—'
}

function columns(): ColumnsType<RunView> {
  return [
    {
      title: 'Run',
      dataIndex: 'run_id',
      width: 220,
      render: (value: string) => <Link to={`/runs/${encodeURIComponent(value)}`}>{value}</Link>,
    },
    { title: '状态', dataIndex: 'effective_status', width: 110, render: (value) => <StatusTag status={value} /> },
    { title: '版本', dataIndex: 'gamever', width: 100, render: (value) => value || '—' },
    { title: 'Agent', dataIndex: 'agent', width: 100, render: (value) => value || '—' },
    {
      title: '进度',
      dataIndex: 'progress',
      width: 220,
      render: (progress: RunView['progress']) => (
        <Progress percent={progress.percent} size="small" status={progress.failed ? 'exception' : 'normal'} />
      ),
    },
    { title: '当前任务', dataIndex: 'current_skill_id', ellipsis: true, render: (value) => value || '—' },
    { title: '创建时间', dataIndex: 'created_at', width: 170, render: formatTime },
  ]
}

function errorDescription(error: Error): string {
  if (error instanceof ApiError && error.detail.code === 'redis_unavailable') return 'Redis 状态服务不可用。'
  return '无法读取 Run 列表，请检查 API 地址、CORS 和本地网络访问权限。'
}

interface ToolbarProps {
  status?: RunStatus
  gamever: string
  refreshing: boolean
  onStatus(status?: RunStatus): void
  onGamever(value: string): void
  onRefresh(): void
}

function RunListToolbar(props: ToolbarProps) {
  return (
    <>
      <div className="page-title-row">
        <div><Typography.Title level={2}>分析任务</Typography.Title><Typography.Text type="secondary">Redis Process Reporter 历史与实时状态</Typography.Text></div>
        <Button icon={<ReloadOutlined />} loading={props.refreshing} onClick={props.onRefresh}>刷新</Button>
      </div>
      <Card>
        <Space wrap className="filter-row">
          <Select allowClear placeholder="全部状态" value={props.status} onChange={props.onStatus} options={STATUS_OPTIONS.map((value) => ({ value, label: statusLabel(value) }))} style={{ width: 150 }} />
          <Input allowClear placeholder="Game version" value={props.gamever} onChange={(event) => props.onGamever(event.target.value)} style={{ width: 180 }} />
        </Space>
      </Card>
    </>
  )
}

interface ResultsProps {
  rows: RunView[]
  loading: boolean
  fetchingNext: boolean
  hasNext: boolean
  onNext(): void
}

function RunResults(props: ResultsProps) {
  return (
    <Card className="table-card">
      <Table rowKey="run_id" columns={columns()} dataSource={props.rows} loading={props.loading} pagination={false} scroll={{ x: 1200 }} />
      {props.hasNext && <div className="load-more"><Button loading={props.fetchingNext} onClick={props.onNext}>加载更多</Button></div>}
    </Card>
  )
}

export function RunListPage() {
  const { baseUrl } = useApiConfig()
  const [status, setStatus] = useState<RunStatus | undefined>()
  const [gamever, setGamever] = useState('')
  const query = useInfiniteQuery({
    queryKey: ['runs', baseUrl, status, gamever],
    queryFn: ({ pageParam, signal }) => listRuns(baseUrl, pageParam, { status, gamever: gamever || undefined }, signal),
    initialPageParam: 0,
    getNextPageParam: (page) => page.next_offset ?? undefined,
    refetchInterval: () => (document.visibilityState === 'visible' ? 10_000 : false),
  })
  const rows = query.data?.pages.flatMap((page) => page.items) || []

  return (
    <Space orientation="vertical" size="large" className="full-width">
      <RunListToolbar status={status} gamever={gamever} refreshing={query.isFetching} onStatus={setStatus} onGamever={setGamever} onRefresh={() => void query.refetch()} />
      {query.error && <Alert type="error" showIcon message={query.error.message} description={errorDescription(query.error)} />}
      <RunResults rows={rows} loading={query.isLoading} fetchingNext={query.isFetchingNextPage} hasNext={query.hasNextPage} onNext={() => void query.fetchNextPage()} />
    </Space>
  )
}
