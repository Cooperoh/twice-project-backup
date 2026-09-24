import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MapPanel from '../src/components/MapPanel.vue'
import type { RuntimeConfig } from '../src/types'
import { TrackSession, type TrackAppend } from '../src/utils/trackSession'

const leafletHarness = vi.hoisted(() => ({
  maps: [] as Array<Record<string, any>>,
  polylines: [] as Array<Record<string, any>>,
  circleMarkers: [] as Array<Record<string, any>>,
  divIcons: [] as Array<Record<string, any>>,
}))

const webglHarness = vi.hoisted(() => ({
  instances: [] as Array<{
    map: unknown
    config: unknown
    session: unknown
    setVisible: ReturnType<typeof vi.fn>
    apply: ReturnType<typeof vi.fn>
    clear: ReturnType<typeof vi.fn>
    dispose: ReturnType<typeof vi.fn>
  }>,
}))

vi.mock('../src/components/WebGLTrackLayer', () => ({
  WebGLTrackLayer: class {
    map: unknown
    config: unknown
    session: unknown
    setVisible = vi.fn()
    apply = vi.fn()
    clear = vi.fn()
    dispose = vi.fn()

    constructor(map: unknown, config: unknown, session: unknown) {
      this.map = map
      this.config = config
      this.session = session
      webglHarness.instances.push(this)
    }
  },
}))

vi.mock('leaflet', () => {
  function removableLayer(extra: Record<string, any> = {}) {
    const layer: Record<string, any> = { ...extra }
    layer.addTo = vi.fn(() => layer)
    layer.remove = vi.fn(() => layer)
    layer.bindTooltip = vi.fn(() => layer)
    layer.setLatLng = vi.fn(() => layer)
    layer.setRadius = vi.fn(() => layer)
    return layer
  }

  const leaflet = {
    map: vi.fn(() => {
      const instance: Record<string, any> = {}
      instance.setView = vi.fn(() => instance)
      instance.invalidateSize = vi.fn(() => instance)
      instance.remove = vi.fn(() => instance)
      instance.getCenter = vi.fn(() => ({ distanceTo: () => 0 }))
      instance.getBounds = vi.fn(() => ({ contains: vi.fn(() => false) }))
      instance.fitBounds = vi.fn(() => instance)
      instance.panTo = vi.fn(() => instance)
      leafletHarness.maps.push(instance)
      return instance
    }),
    tileLayer: vi.fn(() => removableLayer({ bringToBack: vi.fn() })),
    control: { scale: vi.fn(() => removableLayer()) },
    polyline: vi.fn((points: [number, number][], options: Record<string, unknown>) => {
      const line = removableLayer({ options, points })
      line.setLatLngs = vi.fn((next: [number, number][]) => {
        line.points = next
        return line
      })
      leafletHarness.polylines.push(line)
      return line
    }),
    marker: vi.fn(() => removableLayer({ getElement: vi.fn(() => null) })),
    circleMarker: vi.fn(() => {
      const marker = removableLayer()
      leafletHarness.circleMarkers.push(marker)
      return marker
    }),
    circle: vi.fn(() => removableLayer()),
    divIcon: vi.fn((options: Record<string, unknown>) => {
      leafletHarness.divIcons.push(options)
      return options
    }),
    latLng: vi.fn((lat: number, lon: number) => ({ lat, lng: lon })),
    latLngBounds: vi.fn((points: [number, number][]) => ({ points })),
  }

  return { default: leaflet }
})

const config: RuntimeConfig = {
  home_lat: 38.3,
  home_lon: 117.6,
  map_zoom: 14,
  tile_url: 'https://example.invalid/{z}/{x}/{y}.png',
  tile_attribution: 'test',
  log_entries: 2000,
  track_points_per_drone: 10_000,
  obstacles: [],
}

function mountMap(overrides: Record<string, unknown> = {}): VueWrapper {
  return mount(MapPanel, {
    props: {
      drones: [],
      trackSession: new TrackSession(10_000),
      trackAppends: [],
      trackRevision: 0,
      trajectories: {},
      config,
      focusId: null,
      showTracks: true,
      showGoto: true,
      obstacles: [],
      showObstacles: false,
      ...overrides,
    },
  })
}

