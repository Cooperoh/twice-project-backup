import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useGcsStore } from '../src/stores/gcs'
import { EarthSession } from '../src/earth/session'
import { earthStatus } from '../src/earth/status'
import { loadEarthRenderer } from '../src/earth/loader'
import type { EarthOptions, EarthRenderer } from '../src/earth/contracts'
import { DroneTrackBuffer } from '../src/utils/trackSession'
import { TrackMirror } from '../src/earth/trackMirror'
import { mount } from '@vue/test-utils'
import EarthView from '../src/views/EarthView.vue'

vi.mock('../src/earth/loader', () => ({ loadEarthRenderer: vi.fn() }))

function renderer(): EarthRenderer {
  return {
    update: vi.fn(), setTracksVisible: vi.fn(), follow: vi.fn(), locateAll: vi.fn(), skyView: vi.fn(),
    resize: vi.fn(), destroy: vi.fn(), setAltitude: vi.fn(),
    overview: vi.fn(), setQuality: vi.fn(), setEffects: vi.fn(), setTerrainEnabled: vi.fn(), reloadTerrain: vi.fn(),
    setPresentation: vi.fn(), visit: vi.fn(),
    setImagery: vi.fn(async () => true),
    camera: vi.fn(() => ({ longitude: 1, latitude: 0.5, height: 12000, heading: 0, pitch: -1, roll: 0 })),
  }
}
function setup() {
  const store = useGcsStore()
  const callbacks = { warning: vi.fn(), error: vi.fn(), stats: vi.fn() }
  const session = new EarthSession(store, callbacks)
  return { store, callbacks, session }
}

