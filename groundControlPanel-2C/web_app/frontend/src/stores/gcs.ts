import { computed, markRaw, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { api } from '../api'
import type {
  DroneState,
  FormationSettings,
  FormationState,
  GeoPoint,
  LogEntry,
  RealtimeBatchPayload,
  RuntimeConfig,
  Snapshot,
  TelemetryPayload,
  UdpHealth,
  WsEnvelope,
} from '../types'
import {
  DEFAULT_CONFIG,
  DEFAULT_UDP_HEALTH,
  EMPTY_FORMATIONS,
  GROUP_IDS,
} from '../types'
import { errorMessage, finiteNumber } from '../utils/format'
import { TrackSession, type TrackAppend } from '../utils/trackSession'

export interface ToastMessage {
  id: number
  kind: 'success' | 'error' | 'info'
  text: string
}

function normalizePoints(value: unknown): GeoPoint[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const candidate = item as Record<string, unknown>
    return finiteNumber(candidate.lat) && finiteNumber(candidate.lon)
      ? [{ lat: candidate.lat, lon: candidate.lon }]
      : []
  })
}

function normalizePointRecord(value: unknown): Record<string, GeoPoint[]> {
  if (!value || typeof value !== 'object') return {}
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([id, points]) => [id, normalizePoints(points)]),
  )
}

function nonNegativeInteger(value: unknown): number | null {
  return finiteNumber(value) && value >= 0 && Number.isInteger(value) ? value : null
}

function normalizeDrones(value: unknown): Record<string, DroneState> {
  if (!value || typeof value !== 'object') return {}
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).flatMap(([id, drone]) =>
      drone && typeof drone === 'object'
        ? [[id, { ...(drone as DroneState), id: Number(id) }]]
        : [],
    ),
  )
}

function normalizeLogs(value: unknown): LogEntry[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((entry) => {
    if (typeof entry === 'string') return [{ timestamp: '', text: entry }]
    if (!entry || typeof entry !== 'object') return []
    const candidate = entry as Record<string, unknown>
    if (typeof candidate.text !== 'string') return []
    return [{
      timestamp: typeof candidate.timestamp === 'string' ? candidate.timestamp : '',
      text: candidate.text,
    }]
  })
}

function normalizeFormations(value: unknown): FormationState {
  const fallback = EMPTY_FORMATIONS()
  if (!value || typeof value !== 'object') return fallback
  const candidate = value as Record<string, unknown>
  const membersSource = candidate.members && typeof candidate.members === 'object'
    ? candidate.members as Record<string, unknown>
    : {}
  const leadersSource = candidate.leaders && typeof candidate.leaders === 'object'
    ? candidate.leaders as Record<string, unknown>
    : {}
  const seen = new Set<number>()

  for (const groupId of GROUP_IDS) {
    const source = Array.isArray(membersSource[groupId]) ? membersSource[groupId] as unknown[] : []
    fallback.members[groupId] = source
      .map(Number)
      .filter((id) => Number.isInteger(id) && id >= 0 && !seen.has(id) && (seen.add(id) || true))
      .sort((a, b) => a - b)
    const leader = Number(leadersSource[groupId])
    fallback.leaders[groupId] = Number.isInteger(leader) && fallback.members[groupId].includes(leader)
      ? leader
      : fallback.members[groupId][0] ?? null
  }
  fallback.revision = finiteNumber(candidate.revision) ? candidate.revision : 0
  return fallback
}

function normalizeSettings(value: unknown): FormationSettings {
  if (!value || typeof value !== 'object') return { form_type: 1, spacing: 2000 }
  const candidate = value as Record<string, unknown>
  return {
    form_type: finiteNumber(candidate.form_type) ? candidate.form_type : 1,
    spacing: finiteNumber(candidate.spacing) ? candidate.spacing : 2000,
  }
}

