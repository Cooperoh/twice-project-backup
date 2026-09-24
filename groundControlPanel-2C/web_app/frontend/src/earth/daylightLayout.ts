import type { EarthQuality } from './contracts'

const STEP = 0.08
const ROWS = 2250
const clamp = (value: number) => Math.max(0, Math.min(1, value))
export const daylightOpacity = (height: number) => 1 - clamp((height - 18000) / 65000)

function random(row: number, column: number, salt: number): number {
  let value = Math.imul(row + 7919, 374761393) ^ Math.imul(column + salt * 997, 668265263)
  value = Math.imul(value ^ (value >>> 13), 1274126177)
  return ((value ^ (value >>> 16)) >>> 0) / 4294967296
}

/** A bounded geographic grid: turning the camera never moves clouds with the observer. */
export function daylightCloudCells(longitude: number, latitude: number, quality: EarthQuality) {
  const radius = quality === 'smooth' ? 4 : quality === 'sharp' ? 7 : 6
  const centerRow = Math.min(ROWS - 1, Math.max(0, Math.floor((latitude + 90) / STEP)))
  const result = []
  for (let row = Math.max(0, centerRow - radius); row <= Math.min(ROWS - 1, centerRow + radius); row++) {
    const lat = -90 + (row + 0.5) * STEP
    const columns = Math.max(1, Math.round(360 * Math.cos(lat * Math.PI / 180) / STEP))
    const center = Math.floor(((longitude + 180) % 360 + 360) % 360 / 360 * columns)
    const used = new Set<number>()
    for (let delta = -radius; delta <= radius; delta++) {
      const column = ((center + delta) % columns + columns) % columns
      if (used.has(column)) continue
      used.add(column)
      if (random(row, column, 1) < 0.23) continue
      result.push({
        key: `${row}:${column}`,
        lon: -180 + (column + 0.15 + random(row, column, 2) * 0.7) / columns * 360,
        lat: lat + (random(row, column, 3) - 0.5) * STEP * 0.7,
        altitude: 2300 + random(row, column, 4) * 1700,
        width: 2400 + random(row, column, 5) * 3400,
        height: 950 + random(row, column, 6) * 1400,
        slice: 0.3 + random(row, column, 7) * 0.15,
      })
    }
  }
  return result
}
