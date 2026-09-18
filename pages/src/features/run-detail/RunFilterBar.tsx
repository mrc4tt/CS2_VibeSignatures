import { useTranslation } from 'react-i18next'
import type { ExecutionPlanView, ProcessPhase, TaskStatus } from '../../api/types'
import { phaseLabel, statusLabel } from '../../components/status'
import type { GraphFilters } from '../../graph/model'
import { Input, Select, Space } from '../../ui/primitives'

const STATUSES: TaskStatus[] = ['pending', 'running', 'succeeded', 'failed', 'skipped', 'aborted']
const PHASES: ProcessPhase[] = ['preflight', 'waiting_for_mcp', 'validating_binary', 'validating_inputs', 'preprocessing', 'validating_outputs', 'agent_fallback', 'vcall_export', 'postprocessing', 'finished']

interface Props {
  graph: ExecutionPlanView
  filters: GraphFilters
  onChange(filters: GraphFilters): void
}

export function RunFilterBar({ graph, filters, onChange }: Props) {
  const { t } = useTranslation()
  const patch = (next: Partial<GraphFilters>) => onChange({ ...filters, ...next })
  const jobs = filters.stageId && filters.stageId !== 'all'
    ? graph.jobs.filter((job) => job.stage_id === filters.stageId)
    : graph.jobs

  /** antd's `allowClear` becomes an explicit empty option, which is also what a keyboard user gets. */
  const clear = (label: string) => <option value="">{label}</option>

  return (
    <Space wrap className="filter-row" size="small">
      <label htmlFor="run-filter-query" className="sr-only">{t('filters.search')}</label>
      <Input
        id="run-filter-query"
        type="search"
        placeholder={t('filters.search')}
        value={filters.query}
        onChange={(event) => patch({ query: event.target.value })}
        className="w-[260px]"
      />

      <label htmlFor="run-filter-status" className="sr-only">{t('filters.status')}</label>
      <Select
        id="run-filter-status"
        value={filters.status ?? ''}
        onChange={(event) => patch({ status: (event.target.value || undefined) as TaskStatus | undefined })}
        className="w-[130px]"
      >
        {clear(t('filters.status'))}
        {STATUSES.map((value) => <option key={value} value={value}>{statusLabel(value, t)}</option>)}
      </Select>

      <label htmlFor="run-filter-phase" className="sr-only">{t('phase.label')}</label>
      <Select
        id="run-filter-phase"
        value={filters.phase ?? ''}
        onChange={(event) => patch({ phase: (event.target.value || undefined) as ProcessPhase | undefined })}
        className="w-[170px]"
      >
        {clear(t('phase.label'))}
        {PHASES.map((value) => <option key={value} value={value}>{phaseLabel(value, t)}</option>)}
      </Select>

      <label htmlFor="run-filter-type" className="sr-only">{t('filters.taskType')}</label>
      <Select
        id="run-filter-type"
        value={filters.taskType ?? ''}
        onChange={(event) => patch({ taskType: event.target.value || undefined })}
        className="w-[150px]"
      >
        {clear(t('filters.taskType'))}
        {[...new Set(graph.nodes.map((node) => node.node_type))].map((value) => <option key={value} value={value}>{value}</option>)}
      </Select>

      <label htmlFor="run-filter-stage" className="sr-only">{t('filters.allStages')}</label>
      <Select
        id="run-filter-stage"
        value={filters.stageId ?? ''}
        onChange={(event) => patch({ stageId: event.target.value || undefined, jobId: undefined })}
        className="w-[190px]"
      >
        {clear(t('filters.allStages'))}
        {graph.stages.map((stage) => <option key={stage.id} value={stage.id}>{`${stage.stage_index} · ${stage.module_name}`}</option>)}
      </Select>

      <label htmlFor="run-filter-job" className="sr-only">{t('filters.allJobs')}</label>
      <Select
        id="run-filter-job"
        value={filters.jobId ?? ''}
        onChange={(event) => patch({ jobId: event.target.value || undefined })}
        className="w-[220px]"
      >
        {clear(t('filters.allJobs'))}
        {jobs.map((job) => <option key={job.id} value={job.id}>{`${job.module_name} · ${job.platform}`}</option>)}
      </Select>
    </Space>
  )
}