function normalizeConfig(value: unknown): RuntimeConfig {
  if (!value || typeof value !== 'object') return { ...DEFAULT_CONFIG }
  const candidate = value as Record<string, unknown>
  const obstacles = Array.isArray(candidate.obstacles)
    ? candidate.obstacles.flatMap((item) => {
        if (!item || typeof item !== 'object') return []
        const obstacle = item as Record<string, unknown>
        if (!finiteNumber(obstacle.lat) || !finiteNumber(obstacle.lon) || !finiteNumber(obstacle.radius_m)) return []
        return [{
          id: String(obstacle.id ?? `obstacle-${obstacle.lat}-${obstacle.lon}`),
          lat: obstacle.lat,
          lon: obstacle.lon,
          radius_m: obstacle.radius_m,
        }]
      })
    : DEFAULT_CONFIG.obstacles
  return {
    home_lat: finiteNumber(candidate.home_lat) ? candidate.home_lat : DEFAULT_CONFIG.home_lat,
    home_lon: finiteNumber(candidate.home_lon) ? candidate.home_lon : DEFAULT_CONFIG.home_lon,
    map_zoom: finiteNumber(candidate.map_zoom) ? candidate.map_zoom : DEFAULT_CONFIG.map_zoom,
    tile_url: typeof candidate.tile_url === 'string' ? candidate.tile_url : DEFAULT_CONFIG.tile_url,
    tile_attribution: typeof candidate.tile_attribution === 'string'
      ? candidate.tile_attribution
      : DEFAULT_CONFIG.tile_attribution,
    log_entries: finiteNumber(candidate.log_entries) && candidate.log_entries >= 1
      ? Math.floor(candidate.log_entries)
      : DEFAULT_CONFIG.log_entries,
    track_points_per_drone: finiteNumber(candidate.track_points_per_drone)
      && candidate.track_points_per_drone >= 1
      ? Math.floor(candidate.track_points_per_drone)
      : DEFAULT_CONFIG.track_points_per_drone,
    obstacles,
  }
}

function normalizeUdp(value: unknown): UdpHealth {
  if (!value || typeof value !== 'object') return { ...DEFAULT_UDP_HEALTH }
  const candidate = value as Record<string, unknown>
  return {
    receiver_ready: candidate.receiver_ready === true,
    sender_ready: candidate.sender_ready === true,
    last_error: typeof candidate.last_error === 'string' ? candidate.last_error : null,
    bind_host: typeof candidate.bind_host === 'string' ? candidate.bind_host : DEFAULT_UDP_HEALTH.bind_host,
    bind_port: finiteNumber(candidate.bind_port) ? candidate.bind_port : DEFAULT_UDP_HEALTH.bind_port,
    audit_ready: candidate.audit_ready === true,
    audit_last_error: typeof candidate.audit_last_error === 'string' ? candidate.audit_last_error : null,
  }
}

