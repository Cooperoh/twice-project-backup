import { ArcGisMapServerImageryProvider, Credit, UrlTemplateImageryProvider, WebMercatorTilingScheme,
  type ImageryProvider, type ImageryLayer, type ImageryLayerCollection } from 'cesium'
import { imagerySource, type ImagerySelection, type ImageryState } from './imageryConfig'

function credit(text: string): Credit {
  return new Credit(text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'))
}
export async function createImageryProvider(selection: ImagerySelection): Promise<ImageryProvider> {
  const source = imagerySource(selection)
  if (source.kind === 'arcgis') return ArcGisMapServerImageryProvider.fromUrl(source.url, {
    enablePickFeatures: false, maximumLevel: source.maximumLevel, credit: credit(source.attribution),
  })
  return new UrlTemplateImageryProvider({ url: source.url, maximumLevel: source.maximumLevel,
    tilingScheme: new WebMercatorTilingScheme(), credit: credit(source.attribution), enablePickFeatures: false })
}

/** Transactional replacement: validate one image before releasing the current layer. */
export class EarthImagery {
  private generation = 0
  private disposed = false
  private layer?: ImageryLayer
  private stopErrors?: () => void
  private cancelPending?: () => void

  constructor(private readonly layers: ImageryLayerCollection,
    private readonly changed: (ready: boolean, state: ImageryState) => void,
    private readonly load = createImageryProvider) {}

  async set(selection: ImagerySelection): Promise<boolean> {
    if (this.disposed) return false
    const generation = ++this.generation
    this.cancelPending?.()
    const current = () => !this.disposed && generation === this.generation
    this.changed(!!this.layer, { status: 'loading', message: `正在检查${imagerySource(selection).name}…` })
    let timer: ReturnType<typeof setTimeout> | undefined
    const cancelled = new Promise<never>((_resolve, reject) => {
      this.cancelPending = () => reject(new Error('cancelled'))
      timer = setTimeout(() => reject(new Error('timeout')), 15_000)
    })
    try {
      const prepare = async () => {
        const provider = await this.load(selection)
        if (!current()) throw new Error('cancelled')
        // No throttled Request argument: test this root tile independently of camera queues.
        const image = await provider.requestImage(0, 0, 0)
        if (!image) throw new Error('empty tile')
        try {
          if (image instanceof HTMLImageElement && provider.tileDiscardPolicy?.isReady() &&
              provider.tileDiscardPolicy.shouldDiscardImage(image)) throw new Error('discarded tile')
        } finally {
          if ('close' in image && typeof image.close === 'function') image.close()
        }
        return provider
      }
      const provider = await Promise.race([prepare(), cancelled])
      if (!current()) return false
      const next = this.layers.addImageryProvider(provider)
      const previous = this.layer
      this.stopErrors?.()
      this.layer = next
      if (previous) this.layers.remove(previous, true)
      this.stopErrors = provider.errorEvent.addEventListener(() => {
        if (this.layer !== next || this.disposed) return
        this.changed(true, { status: 'error', message: '当前影像有瓦片加载失败。可重新应用或选择其他影像源。' })
      })
      this.changed(true, { status: 'ready', message: `当前影像：${imagerySource(selection).name}` })
      return true
    } catch {
      if (current()) this.changed(!!this.layer, { status: 'error',
        message: `影像源未能通过检查。请检查地址、网络、访问权限及跨域设置。${this.layer ? '已保留原影像。' : '当前显示本地备用底图。'}` })
      return false
    } finally {
      clearTimeout(timer)
      if (current()) {
        // Invalidates late work after a timeout, even before the next selection.
        ++this.generation
        this.cancelPending = undefined
      }
    }
  }

  destroy(): void {
    if (this.disposed) return
    this.disposed = true
    ++this.generation
    this.cancelPending?.()
    this.cancelPending = undefined
    this.stopErrors?.()
    if (this.layer) this.layers.remove(this.layer, true)
    this.layer = undefined
  }
}
