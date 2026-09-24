import {
  BoundingSphere, Cartesian2, Cartesian3, Cartographic, CloudCollection, Color, EllipsoidGeometry,
  GeometryInstance, Material, MaterialAppearance, Math as CesiumMath, Primitive,
  type CumulusCloud, type Scene,
} from 'cesium'
import type { EarthEffects, EarthQuality } from './contracts'
import { daylightCloudCells, daylightOpacity } from './daylightLayout'

const cirrusSource = `
float hash21(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float cloudNoise(vec2 p) {
  vec2 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
  return mix(mix(hash21(i), hash21(i+vec2(1,0)), f.x),
    mix(hash21(i+vec2(0,1)), hash21(i+vec2(1,1)), f.x), f.y);
}
czm_material czm_getMaterial(czm_materialInput materialInput) {
  czm_material m = czm_getDefaultMaterial(materialInput);
  vec2 uv = materialInput.st;
  vec2 p = vec2(uv.s * 8000.0, uv.t * 4000.0);
  float warp = cloudNoise(p * 0.12);
  vec2 streak = p * vec2(0.55, 1.4)
    + vec2(warp, cloudNoise(p * 0.23 + vec2(15.0, 31.0))) * 3.5;
  float fine = cloudNoise(streak) * 0.6 + cloudNoise(streak * 2.0) * 0.27
    + cloudNoise(streak * 4.0) * 0.13;
  float coverage = smoothstep(0.4, 0.7, cloudNoise(p * 0.36));
  float polarFade = smoothstep(0.0, 0.045, uv.t) * smoothstep(0.0, 0.045, 1.0-uv.t);
  m.diffuse = vec3(0.98, 0.99, 1.0);
  float seamFade = smoothstep(0.0, 0.0005, uv.s) * smoothstep(0.0, 0.0005, 1.0-uv.s);
  m.alpha = smoothstep(0.32, 0.78, fine) * coverage * opacity * polarFade * seamFade;
  return m;
}`

type CloudFrame = { commandList: Array<{ owner?: unknown; boundingVolume?: BoundingSphere }> }
// Cesium 1.145 CloudCollection omits command bounds. Its sorted-alpha fallback
// dereferences these when floating-point OIT is unavailable. Keep the workaround
// here, using the custom-primitive update boundary, without patching the engine.
class BoundedCloudCollection extends CloudCollection {
  private bounds = new BoundingSphere()
  updateBounds(): void {
    const points = Array.from({ length: this.length }, (_, i) => this.get(i).position)
    BoundingSphere.fromPoints(points, this.bounds)
    this.bounds.radius += 6500
  }
  update(frame: CloudFrame): void {
    const start = frame.commandList.length
    const base = CloudCollection.prototype as unknown as { update(frame: CloudFrame): void }
    base.update.call(this, frame)
    for (let i = start; i < frame.commandList.length; i++) {
      const command = frame.commandList[i]!
      if (command.owner === this && !command.boundingVolume) command.boundingVolume = this.bounds
    }
  }
}

/** Static, decorative daytime weather. Owns no telemetry, clocks, or camera controls. */
export class EarthDaylight {
  private readonly cumulus: BoundedCloudCollection
  private readonly cirrus: Primitive
  private readonly cirrusMaterial: Material
  private readonly stop: () => void
  private settings: EarthEffects = { clouds: true, satellites: true, animate: true }
  private quality: EarthQuality = 'balanced'
  private cells = new Map<string, { cloud: CumulusCloud; location: Cartographic; altitude: number }>()
  private gridKey = ''
  private cellKeys = ''
  private nextUpdate = 0

  constructor(private readonly scene: Scene, private readonly host: HTMLElement) {
    this.cumulus = scene.primitives.add(new BoundedCloudCollection({ noiseDetail: 16 }))
    this.cirrusMaterial = new Material({ fabric: {
      type: 'EarthDaylightCirrus', uniforms: { opacity: 0.48 }, source: cirrusSource,
    }, translucent: true })
    const radii = scene.globe.ellipsoid.radii
    this.cirrus = scene.primitives.add(new Primitive({
      geometryInstances: new GeometryInstance({ geometry: new EllipsoidGeometry({
        radii: new Cartesian3(radii.x + 11000, radii.y + 11000, radii.z + 11000),
        stackPartitions: 128, slicePartitions: 256,
        vertexFormat: MaterialAppearance.MaterialSupport.TEXTURED.vertexFormat,
      }) }),
      appearance: new MaterialAppearance({ material: this.cirrusMaterial,
        flat: true, faceForward: true, closed: false, translucent: true }),
      asynchronous: false, allowPicking: false,
    }))
    // Tilt/rotate never gates weather. Throttling only bounds terrain queries and grid maintenance.
    this.stop = scene.preUpdate.addEventListener(() => this.update())
    this.configure(this.settings)
  }

