<script setup lang="ts">
import L, {
  type Circle,
  type CircleMarker,
  type Map as LeafletMap,
  type Marker,
  type Polyline,
  type TileLayer,
} from 'leaflet'
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { DroneState, GeoPoint, Obstacle, RuntimeConfig } from '../types'
import type { TrackAppend, TrackSession } from '../utils/trackSession'
import { finiteNumber, normalizeHeading } from '../utils/format'
import { WebGLTrackLayer } from './WebGLTrackLayer'

interface DisplayDrone extends DroneState {
  id: number
}

const props = defineProps<{
  drones: DisplayDrone[]
  trackSession: TrackSession
  trackAppends: TrackAppend[]
  trackRevision: number
  trajectories: Record<string, GeoPoint[]>
  config: RuntimeConfig
  focusId: number | null
  showTracks: boolean
  showGoto: boolean
  obstacles: Obstacle[]
  showObstacles: boolean
}>()

const emit = defineEmits<{ ready: [] }>()
const container = ref<HTMLElement | null>(null)
const webglError = ref<string | null>(null)
const validPositionCount = computed(() => props.drones.filter(hasPosition).length)

let map: LeafletMap | null = null
let tileLayer: TileLayer | null = null
let trackLayer: WebGLTrackLayer | null = null
let resizeObserver: ResizeObserver | null = null
let initialTelemetryViewportResolved = false
const markers = new Map<number, Marker>()
const trajectoryLines = new Map<number, Polyline>()
const gotoMarkers = new Map<number, CircleMarker>()
const gotoLines = new Map<number, Polyline>()
const obstacleLayers = new Map<string, Circle[]>()

function validMapPosition(lat: unknown, lon: unknown): boolean {
  return finiteNumber(lat) && finiteNumber(lon)
    && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180
    && !(lat === 0 && lon === 0)
}

function hasPosition(drone: DisplayDrone): boolean {
  return validMapPosition(drone.lat, drone.lon)
}

function pointList(points: GeoPoint[]): Array<[number, number]> {
  return points.flatMap((point) => validMapPosition(point.lat, point.lon)
    ? [[point.lat, point.lon] as [number, number]]
    : [])
}

function escapeHtml(value: string): string {
  const element = document.createElement('span')
  element.textContent = value
  return element.innerHTML
}

function markerIcon(drone: DisplayDrone): L.DivIcon {
  const heading = normalizeHeading(drone.heading)
  const tag = escapeHtml(drone.tag?.trim() || `DRONE${drone.id}`)
  return L.divIcon({
    className: 'drone-marker-shell',
    html: `<div class="drone-arrow" style="transform:rotate(${heading}deg)"><svg viewBox="0 0 100 100" aria-hidden="true" focusable="false"><polygon points="50,4 85,80 50,58 15,80" fill="#E8232A" stroke="#8B0000" stroke-width="3" stroke-linejoin="round" /></svg></div><div class="drone-label">${tag}</div>`,
    iconSize: [44, 44],
    iconAnchor: [22, 22],
  })
}

function updateMarkerContent(marker: Marker, drone: DisplayDrone): void {
  const element = marker.getElement()
  if (!element) return
  const arrow = element.querySelector<HTMLElement>('.drone-arrow')
  const label = element.querySelector<HTMLElement>('.drone-label')
  if (arrow) arrow.style.transform = `rotate(${normalizeHeading(drone.heading)}deg)`
  if (label) label.textContent = drone.tag?.trim() || `DRONE${drone.id}`
}

function syncMarkers(): void {
  if (!map) return
  const live = new Set<number>()
  for (const drone of props.drones) {
    if (!hasPosition(drone)) continue
    live.add(drone.id)
    const position: L.LatLngExpression = [drone.lat as number, drone.lon as number]
    let marker = markers.get(drone.id)
    if (!marker) {
      marker = L.marker(position, {
        icon: markerIcon(drone),
        keyboard: true,
        riseOnHover: true,
        title: drone.tag?.trim() || `DRONE${drone.id}`,
      }).addTo(map)
      marker.bindTooltip(`#${drone.id}`, { direction: 'bottom', offset: [0, 24], opacity: .9 })
      markers.set(drone.id, marker)
    } else {
      marker.setLatLng(position)
      updateMarkerContent(marker, drone)
    }
  }
  for (const [id, marker] of markers) {
    if (!live.has(id)) {
      marker.remove()
      markers.delete(id)
    }
  }
}

