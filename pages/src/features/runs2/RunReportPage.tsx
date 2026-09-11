import { useQuery } from '@tanstack/react-query'
import { Alert, Skeleton } from 'antd'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getSiteMeta } from '../../api/siteMeta'
import { getSiteDiagnostics, type RunTask } from '../../api/siteData'
import { Explain } from '../../components/Explain'

const METHODS = ['reloc', 'xref', 'llm', 'vtable', 'other', 'none'] as const
const PAGE = 60

/**
 * What the run that produced this build actually did. Live progress needs a
 * connection to the analysis machine; this is the finished report, published
 * with the build, which is the part most people want.
 */
export function RunReportPage() {
  const { t } = useTranslation()
  const [module, setModule] = useState<string>()
  const [method, setMethod] = useState<string>()
  const [limit, setLimit] = useState(PAGE)

  const metaQuery = useQuery({
    queryKey: ['site-meta'],
    queryFn: ({ signal }) => getSiteMeta(signal),
    staleTime: 5 * 60 * 1000,
  })
  const build = metaQuery.data?.latest.gameVersion
  const diagnosticsQuery = useQuery({
    queryKey: ['diagnostics', build],
    queryFn: ({ signal }) => getSiteDiagnostics(build!, signal),
    enabled: Boolean(build),
    staleTime: Infinity,
  })
  const diagnostics = diagnosticsQuery.data
  // Memoised: `?? []` makes a fresh array on every render, which would make the
  // three useMemos below recompute on every keystroke elsewhere on the page.
  const tasks = useMemo<RunTask[]>(() => diagnostics?.run ?? [], [diagnostics])

  const modules = useMemo(() => [...new Set(tasks.map((task) => task.module))].sort(), [tasks])
  const methodCounts = useMemo(
    () => METHODS.map((name) => [name, tasks.filter((task) => task.method === name).length] as const)
      .filter(([, count]) => count > 0),
    [tasks],
  )
  const rows = useMemo(
    () => tasks.filter((task: RunTask) => (!module || task.module === module) && (!method || task.method === method)),
    [tasks, module, method],
  )
  const failed = tasks.filter((task) => task.status === 'failed').length

  return (
    <div className="handbook">
      <div className="hero">
        <h1>{t('runs2.h1')}</h1>
        <p className="lede">{t('runs2.lede', { build: build ?? '…' })}</p>
      </div>

      {diagnosticsQuery.isLoading && <Skeleton active paragraph={{ rows: 6 }} title={false} />}

      {!diagnosticsQuery.isLoading && !diagnostics && (
        <Alert type="info" showIcon message={t('runs2.noReport')} description={t('runs2.noReportWhy')} />
      )}

      {diagnostics && (
        <>
          <section className="panel">
            <header>
              <h2>{t('runs2.reportH', { build: diagnostics.gameVersion })}</h2>
              <span className="sub">{t('runs2.reportSub')}</span>
            </header>
            <div className="statgrid">
              <div className="stat">
                <span className="v">{tasks.length}</span>
                <span className="l">{t('runs2.tasks')}</span>
              </div>
              <div className="stat okv">
                <span className="v">{tasks.length - failed}</span>
                <span className="l">{t('runs2.ok')}</span>
              </div>
              <div className={failed > 0 ? 'stat warnv' : 'stat okv'}>
                <span className="v">{failed}</span>
                <span className="l">{t('runs2.failed')}</span>
              </div>
              <div className="stat">
                <span className="v">{modules.length}</span>
                <span className="l">{t('runs2.modules')}</span>
              </div>
            </div>
            <div className="panel-body">
              <Explain>{t('runs2.explain')}</Explain>
            </div>
          </section>

          {diagnostics.validator.ran && (
            <section className="panel">
              <header>
                <h2>{t('runs2.verifyH')}</h2>
                <span className="sub">{t('runs2.verifySub')}</span>
              </header>
              <div className="statgrid">
                <div className="stat">
                  <span className="v">{diagnostics.validator.artifacts}</span>
                  <span className="l">{t('runs2.artifacts')}</span>
                </div>
                <div className="stat okv">
                  <span className="v">{diagnostics.validator.slotVerified}</span>
                  <span className="l">{t('runs2.slots')}</span>
                </div>
                <div className="stat okv">
                  <span className="v">{diagnostics.validator.errors}</span>
                  <span className="l">{t('runs2.errors')}</span>
                </div>
                <div className="stat warnv">
                  <span className="v">{diagnostics.validator.warnings}</span>
                  <span className="l">{t('runs2.warnings')}</span>
                </div>
              </div>
            </section>
          )}

          <section className="panel">
            <header>
              <h2>{t('runs2.methodH')}</h2>
            </header>
            <div className="panel-body">
              <div className="chiprow">
                {methodCounts.map(([name, count]) => (
                  <span className="minichip" key={name}>{t(`runs2.method.${name}`)} <b>{count}</b></span>
                ))}
              </div>
              <div className="filters">
                <button type="button" className="chip" aria-pressed={!module} onClick={() => setModule(undefined)}>
                  {t('runs2.allModules')}<span className="n">{tasks.length}</span>
                </button>
                {modules.map((name) => (
                  <button
                    key={name}
                    type="button"
                    className="chip"
                    aria-pressed={module === name}
                    onClick={() => { setModule(name); setLimit(PAGE) }}
                  >
                    {name}<span className="n">{tasks.filter((task) => task.module === name).length}</span>
                  </button>
                ))}
                <span className="fsep" />
                <button type="button" className="chip" aria-pressed={!method} onClick={() => setMethod(undefined)}>
                  {t('runs2.allMethods')}
                </button>
                {methodCounts.map(([name, count]) => (
                  <button
                    key={name}
                    type="button"
                    className="chip"
                    aria-pressed={method === name}
                    onClick={() => { setMethod(name); setLimit(PAGE) }}
                  >
                    {t(`runs2.method.${name}`)}<span className="n">{count}</span>
                  </button>
                ))}
              </div>
              <div className="resultline" role="status" aria-live="polite">
                {t('runs2.shown', { count: Math.min(limit, rows.length), total: rows.length })}
              </div>
              <div className="tablewrap">
                <table className="plaintable">
                  <thead>
                    <tr>
                      <th>{t('runs2.tTask')}</th>
                      <th>{t('runs2.tModule')}</th>
                      <th>{t('runs2.tPlatform')}</th>
                      <th>{t('runs2.tMethod')}</th>
                      <th>{t('runs2.tOut')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.slice(0, limit).map((task) => (
                      <tr key={`${task.module}/${task.task}`}>
                        <td className="mono">{task.task}</td>
                        <td className="mono">{task.module}</td>
                        <td className="mono">{task.platform}</td>
                        <td>{t(`runs2.method.${task.method}`)}</td>
                        <td className="mono">
                          {task.produced}
                          {task.missing > 0 && <span style={{ color: 'var(--bad)' }}> -{task.missing}</span>}
                          {task.optionalMissing > 0 && <span style={{ color: 'var(--faint)' }}> ({task.optionalMissing})</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {rows.length > limit && (
                <button type="button" className="btn morebtn" onClick={() => setLimit(limit + PAGE)}>
                  {t('runs2.showMore', { count: Math.min(PAGE, rows.length - limit), total: rows.length })}
                </button>
              )}
            </div>
          </section>
        </>
      )}

      <section className="panel">
        <header><h2>{t('runs2.liveH')}</h2></header>
        <div className="panel-body">
          <p className="plain prose">{t('runs2.liveBody')}</p>
          <div className="steps">
            <div className="step">
              <span className="i">1</span>
              <span dangerouslySetInnerHTML={{ __html: t('runs2.live1') }} />
            </div>
            <div className="step">
              <span className="i">2</span>
              <span dangerouslySetInnerHTML={{ __html: t('runs2.live2') }} />
            </div>
          </div>
          <Explain html={t('runs2.liveExplain')} />
        </div>
      </section>
    </div>
  )
}