  configure(settings: EarthEffects): void {
    this.settings = { ...settings }
    const { globe, skyAtmosphere, fog } = this.scene
    const atmosphere = settings.atmosphere !== false
    globe.showGroundAtmosphere = atmosphere
    globe.atmosphereSaturationShift = -0.08
    globe.atmosphereBrightnessShift = 0.06
    if (skyAtmosphere) {
      skyAtmosphere.show = atmosphere
      skyAtmosphere.perFragmentAtmosphere = this.quality !== 'smooth'
      skyAtmosphere.saturationShift = -0.06
      skyAtmosphere.brightnessShift = 0.08
    }
    fog.enabled = settings.haze !== false
    fog.renderable = settings.haze !== false
    fog.density = 0.00065
    fog.visualDensityScalar = 0.35
    fog.minimumBrightness = 0.65
    fog.screenSpaceErrorFactor = 1.5
    this.nextUpdate = 0
    this.scene.requestRender()
  }

  setQuality(quality: EarthQuality): void {
    if (quality === this.quality) return
    this.quality = quality
    this.gridKey = ''
    this.configure(this.settings)
  }

  private update(): void {
    if (document.hidden || !this.host.isConnected || !this.host.clientWidth || !this.host.clientHeight) return
    const now = performance.now()
    if (now < this.nextUpdate) return
    this.nextUpdate = now + 160
    const camera = this.scene.camera.positionCartographic
    const fade = daylightOpacity(camera.height)
    let changed = false
    const showClouds = this.settings.cumulus !== false && fade > 0
    const showCirrus = this.settings.cirrus !== false && fade > 0
    if (this.cumulus.show !== showClouds) { this.cumulus.show = showClouds; changed = true }
    if (this.cirrus.show !== showCirrus) { this.cirrus.show = showCirrus; changed = true }
    if (this.cirrusMaterial.uniforms.opacity !== 0.48 * fade) {
      this.cirrusMaterial.uniforms.opacity = 0.48 * fade
      changed = true
    }
    if (showClouds) {
      const lon = CesiumMath.toDegrees(camera.longitude), lat = CesiumMath.toDegrees(camera.latitude)
      // Row and column bounds are keyed more finely than the cloud lattice.
      const key = `${Math.floor(lon / 0.025)}:${Math.floor(lat / 0.025)}:${this.quality}`
      if (key !== this.gridKey) {
        this.gridKey = key
        const cells = daylightCloudCells(lon, lat, this.quality)
        const keys = cells.map(cell => cell.key).join(',')
        if (keys !== this.cellKeys) {
          this.cellKeys = keys
          // Cesium 1.145's individual remove() compaction leaves stale cloud indices.
          // Rebuild only when the geographic cell set changes; retain the noise texture.
          const previous = this.cells
          this.cells = new Map()
          this.cumulus.removeAll()
          for (const cell of cells) {
            const location = Cartographic.fromDegrees(cell.lon, cell.lat)
            const old = previous.get(cell.key)
            const ground = this.scene.globe.getHeight(location) ?? (old ? old.location.height - old.altitude : 0)
            location.height = Math.max(0, ground) + cell.altitude
            const cloud = this.cumulus.add({
              position: Cartesian3.fromDegrees(cell.lon, cell.lat, location.height),
              scale: new Cartesian2(cell.width, cell.height),
              maximumSize: new Cartesian3(20, 12, 9), slice: cell.slice,
              brightness: 0.96, color: new Color(1, 1, 1, fade),
            })
            this.cells.set(cell.key, { cloud, location, altitude: cell.altitude })
          }
          changed = true
        }
      }
      for (const { cloud, location, altitude } of this.cells.values()) {
        // Refine height only from already-loaded terrain; no additional network sampling.
        const ground = this.scene.globe.getHeight(location)
        if (ground !== undefined) {
          location.height = Math.max(0, ground) + altitude
          const point = this.scene.globe.ellipsoid.cartographicToCartesian(location)
          if (Cartesian3.distanceSquared(point, cloud.position) > 10000) { cloud.position = point; changed = true }
        }
        const distance = Cartesian3.distance(this.scene.camera.positionWC, cloud.position)
        const alpha = fade * Math.max(0, Math.min(1, (55000 - distance) / 18000))
          * Math.max(0, Math.min(1, (distance - 700) / 1300))
        if (Math.abs(cloud.color.alpha - alpha) > 0.015) {
          cloud.color = new Color(1, 1, 1, alpha)
          changed = true
        }
      }
    }
    if (changed) { this.cumulus.updateBounds(); this.scene.requestRender() }
  }

  destroy(): void {
    this.stop()
    this.cells.clear()
    this.scene.primitives.remove(this.cumulus)
    this.scene.primitives.remove(this.cirrus)
  }
}
