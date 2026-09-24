import {
  Cartesian2, Cartesian3, Color, HorizontalOrigin, LabelCollection,
  LabelStyle, Matrix4, PointPrimitiveCollection, SceneTransforms, type Scene,
} from 'cesium'
import places from './assets/places.json'
import { labelProfiles, overlaps, placeVisible, type LabelBox } from './cartography'
import type { EarthLabelDensity } from './contracts'

/** Local geographic labels, independent of aircraft entities and online services. */
export class EarthPlaceLabels {
  private readonly labels: LabelCollection
  private readonly dots: PointPrimitiveCollection
  private readonly candidates
  private readonly stop: () => void
  private readonly view = new Matrix4()
  private readonly screen = new Cartesian2()
  private readonly measure = document.createElement('canvas').getContext('2d')!
  private readonly widths = new Map<string, number>()
  private enabled = true
  private density: EarthLabelDensity = 'detailed'
  private dirty = true
  private last = 0
  private width = 0
  private height = 0
  private pending: ReturnType<typeof setTimeout> | undefined

  constructor(private readonly scene: Scene, private readonly host: HTMLElement) {
    this.labels = scene.primitives.add(new LabelCollection({ scene }))
    this.dots = scene.primitives.add(new PointPrimitiveCollection())
    this.candidates = [...places].sort((a, b) =>
      (a.kind === 'country' ? 0 : 10) + a.rank - (b.kind === 'country' ? 0 : 10) - b.rank,
    ).map(place => {
      const position = Cartesian3.fromDegrees(place.lon, place.lat, 800)
      const normal = scene.globe.ellipsoid.geodeticSurfaceNormal(position)
      return { ...place, position, normal, horizon: Cartesian3.dot(normal, position) }
    })
    // Bounded screen budget; positions keep tracking the camera on the GPU between layouts.
    for (let i = 0; i < labelProfiles.detailed.limit; i++) {
      this.labels.add({ show: false, text: '', position: Cartesian3.ZERO, horizontalOrigin: HorizontalOrigin.CENTER,
        style: LabelStyle.FILL_AND_OUTLINE, fillColor: Color.fromCssColorString('#f0f2ed'),
        outlineColor: Color.fromCssColorString('#182630'), outlineWidth: 2,
        disableDepthTestDistance: Number.POSITIVE_INFINITY })
      this.dots.add({ show: false, pixelSize: 4, color: Color.fromCssColorString('#eac78c'),
        outlineColor: Color.fromCssColorString('#223243'), outlineWidth: 1,
        disableDepthTestDistance: Number.POSITIVE_INFINITY })
    }
    this.stop = scene.preRender.addEventListener(() => this.update())
    // Re-measure if a deferred web font changes the font fallback after startup.
    void document.fonts?.ready.then(() => { this.widths.clear(); this.dirty = true })
  }

  configure(enabled: boolean, density: EarthLabelDensity = 'detailed'): void {
    this.enabled = enabled
    this.density = density
    this.labels.show = this.dots.show = enabled
    this.dirty = true
    this.scene.requestRender()
  }

  private update(): void {
    if (!this.enabled || document.hidden || !this.host.isConnected || !this.host.clientWidth) return
    const camera = this.scene.camera
    const now = performance.now()
    const changed = !Matrix4.equals(this.view, camera.viewMatrix)
      || this.width !== this.host.clientWidth || this.height !== this.host.clientHeight
    if (!this.dirty && !changed) return
    if (!this.dirty && now - this.last < 120) {
      this.pending ??= setTimeout(() => {
        this.pending = undefined
        this.dirty = true
        this.scene.requestRender()
      }, 120 - (now - this.last))
      return
    }
    this.dirty = false
    this.last = now
    Matrix4.clone(camera.viewMatrix, this.view)
    this.width = this.host.clientWidth
    this.height = this.host.clientHeight
    const altitude = camera.positionCartographic.height
    const profile = labelProfiles[this.density]
    const occupied: LabelBox[] = []
    for (const place of this.candidates) {
      if (occupied.length >= profile.limit) break
      // Surface-normal horizon test: labels on the rear hemisphere must not shine through.
      if (!placeVisible(place, altitude, this.density) || Cartesian3.dot(place.normal, camera.positionWC) <= place.horizon) continue
      const screen = SceneTransforms.worldToWindowCoordinates(this.scene, place.position, this.screen)
      if (!screen) continue
      const country = place.kind === 'country'
      const font = `${country ? '600 16' : '13'}px "Microsoft YaHei", sans-serif`
      const key = `${font}:${place.name}`
      let width = this.widths.get(key)
      if (width === undefined) {
        this.measure.font = font
        width = this.measure.measureText(place.name).width
        this.widths.set(key, width)
      }
      const box = { x: screen.x, y: screen.y - (country ? 0 : 12), width: width + 6, height: country ? 22 : 19 }
      if (box.x - box.width / 2 < 12 || box.x + box.width / 2 > this.width - 12
        || box.y < 18 || box.y > this.height - 38 || occupied.some(other => overlaps(box, other, profile.gap))) continue
      const i = occupied.length
      const label = this.labels.get(i)
      label.text = place.name
      label.font = font
      label.position = place.position
      label.pixelOffset = new Cartesian2(0, country ? 0 : -12)
      label.show = true
      const dot = this.dots.get(i)
      dot.position = place.position
      dot.show = !country
      occupied.push(box)
    }
    for (let i = occupied.length; i < this.labels.length; i++) {
      this.labels.get(i).show = false
      this.dots.get(i).show = false
    }
  }

  destroy(): void {
    this.stop()
    if (this.pending !== undefined) clearTimeout(this.pending)
    this.scene.primitives.remove(this.labels)
    this.scene.primitives.remove(this.dots)
  }
}
