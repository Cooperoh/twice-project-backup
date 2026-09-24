import { Cartographic, Color, PolylineCollection, PrimitiveCollection, type Scene } from 'cesium'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { EarthTrackLines } from '../src/earth/trackLines'
import type { EarthTrackSegment } from '../src/earth/trackMirror'

// jsdom lacks this browser constructor; exercise real Cesium line/material code.
beforeEach(() => {
  vi.stubGlobal('ImageBitmap', class ImageBitmap {})
  vi.stubGlobal('OffscreenCanvas', class OffscreenCanvas {})
})
afterEach(() => vi.unstubAllGlobals())

const segment = (key: number): EarthTrackSegment => ({
  key, sequences: [key * 10, key * 10 + 1],
  points: [{ lat: 38, lon: 117 + key / 100 }, { lat: 38.001, lon: 117 + key / 100 }],
})

it('updates only small edge buffers while completed history retains its lines and position arrays', () => {
  const primitives = new PrimitiveCollection()
  const lines = new EarthTrackLines({ primitives } as Scene, Color.CYAN)
  const segments = [segment(1), segment(2), segment(3)]
  lines.sync(segments, segments, [])
  const head = primitives.get(0) as PolylineCollection
  const history = primitives.get(1) as PolylineCollection
  const tail = primitives.get(2) as PolylineCollection
  const stableLine = history.get(0)
  const stablePositions = stableLine.positions
  const add = vi.spyOn(history, 'add')
  const remove = vi.spyOn(history, 'remove')
  const oldTailPositions = tail.get(0).positions
  segments[2]!.points.push({ lat: 38.002, lon: 117.03 })
  lines.sync(segments, [segments[2]!], [])
  expect(history.get(0)).toBe(stableLine)
  expect(stableLine.positions).toBe(stablePositions)
  expect(add).not.toHaveBeenCalled()
  expect(remove).not.toHaveBeenCalled()
  expect(tail.get(0).positions).not.toBe(oldTailPositions)
  expect(head.get(0).material).not.toBe(stableLine.material)

  // Advancing the capacity window migrates only the boundary segments.
  const next = [segments[1]!, segments[2]!, segment(4)]
  lines.sync(next, [next[2]!], [1])
  expect([head.length, history.length, tail.length]).toEqual([1, 1, 1])
  expect(head.get(0).positions).toHaveLength(2)
  expect(history.get(0).positions).toHaveLength(3)
  lines.setVisible(false)
  for (const group of [head, history, tail]) expect(group.get(0).show).toBe(false)
  lines.sync([next[2]!], [], [2, 3])
  expect([head.length, history.length, tail.length]).toEqual([0, 0, 1])
  lines.destroy()
  expect(primitives.length).toBe(0)
  expect([head, history, tail].every(group => group.isDestroyed())).toBe(true)
})

it('keeps separate gap segments and clears all lines on track reset', () => {
  const primitives = new PrimitiveCollection()
  const lines = new EarthTrackLines({ primitives } as Scene, Color.CYAN)
  const segments = [segment(1), segment(10)]
  lines.setVisible(false)
  lines.sync(segments, segments, [])
  expect(primitives.get(0).get(0).positions).toHaveLength(2)
  expect(primitives.get(2).get(0).positions).toHaveLength(2)
  expect(primitives.get(2).get(0).show).toBe(false)
  lines.sync([], [], [1, 10])
  expect([0, 1, 2].map(i => primitives.get(i).length)).toEqual([0, 0, 0])
  lines.destroy()
})

it('reprojects existing history when height changes and restores fallback without new telemetry', () => {
  const primitives = new PrimitiveCollection()
  const lines = new EarthTrackLines({ primitives } as Scene, Color.CYAN)
  const segments = [segment(1), segment(2), segment(3)]
  lines.sync(segments, segments, [])
  for (const altitude of [600, 0, null]) {
    lines.sync(segments, [], [], altitude)
    for (let group = 0; group < primitives.length; group++) {
      const line = (primitives.get(group) as PolylineCollection).get(0)
      for (const point of line.positions) expect(Cartographic.fromCartesian(point).height).toBeCloseTo(altitude ?? 2000, 5)
    }
  }
  lines.destroy()
})
