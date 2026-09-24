import type { DroneState } from '../types'

export const TELEMETRY_LABELS: Record<string, string> = {
  normal: '正常',
  weak: '较差',
  poor: '很差',
  disconnected: '断开',
}

export const FLIGHT_CONTROL_LABELS: Record<string, string> = {
  normal: '正常',
  fault: '故障',
  dead: '断开',
}

export function finiteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function storedOptionalInteger(raw: string | null): number | null {
  if (raw === null || raw.trim() === '') return null
  const value = Number(raw)
  return Number.isInteger(value) ? value : null
}

export function displayNumber(value: unknown, fractionDigits: number): string {
  return finiteNumber(value) ? value.toFixed(fractionDigits) : '—'
}

export function formationError(drone: DroneState, showErrors: boolean): string {
  if (!showErrors) return '—'
  if (finiteNumber(drone.err_s) && finiteNumber(drone.err_d)) {
    return Math.hypot(drone.err_s, drone.err_d).toFixed(1)
  }
  if (finiteNumber(drone.err_s)) return Math.abs(drone.err_s).toFixed(1)
  return '—'
}

export function rowSeverity(drone: DroneState): 'danger' | 'warning' | 'muted' | 'normal' {
  if ((drone.telemetry_status ?? 'disconnected') === 'disconnected') return 'muted'
  if ((drone.flight_control_status ?? 'dead') === 'dead') return 'danger'
  if (drone.flight_control_status === 'fault') return 'warning'
  return 'normal'
}

export function normalizeHeading(value: unknown): number {
  if (!finiteNumber(value)) return 0
  return ((value % 360) + 360) % 360
}

export function localTime(timestamp: string): string {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return timestamp || '—'
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return '发生未知错误'
}
