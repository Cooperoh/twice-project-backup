import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useGcsStore } from '../src/stores/gcs'
import type { Snapshot, TrackUpdate } from '../src/types'

type FakeListener = (event: { data?: unknown }) => void

class FakeWebSocket {
  static instances: FakeWebSocket[] = []

  readonly url: string
  private readonly listeners = new Map<string, FakeListener[]>()

  constructor(url: string | URL) {
    this.url = String(url)
    FakeWebSocket.instances.push(this)
  }

  addEventListener(type: string, listener: FakeListener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  emit(type: string, data?: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) listener({ data })
  }

  close(): void {
    this.emit('close')
  }
}

function snapshot(): Snapshot {
  return {
    drones: {
      1: { id: 1, lat: 38.3, lon: 117.6, goto_lat: 38.4, goto_lon: 117.7 },
    },
    tracks: {},
    track_meta: {},
    trajectories: {},
    logs: [],
    formations: {
      revision: 2,
      members: { 0: [1], 1: [], 2: [], 3: [] },
      leaders: { 0: 1, 1: null, 2: null, 3: null },
    },
    formation_settings: { form_type: 1, spacing: 2000 },
    active_formations: [],
    command_blocked: false,
    udp: {
      receiver_ready: true,
      sender_ready: true,
      audit_ready: true,
      audit_last_error: null,
      last_error: null,
      bind_host: '0.0.0.0',
      bind_port: 56999,
    },
    config: {
      home_lat: 38.3094,
      home_lon: 117.68,
      map_zoom: 14,
      tile_url: 'https://example.invalid/{z}/{x}/{y}.png',
      tile_attribution: 'test',
      log_entries: 2000,
      track_points_per_drone: 10_000,
      obstacles: [],
    },
  }
}

function update(epoch: number, seq: number, lat: number, lon: number): TrackUpdate {
  return { epoch, seq, point: { lat, lon } }
}

describe('ground-control realtime store', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    FakeWebSocket.instances = []
  })

  it('starts browser-session tracks and logs empty even if an obsolete snapshot includes history', () => {
    const store = useGcsStore()
    const initial = snapshot()
    initial.tracks = { 1: [{ lat: 99, lon: 99 }] }
    initial.track_meta = { 1: { seq: 1, count: 1 } }
    initial.logs = [{ timestamp: 'old', text: 'must not restore' }]

    store.applySnapshot(initial)

    expect(store.trackSession.tracks.size).toBe(0)
    expect(store.logs).toEqual([])
    expect(store.drones['1']?.lat).toBe(38.3)
  })

  it('applies one realtime batch immediately and trims logs in one bounded operation', () => {
    const store = useGcsStore()
    const initial = snapshot()
    initial.config.log_entries = 100
    initial.config.track_points_per_drone = 2
    store.applySnapshot(initial)
    const logBuffer = store.logs
    const pushSpy = vi.spyOn(logBuffer, 'push')
    const spliceSpy = vi.spyOn(logBuffer, 'splice')
    const incomingLogs = Array.from({ length: 101 }, (_, index) => ({
      timestamp: `batch-${index}`,
      text: `log-${index}`,
    }))

    store.applyEvent({
      type: 'realtime_batch',
      seq: 1,
      timestamp: '',
      payload: {
        drones: {
          1: { lat: 38.31, lon: 117.61, alt: 90 },
          2: { lat: 38.32, lon: 117.62, phase: 'hold' },
        },
        track_updates: { 1: update(0, 1, 38.31, 117.61) },
        logs: incomingLogs,
      },
    })

    expect(store.drones['1']?.alt).toBe(90)
    expect(store.drones['2']?.phase).toBe('hold')
    const track = store.trackSession.tracks.get(1)
    expect(track?.count).toBe(1)
    expect(track?.pointAt(0)).toEqual({ lat: 38.31, lon: 117.61 })
    expect(store.lastTrackAppends).toEqual([
      expect.objectContaining({ id: 1, epoch: 0, seq: 1, breakBefore: true }),
    ])
    expect(store.logs).toBe(logBuffer)
    expect(store.logs).toHaveLength(100)
    expect(store.logs[0]?.text).toBe('log-1')
    expect(store.logs.at(-1)?.text).toBe('log-100')
    expect(pushSpy).toHaveBeenCalledTimes(1)
    expect(spliceSpy).toHaveBeenCalledTimes(1)
  })

  it('keeps exactly the configured 2000 most recent browser log entries', () => {
    const store = useGcsStore()
    store.applySnapshot(snapshot())
    const logs = Array.from({ length: 2005 }, (_, index) => ({
      timestamp: String(index),
      text: `log-${index}`,
    }))

    store.applyEvent({
      type: 'realtime_batch',
      seq: 1,
      timestamp: '',
      payload: { logs },
    })

    expect(store.logs).toHaveLength(2000)
    expect(store.logs[0]?.text).toBe('log-5')
    expect(store.logs.at(-1)?.text).toBe('log-2004')
  })

  it('ignores older envelopes and clears both goto coordinates together', () => {
    const store = useGcsStore()
    store.applySnapshot(snapshot())
    store.applyEvent({ type: 'log', seq: 5, timestamp: '', payload: { entry: { timestamp: '', text: 'new' } } })
    store.applyEvent({ type: 'log', seq: 4, timestamp: '', payload: { entry: { timestamp: '', text: 'old' } } })
    store.applyEvent({ type: 'goto_targets_cleared', seq: 6, timestamp: '', payload: {} })

    expect(store.logs.map((entry) => entry.text)).toEqual(['new'])
    expect(store.drones['1']?.goto_lat).toBeUndefined()
    expect(store.drones['1']?.goto_lon).toBeUndefined()
  })

  it('clears tracks by epoch and ignores a late update from the previous epoch', () => {
    const store = useGcsStore()
    store.applySnapshot(snapshot())
    store.applyEvent({
      type: 'realtime_batch', seq: 1, timestamp: '',
      payload: { track_updates: { 1: update(0, 1, 38.3, 117.6) } },
    })
    store.applyEvent({ type: 'tracks_cleared', seq: 2, timestamp: '', payload: { epoch: 1 } })
    store.applyEvent({
      type: 'realtime_batch', seq: 3, timestamp: '',
      payload: { track_updates: { 1: update(0, 2, 38.31, 117.61) } },
    })

    expect(store.trackSession.epoch).toBe(1)
    expect(store.trackSession.tracks.get(1)?.count).toBe(0)
    expect(store.lastTrackAppends).toEqual([])
  })

  it('retains browser-session tracks and logs across WebSocket reconnect snapshots', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const store = useGcsStore()
    store.applySnapshot(snapshot())
    store.applyEvent({
      type: 'realtime_batch', seq: 1, timestamp: '',
      payload: {
        track_updates: { 1: update(0, 1, 38.3, 117.6) },
        logs: [{ timestamp: 'live', text: 'retained' }],
      },
    })
    store.connect()
    const first = FakeWebSocket.instances.at(0)
    first?.emit('open')
    first?.emit('close')
    await vi.advanceTimersByTimeAsync(800)

    const second = FakeWebSocket.instances.at(1)
    second?.emit('open')
    second?.emit('message', JSON.stringify({
      type: 'snapshot',
      seq: 20,
      timestamp: '',
      payload: snapshot(),
    }))

    expect(store.trackSession.tracks.get(1)?.pointAt(0)).toEqual({ lat: 38.3, lon: 117.6 })
    expect(store.logs.map((entry) => entry.text)).toEqual(['retained'])
    expect(store.wsConnected).toBe(true)
    expect(store.stale).toBe(false)
    store.disconnect()
  })
})
