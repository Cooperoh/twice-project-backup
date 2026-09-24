import {
  BoundingSphere, Cartesian2, Cartesian3,
  Color, ConstantPositionProperty, ConstantProperty, Credit, DirectionalLight, EllipsoidTerrainProvider,
  Entity, HeadingPitchRange, LabelStyle, Material, Math as CesiumMath, Cartographic, Matrix4,
  PolylineCollection, SingleTileImageryProvider, TileMapServiceImageryProvider, Viewer, buildModuleUrl, type PerspectiveFrustum, type ImageryLayer,
} from 'cesium'
import 'cesium/Build/Cesium/Widgets/widgets.css'
import planeModelUrl from './assets/fixed-wing.glb?url'
import type { EarthCamera, EarthDestination, EarthInputs, EarthOptions, EarthPresentation, EarthQuality, EarthRenderer } from './contracts'
import { TrackMirror } from './trackMirror'
import type { GeoPoint } from '../types'
import { displayPosition as position, displayPolyline, modelOrientation } from './geography'
import { releaseEllipsoidContextCache } from './cesiumCleanup'
import { EarthTrackLines } from './trackLines'
import { earthRenderQuality } from './quality'
import { createQuietSky, EarthSceneEffects } from './effects'
import reliefUrl from './assets/blue-marble-relief.jpg?url'
import { EarthPlaceLabels } from './placeLabels'
import { EarthBoundaries } from './boundaries'
import { EarthTerrain } from './terrain'
import { cesiumCredentials } from './credentials'
import { altitudeOverride } from './altitude'
import { EarthDaylight } from './daylight'
import { EarthImagery } from './imagery'

const palette = ['#56e0bf', '#ffca6b', '#8ab8ff', '#f795c7', '#a9e885', '#bcabff']
const validPoint = (point: { lat?: unknown; lon?: unknown }): point is GeoPoint =>
  typeof point.lat === 'number' && Number.isFinite(point.lat) && Math.abs(point.lat) <= 90
  && typeof point.lon === 'number' && Number.isFinite(point.lon) && Math.abs(point.lon) <= 180
  && !(point.lat === 0 && point.lon === 0)
const colorFor = (id: number): Color => Color.fromCssColorString(palette[(id - 1) % palette.length] ?? palette[0]!)