describe('Earth manual lifecycle and read-only adapter', () => {
  beforeEach(() => { vi.resetAllMocks(); setActivePinia(createPinia()) })

  it('defers selected imagery until startup and retains the last accepted source across restart', async () => {
    const {session}=setup()
    expect(await session.setImagery({id:'eox'})).toBe(true)
    expect(loadEarthRenderer).not.toHaveBeenCalled()
    const first=renderer(), create=vi.fn((_host: HTMLElement, _options: EarthOptions)=>first)
    vi.mocked(loadEarthRenderer).mockResolvedValue(create)
    await session.start(document.createElement('div'))
    expect(create.mock.calls[0]![1].imagery).toEqual({id:'eox'})
    vi.mocked(first.setImagery).mockResolvedValueOnce(false)
    expect(await session.setImagery({id:'nasa'})).toBe(false)
    session.close()
    await session.start(document.createElement('div'))
    expect(create.mock.calls[1]![1].imagery).toEqual({id:'eox'})
    session.close()
  })

  it('retains daytime switches across restart and changes the view without releasing follow', async () => {
    const { session } = setup()
    const first = renderer()
    vi.mocked(loadEarthRenderer).mockResolvedValueOnce(() => first)
    session.setEffects({ clouds: true, satellites: true, animate: false,
      cumulus: false, cirrus: true, haze: false, atmosphere: true })
    session.follow(2)
    session.skyView()
    expect(loadEarthRenderer).not.toHaveBeenCalled()
    await session.start(document.createElement('div'))
    session.skyView()
    expect(first.skyView).toHaveBeenCalledOnce()
    expect(first.follow).toHaveBeenLastCalledWith(2)
    session.close()
    const second = renderer()
    vi.mocked(loadEarthRenderer).mockResolvedValueOnce(() => second)
    await session.start(document.createElement('div'))
    expect(second.setEffects).toHaveBeenLastCalledWith({ clouds: true, satellites: true, animate: false,
      cumulus: false, cirrus: true, haze: false, atmosphere: true })
    expect(second.follow).toHaveBeenLastCalledWith(2)
    session.close()
  })

  it('applies height input immediately, accepts zero, and returns empty/negative input to telemetry', async () => {
    const view = renderer()
    vi.mocked(loadEarthRenderer).mockResolvedValue(() => view)
    const wrapper = mount(EarthView, { global: { stubs: { EarthTokenSettings: true } } })
    await wrapper.findAll('button').find(button => button.text() === '配置')!.trigger('click')
    const input = wrapper.get('input[aria-label="统一显示高度（米）"]')
    await input.setValue('850')
    expect(loadEarthRenderer).not.toHaveBeenCalled()
    await wrapper.findAll('button').find(button => button.text().includes('启动数字地球'))!.trigger('click')
    expect(view.setAltitude).toHaveBeenLastCalledWith(850)
    for (const [value, expected] of [['0', 0], ['-1', null], ['', null], ['1250.5', 1250.5]] as const) {
      await input.setValue(value)
      expect(view.setAltitude).toHaveBeenLastCalledWith(expected)
    }
    wrapper.unmount()
  })

  it('retains height across restart without changing telemetry', async () => {
    const { session, store } = setup()
    store.drones = { 1: { lat: 38, lon: 117, alt: 340 } }
    const first = renderer()
    vi.mocked(loadEarthRenderer).mockResolvedValueOnce(() => first)
    await session.start(document.createElement('div'))
    expect(first.setAltitude).toHaveBeenLastCalledWith(null)
    session.setAltitude(900)
    expect(first.setAltitude).toHaveBeenLastCalledWith(900)
    expect(store.drones[1]?.alt).toBe(340)
    session.close()
    const second = renderer()
    vi.mocked(loadEarthRenderer).mockResolvedValueOnce(() => second)
    await session.start(document.createElement('div'))
    expect(second.setAltitude).toHaveBeenLastCalledWith(900)
    session.close()
  })

  it('synchronizes tour interruption and restarts with the same sunlight but without auto motion', async () => {
    const { session } = setup()
    const first = renderer()
    const create = vi.fn((_host: HTMLElement, _options: EarthOptions) => first)
    vi.mocked(loadEarthRenderer).mockResolvedValue(create)
    await session.start(document.createElement('div'))
    session.setPresentation({ tour: true, sunlight: true, sunLongitude: -30 })
    create.mock.calls[0]![1].onTourChange?.(false)
    session.visit('polar')
    expect(first.visit).toHaveBeenLastCalledWith('polar')
    session.close()
    const second = renderer()
    vi.mocked(loadEarthRenderer).mockResolvedValueOnce(() => second)
    await session.start(document.createElement('div'))
    expect(second.setPresentation).toHaveBeenLastCalledWith({ tour: false, sunlight: true, sunLongitude: -30 })
    expect(second.follow).toHaveBeenLastCalledWith(null)
    session.close()
  })

  it('keeps quality across restarts and clears following when returning to the globe', async () => {
    const { session } = setup()
    const first = renderer()
    vi.mocked(loadEarthRenderer).mockResolvedValueOnce(() => first)
    session.setQuality('smooth')
    session.setTerrainEnabled(false)
    session.setEffects({ clouds: false, satellites: true, animate: false, labels: false, labelDensity: 'sparse', boundaries: false })
    session.follow(3)
    await session.start(document.createElement('div'))
    expect(first.setQuality).toHaveBeenLastCalledWith('smooth')
    expect(first.setTerrainEnabled).toHaveBeenLastCalledWith(false)
    expect(first.follow).toHaveBeenLastCalledWith(3)
    session.overview()
    expect(first.overview).toHaveBeenCalledOnce()
    session.close()
    const second = renderer()
    vi.mocked(loadEarthRenderer).mockResolvedValueOnce(() => second)
    await session.start(document.createElement('div'))
    expect(second.setQuality).toHaveBeenLastCalledWith('smooth')
    expect(second.setTerrainEnabled).toHaveBeenLastCalledWith(false)
    expect(second.setEffects).toHaveBeenLastCalledWith({ clouds: false, satellites: true, animate: false, labels: false, labelDensity: 'sparse', boundaries: false })
    expect(second.follow).toHaveBeenLastCalledWith(null)
    session.close()
  })

  it('does not load or subscribe while idle, then stops forwarding after close', async () => {
    const { store, session } = setup()
    const view = renderer()
    const create = vi.fn(() => view)
    vi.mocked(loadEarthRenderer).mockResolvedValue(create)
    store.drones = { 1: { lat: 38, lon: 117 } }
    expect(loadEarthRenderer).not.toHaveBeenCalled()
    await session.start(document.createElement('div'))
    expect(view.update).toHaveBeenCalledTimes(1)
    store.drones = { 1: { lat: 39, lon: 118 } }
    expect(view.update).toHaveBeenCalledTimes(2)
    await session.start(document.createElement('div'))
    expect(create).toHaveBeenCalledTimes(1)
    session.close()
    expect(view.destroy).toHaveBeenCalledTimes(1)
    store.drones = { 1: { lat: 40, lon: 119 } }
    expect(view.update).toHaveBeenCalledTimes(2)
    expect(store.drones[1]?.lat).toBe(40)
    expect(earthStatus.value).toBe('idle')
    session.close()
    expect(view.destroy).toHaveBeenCalledTimes(1)
  })

  it('ignores a cancelled import even if it resolves after a newer start', async () => {
    const { session } = setup()
    let release!: (value: () => EarthRenderer) => void
    vi.mocked(loadEarthRenderer).mockImplementationOnce(() => new Promise((resolve) => { release = resolve }))
    const cancelled = session.start(document.createElement('div'))
    session.close()
    const current = renderer()
    vi.mocked(loadEarthRenderer).mockResolvedValueOnce(() => current)
    await session.start(document.createElement('div'))
    const obsolete = vi.fn(() => renderer())
    release(obsolete)
    await cancelled
    expect(obsolete).not.toHaveBeenCalled()
    expect(earthStatus.value).toBe('running')
    session.close()
    expect(current.destroy).toHaveBeenCalledOnce()
  })

  it('allows retry after failure and restores the last camera after explicit close', async () => {
    const { session, callbacks } = setup()
    vi.mocked(loadEarthRenderer).mockRejectedValueOnce(new Error('load failed'))
    await session.start(document.createElement('div'))
    expect(earthStatus.value).toBe('error')
    expect(callbacks.error).toHaveBeenLastCalledWith('load failed')
    const first = renderer()
    vi.mocked(loadEarthRenderer).mockResolvedValueOnce(() => first)
    await session.start(document.createElement('div'))
    session.close()
    const second = renderer()
    const create = vi.fn((_host: HTMLElement, _options: EarthOptions) => second)
    vi.mocked(loadEarthRenderer).mockResolvedValueOnce(create)
    await session.start(document.createElement('div'))
    expect(create.mock.calls[0]?.[1]).toEqual(expect.objectContaining({ camera: first.camera() }))
    session.close()
  })
})

