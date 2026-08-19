export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  const response = await fetch(`/api${path}`, { ...init, headers })
  const text = await response.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { detail: text }
    }
  }
  if (!response.ok) {
    const err = data as { error?: string; detail?: string }
    throw new Error(err.error || err.detail || response.statusText)
  }
  return data as T
}

export const getBootstrap = () => api<Bootstrap>("/bootstrap")
export const saveSetup = (body: Record<string, unknown>) =>
  api<{ ok: boolean; settings: Settings }>("/setup", { method: "POST", body: JSON.stringify(body) })
export const saveSettings = (body: Record<string, unknown>) =>
  api<Settings>("/settings", { method: "POST", body: JSON.stringify(body) })
export const startCollector = () => api("/collector/start", { method: "POST", body: "{}" })
export const stopCollector = () => api("/collector/stop", { method: "POST", body: "{}" })
export const startInference = () => api("/inference/start", { method: "POST", body: "{}" })
export const stopInference = () => api("/inference/stop", { method: "POST", body: "{}" })
export const getLive = () => api<LivePayload>("/live")
export const postBackfill = (days: number, body?: { interval?: string; intervals?: string[]; assets?: string[] }) =>
  api<{
    ok: boolean
    fetched: number
    created: number
    updated: number
    assets?: string[]
    intervals?: string[]
    per?: Array<Record<string, unknown>>
  }>("/backfill", {
    method: "POST",
    body: JSON.stringify({ days, ...body }),
  })
export const getJobs = () => api<{ jobs: TrainJob[] }>("/train")
export const postTrain = (body: Record<string, unknown>) =>
  api<{ ok: boolean; job: TrainJob }>("/train", { method: "POST", body: JSON.stringify(body) })
export const getJob = (id: number) => api<{ job: TrainJob; artifacts: Artifact[] }>(`/train/${id}`)
export const getEnsemble = () => api<Ensemble>("/ensemble")
export const saveEnsemble = (body: Record<string, unknown>) =>
  api<Ensemble>("/ensemble", { method: "POST", body: JSON.stringify(body) })
export const getPredictions = () => api<{ predictions: Prediction[] }>("/predict")
export const postPredict = (place = false) =>
  api<{ prediction: Prediction; order: Order | null }>("/predict", {
    method: "POST",
    body: JSON.stringify({ place }),
  })
export const getOrders = () => api<{ orders: Order[] }>("/orders")

export type Settings = Record<string, unknown> & {
  setup_complete?: boolean
  dry_run?: boolean
  min_edge?: number
  min_confidence?: number
  order_size?: number
  enabled_sources?: string[]
  enabled_assets?: string[]
  bar_timeframes?: string[]
  bar_interval_seconds?: number
  polymarket_private_key_set?: boolean
  ensemble_mode?: string
}

export type UniverseAsset = { id: string; label: string }
export type UniverseTimeframe = { id: string; label: string; seconds: number; kline?: boolean }
export type LabelMode = { id: string; label: string; field: string; detail: string }
export type Universe = {
  assets: UniverseAsset[]
  timeframes: UniverseTimeframe[]
  label_modes: LabelMode[]
  default_assets: string[]
  default_timeframes: string[]
  enabled_assets: string[]
  enabled_timeframes: string[]
}
export type BarBreakdown = {
  asset: string
  interval_seconds: number
  bars: number
  labeled_15m: number
  labeled_next: number
}

export type Source = {
  id: string
  label: string
  kind: string
  detail: string
  enabled: boolean
  status: string
  message_count: number
  last_message_at: string | null
  error: string
}

export type ProcessInfo = {
  name: string
  running: boolean
  pid: number | null
  heartbeat_at: string | null
  stats: Record<string, unknown>
  last_error: string
}

export type Market = {
  slug: string
  question?: string
  start_ts: number
  end_ts?: number
  yes_bid?: number | null
  yes_ask?: number | null
  yes_mid?: number | null
  no_bid?: number | null
  no_ask?: number | null
  btc_open?: number | null
  btc_last?: number | null
  seconds_left?: number
}

export type Bar = {
  ts: number
  asset?: string
  interval_seconds: number
  mid_price: number | null
  label_up_15m: boolean | null
  label_up_next?: boolean | null
  features: Record<string, number | null>
  train_features: Record<string, number>
  n_features: number
}

export type Prediction = {
  id: number
  ts: number
  p_up: number
  per_model: Record<string, number>
  implied_yes: number | null
  edge: number | null
  action: string
  market_slug: string
}

export type Order = {
  id: number
  created_at: string
  dry_run: boolean
  market_slug: string
  outcome: string
  price: number
  size: number
  status: string
}

export type TrainJob = {
  id: number
  status: string
  config: Record<string, unknown>
  summary: Record<string, unknown>
  error: string
  created_at: string
  finished_at: string | null
  models?: Array<Record<string, unknown>>
}

export type Artifact = {
  id: number
  name: string
  metrics: Record<string, unknown>
  selected: boolean
  weight: number
}

export type Ensemble = {
  mode: string
  min_auc: number
  active_job_id: number | null
  members: Array<{
    id: number
    name: string
    selected: boolean
    weight: number
    metrics: Record<string, number | undefined>
  }>
}

export type Architecture = { id: string; label: string; family: string }

export type Bootstrap = {
  setup_complete: boolean
  settings: Settings
  sources: Source[]
  architectures: Architecture[]
  universe?: Universe
  collector: ProcessInfo
  inference: ProcessInfo
  counts: Record<string, number> & { by_asset_interval?: BarBreakdown[] }
  latest_bar: Bar | null
  market: Market
  latest_prediction: Prediction | null
}

export type LivePayload = {
  collector: ProcessInfo
  inference: ProcessInfo
  ticks: Array<{
    ts_ms: number
    venue: string
    asset?: string
    price: number | null
    size: number | null
    is_buyer_maker: boolean | null
  }>
  bars: Bar[]
  logs: Array<{ id: number; created_at: string; level: string; source: string; message: string }>
}
