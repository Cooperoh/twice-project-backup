import {
  ArcType, Cartesian3, Color, GeometryInstance, Material, Math as CesiumMath,
  PolylineGeometry, PolylineMaterialAppearance, Primitive, type Scene,
} from 'cesium'
import borders from './assets/boundaries.json'
import { boundaryOpacity } from './cartography'

/** Static map geometry, separate from telemetry and flight-path collections. */
export class EarthBoundaries {
  private readonly groups: Array<{ primitive: Primitive; material: Material; region: boolean; alpha: number }> = []
  private readonly stop: () => void
  private enabled = true

  constructor(private readonly scene: Scene) {
    for (const [kind, lines] of Object.entries(borders)) {
      const region = kind === 'region'
      const disputed = kind === 'disputed'
      const color = Color.fromCssColorString(region ? '#d9e2e1' : '#e3cc9b')
      const material = Material.fromType(disputed ? 'PolylineDash' : 'Color', disputed
        ? { color, dashLength: 12 } : { color })
      const primitive = scene.primitives.add(new Primitive({
        geometryInstances: lines.flatMap(line => {
          // Bake once on startup; no worker pool or live path-buffer rebuilds.
          const geometry = PolylineGeometry.createGeometry(new PolylineGeometry({
            positions: line.map(p => Cartesian3.fromDegrees(p[0]!, p[1]!, 900)),
            width: region ? 1 : 1.25,
            arcType: ArcType.GEODESIC,
            granularity: CesiumMath.RADIANS_PER_DEGREE / 4,
            vertexFormat: PolylineMaterialAppearance.VERTEX_FORMAT,
          }))
          return geometry ? [new GeometryInstance({ geometry })] : []
        }),
        appearance: new PolylineMaterialAppearance({ material, translucent: true }),
        asynchronous: false, allowPicking: false,
      })) as Primitive
      this.groups.push({ primitive, material, region, alpha: region ? 0.4 : disputed ? 0.45 : 0.66 })
    }
    this.stop = scene.preRender.addEventListener(() => this.update())
    this.update()
  }

  private update(): void {
    const opacity = boundaryOpacity(this.scene.camera.positionCartographic.height)
    for (const group of this.groups) {
      const fade = opacity[group.region ? 'region' : 'country']
      group.primitive.show = this.enabled && fade > 0
      group.material.uniforms.color.alpha = group.alpha * fade
    }
  }

  setVisible(enabled: boolean): void { this.enabled = enabled; this.update(); this.scene.requestRender() }

  destroy(): void {
    this.stop()
    for (const group of this.groups) this.scene.primitives.remove(group.primitive)
  }
}