function append(buffer: DroneTrackBuffer, seq: number, epoch = 0): void {
  buffer.append({ epoch, seq, point: { lat: 38 + seq / 1000000, lon: 117 } })
}

describe('Earth bounded incremental track mirror', () => {
  it('batches history, preserves sequence gaps and does no geometry work on unchanged buffers', () => {
    const buffer = new DroneTrackBuffer(1000)
    for (let seq = 1; seq <= 260; ++seq) append(buffer, seq)
    append(buffer, 262)
    const mirror = new TrackMirror()
    expect(mirror.sync(buffer, 100).pending).toBe(true)
    while (mirror.sync(buffer, 100).pending) { /* bounded catch-up */ }
    expect(mirror.pointCount).toBe(261)
    expect(mirror.segments.every((segment) => segment.points.length <= 128)).toBe(true)
    expect(mirror.segments.at(-1)?.sequences).toEqual([262])
    expect(mirror.sync(buffer).changed).toEqual([])
    expect(buffer.count).toBe(261)
  })

  it('evicts expired points while receiving data during catch-up and clears on epoch reset', () => {
    const buffer = new DroneTrackBuffer(150)
    const mirror = new TrackMirror()
    for (let seq = 1; seq <= 200; ++seq) append(buffer, seq)
    mirror.sync(buffer, 50)
    for (let seq = 201; seq <= 500; ++seq) append(buffer, seq)
    while (mirror.sync(buffer, 40).pending) { /* catch up from retained source */ }
    expect(mirror.pointCount).toBe(150)
    expect(mirror.segments[0]?.sequences[0]).toBe(351)
    expect(mirror.segments.at(-1)?.sequences.at(-1)).toBe(500)
    buffer.clear(1)
    expect(mirror.sync(buffer).removed.length).toBeGreaterThan(0)
    expect(mirror.pointCount).toBe(0)
    append(buffer, 1, 1)
    mirror.sync(buffer)
    expect(mirror.pointCount).toBe(1)
  })

  it('handles all 24 drones at the existing 10000-point capacity', () => {
    for (let id = 1; id <= 24; ++id) {
      const buffer = new DroneTrackBuffer(10000)
      const mirror = new TrackMirror()
      for (let seq = 1; seq <= 12000; ++seq) append(buffer, seq)
      while (mirror.sync(buffer, 2048).pending) { /* bounded catch-up */ }
      expect(mirror.pointCount).toBe(10000)
      expect(mirror.segments[0]?.sequences[0]).toBe(2001)
      expect(mirror.segments.length).toBeLessThan(81)
    }
  })
})
