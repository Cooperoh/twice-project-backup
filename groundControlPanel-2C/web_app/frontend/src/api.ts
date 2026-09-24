import type {
  CommandResponse,
  FormationSettings,
  FormationState,
  GroupId,
  LogEntry,
  Snapshot,
} from './types'

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, {
    ...init,
    headers,
    credentials: 'same-origin',
  })

  const contentType = response.headers.get('content-type') ?? ''
  let body: unknown = null
  if (response.status !== 204) {
    body = contentType.includes('application/json')
      ? await response.json().catch(() => null)
      : await response.text().catch(() => '')
  }

  if (!response.ok) {
    const objectBody = body && typeof body === 'object' ? (body as Record<string, unknown>) : null
    const detail = objectBody?.detail ?? objectBody?.message ?? body
    let message = `请求失败（HTTP ${response.status}）`
    if (typeof detail === 'string' && detail) {
      message = detail
    } else if (Array.isArray(detail)) {
      const items = detail
        .map((item) => (item && typeof item === 'object' ? String((item as Record<string, unknown>).msg ?? '') : ''))
        .filter(Boolean)
      if (items.length) message = items.join('；')
    }
    throw new ApiError(response.status, message, detail)
  }

  return body as T
}

export const api = {
  bootstrap: (signal?: AbortSignal) => request<Snapshot>('/api/bootstrap', { signal }),
  health: (signal?: AbortSignal) => request<Record<string, unknown>>('/api/health', { signal }),

  updateFormationSettings: (settings: FormationSettings) =>
    request<FormationSettings>('/api/formation-settings', {
      method: 'PUT',
      body: JSON.stringify(settings),
    }),

  updateFormations: (formations: FormationState) =>
    request<FormationState | { formations: FormationState }>('/api/formations', {
      method: 'PUT',
      body: JSON.stringify({
        revision: formations.revision,
        members: formations.members,
        leaders: formations.leaders,
      }),
    }),

  basicCommand: (command: 'takeoff' | 'rtl' | 'land', group: GroupId) =>
    request<CommandResponse>('/api/commands/basic', {
      method: 'POST',
      body: JSON.stringify({ command, group }),
    }),

  formationCommand: (group: GroupId, settings?: FormationSettings) =>
    request<CommandResponse>('/api/commands/formation', {
      method: 'POST',
      body: JSON.stringify({ group, ...settings }),
    }),

  workbenchCommand: (
    command: 'test_dubins' | 'test_vo' | 'mission',
    targets?: number[],
  ) =>
    request<CommandResponse>('/api/commands/workbench', {
      method: 'POST',
      body: JSON.stringify(targets ? { command, targets } : { command }),
    }),

  abort: () =>
    request<CommandResponse>('/api/commands/abort', {
      method: 'POST',
      body: '{}',
    }),

  resume: () =>
    request<CommandResponse>('/api/commands/resume', {
      method: 'POST',
      body: '{}',
    }),

  clearTracks: () => request<void>('/api/tracks', { method: 'DELETE' }),
  clearGotoTargets: () => request<void>('/api/goto-targets', { method: 'DELETE' }),
  clearLogs: () => request<void>('/api/logs', { method: 'DELETE' }),

  async downloadVisibleLogs(entries: LogEntry[]): Promise<void> {
    if (!entries.length) throw new ApiError(404, '暂无界面日志可导出。')
    const text = entries.map((entry) => `[${entry.timestamp}] ${entry.text}\n`).join('')
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    anchor.download = `ground-control-${stamp}.txt`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  },

  async downloadLogs(): Promise<void> {
    const response = await fetch('/api/logs/export', { credentials: 'same-origin' })
    if (!response.ok) {
      throw new ApiError(response.status, `日志导出失败（HTTP ${response.status}）`)
    }
    const blob = await response.blob()
    if (!blob.size) throw new ApiError(404, '暂无日志可导出')
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    anchor.download = `ground-control-${stamp}.txt`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  },
}
