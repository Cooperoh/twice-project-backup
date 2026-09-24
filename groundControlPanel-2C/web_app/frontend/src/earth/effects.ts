import {
  BillboardCollection, Cartesian3, Color, EllipsoidGeometry, GeometryInstance,
  Material, MaterialAppearance, PolylineCollection, Primitive, SkyBox, type Scene,
  Matrix3, Matrix4, Quaternion,
} from 'cesium'
import cloudUrl from './assets/clouds.jpg?url'
import satelliteUrl from './assets/satellite.svg?url'
import type { EarthEffects } from './contracts'
import { DEMO_ORBITS, effectOpacity, orbitNormal, orbitPoint } from './orbits'

/** Small local cube maps, with sparse stars and no noisy photographic Milky Way. */
export function createQuietSky(): SkyBox {
  let seed = 7019
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296 }
  const face = () => {
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 1024
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = '#030711'
    ctx.fillRect(0, 0, 1024, 1024)
    const haze = ctx.createRadialGradient(512, 512, 0, 512, 512, 490)
    haze.addColorStop(0, '#080e1b')
    haze.addColorStop(1, '#030711')
    ctx.fillStyle = haze
    ctx.fillRect(0, 0, 1024, 1024)
    for (let i = 0; i < 180; i++) {
      const x = 5 + random() * 1014, y = 5 + random() * 1014
      const bright = random()
      const radius = bright > 0.985 ? 0.9 : 0.3 + random() * 0.4
      if (bright > 0.985) {
        const glow = ctx.createRadialGradient(x, y, 0, x, y, 3)
        glow.addColorStop(0, '#b7d8ff44'); glow.addColorStop(1, '#b7d8ff00')
        ctx.fillStyle = glow; ctx.fillRect(x - 3, y - 3, 6, 6)
      }
      ctx.fillStyle = `rgba(207,225,255,${0.2 + bright * 0.65})`
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill()
    }
    return canvas
  }
  return new SkyBox({ sources: {
    positiveX: face(), negativeX: face(), positiveY: face(), negativeY: face(),
    positiveZ: face(), negativeZ: face(),
  } })
}

/** Owns only decorative primitives; never enters entities, telemetry, or follow targets. */
export class EarthSceneEffects {
  private readonly orbits: PolylineCollection
  private readonly tails: PolylineCollection[] = []
  private readonly axes: Cartesian3[] = []
  private readonly rotation = new Matrix3()
  private readonly quaternion = new Quaternion()
  private lastFade = -1
  private readonly satellites: BillboardCollection
  private readonly clouds: Primitive
  private readonly cloudMaterial: Material
  private readonly stop: () => void
  private settings: EarthEffects = { clouds: true, satellites: true, animate: true }
  private elapsed = 0
  private previous = performance.now()
  private readonly reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')

  constructor(private readonly scene: Scene, private readonly host: HTMLElement) {
    this.orbits = scene.primitives.add(new PolylineCollection())
    this.satellites = scene.primitives.add(new BillboardCollection({ scene }))
    for (const orbit of DEMO_ORBITS) {
      const positions = Array.from({ length: 193 }, (_, i) => this.position(orbit, i / 192 * Math.PI * 2))
      this.orbits.add({ positions, width: 1,
        material: Material.fromType('Color', { color: Color.fromCssColorString(orbit.color).withAlpha(0.19) }) })
      const tail = scene.primitives.add(new PolylineCollection()) as PolylineCollection
      this.tails.push(tail)
      const axis = orbitNormal(orbit)
      this.axes.push(new Cartesian3(axis.x, axis.y, axis.z))
      tail.add({ positions: this.trail(orbit, orbit.phase), width: 4,
        material: Material.fromType('PolylineGlow', {
          color: Color.fromCssColorString(orbit.color).withAlpha(0.8), glowPower: 0.22, taperPower: 0.8,
        }) })
      this.satellites.add({ position: this.position(orbit, orbit.phase), image: satelliteUrl,
        width: 34, height: 22, color: Color.WHITE })
    }
    this.cloudMaterial = new Material({ fabric: {
      type: 'EarthDecorativeClouds',
      uniforms: { image: cloudUrl, offset: 0, opacity: 0.48 },
      source: `czm_material czm_getMaterial(czm_materialInput materialInput) {
        czm_material material = czm_getDefaultMaterial(materialInput);
        float cloud = texture(image, vec2(fract(materialInput.st.s + offset), materialInput.st.t)).r;
        material.diffuse = vec3(0.94, 0.97, 1.0);
        material.alpha = smoothstep(0.22, 0.95, cloud) * opacity;
        return material;
      }`,
    }, translucent: true })
    const radii = scene.globe.ellipsoid.radii
    this.clouds = scene.primitives.add(new Primitive({
      geometryInstances: new GeometryInstance({ geometry: new EllipsoidGeometry({
        radii: new Cartesian3(radii.x + 35_000, radii.y + 35_000, radii.z + 35_000),
        stackPartitions: 64, slicePartitions: 128,
        vertexFormat: MaterialAppearance.MaterialSupport.TEXTURED.vertexFormat,
      }) }),
      appearance: new MaterialAppearance({ material: this.cloudMaterial, flat: false, closed: true, translucent: true }),
      asynchronous: false, allowPicking: false,
    }))
    this.stop = scene.preUpdate.addEventListener(() => this.update())
  }

