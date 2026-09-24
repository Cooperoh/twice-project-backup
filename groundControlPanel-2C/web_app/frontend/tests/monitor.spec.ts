import { createPinia, setActivePinia } from 'pinia'
import { shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useGcsStore } from '../src/stores/gcs'
import MonitorView from '../src/views/MonitorView.vue'

vi.mock('../src/components/MapPanel.vue', () => ({
  default: {
    name: 'MapPanel',
    props: [
      'drones',
      'trackSession',
      'trackAppends',
      'trackRevision',
      'trajectories',
    ],
    template: '<div class="map-stub" />',
  },
}))

describe('monitor immediate updates and bounded virtual log', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('retains 2000 logs while rendering only the visible virtual window', async () => {
    const store = useGcsStore()
    store.config.log_entries = 2000
    const wrapper = shallowMount(MonitorView)
    const scroller = wrapper.get('.log-stream').element as HTMLElement
    const scrollTopSetter = vi.fn()
    let scrollTop = 0
    Object.defineProperties(scroller, {
      clientHeight: { configurable: true, value: 280 },
      scrollHeight: { configurable: true, value: 56_000 },
      scrollTop: {
        configurable: true,
        get: () => scrollTop,
        set: (value: number) => {
          scrollTop = value
          scrollTopSetter(value)
        },
      },
    })
    const entries = Array.from({ length: 2000 }, (_, index) => ({
      timestamp: `timestamp-${index}`,
      text: `log-${index}`,
    }))

    store.applyEvent({
      type: 'realtime_batch',
      seq: 1,
      timestamp: '',
      payload: { logs: entries },
    })
    await nextTick()

    expect(store.logs).toHaveLength(2000)
    expect(wrapper.findAll('.log-line').length).toBeLessThanOrEqual(56)
    expect(wrapper.text()).not.toContain('log-0 ')
    expect(wrapper.text()).toContain('log-1999')
    expect(scrollTopSetter).toHaveBeenCalledTimes(1)
    expect(scrollTopSetter).toHaveBeenCalledWith(55_720)
    wrapper.unmount()
  })

  it('updates telemetry, markers, and track appends as soon as each batch arrives', async () => {
    const store = useGcsStore()
    const wrapper = shallowMount(MonitorView)
    const map = wrapper.getComponent({ name: 'MapPanel' })

    store.applyEvent({
      type: 'realtime_batch',
      seq: 1,
      timestamp: '',
      payload: {
        drones: { 1: { lat: 38.1, lon: 117.1, alt: 10 } },
        track_updates: {
          1: { epoch: 0, seq: 1, point: { lat: 38.1, lon: 117.1 } },
        },
        logs: [{ timestamp: 'one', text: 'first batch' }],
      },
    })
    await nextTick()

    expect(wrapper.findAll('.telemetry-table tbody tr')).toHaveLength(1)
    expect(map.props('drones')).toEqual([
      expect.objectContaining({ id: 1, lat: 38.1, lon: 117.1, alt: 10 }),
    ])
    expect(map.props('trackAppends')).toEqual([
      expect.objectContaining({ id: 1, seq: 1, breakBefore: true }),
    ])

    store.applyEvent({
      type: 'realtime_batch',
      seq: 2,
      timestamp: '',
      payload: {
        drones: {
          1: { lat: 38.2, lon: 117.2, alt: 20 },
          2: { lat: 39.0, lon: 118.0 },
        },
        track_updates: {
          1: { epoch: 0, seq: 2, point: { lat: 38.2, lon: 117.2 } },
        },
        logs: [{ timestamp: 'two', text: 'second batch' }],
      },
    })
    await nextTick()

    expect(wrapper.findAll('.telemetry-table tbody tr')).toHaveLength(2)
    expect(map.props('drones')).toEqual([
      expect.objectContaining({ id: 1, lat: 38.2, lon: 117.2, alt: 20 }),
      expect.objectContaining({ id: 2, lat: 39.0, lon: 118.0 }),
    ])
    expect(map.props('trackAppends')).toEqual([
      expect.objectContaining({ id: 1, seq: 2, breakBefore: false }),
    ])
    expect(store.trackSession.tracks.get(1)?.count).toBe(2)
    expect(store.logs.map((entry) => entry.text)).toEqual(['first batch', 'second batch'])
    wrapper.unmount()
  })
})