function syncTrajectories(): void {
  if (!map) return
  const live = new Set<number>()
  for (const [rawId, points] of Object.entries(props.trajectories)) {
    const id = Number(rawId)
    const positions = pointList(points)
    if (!Number.isInteger(id) || positions.length < 2) continue
    live.add(id)
    const line = trajectoryLines.get(id)
    if (line) line.setLatLngs(positions)
    else trajectoryLines.set(id, L.polyline(positions, {
      color: '#1768e5', weight: 4, opacity: .9, dashArray: '9 6',
    }).addTo(map))
  }
  for (const [id, line] of trajectoryLines) {
    if (!live.has(id)) {
      line.remove()
      trajectoryLines.delete(id)
    }
  }
}

function syncGoto(): void {
  if (!map) return
  const live = new Set<number>()
  if (props.showGoto) {
    for (const drone of props.drones) {
      if (!validMapPosition(drone.goto_lat, drone.goto_lon)) continue
      live.add(drone.id)
      const target: L.LatLngExpression = [drone.goto_lat as number, drone.goto_lon as number]
      let marker = gotoMarkers.get(drone.id)
      if (marker) marker.setLatLng(target)
      else {
        marker = L.circleMarker(target, {
          radius: 7, color: '#8e6900', weight: 2, fillColor: '#ffd400', fillOpacity: 1,
        }).addTo(map)
        marker.bindTooltip(`无人机 #${drone.id} 期望点`)
        gotoMarkers.set(drone.id, marker)
      }
      if (hasPosition(drone)) {
        const positions: L.LatLngExpression[] = [
          [drone.lat as number, drone.lon as number], target,
        ]
        const line = gotoLines.get(drone.id)
        if (line) line.setLatLngs(positions)
        else gotoLines.set(drone.id, L.polyline(positions, {
          color: '#e2b400', weight: 3, opacity: .95, dashArray: '7 5',
        }).addTo(map))
      }
    }
  }
  for (const registry of [gotoMarkers, gotoLines]) {
    for (const [id, layer] of registry) {
      if (!live.has(id)) {
        layer.remove()
        registry.delete(id)
      }
    }
  }
}

function syncObstacles(): void {
  if (!map) return
  const live = new Set<string>()
  if (props.showObstacles) {
    for (const obstacle of props.obstacles) {
      if (!validMapPosition(obstacle.lat, obstacle.lon) || !finiteNumber(obstacle.radius_m) || obstacle.radius_m <= 0) continue
      live.add(obstacle.id)
      const position: L.LatLngExpression = [obstacle.lat, obstacle.lon]
      const existing = obstacleLayers.get(obstacle.id)
      if (existing) {
        existing[0]?.setLatLng(position).setRadius(obstacle.radius_m)
        existing[1]?.setLatLng(position).setRadius(Math.max(1, obstacle.radius_m - 30))
      } else {
        const outer = L.circle(position, {
          radius: obstacle.radius_m, color: '#c92c38', weight: 3, fillOpacity: 0,
        }).addTo(map)
        const inner = L.circle(position, {
          radius: Math.max(1, obstacle.radius_m - 30), color: '#c92c38', weight: 1,
          fillColor: '#c92c38', fillOpacity: .16,
        }).addTo(map)
        outer.bindTooltip(`${obstacle.id} · ${obstacle.radius_m.toFixed(0)} m`)
        obstacleLayers.set(obstacle.id, [outer, inner])
      }
    }
  }
  for (const [id, layers] of obstacleLayers) {
    if (!live.has(id)) {
      layers.forEach((layer) => layer.remove())
      obstacleLayers.delete(id)
    }
  }
}

function syncFocus(): void {
  if (!map || props.focusId === null) return
  const drone = props.drones.find((item) => item.id === props.focusId)
  if (!drone || !hasPosition(drone)) return
  const target = L.latLng(drone.lat as number, drone.lon as number)
  if (map.getCenter().distanceTo(target) > .05) map.panTo(target, { animate: false })
}

function syncInitialViewport(): void {
  if (!map || initialTelemetryViewportResolved || props.focusId !== null) return
  const positions = props.drones.filter(hasPosition)
    .map((drone): [number, number] => [drone.lat as number, drone.lon as number])
  if (!positions.length) return
  initialTelemetryViewportResolved = true
  if (positions.some((position) => map!.getBounds().contains(position))) return
  map.fitBounds(L.latLngBounds(positions), {
    animate: false, maxZoom: props.config.map_zoom, padding: [48, 48],
  })
}