  private position(orbit: typeof DEMO_ORBITS[number], angle: number): Cartesian3 {
    const p = orbitPoint(orbit, angle)
    return new Cartesian3(p.x, p.y, p.z)
  }

  private trail(orbit: typeof DEMO_ORBITS[number], angle: number): Cartesian3[] {
    return Array.from({ length: 25 }, (_, i) => this.position(orbit, angle - (24 - i) / 24 * 0.4))
  }

  private update(): void {
    const now = performance.now()
    const delta = Math.min((now - this.previous) / 1000, 0.1)
    this.previous = now
    const fade = effectOpacity(this.scene.camera.positionCartographic.height)
    const visible = !document.hidden && this.host.isConnected && this.host.clientWidth > 0 && this.host.clientHeight > 0
    this.clouds.show = this.settings.clouds && fade > 0
    this.orbits.show = this.satellites.show = this.settings.satellites && fade > 0
    for (const tail of this.tails) tail.show = this.orbits.show
    this.cloudMaterial.uniforms.opacity = 0.48 * fade
    if (fade !== this.lastFade) {
      this.lastFade = fade
      for (let i = 0; i < DEMO_ORBITS.length; i++) {
        this.orbits.get(i).material.uniforms.color.alpha = 0.19 * fade
        this.tails[i]!.get(0).material.uniforms.color.alpha = 0.8 * fade
        this.satellites.get(i).color = Color.WHITE.withAlpha(fade)
      }
    }
    // Camera gestures do not pause the orbital clock or decorative animation.
    if (!visible || !fade || !this.settings.animate || this.reducedMotion.matches
      || (!this.settings.clouds && !this.settings.satellites)) return
    this.elapsed += delta
    if (this.settings.clouds) this.cloudMaterial.uniforms.offset = (this.elapsed / 3600) % 1
    if (this.settings.satellites) {
      for (let i = 0; i < DEMO_ORBITS.length; i++) {
        const orbit = DEMO_ORBITS[i]!
        const angle = orbit.phase + this.elapsed / orbit.period * Math.PI * 2
        this.satellites.get(i).position = this.position(orbit, angle)
        // Rotate a static arc instead of recreating positions and uploading its vertices.
        Quaternion.fromAxisAngle(this.axes[i]!, angle - orbit.phase, this.quaternion)
        Matrix3.fromQuaternion(this.quaternion, this.rotation)
        Matrix4.fromRotationTranslation(this.rotation, Cartesian3.ZERO, this.tails[i]!.modelMatrix)
      }
    }
    this.scene.requestRender()
  }

  configure(settings: EarthEffects): void {
    this.settings = { ...settings }
    this.scene.requestRender()
  }

  destroy(): void {
    this.stop()
    for (const primitive of [this.orbits, ...this.tails, this.satellites, this.clouds]) this.scene.primitives.remove(primitive)
  }
}
