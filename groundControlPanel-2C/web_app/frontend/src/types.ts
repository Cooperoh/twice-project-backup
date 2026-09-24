export type GroupId = 0 | 1 | 2 | 3

export interface GeoPoint {
  lat: number
  lon: number
}

export interface TrackMeta {
  seq: number
  count: number
}

export interface TrackUpdate {
  epoch: number
  seq: number
  point: GeoPoint
}

export interface TelemetryPayload {
  drones?: Record<string, DroneState>
  [key: string]: unknown
}

export interface RealtimeBatchPayload {
  drones?: Record<string, DroneState>
  track_updates?: Record<string, TrackUpdate>
  logs?: LogEntry[]
  formations?: FormationState
}

export interface DroneState {
  id?: number
  lat?: number | null
  lon?: number | null
  speed?: number | null
  heading?: number | null
  err_s?: number | null
  err_d?: number | null
  tag?: string | null
  goto_lat?: number | null
  goto_lon?: number | null
  telemetry_status?: 'normal' | 'weak' | 'poor' | 'disconnected' | string
  flight_control_status?: 'normal' | 'fault' | 'dead' | string
  [key: string]: unknown
}

export interface LogEntry {
  timestamp: string
  text: string
}

export interface FormationState {
  revision: number
  members: Record<GroupId, number[]>
  leaders: Record<GroupId, number | null>
}

export interface FormationSettings {
  form_type: number
  spacing: number
}

export interface Obstacle {
  id: string
  lat: number
  lon: number
  radius_m: number
}

export interface UdpHealth {
  receiver_ready: boolean
  sender_ready: boolean
  last_error: string | null
  bind_host: string
  bind_port: number
  audit_ready?: boolean
  audit_last_error?: string | null
}

export interface RuntimeConfig {
  home_lat: number
  home_lon: number
  map_zoom: number
  tile_url: string
  tile_attribution: string
  log_entries: number
  track_points_per_drone: number
  obstacles: Obstacle[]
}

export interface Snapshot {
  drones: Record<string, DroneState>
  tracks: Record<string, GeoPoint[]>
  track_meta: Record<string, TrackMeta>
  trajectories: Record<string, GeoPoint[]>
  logs: LogEntry[]
  formations: FormationState
  formation_settings: FormationSettings
  active_formations: number[]
  command_blocked: boolean
  udp: UdpHealth
  config: RuntimeConfig
}

export interface WsEnvelope<T = unknown> {
  type: string
  seq: number
  timestamp: string
  payload: T
}

export interface DispatchTarget {
  host: string
  port: number
  sent: boolean
  error: string | null
}

export interface CommandDispatch {
  payload: Record<string, unknown>
  targets: DispatchTarget[]
}

export interface CommandResponse {
  locally_dispatched: boolean
  message: string
  dispatches: CommandDispatch[]
}

export interface ApiErrorBody {
  detail?: string | Array<{ loc?: Array<string | number>; msg?: string }>
  message?: string
}

export const GROUP_IDS: readonly GroupId[] = [0, 1, 2, 3]

export const EMPTY_FORMATIONS = (): FormationState => ({
  revision: 0,
  members: { 0: [], 1: [], 2: [], 3: [] },
  leaders: { 0: null, 1: null, 2: null, 3: null },
})

export const DEFAULT_CONFIG: RuntimeConfig = {
  home_lat: 38.3094,
  home_lon: 117.68,
  map_zoom: 14,
  tile_url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  tile_attribution: '&copy; OpenStreetMap contributors',
  log_entries: 2000,
  track_points_per_drone: 10_000,
  obstacles: [
    { id: 'obs_0', lat: 38.31658652, lon: 117.68, radius_m: 100 },
    { id: 'obs_1', lat: 38.32017978, lon: 117.6754207, radius_m: 300 },
    { id: 'obs_2', lat: 38.32017978, lon: 117.6845793, radius_m: 200 },
  ],
}

export const DEFAULT_UDP_HEALTH: UdpHealth = {
  receiver_ready: false,
  sender_ready: false,
  last_error: null,
  bind_host: '0.0.0.0',
  bind_port: 56999,
  audit_ready: false,
  audit_last_error: null,
}
