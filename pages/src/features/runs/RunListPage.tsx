import { useInfiniteQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import type { TFunction } from 'i18next'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiError, listRuns } from '../../api/client'
import type { RunStatus, RunView } from '../../api/types'
import { useApiConfig } from '../../app/apiContext'
import { StatusTag } from '../../components/StatusTag'
import { statusLabel } from '../../components/status'
import { ReloadIcon } from '../../ui/icons'
import { Alert, Button, Card, Input, Progress, Select, Space, Spin, Table, Td, Text, Th, Title } from '../../ui/primitives'

const STATUS_OPTIONS: RunStatus[] = ['queued', 'starting', 'running', 'succeeded', 'failed', 'aborted', 'stale']

function formatTime(value: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '—'
}

function errorDescription(error: Error, t: TFunction): string {
  if (error instanceof ApiError && error.detail.code === 'redis_unavailable') return t('runs.redisUnavailable')
  return t('runs.error')
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
  const { t } = useTranslation()
  return (
    <>
      <div className="page-title-row">
        <div className="flex flex-col gap-1.5">
          <Title level={2}>{t('runs.title')}</Title>
          <Text type="secondary">{t('runs.subtitle')}</Text>
        </div>
        <Button icon={<ReloadIcon />} loading={props.refreshing} onClick={props.onRefresh}>{t('runs.refresh')}</Button>
      </div>
      <Card>
        <Space wrap className="filter-row" size="small">
            <label htmlFor="run-status" className="sr-only">{t('runs.allStatuses')}</label>
            <Select
              id="run-status"
              className="w-[150px]"
              value={props.status ?? ''}
              onChange={(event) => props.onStatus((event.target.value || undefined) as RunStatus | undefined)}
            >
              <option value="">{t('runs.allStatuses')}</option>
              {STATUS_OPTIONS.map((value) => <option key={value} value={value}>{statusLabel(value, t)}</option>)}
            </Select>
            <label htmlFor="run-gamever" className="sr-only">{t('runs.gameVersion')}</label>
            <Input
              id="run-gamever"
              type="search"
              className="w-[180px] font-mono"
              placeholder={t('runs.gameVersion')}
              value={props.gamever}
              onChange={(event) => props.onGamever(event.target.value)}
            />
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
  const { t } = useTranslation()
  return (
    <Card className="table-card p-0">
      {props.loading ? (
        <div className="page-spinner"><Spin /></div>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th className="w-[220px]">{t('runs.run')}</Th>
              <Th className="w-[110px]">{t('runs.status')}</Th>
              <Th className="w-[100px]">{t('runs.version')}</Th>
              <Th className="w-[100px]">{t('runs.agent')}</Th>
              <Th className="w-[220px]">{t('runs.progress')}</Th>
              <Th>{t('runs.currentTask')}</Th>
              <Th className="w-[170px]">{t('runs.createdAt')}</Th>
            </tr>
          </thead>
          <tbody>
            {props.rows.map((run) => (
              <tr key={run.run_id} className="hover:bg-card-2">
                <Td className="font-mono text-[12.5px]">
                  <Link to={`/runs/${encodeURIComponent(run.run_id)}`}>{run.run_id}</Link>
                </Td>
                <Td><StatusTag status={run.effective_status} /></Td>
                <Td className="font-mono text-[12.5px]">{run.gamever || t('common.notAvailable')}</Td>
                <Td>{run.agent || t('common.notAvailable')}</Td>
                <Td>
                  <Progress
                    percent={run.progress.percent}
                    tone={run.progress.failed ? 'bad' : 'accent'}
                    label={t('runs.progress')}
                  />
                </Td>
                <Td className="truncate font-mono text-[12.5px]" title={run.current_skill_id || undefined}>
                  {run.current_skill_id || t('common.notAvailable')}
                </Td>
                <Td className="font-mono text-[12.5px]">{formatTime(run.created_at)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {props.hasNext && (
        <div className="load-more">
          <Button loading={props.fetchingNext} onClick={props.onNext}>{t('runs.loadMore')}</Button>
        </div>
      )}
    </Card>
  )
}

export function RunListPage() {
  const { baseUrl } = useApiConfig()
  const { t } = useTranslation()
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
    <Space direction="vertical" size="large" className="full-width" align="start">
      <RunListToolbar status={status} gamever={gamever} refreshing={query.isFetching} onStatus={setStatus} onGamever={setGamever} onRefresh={() => void query.refetch()} />
      {query.error && <Alert tone="bad" title={query.error.message} description={errorDescription(query.error, t)} />}
      <RunResults rows={rows} loading={query.isLoading} fetchingNext={query.isFetchingNextPage} hasNext={query.hasNextPage} onNext={() => void query.fetchNextPage()} />
    </Space>
  )
}
