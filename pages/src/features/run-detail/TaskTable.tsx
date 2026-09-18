import dayjs from 'dayjs'
import { useTranslation } from 'react-i18next'
import type { TaskView } from '../../api/types'
import { StatusTag } from '../../components/StatusTag'
import { phaseLabel } from '../../components/status'
import type { GraphFilters } from '../../graph/model'
import { Button, Table, Td, Th } from '../../ui/primitives'

function matches(task: TaskView, filters: GraphFilters): boolean {
  const query = filters.query.trim().toLowerCase()
  if (query && !`${task.name} ${task.task_id} ${task.description || ''}`.toLowerCase().includes(query)) return false
  if (filters.status && task.status !== filters.status) return false
  if (filters.phase && task.phase !== filters.phase) return false
  if (filters.taskType && task.task_type !== filters.taskType) return false
  if (filters.stageId && filters.stageId !== 'all' && task.stage_id !== filters.stageId) return false
  return !filters.jobId || filters.jobId === 'all' || task.job_id === filters.jobId
}

/**
 * antd's Table did virtualisation, column widths and paging for us. A run plan
 * is ~1,300 tasks and the filters above already cut it down, so a plain table in
 * a scroll container is enough - and it keeps the rows selectable and printable,
 * which the virtualised body did not.
 */
export function TaskTable({ tasks, filters, onSelect }: { tasks: TaskView[]; filters: GraphFilters; onSelect(id: string): void }) {
  const rows = tasks.filter((task) => matches(task, filters))
  const { t } = useTranslation()
  return (
    <div className="max-h-[520px] overflow-auto rounded-[12px] border border-rule">
      <Table>
        <thead className="sticky top-0 z-10 bg-card">
          <tr>
            <Th className="w-[260px]">{t('taskTable.task')}</Th>
            <Th className="w-[360px]">{t('taskTable.description')}</Th>
            <Th className="w-[105px]">{t('runs.status')}</Th>
            <Th className="w-[170px]">{t('phase.label')}</Th>
            <Th className="w-[130px]">{t('taskTable.type')}</Th>
            <Th className="w-[190px]">{t('taskTable.stage')}</Th>
            <Th className="w-[220px]">{t('taskTable.job')}</Th>
            <Th className="w-[170px]">{t('taskTable.updatedAt')}</Th>
            <Th>{t('taskTable.reason')}</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((task) => (
            <tr key={task.task_id} className="hover:bg-card-2">
              <Td>
                <Button variant="link" onClick={() => onSelect(task.task_id)}>{task.name}</Button>
              </Td>
              <Td className="max-w-[360px] truncate" title={task.description || undefined}>
                {task.description || t('common.notAvailable')}
              </Td>
              <Td><StatusTag status={task.status} /></Td>
              <Td>{phaseLabel(task.phase, t)}</Td>
              <Td className="font-mono text-[12.5px]">{task.task_type}</Td>
              <Td className="max-w-[190px] truncate font-mono text-[12.5px]" title={task.stage_id || undefined}>{task.stage_id}</Td>
              <Td className="max-w-[220px] truncate font-mono text-[12.5px]" title={task.job_id || undefined}>{task.job_id}</Td>
              <Td className="font-mono text-[12.5px]">
                {task.updated_at ? dayjs(task.updated_at).format('YYYY-MM-DD HH:mm:ss') : t('common.notAvailable')}
              </Td>
              <Td className="truncate" title={task.reason || undefined}>{task.reason || t('common.notAvailable')}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  )
}
