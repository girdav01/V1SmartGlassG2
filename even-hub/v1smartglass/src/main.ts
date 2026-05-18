import './styles.css'
import { EvenBetterSdk } from '@jappyjan/even-better-sdk'
import { OsEventTypeList } from '@evenrealities/even_hub_sdk'
import { createAutoConnector } from '../../_shared/autoconnect'
import { applyConnectionPillPhase, inferConnectionPillPhaseFromStatus } from '../../_shared/connection-pill'
import { getRawEventType, normalizeEventType } from '../../_shared/even-events'
import { appendEventLog } from '../../_shared/log'
import { withTimeout } from '../../_shared/async'

import { buildAlertsFrame, buildRiskFrame, type Frame } from './formatter'
import { ensureHud } from './glasses'
import {
  fetchAlerts,
  fetchTopRiskyDevices,
  fetchTopRiskyUsers,
  rankAlerts,
  REGION_HOSTS,
  type Region,
  type Severity,
  type VisionOneConfig,
} from './vision-one'

const STORAGE_KEY = 'v1smartglass.config.v1'
const TOP_N = 3

type PageKind = 'alerts' | 'top_users' | 'top_devices'
const PAGE_ORDER: PageKind[] = ['alerts', 'top_users', 'top_devices']

type Cache = {
  alertsFrame: Frame
  usersFrame: Frame
  devicesFrame: Frame
}

type AppState = {
  config: VisionOneConfig
  cache: Cache | null
  pageIndex: number
}

const state: AppState = {
  config: loadConfig(),
  cache: null,
  pageIndex: 0,
}

function loadConfig(): VisionOneConfig {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (raw) {
    try {
      return JSON.parse(raw) as VisionOneConfig
    } catch {
      // fall through
    }
  }
  return { apiKey: '', region: 'eu', lookbackMinutes: 60, minSeverity: 'medium' }
}

function saveConfig(cfg: VisionOneConfig): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg))
}

const root = document.querySelector<HTMLDivElement>('#app')
if (!root) throw new Error('Missing #app')

root.innerHTML = `
  <header class="hero card">
    <div>
      <p class="eyebrow">Trend Vision One</p>
      <h1 class="page-title">V1 SmartGlass</h1>
      <p class="page-subtitle">Workbench alerts + top risky users/devices on the G2 HUD.</p>
    </div>
    <div id="hero-pill" class="hero-pill is-ready" aria-live="polite">Ready</div>
  </header>

  <section class="card">
    <div class="row">
      <div class="field">
        <label for="api-key">Vision One API key</label>
        <input id="api-key" type="password" autocomplete="off" spellcheck="false" placeholder="eyJ..." />
      </div>
      <div class="field">
        <label for="region">Hosting region</label>
        <select id="region"></select>
      </div>
      <div class="field">
        <label for="lookback">Lookback (minutes)</label>
        <input id="lookback" type="number" min="5" max="1440" />
      </div>
      <div class="field">
        <label for="min-severity">Minimum severity</label>
        <select id="min-severity">
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
          <option value="critical">critical</option>
        </select>
      </div>
    </div>
    <div class="top-actions">
      <button id="connect-btn" class="btn btn-primary connect-glasses-btn" type="button">Connect glasses</button>
      <button id="refresh-btn" class="btn" type="button">Refresh data</button>
      <button id="alerts-btn" class="btn" type="button">Show alerts</button>
      <button id="top-risk-btn" class="btn" type="button">Show top risk</button>
    </div>
    <p id="status" class="status-line">Paste your Vision One API key + region to begin.</p>
  </section>

  <section class="card">
    <p class="log-title">HUD preview</p>
    <div id="hud-preview" class="hud-preview"></div>
    <p style="font-size:12px;opacity:0.7;margin-top:6px">
      Clicker mapping: <b>CLICK</b> = next page (alerts → users → devices),
      <b>DOUBLE_CLICK</b> = refresh data.
    </p>
  </section>

  <section class="card">
    <p class="log-title">Event log</p>
    <pre id="event-log" aria-live="polite"></pre>
  </section>
`

// --- form wiring ---

const apiKeyEl = byId<HTMLInputElement>('api-key')
const regionEl = byId<HTMLSelectElement>('region')
const lookbackEl = byId<HTMLInputElement>('lookback')
const minSevEl = byId<HTMLSelectElement>('min-severity')
const statusEl = byId<HTMLParagraphElement>('status')
const heroPill = byId<HTMLDivElement>('hero-pill')
const hudPreviewEl = byId<HTMLDivElement>('hud-preview')

const connectBtn = byId<HTMLButtonElement>('connect-btn')
const refreshBtn = byId<HTMLButtonElement>('refresh-btn')
const alertsBtn = byId<HTMLButtonElement>('alerts-btn')
const topRiskBtn = byId<HTMLButtonElement>('top-risk-btn')

for (const region of Object.keys(REGION_HOSTS) as Region[]) {
  const opt = document.createElement('option')
  opt.value = region
  opt.textContent = `${region.toUpperCase()} — ${REGION_HOSTS[region]}`
  regionEl.appendChild(opt)
}

apiKeyEl.value = state.config.apiKey
regionEl.value = state.config.region
lookbackEl.value = String(state.config.lookbackMinutes)
minSevEl.value = state.config.minSeverity

