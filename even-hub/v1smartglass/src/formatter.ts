// Mirrors src/v1smartglass/formatter.py: pack alerts and top risks into
// 5-line / 32-char HUD pages. The Hub renderer uses real text elements
// rather than monospace stdout, but we keep the same character budget so
// the layout doesn't break when sent to the glasses.

import type { Alert, RiskEntity } from './vision-one'

export const MAX_LINES = 5
export const LINE_CHARS = 32

const SEVERITY_GLYPH: Record<Alert['severity'], string> = {
  critical: '!!',
  high: '! ',
  medium: '~ ',
  low: '. ',
}

export type Frame = {
  title: string
  lines: string[]
}

export function buildAlertsFrame(alerts: Alert[]): Frame {
  const title = truncate(`V1 ALERTS (${alerts.length})`, LINE_CHARS)
  if (alerts.length === 0) {
    return { title, lines: ['No alerts in window.'] }
  }
  const lines = alerts.slice(0, MAX_LINES - 1).map((alert) => {
    const glyph = SEVERITY_GLYPH[alert.severity] ?? '  '
    const who = alert.impactedEntities[0] ?? '-'
    return truncate(`${glyph}${alert.model} [${who}]`, LINE_CHARS)
  })
  return { title, lines }
}

export function buildRiskFrame(title: string, entities: RiskEntity[], topN: number): Frame {
  const t = truncate(title, LINE_CHARS)
  if (entities.length === 0) {
    return { title: t, lines: ['No risk data.'] }
  }
  const lines = entities
    .slice(0, topN)
    .map((e, idx) => truncate(`${idx + 1}. ${e.name}  (${e.score})`, LINE_CHARS))
  while (lines.length < Math.min(topN, MAX_LINES - 1)) {
    lines.push('')
  }
  return { title: t, lines }
}

function truncate(text: string, width: number): string {
  return text.length <= width ? text : text.slice(0, width - 1) + '…'
}
