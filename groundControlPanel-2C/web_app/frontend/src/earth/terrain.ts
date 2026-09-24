import { CesiumTerrainProvider, EllipsoidTerrainProvider, IonResource, type TerrainProvider } from 'cesium'
import type { EarthTerrainStatus } from './contracts'

/** Owns terrain requests/listeners for one viewer; stale completions cannot revive it. */
export class EarthTerrain {
  private generation = 0
  private disposed = false
  private enabled = false
  private timer?: ReturnType<typeof setTimeout>
  private stopErrors?: () => void
  private cached?: CesiumTerrainProvider
  private readonly flat = new EllipsoidTerrainProvider()

  constructor(
    private readonly readToken: () => Promise<string | null>,
    private readonly apply: (provider: TerrainProvider) => void,
    private readonly status: (status: EarthTerrainStatus) => void,
  ) {}

  setEnabled(enabled: boolean): void {
    if (this.disposed) return
    this.enabled = enabled
    const generation = ++this.generation
    this.clearPending()
    this.apply(this.flat)
    if (!enabled) { this.status('off'); return }
    this.status('loading')
    const current = () => !this.disposed && this.enabled && generation === this.generation
    const fail = () => {
      if (!current()) return
      ++this.generation
      this.clearPending()
      this.cached = undefined
      this.apply(this.flat)
      this.status('error')
    }
    const ready = (provider: CesiumTerrainProvider) => {
      if (!current()) return
      if (this.timer) clearTimeout(this.timer)
      this.timer = undefined
      this.cached = provider
      this.stopErrors = provider.errorEvent.addEventListener(fail)
      this.apply(provider)
      this.status('ready')
    }
    if (this.cached) { ready(this.cached); return }
    this.timer = setTimeout(fail, 20_000)
    // Per-provider token: do not modify Cesium's global default token.
    void this.readToken().then(async (token) => {
      if (!current()) return
      if (!token) {
        this.clearPending()
        this.status('unconfigured')
        return
      }
      const resource = await IonResource.fromAssetId(1, { accessToken: token })
      if (!current()) return
      const provider = await CesiumTerrainProvider.fromUrl(resource, {
        requestVertexNormals: true, requestWaterMask: false,
      })
      ready(provider)
    }).catch(fail)
  }

  reload(): void {
    this.cached = undefined
    this.setEnabled(this.enabled)
  }

  private clearPending(): void {
    if (this.timer) clearTimeout(this.timer)
    this.timer = undefined
    this.stopErrors?.()
    this.stopErrors = undefined
  }

  destroy(): void {
    this.disposed = true
    ++this.generation
    this.clearPending()
    this.cached = undefined
  }
}
