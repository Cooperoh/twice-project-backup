import type { EarthQuality } from './contracts'

const profiles = {
  smooth: { scale: 0.85, pixels: 2_100_000, detail: 3 },
  balanced: { scale: 1, pixels: 3_000_000, detail: 2 },
  sharp: { scale: 1.5, pixels: 5_000_000, detail: 1.5 },
} as const

/** Bound total GPU pixels as well as DPI; a large 4K window needs both limits. */
export function earthRenderQuality(quality: EarthQuality, width: number, height: number, dpr: number) {
  const profile = profiles[quality]
  return {
    // Camera motion must not change buffer size or tile error: coarser imagery
    // levels can contain different photographs, causing large color patches.
    scale: Math.min(dpr || 1, profile.scale,
      Math.sqrt(profile.pixels / Math.max(1, width * height))),
    detail: profile.detail,
  }
}
