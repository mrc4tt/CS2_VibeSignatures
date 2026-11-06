import type { TFunction } from 'i18next'
import { pluginLabel } from '../gamedata/pluginLabel'
import type { Coverage, Origin } from './origin'

type Answer = 'yes' | 'signaturesOnly' | 'no' | 'unknown'

const ANSWER: Record<Coverage, Answer> = {
  core: 'yes',
  plugin: 'signaturesOnly',
  stock: 'no',
  noFeed: 'no',
  otherFramework: 'no',
  compiled: 'no',
  unknown: 'unknown',
}
const ANSWER_TONE = { yes: 'ok', signaturesOnly: 'ok', no: 'warn', unknown: 'neutral' } as const

/** "Metamod:Source plugin: gamebanfix", or just the kind, or undefined when nothing is known. */
export function originSummary(origin: Origin | null | undefined, t: TFunction): string | undefined {
  if (!origin?.framework) return undefined
  const kind = t(`scan.origin.kind.${origin.coverage === 'core' || origin.coverage === 'stock' ? 'core' : origin.framework}`)
  const named = origin.plugin
    ? pluginLabel(origin.plugin)
    : origin.candidates?.length
      ? t('scan.origin.either', { first: pluginLabel(origin.candidates[0]!), second: origin.candidates.slice(1).map(pluginLabel).join(', ') })
      : undefined
  return named ? t('scan.origin.summaryNamed', { kind, plugin: named }) : t('scan.origin.summary', { kind })
}

/** The answer to "will CounterStrikeSharp keep this current", in one word and its tone. */
export function coverageAnswer(origin: Origin): { answer: Answer; tone: (typeof ANSWER_TONE)[Answer] } {
  const answer = ANSWER[origin.coverage]
  return { answer, tone: ANSWER_TONE[answer] }
}
