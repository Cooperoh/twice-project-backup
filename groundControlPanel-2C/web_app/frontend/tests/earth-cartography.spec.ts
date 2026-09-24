import { describe, expect, it } from 'vitest'
import places from '../src/earth/assets/places.json'
import borders from '../src/earth/assets/boundaries.json'
import { boundaryOpacity, overlaps, overviewOpacity, placeVisible } from '../src/earth/cartography'

describe('Earth geographic context', () => {
  it('uses valid, bounded local label data and includes Chinese city names', () => {
    expect(places.length).toBeGreaterThan(7000)
    expect(places.length).toBeLessThan(8000)
    expect(places.some(p => p.name === '北京' && p.kind === 'city')).toBe(true)
    for (const place of places) {
      expect(place.name.trim().length).toBeGreaterThan(0)
      expect(Math.abs(place.lat)).toBeLessThanOrEqual(90)
      expect(Math.abs(place.lon)).toBeLessThanOrEqual(180)
      expect(Number.isFinite(place.rank)).toBe(true)
    }
  })
  it('adds cities as the camera approaches and removes country labels in aircraft close-ups', () => {
    const count = (height: number) => places.filter(p => p.kind === 'city' && placeVisible(p, height)).length
    expect(count(15_000_000)).toBe(0)
    expect(count(5_000_000)).toBeGreaterThan(0)
    expect(count(800_000)).toBeGreaterThan(count(5_000_000))
    expect(places.some(p => p.kind === 'country' && placeVisible(p, 12_000))).toBe(false)
  })
  it('rejects overlapping labels including a readable margin', () => {
    const a = { x: 100, y: 100, width: 60, height: 20 }
    expect(overlaps(a, { ...a, x: 169 })).toBe(true)
    expect(overlaps(a, { ...a, x: 171 })).toBe(false)
    expect(overlaps(a, { ...a, y: 129 })).toBe(false)
  })
  it('offers more names at the same zoom in detailed mode and reveals small towns only nearby', () => {
    const count = (density: 'sparse' | 'standard' | 'detailed') =>
      places.filter(p => p.kind === 'city' && placeVisible(p, 5_000_000, density)).length
    expect(count('detailed')).toBeGreaterThan(count('standard'))
    expect(count('standard')).toBeGreaterThan(count('sparse'))
    const town = places.find(p => p.kind === 'city' && p.rank === 10)!
    expect(placeVisible(town, 2_000_000, 'detailed')).toBe(false)
    expect(placeVisible(town, 100_000, 'detailed')).toBe(true)
    // Even the tightest spacing never allows the text rectangles themselves to overlap.
    const box = { x: 100, y: 100, width: 60, height: 20 }
    expect(overlaps(box, { ...box, x: 159 }, 4)).toBe(true)
  })
  it('blends to satellite imagery near the ground without extrapolating opacity', () => {
    expect(overviewOpacity(0)).toBe(0)
    expect(overviewOpacity(900_000)).toBe(0)
    expect(overviewOpacity(2_200_000)).toBeCloseTo(0.5)
    expect(overviewOpacity(3_500_000)).toBe(1)
    expect(overviewOpacity(30_000_000)).toBe(1)
  })
  it('keeps boundary paths valid and never draws a longitude wrap across the map', () => {
    for (const lines of Object.values(borders)) for (const line of lines) {
      expect(new Set(line.map(point => point.join(','))).size).toBeGreaterThan(1)
      for (let i = 0; i < line.length; i++) {
        const [lon, lat] = line[i]!
        expect(Number.isFinite(lon) && Math.abs(lon!) <= 180).toBe(true)
        expect(Number.isFinite(lat) && Math.abs(lat!) <= 90).toBe(true)
        if (i) expect(Math.abs(lon! - line[i - 1]![0]!)).toBeLessThanOrEqual(180)
      }
    }
  })
  it('shows national boundaries first, then province lines, and hides generalized lines near aircraft', () => {
    expect(boundaryOpacity(15_000_000)).toEqual({ country: 1, region: 0 })
    expect(boundaryOpacity(3_000_000)).toEqual({ country: 1, region: 1 })
    expect(boundaryOpacity(12_000)).toEqual({ country: 0, region: 0 })
  })
})