function syncConfigFromForm(): void {
  state.config = {
    apiKey: apiKeyEl.value.trim(),
    region: regionEl.value as Region,
    lookbackMinutes: clamp(Number(lookbackEl.value) || 60, 5, 1440),
    minSeverity: minSevEl.value as Severity,
  }
  saveConfig(state.config)
}

for (const el of [apiKeyEl, regionEl, lookbackEl, minSevEl]) {
  el.addEventListener('change', syncConfigFromForm)
}

// --- preview + status helpers ---

function setStatus(text: string): void {
  statusEl.textContent = text
  const inferred = inferConnectionPillPhaseFromStatus(text)
  if (inferred) applyConnectionPillPhase(heroPill, inferred)
}

function renderPreview(frame: Frame): void {
  hudPreviewEl.textContent = [frame.title, ...frame.lines].join('\n')
}

// --- Vision One fetch + page bookkeeping ---

async function refreshData(): Promise<void> {
  syncConfigFromForm()
  if (!state.config.apiKey) {
    setStatus('Missing API key — paste it above.')
    return
  }
  setStatus(`Fetching from ${REGION_HOSTS[state.config.region]}…`)
  try {
    const [alerts, users, devices] = await Promise.all([
      fetchAlerts(state.config),
      fetchTopRiskyUsers(state.config, TOP_N),
      fetchTopRiskyDevices(state.config, TOP_N),
    ])
    state.cache = {
      alertsFrame: buildAlertsFrame(rankAlerts(alerts)),
      usersFrame: buildRiskFrame('TOP RISKY USERS', users, TOP_N),
      devicesFrame: buildRiskFrame('TOP RISKY DEVICES', devices, TOP_N),
    }
    setStatus(
      `OK — alerts:${alerts.length} users:${users.length} devices:${devices.length}`,
    )
    appendEventLog(`refresh ok (alerts=${alerts.length}, users=${users.length}, devices=${devices.length})`)
    await showPage(state.pageIndex)
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error)
    setStatus(`Fetch failed: ${msg}`)
    appendEventLog(`refresh failed: ${msg}`)
  }
}

function currentFrame(): Frame | null {
  if (!state.cache) return null
  switch (PAGE_ORDER[state.pageIndex]) {
    case 'alerts':
      return state.cache.alertsFrame
    case 'top_users':
      return state.cache.usersFrame
    case 'top_devices':
      return state.cache.devicesFrame
  }
}

async function showPage(index: number): Promise<void> {
  state.pageIndex = ((index % PAGE_ORDER.length) + PAGE_ORDER.length) % PAGE_ORDER.length
  const frame = currentFrame()
  if (!frame) {
    setStatus('No data yet — press "Refresh data".')
    return
  }
  renderPreview(frame)
  if (bridge?.mode === 'bridge') {
    await bridge.update(frame)
  }
}

// --- glasses bridge wiring ---

type Bridge =
  | { mode: 'bridge'; update: (frame: Frame) => Promise<void> }
  | { mode: 'mock' }

let bridge: Bridge | null = null

async function initBridge(): Promise<Bridge> {
  try {
    await withTimeout(EvenBetterSdk.getRawBridge(), 4000)
    const sdk = new EvenBetterSdk()
    const hud = await ensureHud(sdk)

    sdk.addEventListener((event) => {
      const type = normalizeEventType(getRawEventType(event), OsEventTypeList)
      if (type === OsEventTypeList.CLICK_EVENT) {
        void showPage(state.pageIndex + 1)
        appendEventLog(`click -> page ${PAGE_ORDER[(state.pageIndex + 1) % PAGE_ORDER.length]}`)
      } else if (type === OsEventTypeList.DOUBLE_CLICK_EVENT) {
        appendEventLog('double-click -> refresh')
        void refreshData()
      }
    })

    return {
      mode: 'bridge',
      update: (frame) => hud.update(frame),
    }
  } catch {
    return { mode: 'mock' }
  }
}

// --- buttons ---

const connector = createAutoConnector({
  connect: async () => {
    setStatus('Connecting to Even bridge…')
    bridge = await initBridge()
    if (bridge.mode === 'bridge') {
      setStatus('Bridge connected. Press CLICK on the temple to cycle pages.')
      appendEventLog('bridge connected')
      if (state.cache) await showPage(state.pageIndex)
    } else {
      setStatus('Bridge unavailable — running in browser-only mock mode.')
      appendEventLog('mock mode (no bridge)')
    }
  },
  onConnecting: () => applyConnectionPillPhase(heroPill, 'connecting'),
})
connector.bind(connectBtn)

refreshBtn.addEventListener('click', () => void refreshData())
alertsBtn.addEventListener('click', () => {
  state.pageIndex = PAGE_ORDER.indexOf('alerts')
  void showPage(state.pageIndex)
})
topRiskBtn.addEventListener('click', () => {
  state.pageIndex = PAGE_ORDER.indexOf('top_users')
  void showPage(state.pageIndex)
})

applyConnectionPillPhase(heroPill, 'idle')

// --- utilities ---

function byId<T extends HTMLElement>(id: string): T {
  const el = document.getElementById(id) as T | null
  if (!el) throw new Error(`Missing #${id}`)
  return el
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}