function syncDroneLayers(): void {
  syncMarkers()
  syncGoto()
  syncFocus()
  syncInitialViewport()
}

function syncTiles(): void {
  if (!map) return
  tileLayer?.remove()
  tileLayer = L.tileLayer(props.config.tile_url, {
    attribution: props.config.tile_attribution, maxZoom: 20,
  }).addTo(map)
  tileLayer.bringToBack()
}

function createTrackLayer(): void {
  if (!map) return
  trackLayer?.dispose()
  try {
    trackLayer = new WebGLTrackLayer(map, props.config, props.trackSession)
    trackLayer.setVisible(props.showTracks)
    webglError.value = null
  } catch (error) {
    trackLayer = null
    webglError.value = error instanceof Error ? error.message : String(error)
  }
}

onMounted(() => {
  if (!container.value) return
  map = L.map(container.value, { zoomControl: true, preferCanvas: true })
    .setView([props.config.home_lat, props.config.home_lon], props.config.map_zoom)
  syncTiles()
  L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map)
  resizeObserver = new ResizeObserver(() => map?.invalidateSize({ animate: false }))
  resizeObserver.observe(container.value)
  createTrackLayer()
  syncDroneLayers()
  syncTrajectories()
  syncObstacles()
  emit('ready')
})

watch(() => props.drones, syncDroneLayers)
watch(() => props.trajectories, syncTrajectories)
watch(() => [props.showObstacles, props.obstacles] as const, syncObstacles, { deep: true })
watch(() => [props.config.tile_url, props.config.tile_attribution] as const, syncTiles)
watch(() => props.showGoto, syncGoto)
watch(() => props.focusId, syncFocus)
watch(() => props.showTracks, (visible) => trackLayer?.setVisible(visible))
watch(() => props.trackSession, createTrackLayer)
watch(() => props.trackRevision, () => {
  if (props.trackAppends.length) trackLayer?.apply(props.trackAppends)
  else trackLayer?.clear()
})

onActivated(() => nextTick(() => map?.invalidateSize({ animate: false })))
onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  trackLayer?.dispose()
  map?.remove()
  trackLayer = null
  map = null
})
</script>

<template>
  <div class="map-wrapper">
    <div ref="container" class="leaflet-host" aria-label="无人机地图" />
    <div v-if="webglError" class="map-error">轨迹 WebGL 不可用：{{ webglError }}</div>
    <div class="map-readout">
      <span>{{ validPositionCount }} 架在线定位</span>
      <span>HOME {{ config.home_lat.toFixed(4) }}, {{ config.home_lon.toFixed(4) }}</span>
    </div>
  </div>
</template>

<style scoped>
.map-wrapper { position: relative; min-height: 430px; height: 100%; overflow: hidden; background: #dfe7ef; }
.leaflet-host { position: absolute; inset: 0; z-index: 0; }
.map-readout { position: absolute; z-index: 500; right: 10px; bottom: 10px; display: flex; gap: 10px; padding: 6px 8px; color: #fff; border: 1px solid rgb(255 255 255 / 20%); border-radius: 4px; background: rgb(15 29 54 / 84%); backdrop-filter: blur(4px); font: 600 11px/1.2 ui-monospace, monospace; pointer-events: none; }
.map-error { position: absolute; z-index: 550; top: 10px; left: 50%; max-width: 80%; padding: 8px 12px; color: #fff; border-radius: 4px; background: #a51d2d; transform: translateX(-50%); }
:deep(.leaflet-control-attribution) { font-size: 10px; }
:deep(.drone-marker-shell) { overflow: visible !important; border: none; background: transparent; }
:deep(.drone-arrow) { position: absolute; inset: 0; width: 44px; height: 44px; transform-origin: 22px 22px; }
:deep(.drone-arrow svg) { display: block; width: 100%; height: 100%; }
:deep(.drone-label) { position: absolute; top: -15px; left: 50%; color: #652A22; font: 700 11px/1.2 Tahoma, sans-serif; white-space: nowrap; pointer-events: none; transform: translateX(-50%); }
@media (max-width: 1100px) { .map-wrapper { min-height: 460px; } }
</style>
