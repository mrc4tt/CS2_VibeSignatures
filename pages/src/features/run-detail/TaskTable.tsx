import { Button, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import type { TaskView } from '../../api/types'
import { StatusTag } from '../../components/StatusTag'
import type { GraphFilters } from '../../graph/model'

function matches(task: TaskView, filters: GraphFilters): boolean {
  const query = filters.query.trim().toLowerCase()
  if (query && !`${task.name} ${task.task_id}`.toLowerCase().includes(query)) return false
  if (filters.status && task.status !== filters.status) return false
  if (filters.phase && task.phase !== filters.phase) return false
  if (filters.taskType && task.task_type !== filters.taskType) return false
  if (filters.stageId && filters.stageId !== 'all' && task.stage_id !== filters.stageId) return false
  return !filters.jobId || filters.jobId === 'all' || task.job_id === filters.jobId
}

function columns(onSelect: (id: string) => void): ColumnsType<TaskView> {
  return [
    { title: '任务', dataIndex: 'name', width: 260, render: (name, task) => <Button type="link" onClick={() => onSelect(task.task_id)}>{name}</Button> },
    { title: '状态', dataIndex: 'status', width: 105, render: (status) => <StatusTag status={status} /> },
    { title: 'Phase', dataIndex: 'phase', width: 170 },
    { title: '类型', dataIndex: 'task_type', width: 130 },
    { title: 'Stage', dataIndex: 'stage_id', width: 190, ellipsis: true },
    { title: 'Job', dataIndex: 'job_id', width: 220, ellipsis: true },
    { title: '更新时间', dataIndex: 'updated_at', width: 170, render: (value) => value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '—' },
    { title: '原因', dataIndex: 'reason', ellipsis: true, render: (value) => value || '—' },
  ]
}

export function TaskTable({ tasks, filters, onSelect }: { tasks: TaskView[]; filters: GraphFilters; onSelect(id: string): void }) {
  const rows = tasks.filter((task) => matches(task, filters))
  return <Table rowKey="task_id" virtual columns={columns(onSelect)} dataSource={rows} pagination={{ pageSize: 100, showSizeChanger: false }} scroll={{ x: 1400, y: 520 }} />
}
