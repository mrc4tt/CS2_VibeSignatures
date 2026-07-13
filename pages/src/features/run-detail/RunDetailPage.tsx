import { ArrowLeftOutlined, ReloadOutlined, WarningOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Empty, Progress, Space, Spin, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import type { ProcessPhase, TaskStatus } from '../../api/types'
import { StatusTag } from '../../components/StatusTag'
import { buildDag, buildMindMap, type GraphFilters } from '../../graph/model'
import type { ExecutionPlanView, TaskView } from '../../api/types'
import { useRunLiveStore } from './liveStore'
import { RunFilterBar } from './RunFilterBar'
import { TaskDrawer } from './TaskDrawer'
import { RunViewTabs } from './RunViewTabs'
import { useRunLive } from './useRunLive'

type ViewMode = 'mindmap' | 'dag' | 'list'

function filtersFromParams(params: URLSearchParams): GraphFilters {
  return {
    query: params.get('q') || '',
    status: (params.get('status') || undefined) as TaskStatus | undefined,
    phase: (params.get('phase') || undefined) as ProcessPhase | undefined,
    taskType: params.get('type') || undefined,
    stageId: params.get('stage') || undefined,
    jobId: params.get('job') || undefined,
  }
}

function writeFilters(params: URLSearchParams, filters: GraphFilters): URLSearchParams {
  const next = new URLSearchParams(params)
  const values: Record<string, string | undefined> = {
    q: filters.query || undefined,
    status: filters.status,
    phase: filters.phase,
    type: filters.taskType,
    stage: filters.stageId,
    job: filters.jobId,
  }
  Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key))
  return next
}

function streamLabel(status: string): string {
  return { connecting: 'SSE 连接中', connected: 'SSE 已连接', reconnecting: 'SSE 重连中', closed: 'SSE 已关闭' }[status] || status
}

function RunHeader({ onRefresh }: { onRefresh(): void }) {
  const run = useRunLiveStore((state) => state.run)
  const streamStatus = useRunLiveStore((state) => state.streamStatus)
  if (!run) return null
  return (
    <Card>
      <div className="run-header-grid">
        <div>
          <Space wrap><StatusTag status={run.effective_status} /><Tag>{streamLabel(streamStatus)}</Tag></Space>
          <Typography.Title level={2}>{run.run_id}</Typography.Title>
          <Typography.Text type="secondary">{run.current_skill_id || '当前没有正在执行的任务'}</Typography.Text>
        </div>
        <div className="run-progress">
          <Progress type="dashboard" percent={run.progress.percent} status={run.progress.failed ? 'exception' : 'normal'} />
          <Typography.Text type="secondary">成功 {run.progress.succeeded} · 失败 {run.progress.failed} · 跳过 {run.progress.skipped} · 中止 {run.progress.aborted}</Typography.Text>
          <Button icon={<ReloadOutlined />} onClick={onRefresh}>刷新快照</Button>
        </div>
      </div>
      {run.error_summary && <Alert type="error" showIcon message={run.error_summary} className="run-error" />}
    </Card>
  )
}

interface DetailContentProps {
  runId: string
  graph: ExecutionPlanView | null
  tasks: TaskView[]
  filters: GraphFilters
  view: ViewMode
  selectedTask?: string
  mindMap: ReturnType<typeof buildMindMap> | null
  dag: ReturnType<typeof buildDag> | null
  showStageOrder: boolean
  onRefresh(): void
  onFilters(filters: GraphFilters): void
  onParam(key: string, value?: string): void
  onSelect(id: string): void
  onToggle(id: string): void
  onShowStageOrder(value: boolean): void
}

function RunDetailContent(props: DetailContentProps) {
  return (
    <Space orientation="vertical" size="large" className="full-width">
      <Link to="/"><ArrowLeftOutlined /> 返回 Run 列表</Link>
      <RunHeader onRefresh={props.onRefresh} />
      {!props.graph ? <Card><Empty description="任务已排队，等待 ExecutionPlan 初始化；页面会保持 SSE 连接并自动刷新。" /></Card> : (
        <>
          {props.graph.warnings.length > 0 && <Alert type="warning" showIcon icon={<WarningOutlined />} message="ExecutionPlan 警告" description={<pre className="warning-block">{JSON.stringify(props.graph.warnings, null, 2)}</pre>} />}
          <Card><RunFilterBar graph={props.graph} filters={props.filters} onChange={props.onFilters} /></Card>
          {props.mindMap && props.dag && <RunViewTabs view={props.view} mindMap={props.mindMap} dag={props.dag} tasks={props.tasks} filters={props.filters} selectedTask={props.selectedTask} showStageOrder={props.showStageOrder} automaticDagScope={!props.filters.jobId && !props.filters.stageId} onView={(key) => props.onParam('view', key)} onSelect={props.onSelect} onToggleExpand={props.onToggle} onShowStageOrder={props.onShowStageOrder} />}
          <TaskDrawer runId={props.runId} taskId={props.selectedTask} graph={props.graph} onClose={() => props.onParam('task')} onNavigate={props.onSelect} />
        </>
      )}
    </Space>
  )
}

export function RunDetailPage() {
  const { runId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [showStageOrder, setShowStageOrder] = useState(false)
  const { snapshotQuery } = useRunLive(runId)
  const run = useRunLiveStore((state) => state.run)
  const graph = useRunLiveStore((state) => state.graph)
  const tasksById = useRunLiveStore((state) => state.tasksById)
  const filters = filtersFromParams(params)
  const tasks = useMemo(() => Object.values(tasksById), [tasksById])
  const defaultView: ViewMode = window.innerWidth < 900 ? 'list' : 'mindmap'
  const view = (params.get('view') || defaultView) as ViewMode
  const selectedTask = params.get('task') || undefined
  const dagFilters = useMemo(() => {
    if (!graph || !run || filters.jobId || filters.stageId) return filters
    return { ...filters, jobId: run.current_job_id || graph.jobs[0]?.id || 'all' }
  }, [filters, graph, run])
  const mindMap = useMemo(() => run && graph ? buildMindMap(run, graph, tasks, filters, expanded) : null, [expanded, filters, graph, run, tasks])
  const dag = useMemo(() => graph ? buildDag(graph, tasks, dagFilters, showStageOrder) : null, [dagFilters, graph, showStageOrder, tasks])

  function updateParam(key: string, value?: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  function selectTask(id: string) {
    if (tasksById[id]) updateParam('task', id)
  }

  function toggleExpanded(id: string) {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  if (snapshotQuery.isLoading || !run) return <div className="page-spinner"><Spin size="large" /></div>
  if (snapshotQuery.error) return <Alert type="error" showIcon message={snapshotQuery.error.message} description="无法读取 Run Snapshot，请检查 Run ID 和 API 状态。" />

  return <RunDetailContent runId={runId} graph={graph} tasks={tasks} filters={filters} view={view} selectedTask={selectedTask} mindMap={mindMap} dag={dag} showStageOrder={showStageOrder} onRefresh={() => void snapshotQuery.refetch()} onFilters={(next) => setParams(writeFilters(params, next), { replace: true })} onParam={updateParam} onSelect={selectTask} onToggle={toggleExpanded} onShowStageOrder={setShowStageOrder} />
}