export const useGcsStore = defineStore('gcs', () => {
  const drones = ref<Record<string, DroneState>>({})
  const trajectories = ref<Record<string, GeoPoint[]>>({})
  const logs = ref<LogEntry[]>([])
  const formations = ref<FormationState>(EMPTY_FORMATIONS())
  const formationSettings = ref<FormationSettings>({ form_type: 1, spacing: 2000 })
  const activeFormations = ref<number[]>([])
  const commandBlocked = ref(false)
  const udp = ref<UdpHealth>({ ...DEFAULT_UDP_HEALTH })
  const config = ref<RuntimeConfig>({ ...DEFAULT_CONFIG })
  const trackSession = shallowRef(markRaw(new TrackSession(DEFAULT_CONFIG.track_points_per_drone)))
  const lastTrackAppends = shallowRef<TrackAppend[]>([])
  const trackRevision = ref(0)

  const initialized = ref(false)
  const loading = ref(false)
  const bootstrapError = ref<string | null>(null)
  const wsConnected = ref(false)
  const stale = ref(true)
  const reconnectAttempt = ref(0)
  const lastSeq = ref(-1)
  const lastEventAt = ref<string | null>(null)
  const monitorRevision = ref(0)
  const toasts = ref<ToastMessage[]>([])
  const obstaclesVisible = ref(localStorage.getItem('gcs.obstaclesVisible') === 'true')

  let socket: WebSocket | null = null
  let reconnectTimer: number | null = null
  let socketGeneration = 0
  let toastId = 0

  const sortedDrones = computed(() => Object.entries(drones.value)
    .map(([id, data]) => ({ ...data, id: Number(id) }))
    .filter((drone) => Number.isInteger(drone.id))
    .sort((a, b) => (a.id ?? 0) - (b.id ?? 0)))

  const knownDroneIds = computed(() => sortedDrones.value.map((drone) => drone.id as number))
  const udpReady = computed(() => (
    udp.value.receiver_ready && udp.value.sender_ready && udp.value.audit_ready === true
  ))

  function notify(text: string, kind: ToastMessage['kind'] = 'info'): void {
    const id = ++toastId
    toasts.value.push({ id, kind, text })
    window.setTimeout(() => {
      toasts.value = toasts.value.filter((item) => item.id !== id)
    }, 5000)
  }

  function dismissToast(id: number): void {
    toasts.value = toasts.value.filter((item) => item.id !== id)
  }

  function applySnapshot(snapshot: Snapshot | Record<string, unknown>): void {
    const data = snapshot as Record<string, unknown>
    const nextConfig = normalizeConfig(data.config)
    const shouldResetSession = !initialized.value
    drones.value = normalizeDrones(data.drones)
    trajectories.value = normalizePointRecord(data.trajectories)
    if (shouldResetSession || trackSession.value.capacity !== nextConfig.track_points_per_drone) {
      trackSession.value = markRaw(new TrackSession(nextConfig.track_points_per_drone))
      lastTrackAppends.value = []
      trackRevision.value += 1
    }
    if (shouldResetSession) logs.value = []
    formations.value = normalizeFormations(data.formations)
    formationSettings.value = normalizeSettings(data.formation_settings)
    activeFormations.value = Array.isArray(data.active_formations)
      ? data.active_formations.map(Number).filter(Number.isInteger)
      : []
    commandBlocked.value = data.command_blocked === true
    udp.value = normalizeUdp(data.udp)
    config.value = nextConfig
    initialized.value = true
    bootstrapError.value = null
    monitorRevision.value += 1
  }

  function applyTracksCleared(value: unknown): void {
    const candidate = value && typeof value === 'object'
      ? value as Record<string, unknown>
      : {}
    const epoch = nonNegativeInteger(candidate.epoch) ?? trackSession.value.epoch + 1
    if (epoch < trackSession.value.epoch) return
    trackSession.value.clear(epoch)
    lastTrackAppends.value = []
    trackRevision.value += 1
  }

  function applyEvent(envelope: WsEnvelope): void {
    if (!envelope || typeof envelope !== 'object') return
    if (envelope.type !== 'snapshot' && finiteNumber(envelope.seq) && envelope.seq <= lastSeq.value) return
    if (finiteNumber(envelope.seq)) lastSeq.value = envelope.seq
    lastEventAt.value = envelope.timestamp || new Date().toISOString()

    const payload = envelope.payload && typeof envelope.payload === 'object'
      ? envelope.payload as Record<string, unknown>
      : {}

    switch (envelope.type) {
      case 'snapshot':
        applySnapshot(payload)
        break
      case 'telemetry': {
        const telemetry = payload as TelemetryPayload
        const incomingDrones = normalizeDrones(telemetry.drones)
        drones.value = { ...drones.value, ...incomingDrones }
        monitorRevision.value += 1
        break
      }
      case 'realtime_batch': {
        const batch = payload as RealtimeBatchPayload
        const incomingDrones = normalizeDrones(batch.drones)
        if (Object.keys(incomingDrones).length) {
          drones.value = { ...drones.value, ...incomingDrones }
        }
        const appends = trackSession.value.apply(batch.track_updates)
        if (appends.length) {
          lastTrackAppends.value = appends
          trackRevision.value += 1
        }
        const incomingLogs = normalizeLogs(batch.logs)
        if (incomingLogs.length) {
          logs.value.push(...incomingLogs)
          const overflow = logs.value.length - config.value.log_entries
          if (overflow > 0) logs.value.splice(0, overflow)
        }
        if (batch.formations) formations.value = normalizeFormations(batch.formations)
        if (Object.keys(incomingDrones).length
          || appends.length) {
          monitorRevision.value += 1
        }
        break
      }
      case 'log': {
        const entries = normalizeLogs(payload.entry === undefined ? [] : [payload.entry])
        const incoming = entries.at(0)
        if (incoming) {
          const latest = logs.value.at(-1)
          if (!latest || latest.timestamp !== incoming.timestamp || latest.text !== incoming.text) {
            logs.value.push(incoming)
            const overflow = logs.value.length - config.value.log_entries
            if (overflow > 0) logs.value.splice(0, overflow)
          }
        }
        break
      }
      case 'trajectory': {
        const id = Number(payload.drone_id)
        if (Number.isInteger(id)) {
          trajectories.value = { ...trajectories.value, [String(id)]: normalizePoints(payload.points) }
          monitorRevision.value += 1
        }
        break
      }
      case 'formations':
        formations.value = normalizeFormations(payload)
        break
      case 'formation_settings':
        formationSettings.value = normalizeSettings(payload)
        break
      case 'emergency':
        commandBlocked.value = payload.command_blocked === true
        activeFormations.value = Array.isArray(payload.active_formations)
          ? payload.active_formations.map(Number).filter(Number.isInteger)
          : []
        break
      case 'udp_health':
        udp.value = normalizeUdp(payload)
        break
      case 'tracks_cleared':
        applyTracksCleared(payload)
        monitorRevision.value += 1
        break
      case 'goto_targets_cleared':
        drones.value = Object.fromEntries(Object.entries(drones.value).map(([id, drone]) => {
          const clean = { ...drone }
          delete clean.goto_lat
          delete clean.goto_lon
          return [id, clean]
        }))
        monitorRevision.value += 1
        break
      case 'logs_cleared':
        logs.value = []
        break
      default:
        break
    }
  }

  async function fetchBootstrap(): Promise<void> {
    loading.value = true
    try {
      applySnapshot(await api.bootstrap())
    } catch (error) {
      bootstrapError.value = errorMessage(error)
      stale.value = true
      throw error
    } finally {
      loading.value = false
    }
  }

  function scheduleReconnect(generation: number): void {
    if (generation !== socketGeneration || reconnectTimer !== null) return
    const delay = Math.min(10_000, 800 * (2 ** reconnectAttempt.value))
    reconnectAttempt.value += 1
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      openSocket(generation)
    }, delay)
  }

  function openSocket(generation: number): void {
    if (generation !== socketGeneration) return
    const url = new URL('/api/ws', window.location.href)
    url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    socket = new WebSocket(url)

    socket.addEventListener('open', () => {
      if (generation !== socketGeneration) return
      wsConnected.value = true
      stale.value = false
      reconnectAttempt.value = 0
    })
    socket.addEventListener('message', (event) => {
      if (generation !== socketGeneration) return
      try {
        applyEvent(JSON.parse(String(event.data)) as WsEnvelope)
      } catch {
        notify('收到无法解析的实时消息，已忽略。', 'error')
      }
    })
    socket.addEventListener('close', () => {
      if (generation !== socketGeneration) return
      wsConnected.value = false
      stale.value = true
      socket = null
      scheduleReconnect(generation)
    })
    socket.addEventListener('error', () => socket?.close())
  }

  function connect(): void {
    disconnect()
    socketGeneration += 1
    lastSeq.value = -1
    openSocket(socketGeneration)
  }

  function disconnect(): void {
    socketGeneration += 1
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
    reconnectTimer = null
    socket?.close()
    socket = null
    wsConnected.value = false
  }

  async function initialize(): Promise<void> {
    try {
      await fetchBootstrap()
    } catch {
      // WebSocket may still recover and supply a complete snapshot.
    }
    connect()
  }

  function setObstaclesVisible(visible: boolean): void {
    obstaclesVisible.value = visible
    localStorage.setItem('gcs.obstaclesVisible', String(visible))
  }

  return {
    drones,
    trajectories,
    logs,
    formations,
    formationSettings,
    activeFormations,
    commandBlocked,
    udp,
    config,
    trackSession,
    lastTrackAppends,
    trackRevision,
    initialized,
    loading,
    bootstrapError,
    wsConnected,
    stale,
    reconnectAttempt,
    lastSeq,
    lastEventAt,
    monitorRevision,
    toasts,
    obstaclesVisible,
    sortedDrones,
    knownDroneIds,
    udpReady,
    notify,
    dismissToast,
    applySnapshot,
    applyEvent,
    fetchBootstrap,
    initialize,
    connect,
    disconnect,
    setObstaclesVisible,
  }
})
