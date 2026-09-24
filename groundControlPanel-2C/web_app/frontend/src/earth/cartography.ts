import type { EarthLabelDensity } from './contracts'

export interface Place { name: string; lon: number; lat: number; rank: number; kind: string }
export interface LabelBox { x: number; y: number; width: number; height: number }

export const labelProfiles = {
  sparse: { limit: 60, scale: 0.65, gap: 12 },
  standard: { limit: 120, scale: 1, gap: 8 },
  detailed: { limit: 220, scale: 1.5, gap: 4 },
} as const
const cityAltitudes = [14_000_000, 12_000_000, 9_000_000, 6_500_000, 4_500_000,
  3_000_000, 2_000_000, 1_200_000, 650_000, 300_000, 120_000]

/** A global overview stays quiet; regional views progressively reveal settlements. */
export function placeVisible(place: Place, altitude: number, density: EarthLabelDensity = 'standard'): boolean {
  if (place.kind === 'country') {
    return altitude > 350_000 && (place.rank <= 2 || altitude < 9_000_000)
      && (place.rank <= 4 || altitude < 4_000_000)
  }
  return altitude < (cityAltitudes[place.rank] ?? 0) * labelProfiles[density].scale
}

export function overlaps(a: LabelBox, b: LabelBox, gap = 10): boolean {
  return Math.abs(a.x - b.x) < (a.width + b.width) / 2 + gap
    && Math.abs(a.y - b.y) < (a.height + b.height) / 2 + Math.min(gap, 8)
}

export function overviewOpacity(altitude: number): number {
  const t = Math.max(0, Math.min(1, (altitude - 900_000) / 2_600_000))
  return t * t * (3 - 2 * t)
}

export function boundaryOpacity(altitude: number): { country: number; region: number } {
  const clamp = (value: number) => Math.max(0, Math.min(1, value))
  // These generalized borders suit a regional map; keep aircraft close-ups uncluttered.
  const near = clamp((altitude - 25_000) / 75_000)
  return {
    country: near * clamp((36_000_000 - altitude) / 16_000_000),
    region: near * clamp((10_000_000 - altitude) / 7_000_000),
  }
}
