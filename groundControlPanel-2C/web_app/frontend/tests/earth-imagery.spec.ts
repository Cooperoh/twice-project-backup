import { afterEach, describe, expect, it, vi } from 'vitest'
import { ImageryLayerCollection, UrlTemplateImageryProvider } from 'cesium'
import { EarthImagery, createImageryProvider } from '../src/earth/imagery'
import { imagerySource, normalizeImagery, loadImagerySelection, saveImagerySelection, IMAGERY_STORAGE_KEY } from '../src/earth/imageryConfig'

function provider() {
  const value = new UrlTemplateImageryProvider({url:'https://example.test/{z}/{x}/{y}.png'})
  vi.spyOn(value, 'requestImage').mockResolvedValue(document.createElement('canvas'))
  return value
}
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); localStorage.clear() })

describe('Earth imagery configuration', () => {
  it('accepts XYZ, TMS and ArcGIS URLs while preserving query credentials', () => {
    const custom = normalizeImagery({id:'custom',url:' https://example.test/{z}/{x}/{-y}.jpg?key=user-key ',maximumLevel:14})
    expect(imagerySource(custom).url).toBe('https://example.test/{z}/{x}/{reverseY}.jpg?key=user-key')
    expect(imagerySource(normalizeImagery({id:'custom',url:'https://example.test/MapServer?token=user-key'})).kind).toBe('arcgis')
  })
  it.each(['javascript:alert(1)', 'file:///tiles/{z}/{x}/{y}.png', 'https://user:pass@example.test/MapServer',
    'https://example.test/map', 'https://example.test/{z}/{x}/{y}/{bad}.png'])('rejects invalid source %s', url => {
    expect(() => normalizeImagery({id:'custom',url})).toThrow()
  })
  it('bounds zoom levels and recovers from corrupt persisted settings', () => {
    expect(() => normalizeImagery({id:'custom',url:'https://example.test/{z}/{x}/{y}.png',maximumLevel:99})).toThrow()
    localStorage.setItem(IMAGERY_STORAGE_KEY,'{bad json')
    expect(loadImagerySelection()).toEqual({id:'esri'})
    expect(saveImagerySelection({id:'eox'})).toBe(true)
    expect(loadImagerySelection()).toEqual({id:'eox'})
  })
  it('treats a custom attribution as text rather than HTML', async () => {
    const value = await createImageryProvider({id:'custom',url:'https://example.test/{z}/{x}/{y}.png',attribution:'<img src=x onerror=alert(1)>'})
    expect(value.credit.html).toContain('&lt;img')
    expect(value.credit.html).not.toContain('<img')
  })
})

describe('Earth imagery replacement lifecycle', () => {
  it('keeps the old layer during preparation, replaces it once, and retains it on failure', async () => {
    const layers = new ImageryLayerCollection(), state = vi.fn()
    const first = provider(), second = provider()
    const load = vi.fn().mockResolvedValueOnce(first)
    const imagery = new EarthImagery(layers,state,load)
    expect(await imagery.set({id:'esri'})).toBe(true)
    const oldLayer = layers.get(0)
    let resolve!: (value: UrlTemplateImageryProvider) => void
    load.mockImplementationOnce(() => new Promise(r => {resolve=r}))
    const pending = imagery.set({id:'eox'})
    expect(layers.length).toBe(1)
    expect(layers.get(0)).toBe(oldLayer)
    resolve(second)
    expect(await pending).toBe(true)
    expect(layers.length).toBe(1)
    expect(oldLayer.isDestroyed()).toBe(true)
    expect(first.errorEvent.numberOfListeners).toBe(0)
    load.mockRejectedValueOnce(new Error('private address or key'))
    expect(await imagery.set({id:'nasa'})).toBe(false)
    expect(layers.get(0).imageryProvider).toBe(second)
    expect(JSON.stringify(state.mock.calls)).not.toContain('private address')
    imagery.destroy()
    expect(layers.length).toBe(0)
    expect(second.errorEvent.numberOfListeners).toBe(0)
  })
  it.each(['superseded', 'closed', 'timed out'] as const)('does not install a late provider when %s', async action => {
    vi.useFakeTimers()
    const layers = new ImageryLayerCollection(), state = vi.fn(), stale = provider()
    let resolve!: (value: UrlTemplateImageryProvider) => void
    const load=vi.fn().mockImplementationOnce(()=>new Promise(r=>{resolve=r})).mockResolvedValue(provider())
    const imagery=new EarthImagery(layers,state,load)
    const pending=imagery.set({id:'esri'})
    if(action==='superseded') expect(await imagery.set({id:'eox'})).toBe(true)
    if(action==='closed') imagery.destroy()
    if(action==='timed out') await vi.advanceTimersByTimeAsync(15_000)
    expect(await pending).toBe(false)
    resolve(stale)
    await vi.advanceTimersByTimeAsync(0)
    expect(stale.requestImage).not.toHaveBeenCalled()
    expect(layers.length).toBe(action==='superseded'?1:0)
    imagery.destroy()
  })
  it('rejects an unavailable root image before dropping the existing source', async () => {
    const layers=new ImageryLayerCollection(), first=provider(), broken=provider()
    vi.mocked(broken.requestImage).mockRejectedValue(new Error('HTTP 404 with private URL'))
    const imagery=new EarthImagery(layers,vi.fn(),vi.fn().mockResolvedValueOnce(first).mockResolvedValueOnce(broken))
    await imagery.set({id:'esri'})
    expect(await imagery.set({id:'eox'})).toBe(false)
    expect(layers.get(0).imageryProvider).toBe(first)
    imagery.destroy()
  })
})
