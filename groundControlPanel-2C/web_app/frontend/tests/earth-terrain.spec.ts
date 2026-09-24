import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CesiumTerrainProvider, EllipsoidTerrainProvider, Event, IonResource } from 'cesium'
import { EarthTerrain } from '../src/earth/terrain'

function provider() { return { errorEvent: new Event() } as CesiumTerrainProvider }
function setup() {
  const apply = vi.fn()
  const status = vi.fn()
  return { apply, status, terrain: new EarthTerrain(async () => 'test-public-token', apply, status) }
}

describe('online terrain lifecycle and fallback', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.spyOn(IonResource, 'fromAssetId').mockResolvedValue({} as IonResource)
  })
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })

  it('never requests terrain while idle or disabled, and handles a missing token', async () => {
    const load = vi.mocked(IonResource.fromAssetId)
    const { terrain } = setup()
    expect(load).not.toHaveBeenCalled()
    terrain.setEnabled(false)
    expect(load).not.toHaveBeenCalled()
    const status = vi.fn()
    const missing = new EarthTerrain(async () => null, vi.fn(), status)
    missing.setEnabled(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(status).toHaveBeenLastCalledWith('unconfigured')
    expect(load).not.toHaveBeenCalled()
    terrain.destroy(); missing.destroy()
  })

  it('reuses a ready provider, then falls back on tile failure and permits retry', async () => {
    const first = provider()
    const load = vi.spyOn(CesiumTerrainProvider, 'fromUrl').mockResolvedValue(first)
    const { terrain, apply, status } = setup()
    terrain.setEnabled(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(apply).toHaveBeenLastCalledWith(first)
    expect(status).toHaveBeenLastCalledWith('ready')
    terrain.setEnabled(false)
    expect(first.errorEvent.numberOfListeners).toBe(0)
    expect(apply.mock.lastCall?.[0]).toBeInstanceOf(EllipsoidTerrainProvider)
    terrain.setEnabled(true)
    expect(load).toHaveBeenCalledTimes(1)
    first.errorEvent.raiseEvent({ message: 'private URL should never reach UI' })
    expect(status).toHaveBeenLastCalledWith('error')
    expect(apply.mock.lastCall?.[0]).toBeInstanceOf(EllipsoidTerrainProvider)
    expect(first.errorEvent.numberOfListeners).toBe(0)
    terrain.setEnabled(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(load).toHaveBeenCalledTimes(2)
    terrain.destroy()
    expect(first.errorEvent.numberOfListeners).toBe(0)
  })

  it.each(['disable', 'destroy', 'timeout'] as const)('ignores completion after %s', async (action) => {
    let resolve!: (value: CesiumTerrainProvider) => void
    vi.spyOn(CesiumTerrainProvider, 'fromUrl').mockImplementation(() => new Promise(r => { resolve = r }))
    const { terrain, apply, status } = setup()
    terrain.setEnabled(true)
    await vi.advanceTimersByTimeAsync(0)
    if (action === 'disable') terrain.setEnabled(false)
    if (action === 'destroy') terrain.destroy()
    if (action === 'timeout') {
      await vi.advanceTimersByTimeAsync(20_000)
      expect(status).toHaveBeenLastCalledWith('error')
    }
    apply.mockClear(); status.mockClear()
    const stale = provider()
    resolve(stale)
    await vi.advanceTimersByTimeAsync(0)
    expect(apply).not.toHaveBeenCalled()
    expect(status).not.toHaveBeenCalled()
    expect(stale.errorEvent.numberOfListeners).toBe(0)
    terrain.destroy()
  })

  it('contains initial network failures without exposing service errors', async () => {
    vi.spyOn(CesiumTerrainProvider, 'fromUrl').mockRejectedValue(new Error('sensitive URL'))
    const { terrain, apply, status } = setup()
    terrain.setEnabled(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(status).toHaveBeenLastCalledWith('error')
    expect(apply.mock.lastCall?.[0]).toBeInstanceOf(EllipsoidTerrainProvider)
    terrain.destroy()
  })

  it('reloads changed credentials and discards a pending read from the previous token', async () => {
    let resolveOld!: (token: string) => void
    const read = vi.fn().mockImplementationOnce(() => new Promise(r => { resolveOld = r }))
      .mockResolvedValueOnce('replacement-token').mockResolvedValueOnce(null)
    const ready = provider()
    vi.spyOn(CesiumTerrainProvider, 'fromUrl').mockResolvedValue(ready)
    const status = vi.fn()
    const terrain = new EarthTerrain(read, vi.fn(), status)
    terrain.setEnabled(true)
    terrain.reload()
    await vi.advanceTimersByTimeAsync(0)
    expect(IonResource.fromAssetId).toHaveBeenCalledExactlyOnceWith(1, { accessToken: 'replacement-token' })
    resolveOld('obsolete-token')
    await vi.advanceTimersByTimeAsync(0)
    expect(IonResource.fromAssetId).toHaveBeenCalledTimes(1)
    terrain.reload()
    await vi.advanceTimersByTimeAsync(0)
    expect(status).toHaveBeenLastCalledWith('unconfigured')
    expect(ready.errorEvent.numberOfListeners).toBe(0)
    terrain.destroy()
  })
})