describe('MapPanel WebGL tracks and independent Leaflet layers', () => {
  beforeEach(() => {
    leafletHarness.maps = []
    leafletHarness.polylines = []
    leafletHarness.circleMarkers = []
    leafletHarness.divIcons = []
    webglHarness.instances = []
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      disconnect() {}
    })
  })

  afterEach(() => vi.unstubAllGlobals())

  it('creates one WebGL layer and sends only incremental appends or clear revisions', async () => {
    const session = new TrackSession(10_000)
    const wrapper = mountMap({ trackSession: session })
    const layer = webglHarness.instances[0]!
    expect((layer.session as TrackSession).capacity).toBe(session.capacity)
    expect(layer.setVisible).toHaveBeenCalledWith(true)
    expect(leafletHarness.polylines).toHaveLength(0)

    const appends: TrackAppend[] = [{
      id: 1,
      epoch: 0,
      seq: 2,
      lat: 38.31,
      lon: 117.61,
      previousLat: 38.3,
      previousLon: 117.6,
      oldestSeq: 1,
      breakBefore: false,
    }]
    await wrapper.setProps({ trackAppends: appends, trackRevision: 1 })
    expect(layer.apply).toHaveBeenCalledWith(appends)

    await wrapper.setProps({ trackAppends: [], trackRevision: 2 })
    expect(layer.clear).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ showTracks: false })
    expect(layer.setVisible).toHaveBeenLastCalledWith(false)

    const replacement = new TrackSession(100)
    await wrapper.setProps({ trackSession: replacement })
    expect(layer.dispose).toHaveBeenCalledTimes(1)
    expect((webglHarness.instances[1]?.session as TrackSession).capacity).toBe(replacement.capacity)
    wrapper.unmount()
    expect(webglHarness.instances[1]?.dispose).toHaveBeenCalledTimes(1)
  })

  it('uses the 44px inline navigation arrow and keeps its label outside the rotation', () => {
    const wrapper = mountMap({
      drones: [{ id: 3, lat: 38.3, lon: 117.6, heading: 90, tag: 'DRONE3' }],
    })
    const icon = leafletHarness.divIcons[0]!
    const html = String(icon.html)

    expect(icon.iconSize).toEqual([44, 44])
    expect(icon.iconAnchor).toEqual([22, 22])
    expect(html).toContain('class="drone-arrow" style="transform:rotate(90deg)"')
    expect(html).toContain('<svg viewBox="0 0 100 100"')
    expect(html).toContain('points="50,4 85,80 50,58 15,80"')
    expect(html).toContain('fill="#E8232A"')
    expect(html).toContain('stroke="#8B0000"')
    expect(html).toContain('</svg></div><div class="drone-label">DRONE3</div>')
    wrapper.unmount()
  })

  it('ignores the zero-position placeholder and frames the first valid telemetry once', async () => {
    const wrapper = mountMap({ drones: [{ id: 1, lat: 0, lon: 0 }] })
    const map = leafletHarness.maps[0]!
    expect(leafletHarness.divIcons).toHaveLength(0)
    expect(map.fitBounds).not.toHaveBeenCalled()

    await wrapper.setProps({ drones: [{ id: 1, lat: 38.31, lon: 117.61 }] })
    expect(leafletHarness.divIcons).toHaveLength(1)
    expect(map.fitBounds).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ drones: [{ id: 1, lat: 38.32, lon: 117.62 }] })
    expect(map.fitBounds).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('keeps WebGL tracks, reference trajectories, and Goto layers independently visible', async () => {
    const wrapper = mountMap({
      drones: [{
        id: 1,
        lat: 38.3,
        lon: 117.6,
        goto_lat: 38.4,
        goto_lon: 117.7,
      }],
      trajectories: { 1: [{ lat: 38.2, lon: 117.5 }, { lat: 38.3, lon: 117.6 }] },
    })
    const webgl = webglHarness.instances[0]!
    const trajectory = leafletHarness.polylines.find((line) => line.options.color === '#1768e5')!
    const goto = leafletHarness.polylines.find((line) => line.options.color === '#e2b400')!
    const gotoMarker = leafletHarness.circleMarkers[0]!

    await wrapper.setProps({ showTracks: false })
    expect(webgl.setVisible).toHaveBeenLastCalledWith(false)
    expect(trajectory.remove).not.toHaveBeenCalled()
    expect(goto.remove).not.toHaveBeenCalled()
    expect(gotoMarker.remove).not.toHaveBeenCalled()

    await wrapper.setProps({ showGoto: false })
    expect(goto.remove).toHaveBeenCalledTimes(1)
    expect(gotoMarker.remove).toHaveBeenCalledTimes(1)
    expect(trajectory.remove).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
