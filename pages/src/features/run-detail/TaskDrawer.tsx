import { useQuery } from '@tanstack/react-query'
import { Button, Descriptions, Drawer, Empty, List, Space, Spin, Typography } from 'antd'
import dayjs from 'dayjs'
import { getTaskDetail } from '../../api/client'
import type { ExecutionPlanView, TaskView } from '../../api/types'
import { useApiConfig } from '../../app/apiContext'
import { StatusTag } from '../../components/StatusTag'

function duration(task: TaskView): string {
  if (!task.started_at) return '—'
  const end = task.finished_at ? dayjs(task.finished_at) : dayjs()
  return `${Math.max(0, end.diff(dayjs(task.started_at), 'second'))} 秒`
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>
}

function planValue(value: unknown): string {
  if (Array.isArray(value)) return value.join('\n') || '—'
  return value == null || value === '' ? '—' : String(value)
}

interface Props {
  runId: string
  taskId?: string
  graph: ExecutionPlanView
  onClose(): void
  onNavigate(id: string): void
}

export function TaskDrawer({ runId, taskId, graph, onClose, onNavigate }: Props) {
  const { baseUrl } = useApiConfig()
  const query = useQuery({
    queryKey: ['task', baseUrl, runId, taskId],
    queryFn: ({ signal }) => getTaskDetail(baseUrl, runId, taskId!, signal),
    enabled: Boolean(taskId),
  })
  const node = graph.nodes.find((item) => item.id === taskId)
  const job = graph.jobs.find((item) => item.id === (query.data?.job_id || taskId))
  return (
    <Drawer title="任务详情" open={Boolean(taskId)} onClose={onClose} width={620}>
      {query.isLoading && <Spin />}
      {query.error && <Empty description={query.error.message} />}
      {query.data && (
        <Space orientation="vertical" size="large" className="full-width">
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="名称">{query.data.name}</Descriptions.Item>
            <Descriptions.Item label="描述"><Typography.Paragraph className="task-description">{query.data.description || '—'}</Typography.Paragraph></Descriptions.Item>
            <Descriptions.Item label="Task ID"><Typography.Text copyable>{query.data.task_id}</Typography.Text></Descriptions.Item>
            <Descriptions.Item label="类型">{query.data.task_type}</Descriptions.Item>
            <Descriptions.Item label="状态"><StatusTag status={query.data.status} /></Descriptions.Item>
            <Descriptions.Item label="Phase">{query.data.phase}</Descriptions.Item>
            <Descriptions.Item label="Stage / Job">{query.data.stage_id || '—'} / {query.data.job_id || '—'}</Descriptions.Item>
            <Descriptions.Item label="Attempt">{query.data.attempt ?? '—'} / {query.data.max_attempts ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="开始时间">{query.data.started_at || '—'}</Descriptions.Item>
            <Descriptions.Item label="更新时间">{query.data.updated_at || '—'}</Descriptions.Item>
            <Descriptions.Item label="结束时间">{query.data.finished_at || '—'}</Descriptions.Item>
            <Descriptions.Item label="耗时">{duration(query.data)}</Descriptions.Item>
            <Descriptions.Item label="Reason">{query.data.reason || '—'}</Descriptions.Item>
            <Descriptions.Item label="Message">{query.data.message || '—'}</Descriptions.Item>
            <Descriptions.Item label="Error">{query.data.error || '—'}</Descriptions.Item>
            <Descriptions.Item label="Binary path"><Typography.Text copyable>{job?.binary_path || '—'}</Typography.Text></Descriptions.Item>
            <Descriptions.Item label="Expected inputs"><Typography.Text code>{planValue(node?.data.expected_input)}</Typography.Text></Descriptions.Item>
            <Descriptions.Item label="Expected outputs"><Typography.Text code>{planValue(node?.data.expected_output)}</Typography.Text></Descriptions.Item>
          </Descriptions>
          <div><Typography.Title level={5}>ExecutionPlan data</Typography.Title><JsonBlock value={node?.data || {}} /></div>
          <div><Typography.Title level={5}>Event payload</Typography.Title><JsonBlock value={query.data.payload} /></div>
          <List header="Dependencies" dataSource={query.data.dependencies} locale={{ emptyText: '无' }} renderItem={(id) => <List.Item><Button type="link" onClick={() => onNavigate(id)}>{id}</Button></List.Item>} />
          <List header="Dependents" dataSource={query.data.dependents} locale={{ emptyText: '无' }} renderItem={(id) => <List.Item><Button type="link" onClick={() => onNavigate(id)}>{id}</Button></List.Item>} />
        </Space>
      )}
    </Drawer>
  )
}
