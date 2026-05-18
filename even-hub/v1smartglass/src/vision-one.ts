// Vision One v3 API client for the Hub app. Goes through /__v1proxy so the
// Bearer token never lives in browser-visible request URLs and CORS is not
// an issue.

export type Region = 'us' | 'eu' | 'jp' | 'sg' | 'au' | 'in' | 'uae'

export const REGION_HOSTS: Record<Region, string> = {
  us: 'api.xdr.trendmicro.com',
  eu: 'api.eu.xdr.trendmicro.com',
  jp: 'api.xdr.trendmicro.co.jp',
  sg: 'api.sg.xdr.trendmicro.com',
  au: 'api.au.xdr.trendmicro.com',
  in: 'api.in.xdr.trendmicro.com',
  uae: 'api.uae.xdr.trendmicro.com',
}

export type Severity = 'low' | 'medium' | 'high' | 'critical'
const SEVERITY_RANK: Record<Severity, number> = { low: 0, medium: 1, high: 2, critical: 3 }

export type Alert = {
  id: string
  model: string
  severity: Severity
  score: number
  createdAt: string
  impactedEntities: string[]
}

export type RiskEntity = {
  name: string
  score: number
  kind: 'user' | 'device'
}

export type VisionOneConfig = {
  apiKey: string
  region: Region
  lookbackMinutes: number
  minSeverity: Severity
}

const PROXY_PATH = '/__v1proxy'

async function proxyGet(cfg: VisionOneConfig, path: string, params: Record<string, string | number>): Promise<unknown> {
  const target = new URL(`https://${REGION_HOSTS[cfg.region]}${path}`)
  for (const [k, v] of Object.entries(params)) {
    target.searchParams.set(k, String(v))
  }
  const resp = await fetch(`${PROXY_PATH}?url=${encodeURIComponent(target.toString())}`, {
    headers: { 'X-V1-Auth': cfg.apiKey },
  })
  if (!resp.ok) {
    const body = await resp.text()
    throw new Error(`Vision One ${resp.status}: ${body.slice(0, 200)}`)
  }
  return resp.json()
}

export async function fetchAlerts(cfg: VisionOneConfig): Promise<Alert[]> {
  const start = new Date(Date.now() - cfg.lookbackMinutes * 60_000).toISOString().replace(/\.\d+Z$/, 'Z')
  const data = (await proxyGet(cfg, '/v3.0/workbench/alerts', {
    startDateTime: start,
    orderBy: 'createdDateTime desc',
    top: 50,
  })) as { items?: unknown[] }

  const minRank = SEVERITY_RANK[cfg.minSeverity]
  const items = Array.isArray(data.items) ? data.items : []
  return items
    .map(toAlert)
    .filter((a): a is Alert => a !== null && SEVERITY_RANK[a.severity] >= minRank)
}

export async function fetchTopRiskyUsers(cfg: VisionOneConfig, topN: number): Promise<RiskEntity[]> {
  return fetchRisk(cfg, '/v3.0/asrm/highRiskUsers', 'user', topN)
}

export async function fetchTopRiskyDevices(cfg: VisionOneConfig, topN: number): Promise<RiskEntity[]> {
  return fetchRisk(cfg, '/v3.0/asrm/highRiskDevices', 'device', topN)
}

async function fetchRisk(
  cfg: VisionOneConfig,
  path: string,
  kind: 'user' | 'device',
  topN: number,
): Promise<RiskEntity[]> {
  const data = (await proxyGet(cfg, path, { top: Math.max(topN, 10), orderBy: 'riskScore desc' })) as {
    items?: unknown[]
  }
  const items = Array.isArray(data.items) ? data.items : []
  return items
    .map((raw) => toRiskEntity(raw, kind))
    .filter((r): r is RiskEntity => r !== null)
    .slice(0, topN)
}

function toAlert(raw: unknown): Alert | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const severity = String(r.severity ?? 'low').toLowerCase() as Severity
  if (!(severity in SEVERITY_RANK)) return null

  const scope = (r.impactScope ?? {}) as Record<string, unknown>
  const entities = [
    ...((scope.users as Array<Record<string, unknown>>) ?? []).map((u) => String(u.name ?? u.userPrincipalName ?? '')),
    ...((scope.entities as Array<Record<string, unknown>>) ?? []).map((e) => String(e.entityValue ?? e.name ?? '')),
  ].filter(Boolean)

  return {
    id: String(r.id ?? ''),
    model: String(r.model ?? r.alertName ?? 'alert'),
    severity,
    score: Number(r.score ?? 0),
    createdAt: String(r.createdDateTime ?? ''),
    impactedEntities: entities,
  }
}

function toRiskEntity(raw: unknown, kind: 'user' | 'device'): RiskEntity | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const name = r.name ?? r.userPrincipalName ?? r.endpointName
  if (!name) return null
  return { name: String(name), score: Number(r.riskScore ?? 0), kind }
}

export function rankAlerts(alerts: Alert[]): Alert[] {
  return [...alerts].sort((a, b) => {
    const sevDiff = SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity]
    if (sevDiff !== 0) return sevDiff
    return (b.createdAt ?? '').localeCompare(a.createdAt ?? '')
  })
}
