import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { getSiteDiagnostics, getSiteHistory, type PluginCheckFile, type SiteDiagnostics } from '../../api/siteData'
import { Tag } from '../../ui/primitives'
import { Explain } from '../../components/Explain'

/**
 * verify_plugin_gamedata's defect statuses. Everything else it can say is a pass
 * (ok, match, ok-midfunction, ok-globalref) or "could not check" (no-reference,
 * ambiguous-reference, patch-unverifiable) - listed, but not counted against the file.
 */
const DEFECTS = new Set(['broken', 'ambiguous', 'mismatch', 'unparsable'])

/** The build published before `build`, from history.json's build list. */
function previousBuild(builds: string[], build: string): string | undefined {
  const index = builds.indexOf(build)
  return index > 0 ? builds[index - 1] : undefined
}

function Verdict({ file }: { file?: PluginCheckFile }) {
  const { t } = useTranslation()
  if (!file) return <span className="text-faint">-</span>
  if (!file.ran) return <Tag tone="qualify">{t('runs2.plugins.notRun')}</Tag>
  return (file.unhealthy ?? 0) === 0
    ? <Tag tone="ok">{t('runs2.plugins.holds')}</Tag>
    : <Tag tone="bad">{t('runs2.plugins.unhealthy', { count: file.unhealthy })}</Tag>
}

/**
 * Does every file an enabled plugin ships hold against this build's binaries?
 * Published per build by publish_site_data.py, so this build and the one before
 * it sit side by side: a file that held last build and breaks now is the case
 * worth seeing at a glance.
 */
export function PluginChecksPanel({ diagnostics }: { diagnostics: SiteDiagnostics }) {
  const { t } = useTranslation()
  const historyQuery = useQuery({
    queryKey: ['history'],
    queryFn: ({ signal }) => getSiteHistory(signal),
    staleTime: Infinity,
  })
  const previous = previousBuild(
    (historyQuery.data?.builds ?? []).map((entry) => entry.gameVersion),
    diagnostics.gameVersion,
  )
  const previousQuery = useQuery({
    queryKey: ['diagnostics', previous],
    queryFn: ({ signal }) => getSiteDiagnostics(previous!, signal),
    enabled: Boolean(previous),
    staleTime: Infinity,
  })

  const files = diagnostics.plugins?.ran ? diagnostics.plugins.files ?? [] : []
  if (files.length === 0) return null
  const before = new Map((previousQuery.data?.plugins?.files ?? []).map((file) => [file.path, file]))
  const unhealthy = files.reduce((sum, file) => sum + (file.unhealthy ?? 0), 0)

  return (
    <section className="panel">
      <header>
        <h2>{t('runs2.plugins.h')}</h2>
        <span className="sub">{t('runs2.plugins.sub')}</span>
      </header>
      <div className="statgrid">
        <div className="stat">
          <span className="v">{files.length}</span>
          <span className="l">{t('runs2.plugins.files')}</span>
        </div>
        <div className="stat">
          <span className="v">{files.reduce((sum, file) => sum + (file.entries ?? 0), 0)}</span>
          <span className="l">{t('runs2.plugins.entries')}</span>
        </div>
        <div className={unhealthy > 0 ? 'stat warnv' : 'stat okv'}>
          <span className="v">{unhealthy}</span>
          <span className="l">{t('runs2.plugins.unhealthyTotal')}</span>
        </div>
      </div>
      <div className="panel-body">
        <div className="tablewrap">
          <table className="plaintable">
            <thead>
              <tr>
                <th>{t('runs2.plugins.tFile')}</th>
                <th>{t('runs2.plugins.tEntries')}</th>
                <th>{t('runs2.plugins.tThis', { build: diagnostics.gameVersion })}</th>
                <th>{previous ? t('runs2.plugins.tBefore', { build: previous }) : t('runs2.plugins.tBeforeNone')}</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <tr key={file.path}>
                  <td>
                    <details className="chgrow">
                      <summary>
                        <span className="mono">{file.path}</span>
                        {file.statuses && (
                          <span className="text-faint">
                            {Object.entries(file.statuses).map(([status, count]) => `${count} ${status}`).join(' · ')}
                          </span>
                        )}
                      </summary>
                      {file.ran ? (
                        (file.problems ?? []).length === 0 ? (
                          <p className="plain">{t('runs2.plugins.allPass')}</p>
                        ) : (
                          <ul className="plain">
                            {(file.problems ?? []).map((problem) => (
                              <li key={`${problem.name}/${problem.platform}`}>
                                <span className="mono">{problem.name}</span> {problem.platform}{' '}
                                <Tag tone={DEFECTS.has(problem.status) ? 'bad' : 'qualify'}>{problem.status}</Tag>
                              </li>
                            ))}
                          </ul>
                        )
                      ) : (
                        <p className="plain">{file.reason}</p>
                      )}
                    </details>
                  </td>
                  <td className="mono">{file.entries ?? '-'}</td>
                  <td><Verdict file={file} /></td>
                  <td><Verdict file={before.get(file.path)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Explain>{t('runs2.plugins.explain')}</Explain>
      </div>
    </section>
  )
}
