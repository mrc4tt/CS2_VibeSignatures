import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { getTaskDetail } from '../../api/client'
import type { ExecutionPlanView, TaskView } from '../../api/types'
import { useApiConfig } from '../../app/apiContext'
import { StatusTag } from '../../components/StatusTag'
import { phaseLabel } from '../../components/status'
import { Button, Descriptions, Drawer, Empty, List, Space, Spin, Title } from '../../ui/primitives'

function duration(task: TaskView, t: TFunction): string {
  if (!task.started_at) return t('common.notAvailable')
  const end = task.finished_at ? dayjs(task.finished_at) : dayjs()
  return t('taskDetail.seconds', { count: Math.max(0, end.diff(dayjs(task.started_at), 'second')) })
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>
}

function planValue(value: unknown, t: TFunction): string {
  if (Array.isArray(value)) return value.join('\n') || t('common.notAvailable')
  return value == null || value === '' ? t('common.notAvailable') : String(value)
}

function Mono({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-[12.5px] break-all whitespace-pre-wrap">{children}</span>
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
  const { t } = useTranslation()
  const query = useQuery({
    queryKey: ['task', baseUrl, runId, taskId],
    queryFn: ({ signal }) => getTaskDetail(baseUrl, runId, taskId!, signal),
    enabled: Boolean(taskId),
  })
  const node = graph.nodes.find((item) => item.id === taskId)
  const job = graph.jobs.find((item) => item.id === (query.data?.job_id || taskId))
  const detail = query.data
  const na = t('common.notAvailable')

  return (
    <Drawer title={t('taskDetail.title')} open={Boolean(taskId)} onClose={onClose} width={620}>
      {query.isLoading && <Spin />}
      {query.error && <Empty description={query.error.message} />}
      {detail && (
        <Space direction="vertical" size="large" className="full-width" align="start">
          <Descriptions
            items={[
              { label: t('taskDetail.name'), value: detail.name },
              { label: t('taskDetail.description'), value: <p className="task-description m-0">{detail.description || na}</p> },
              { label: t('taskDetail.taskId'), value: <Mono>{detail.task_id}</Mono> },
              { label: t('taskDetail.type'), value: detail.task_type },
              { label: t('taskDetail.status'), value: <StatusTag status={detail.status} /> },
              { label: t('taskDetail.phase'), value: phaseLabel(detail.phase, t) },
              { label: t('taskDetail.stageJob'), value: `${detail.stage_id || na} / ${detail.job_id || na}` },
              { label: t('taskDetail.attempt'), value: `${detail.attempt ?? na} / ${detail.max_attempts ?? na}` },
              { label: t('taskDetail.startedAt'), value: detail.started_at || na },
              { label: t('taskDetail.updatedAt'), value: detail.updated_at || na },
              { label: t('taskDetail.finishedAt'), value: detail.finished_at || na },
              { label: t('taskDetail.duration'), value: duration(detail, t) },
              { label: t('taskDetail.reason'), value: detail.reason || na },
              { label: t('taskDetail.message'), value: detail.message || na },
              { label: t('taskDetail.error'), value: detail.error || na },
              { label: t('taskDetail.binaryPath'), value: <Mono>{job?.binary_path || na}</Mono> },
              { label: t('taskDetail.expectedInputs'), value: <Mono>{planValue(node?.data.expected_input, t)}</Mono> },
              { label: t('taskDetail.expectedOutputs'), value: <Mono>{planValue(node?.data.expected_output, t)}</Mono> },
            ]}
          />
          <div className="flex w-full flex-col gap-2">
            <Title level={4}>{t('taskDetail.executionPlanData')}</Title>
            <JsonBlock value={node?.data || {}} />
          </div>
          <div className="flex w-full flex-col gap-2">
            <Title level={4}>{t('taskDetail.eventPayload')}</Title>
            <JsonBlock value={detail.payload} />
          </div>
          <div className="flex w-full flex-col gap-2">
            <Title level={4}>{t('taskDetail.dependencies')}</Title>
            <List
              empty={na}
              items={detail.dependencies.map((id) => (
                <Button key={id} variant="link" onClick={() => onNavigate(id)}>{id}</Button>
              ))}
            />
          </div>
          <div className="flex w-full flex-col gap-2">
            <Title level={4}>{t('taskDetail.dependents')}</Title>
            <List
              empty={na}
              items={detail.dependents.map((id) => (
                <Button key={id} variant="link" onClick={() => onNavigate(id)}>{id}</Button>
              ))}
            />
          </div>
        </Space>
      )}
    </Drawer>
  )
}