export function createEarthRenderer(host: HTMLElement, options: EarthOptions): EarthRenderer {
  const viewer = new Viewer(host, {
    animation: false, timeline: false, baseLayerPicker: false, geocoder: false,
    homeButton: false, sceneModePicker: false, navigationHelpButton: false,
    fullscreenButton: false, vrButton: false, infoBox: false, selectionIndicator: false,
    baseLayer: false, terrainProvider: new EllipsoidTerrainProvider(),
    skyBox: createQuietSky(),
    shadows: false,
    requestRenderMode: true, maximumRenderTimeChange: Infinity,
    // No targetFrameRate: follow the browser's requestAnimationFrame cadence (including 120 Hz).
    shouldAnimate: false, msaaSamples: 1, scene3DOnly: true,
    orderIndependentTranslucency: true,
    contextOptions: { webgl: { powerPreference: 'high-performance' } },
  })
  // Keep recently viewed terrain meshes/textures resident when looking away.
  // Cesium's default 100-tile target evicts even a single mountain view on return.
  // This is a soft tile-count target, not a byte limit; visible tiles can exceed it.
  viewer.scene.globe.tileCacheSize = 1000
  // Warm adjacent tiles outside the frustum at Cesium's lower request priority.
  viewer.scene.globe.preloadSiblings = true
  let destroyed = false
  const terrain = new EarthTerrain(cesiumCredentials.read, (provider) => {
    if (destroyed) return
    viewer.terrainProvider = provider
    requestRender()
  }, (status) => {
    host.dataset.earthTerrain = status
    options.onTerrainStatus?.(status)
  })
  let pending: ReturnType<typeof setTimeout> | null = null
  let input: EarthInputs | null = null
  let tracksVisible = true
  let altitude: number | null = null
  let followed: number | null = null
  let located = Boolean(options.camera)
  let trackSource: EarthInputs['tracks'] | null = null
  let trackEpoch = -1
  let trajectorySource: EarthInputs['trajectories'] | null = null
  let droneSource: EarthInputs['drones'] | null = null
  let lastStale = false
  let quality: EarthQuality = 'balanced'
  let effects: EarthSceneEffects | undefined
  let daylight: EarthDaylight | undefined
  let labels: EarthPlaceLabels | undefined
  let boundaries: EarthBoundaries | undefined
  let relief: ImageryLayer | undefined
  let satelliteReady = false
  const imagery = new EarthImagery(viewer.imageryLayers, (ready, state) => {
    satelliteReady = ready
    if (relief) relief.alpha = ready ? 0 : 1
    host.dataset.earthImagery = state.status
    options.onImageryState?.(state)
    requestRender()
  })
  let presentation: EarthPresentation = { tour: false, sunlight: false, sunLongitude: 45 }
  let previousFrame = performance.now()
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
  const sunlightDirection = new Cartesian3()
  const lightingFade = [viewer.scene.globe.lightingFadeOutDistance, viewer.scene.globe.lightingFadeInDistance]
  const planes = new Map<number, Entity>()
  const histories = new Map<number, { mirror: TrackMirror; lines: EarthTrackLines }>()
  const planned = viewer.scene.primitives.add(new PolylineCollection()) as PolylineCollection
  const unsubscribe: Array<() => void> = []
  let resizeObserver: ResizeObserver | undefined

  function requestRender(): void { if (!destroyed) viewer.scene.requestRender() }
  function schedule(delay = 50): void {
    if (!destroyed && pending === null) pending = setTimeout(flush, delay)
  }
  function clearHistory(): void {
    for (const history of histories.values()) {
      history.lines.destroy()
    }
    histories.clear()
  }
  function locateAll(): void {
    stopTour()
    followed = null
    viewer.trackedEntity = undefined
    const points = input?.drones.flatMap((drone) => validPoint(drone) ? [position(drone, altitude)] : []) ?? []
    if (!points.length) return
    const sphere = BoundingSphere.fromPoints(points)
    viewer.camera.flyToBoundingSphere(sphere, {
      duration: 0.6,
      offset: new HeadingPitchRange(0, -CesiumMath.PI_OVER_FOUR, Math.max(12000, sphere.radius * 3)),
    })
    requestRender()
  }
  function overview(): void {
    visit('asia')
  }
  function skyView(): void {
    stopTour()
    located = true
    viewer.camera.cancelFlight()
    const entity = followed === null ? undefined : planes.get(followed)
    if (entity) {
      const target = entity.position?.getValue(viewer.clock.currentTime)
      if (target) {
        viewer.camera.lookAt(target, new HeadingPitchRange(viewer.camera.heading, -0.16, 2800))
        requestRender()
        return
      }
    }
    const drone = input?.drones.find(validPoint)
    const current = viewer.camera.positionCartographic
    const target = drone && validPoint(drone) ? position(drone, altitude)
      : Cartesian3.fromRadians(current.longitude, current.latitude,
        Math.max(0, viewer.scene.globe.getHeight(new Cartographic(current.longitude, current.latitude)) ?? 0) + 2400)
    // Set a local orbit once, then restore free camera controls without changing the view.
    viewer.camera.lookAt(target, new HeadingPitchRange(viewer.camera.heading, -0.14, 3500))
    viewer.camera.lookAtTransform(Matrix4.IDENTITY)
    requestRender()
  }
  function visit(destination: EarthDestination): void {
    stopTour()
    followed = null
    located = true
    viewer.trackedEntity = undefined
    viewer.camera.flyTo({
      destination: destination === 'himalaya'
        ? Cartesian3.fromDegrees(86.93, 27.72, 16000) : overviewPosition(destination),
      orientation: { heading: 0, pitch: destination === 'himalaya' ? -0.32 : -CesiumMath.PI_OVER_TWO, roll: 0 },
      duration: reducedMotion.matches ? 0 : 1.6,
    })
    requestRender()
  }
  function overviewPosition(destination: Exclude<EarthDestination, 'himalaya'> = 'asia'): Cartesian3 {
    const frustum = viewer.camera.frustum as PerspectiveFrustum
    const halfAngle = Math.atan(Math.tan((frustum.fovy ?? CesiumMath.PI_OVER_THREE) / 2)
      * Math.min(1, frustum.aspectRatio ?? 1))
    const radius = viewer.scene.globe.ellipsoid.maximumRadius
    const coordinates = { asia: [110, 25], pacific: [-155, 12], polar: [30, 82] } as const
    const [longitude, latitude] = coordinates[destination]
    return Cartesian3.fromDegrees(longitude, latitude, radius / Math.sin(halfAngle) * 1.16 - radius)
  }
  function stopTour(): void {
    if (!presentation.tour) return
    presentation.tour = false
    options.onTourChange?.(false)
  }
  function setPresentation(value: EarthPresentation): void {
    const wasTouring = presentation.tour
    presentation = { ...value }
    if (presentation.tour && !wasTouring) {
      followed = null
      located = true
      viewer.trackedEntity = undefined
      if (viewer.camera.positionCartographic.height < 2_000_000) {
        viewer.camera.flyTo({ destination: overviewPosition(), duration: reducedMotion.matches ? 0 : 1.4 })
      }
    }
    const globe = viewer.scene.globe
    globe.dynamicAtmosphereLighting = value.sunlight
    globe.lightingFadeOutDistance = value.sunlight ? 0 : lightingFade[0]!
    globe.lightingFadeInDistance = value.sunlight ? 1 : lightingFade[1]!
    Cartesian3.fromDegrees(value.sunLongitude, 15, 0, globe.ellipsoid, sunlightDirection)
    Cartesian3.normalize(sunlightDirection, sunlightDirection)
    Cartesian3.negate(sunlightDirection, sunlightDirection)
    requestRender()
  }
  function applyFollow(): void {
    const entity = followed === null ? undefined : planes.get(followed)
    if (viewer.trackedEntity !== entity) viewer.trackedEntity = entity
  }
  function flush(): void {
    pending = null
    if (destroyed || !input) return
    let catchingUp = false
    viewer.entities.suspendEvents()
    try {
      if (droneSource !== input.drones || lastStale !== input.stale) {
        droneSource = input.drones
        lastStale = input.stale
        const live = new Set<number>()
        for (const drone of input.drones) {
          if (!validPoint(drone)) continue
          live.add(drone.id)
          const point = position(drone, altitude)
          const heading = typeof drone.heading === 'number' && Number.isFinite(drone.heading)
            ? drone.heading : 0
          const orientation = modelOrientation(point, heading)
          const stale = input.stale || drone.telemetry_status === 'disconnected'
          let entity = planes.get(drone.id)
          if (!entity) {
            entity = viewer.entities.add({
              id: `earth-plane-${drone.id}`,
              position: point,
              orientation,
              viewFrom: new Cartesian3(0, -2800, 450),
              model: { uri: planeModelUrl, scale: 10, minimumPixelSize: 52 },
              label: {
                text: '', font: '13px sans-serif', pixelOffset: new Cartesian2(0, 42),
                style: LabelStyle.FILL_AND_OUTLINE, fillColor: Color.WHITE,
                outlineColor: Color.BLACK, outlineWidth: 3,
              },
            })
            planes.set(drone.id, entity)
          }
          entity.position = new ConstantPositionProperty(point)
          entity.orientation = new ConstantProperty(orientation)
          entity.model!.color = new ConstantProperty(stale ? Color.GRAY : colorFor(drone.id))
          entity.label!.text = new ConstantProperty(`${drone.tag?.trim() || `DRONE${drone.id}`}${stale ? ' · 过期' : ''}`)
        }
        for (const [id, entity] of planes) {
          if (!live.has(id)) { viewer.entities.remove(entity); planes.delete(id) }
        }
        if (!located && live.size) { located = true; if (followed === null) locateAll() }
        applyFollow()
      }

      if (trajectorySource !== input.trajectories) {
        trajectorySource = input.trajectories
        planned.removeAll()
        for (const [id, points] of Object.entries(input.trajectories)) {
          const positions = displayPolyline(points.filter(validPoint), altitude)
          if (positions.length < 2) continue
          planned.add({
            id: `earth-planned-${id}`,
            show: tracksVisible,
            positions, width: 2,
            material: Material.fromType('PolylineDash', { color: Color.fromCssColorString('#7fb9ff'), dashLength: 16 }),
          })
        }
      }

      if (trackSource !== input.tracks || trackEpoch !== input.tracks.epoch) {
        clearHistory()
        trackSource = input.tracks
        trackEpoch = input.tracks.epoch
      }
      let budget = 2048
      for (const [id, buffer] of input.tracks.tracks) {
        let history = histories.get(id)
        if (!history) {
          history = { mirror: new TrackMirror(), lines: new EarthTrackLines(viewer.scene, colorFor(id)) }
          history.lines.setVisible(tracksVisible)
          histories.set(id, history)
        }
        const delta = history.mirror.sync(buffer, Math.max(0, budget))
        budget -= delta.processed
        catchingUp ||= delta.pending
        history.lines.sync(history.mirror.segments, delta.changed, delta.removed, altitude)
      }
      for (const [id, history] of histories) {
        if (input.tracks.tracks.has(id)) continue
        history.lines.destroy()
        histories.delete(id)
      }
      const points = [...histories.values()].reduce((total, history) => total + history.mirror.pointCount, 0)
      options.onStats({ drones: planes.size, points, catchingUp })
      host.dataset.earthPoints = String(points)
      host.dataset.earthDrones = String(planes.size)
    } catch (error) {
      options.onWarning(`地球更新失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      viewer.entities.resumeEvents()
    }
    requestRender()
    if (catchingUp) schedule(16)
  }

  function resize(): void {
    if (destroyed) return
    // Allocate a drawing buffer only for viewport/quality changes, never for a gesture.
    const settings = earthRenderQuality(quality, host.clientWidth, host.clientHeight, window.devicePixelRatio)
    viewer.useBrowserRecommendedResolution = true
    viewer.resolutionScale = settings.scale
    viewer.scene.globe.maximumScreenSpaceError = settings.detail
    if (host.clientWidth && host.clientHeight) {
      viewer.resize()
      // Integer drawing-buffer rounding must not change the projection when quality
      // changes, otherwise moveEnd -> resize -> moveStart can loop indefinitely.
      ;(viewer.camera.frustum as PerspectiveFrustum).aspectRatio = host.clientWidth / host.clientHeight
    }
    requestRender()
  }
  function camera(): EarthCamera {
    const current = viewer.camera
    return {
      longitude: current.positionCartographic.longitude, latitude: current.positionCartographic.latitude,
      height: current.positionCartographic.height,
      heading: current.heading, pitch: current.pitch, roll: current.roll,
    }
  }
  function destroy(): void {
    if (destroyed) return
    destroyed = true
    terrain.destroy()
    imagery.destroy()
    delete host.dataset.earthTerrain
    delete host.dataset.earthImagery
    if (pending !== null) clearTimeout(pending)
    pending = null
    resizeObserver?.disconnect()
    for (const stop of unsubscribe) stop()
    effects?.destroy()
    daylight?.destroy()
    labels?.destroy()
    boundaries?.destroy()
    input = null
    trackSource = null
    droneSource = null
    trajectorySource = null
    planes.clear()
    histories.clear()
    delete host.dataset.earthPoints
    delete host.dataset.earthDrones
    if (!viewer.isDestroyed()) {
      const contextId = (viewer.scene as unknown as { context: { id: string } }).context.id
      const canvas = viewer.canvas
      const gl = canvas.getContext('webgl2') ?? canvas.getContext('webgl')
      const releaseContext = gl?.getExtension('WEBGL_lose_context')
      // Cesium 1.145's widget destroy does not destroy its public input handler.
      // Explicitly dispose it and surrender the native context, which can otherwise
      // retain detached canvases across repeated start/close cycles in Chromium.
      const handler = viewer.screenSpaceEventHandler
      if (!handler.isDestroyed()) handler.destroy()
      viewer.destroy()
      releaseEllipsoidContextCache(contextId)
      releaseContext?.loseContext()
      canvas.width = 1
      canvas.height = 1
    }
  }

  try {
    viewer.scene.globe.baseColor = Color.fromCssColorString('#15314d')
    // A camera-facing light gives the globe depth without a time-dependent dark hemisphere.
    // Cesium fades this shading out near the ground so local imagery remains readable.
    const light = new DirectionalLight({ direction: Cartesian3.clone(viewer.camera.directionWC) })
    viewer.scene.light = light
    viewer.scene.globe.enableLighting = true
    viewer.scene.globe.lambertDiffuseMultiplier = 1.04
    unsubscribe.push(viewer.scene.preRender.addEventListener(() => {
      if (presentation.sunlight) Cartesian3.clone(sunlightDirection, light.direction)
      else {
        // Slightly off-axis illumination keeps relief readable without flattening the sphere.
        const camera = viewer.camera
        light.direction.x = camera.directionWC.x + camera.rightWC.x * 0.28 - camera.upWC.x * 0.16
        light.direction.y = camera.directionWC.y + camera.rightWC.y * 0.28 - camera.upWC.y * 0.16
        light.direction.z = camera.directionWC.z + camera.rightWC.z * 0.28 - camera.upWC.z * 0.16
        Cartesian3.normalize(light.direction, light.direction)
      }
    }))
    unsubscribe.push(viewer.scene.preUpdate.addEventListener(() => {
      const now = performance.now()
      const delta = Math.min((now - previousFrame) / 1000, 0.05)
      previousFrame = now
      if (!presentation.tour || reducedMotion.matches || document.hidden || !host.isConnected
        || !host.clientWidth || viewer.camera.positionCartographic.height < 2_000_000) return
      viewer.camera.rotate(Cartesian3.UNIT_Z, -delta * 0.035)
      requestRender()
    }))
    viewer.scene.globe.showGroundAtmosphere = true
    viewer.scene.globe.dynamicAtmosphereLighting = false
    viewer.scene.globe.atmosphereSaturationShift = -0.12
    viewer.scene.skyAtmosphere!.saturationShift = -0.12
    viewer.scene.backgroundColor = Color.fromCssColorString('#030711')
    viewer.scene.fog.enabled = true
    viewer.scene.sunBloom = false
    if (viewer.scene.sun) viewer.scene.sun.show = false
    if (viewer.scene.moon) viewer.scene.moon.show = false
    viewer.scene.postProcessStages.fxaa.enabled = true
    effects = new EarthSceneEffects(viewer.scene, host)
    daylight = new EarthDaylight(viewer.scene, host)
    labels = new EarthPlaceLabels(viewer.scene, host)
    boundaries = new EarthBoundaries(viewer.scene)
    viewer.cesiumWidget.creditDisplay.addStaticCredit(new Credit('Place names and boundaries: Natural Earth (public domain)'))
    viewer.cesiumWidget.creditDisplay.addStaticCredit(new Credit('Cloud imagery: NASA Visible Earth (archival)'))
    viewer.scene.screenSpaceCameraController.zoomFactor = 3
    viewer.scene.screenSpaceCameraController.inertiaZoom = 0.75
    for (const event of ['pointerdown', 'wheel', 'keydown']) {
      host.addEventListener(event, stopTour, { passive: true })
      unsubscribe.push(() => host.removeEventListener(event, stopTour))
    }
    if (options.camera) {
      const saved = options.camera
      viewer.camera.setView({
        destination: Cartesian3.fromRadians(saved.longitude, saved.latitude, saved.height),
        orientation: { heading: saved.heading, pitch: saved.pitch, roll: saved.roll },
      })
    } else {
      viewer.camera.setView({ destination: overviewPosition() })
    }
    resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(host)
    resize()
    unsubscribe.push(viewer.scene.renderError.addEventListener((_scene, error) => {
      options.onWarning(`地球渲染异常，请关闭后重试：${String(error)}`)
    }))
    // Metadata and satellite requests only begin here, after the user's explicit start.
    // The bundled map also gives a recognizable globe while online imagery loads/fails.
    void TileMapServiceImageryProvider.fromUrl(buildModuleUrl('Assets/Textures/NaturalEarthII'), {
      maximumLevel: 2, credit: 'Natural Earth II',
    }).then((provider) => {
      if (destroyed) return
      viewer.imageryLayers.addImageryProvider(provider, 0)
      requestRender()
    }).catch(() => {
      if (!destroyed) options.onWarning('本地地球底图加载失败，请刷新页面重试。')
    })
    void imagery.set(options.imagery ?? { id: 'esri' })
    void SingleTileImageryProvider.fromUrl(reliefUrl, {
      credit: 'NASA Blue Marble Next Generation (December 2004), topography and bathymetry',
    }).then(provider => {
      if (destroyed) return
      relief = viewer.imageryLayers.addImageryProvider(provider)
      relief.brightness = 1.12
      relief.saturation = 0.9
      relief.gamma = 1.12
      relief.alpha = satelliteReady ? 0 : 1
      requestRender()
    }).catch(() => {
      if (!destroyed) options.onWarning('全球地貌纹理加载失败，当前使用备用底图。')
    })
    return {
      update(next) { input = next; schedule() },
      setAltitude(value) {
        const next = altitudeOverride(value)
        if (next === altitude) return
        altitude = next
        droneSource = null
        trajectorySource = null
        schedule(0)
      },
      setTracksVisible(visible) {
        tracksVisible = visible
        for (const history of histories.values()) history.lines.setVisible(visible)
        for (let index = 0; index < planned.length; index++) planned.get(index).show = visible
        requestRender()
      },
      follow(id) { if (id !== null) stopTour(); followed = id; applyFollow(); requestRender() },
      setQuality(value) { quality = value; daylight?.setQuality(value); resize() },
      setTerrainEnabled(enabled) { terrain.setEnabled(enabled) },
      reloadTerrain() { terrain.reload() },
      setImagery(selection) { return imagery.set(selection) },
      setEffects(value) {
        effects?.configure(value)
        daylight?.configure(value)
        labels?.configure(value.labels !== false, value.labelDensity)
        boundaries?.setVisible(value.boundaries !== false)
      },
      setPresentation, visit, overview, locateAll, skyView, resize, camera, destroy,
    }
  } catch (error) {
    destroy()
    throw error
  }
}
