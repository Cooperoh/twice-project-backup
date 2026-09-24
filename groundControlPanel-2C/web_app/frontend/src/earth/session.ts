import { watch, type WatchStopHandle } from 'vue'
import type { useGcsStore } from '../stores/gcs'
import type { EarthCamera, EarthDestination, EarthEffects, EarthPresentation, EarthQuality, EarthRenderer, EarthStats, EarthTerrainStatus } from './contracts'
import { loadEarthRenderer } from './loader'
import { setEarthStatus } from './status'
import { altitudeOverride } from './altitude'
import type { ImagerySelection, ImageryState } from './imageryConfig'

// The adapter owns all subscriptions; the renderer knows nothing about Pinia or APIs.
export class EarthSession {
  private generation = 0
  private renderer: EarthRenderer | null = null
  private stop: WatchStopHandle | null = null
  private savedCamera?: EarthCamera
  private active = false
  private tracksVisible = true
  private followId: number | null = null
  private quality: EarthQuality = 'balanced'
  private terrainEnabled = true
  private imagery: ImagerySelection = { id: 'esri' }
  private altitude: number | null = null
  private effects: EarthEffects = { clouds: true, satellites: true, animate: true }
  private presentation: EarthPresentation = { tour: false, sunlight: false, sunLongitude: 45 }

  constructor(private readonly store: ReturnType<typeof useGcsStore>, private readonly callbacks: {
    warning(message: string): void
    error(message: string): void
    stats(stats: EarthStats): void
    tour?(active: boolean): void
    terrain?(status: EarthTerrainStatus): void
    imagery?(state: ImageryState): void
  }) {}

  async start(host: HTMLElement): Promise<void> {
    if (this.active) return
    this.active = true
    const generation = ++this.generation
    setEarthStatus('loading')
    this.callbacks.error('')
    this.callbacks.warning('')
    try {
      const create = await loadEarthRenderer()
      if (!this.active || generation !== this.generation) return
      this.renderer = create(host, {
        camera: this.savedCamera,
        imagery: this.imagery,
        onImageryState: (state) => {
          if (generation === this.generation) this.callbacks.imagery?.(state)
        },
        onWarning: (message) => {
          if (generation === this.generation) this.callbacks.warning(message)
        },
        onStats: (stats) => {
          if (generation === this.generation) this.callbacks.stats(stats)
        },
        onTerrainStatus: (status) => {
          if (generation === this.generation) this.callbacks.terrain?.(status)
        },
        onTourChange: (active) => {
          if (generation !== this.generation) return
          this.presentation.tour = active
          this.callbacks.tour?.(active)
        },
      })
      this.renderer.setTracksVisible(this.tracksVisible)
      this.renderer.setAltitude(this.altitude)
      this.renderer.setQuality(this.quality)
      this.renderer.setTerrainEnabled(this.terrainEnabled)
      this.renderer.setEffects(this.effects)
      this.renderer.setPresentation(this.presentation)
      // Subscribe only after a successful start; retain this across KeepAlive deactivation.
      this.stop = watch(
        () => [this.store.drones, this.store.trackRevision, this.store.trackSession,
          this.store.trajectories, this.store.stale] as const,
        () => this.renderer?.update({
          drones: this.store.sortedDrones,
          tracks: this.store.trackSession,
          trajectories: this.store.trajectories,
          stale: this.store.stale,
        }),
        { immediate: true, flush: 'sync' },
      )
      this.renderer.follow(this.followId)
      setEarthStatus('running')
    } catch (error) {
      if (generation !== this.generation) return
      this.close()
      this.callbacks.error(error instanceof Error ? error.message : String(error))
      setEarthStatus('error')
    }
  }

  close(): void {
    this.presentation.tour = false
    this.callbacks.tour?.(false)
    ++this.generation
    this.active = false
    this.stop?.()
    this.stop = null
    const renderer = this.renderer
    this.renderer = null
    if (renderer) {
      try {
        this.savedCamera = renderer.camera()
      } catch {
        // A lost WebGL context must not prevent explicit shutdown.
        this.savedCamera = undefined
      } finally {
        renderer.destroy()
      }
    }
    this.callbacks.stats({ drones: 0, points: 0, catchingUp: false })
    this.callbacks.terrain?.('idle')
    this.callbacks.imagery?.({ status: 'idle', message: '' })
    setEarthStatus('idle')
  }

  setTracksVisible(visible: boolean): void {
    this.tracksVisible = visible
    this.renderer?.setTracksVisible(visible)
  }
  setAltitude(value: unknown): void {
    this.altitude = altitudeOverride(value)
    this.renderer?.setAltitude(this.altitude)
  }
  follow(id: number | null): void { this.followId = id; this.renderer?.follow(id) }
  locateAll(): void { this.followId = null; this.renderer?.locateAll() }
  skyView(): void { this.renderer?.skyView() }
  overview(): void { this.followId = null; this.renderer?.overview() }
  setQuality(quality: EarthQuality): void { this.quality = quality; this.renderer?.setQuality(quality) }
  setTerrainEnabled(enabled: boolean): void { this.terrainEnabled = enabled; this.renderer?.setTerrainEnabled(enabled) }
  reloadTerrain(): void { this.renderer?.reloadTerrain() }
  async setImagery(selection: ImagerySelection): Promise<boolean> {
    const renderer = this.renderer
    const generation = this.generation
    if (renderer && !await renderer.setImagery(selection)) return false
    if (generation !== this.generation || renderer !== this.renderer) return false
    this.imagery = { ...selection }
    return true
  }
  setEffects(effects: EarthEffects): void { this.effects = { ...effects }; this.renderer?.setEffects(this.effects) }
  setPresentation(value: EarthPresentation): void {
    this.presentation = { ...value }
    if (value.tour) this.followId = null
    this.renderer?.setPresentation(this.presentation)
  }
  visit(destination: EarthDestination): void { this.followId = null; this.renderer?.visit(destination) }
  resize(): void { this.renderer?.resize() }
}
