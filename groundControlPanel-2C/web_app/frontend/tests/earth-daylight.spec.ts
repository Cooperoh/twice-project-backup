import { describe, expect, it } from 'vitest'
import { daylightCloudCells, daylightOpacity } from '../src/earth/daylightLayout'

describe('static daylight cloud coverage', () => {
  it('keeps shared clouds fixed when the observer crosses a cell boundary', () => {
    const first = daylightCloudCells(117.68, 38.31, 'balanced')
    const moved = new Map(daylightCloudCells(117.75, 38.35, 'balanced').map(cell => [cell.key, cell]))
    const shared = first.filter(cell => moved.has(cell.key))
    expect(shared.length).toBeGreaterThan(80)
    for (const cell of shared) expect(cell).toEqual(moved.get(cell.key))
  })
  it('bounds allocation and avoids duplicate cells at poles and the date line', () => {
    for (const [lon, lat] of [[180, 0], [-180, 89.99], [0, -90], [117.68, 38.31]]) {
      for (const quality of ['smooth', 'balanced', 'sharp'] as const) {
        const cells = daylightCloudCells(lon!, lat!, quality)
        expect(cells.length).toBeLessThanOrEqual(quality === 'smooth' ? 81 : quality === 'balanced' ? 169 : 225)
        expect(new Set(cells.map(cell => cell.key)).size).toBe(cells.length)
        for (const cell of cells) {
          expect(Math.abs(cell.lon)).toBeLessThanOrEqual(180)
          expect(Math.abs(cell.lat)).toBeLessThanOrEqual(90)
        }
      }
    }
    expect(daylightCloudCells(-180, 20, 'balanced')).toEqual(daylightCloudCells(180, 20, 'balanced'))
  })
  it('retains full clouds at flight heights and fades them out for the globe overview', () => {
    expect(daylightOpacity(2000)).toBe(1)
    expect(daylightOpacity(18000)).toBe(1)
    expect(daylightOpacity(50000)).toBeGreaterThan(0)
    expect(daylightOpacity(83000)).toBe(0)
    expect(daylightOpacity(2000000)).toBe(0)
  })
})
