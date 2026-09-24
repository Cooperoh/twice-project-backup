import { describe, expect, it } from 'vitest'
import { earthRenderQuality } from '../src/earth/quality'

describe('Earth GPU pixel budget', () => {
  it('caps a 4K high-DPI viewport in every quality mode', () => {
    for (const [quality, budget] of [['smooth', 2_100_000], ['balanced', 3_000_000], ['sharp', 5_000_000]] as const) {
      const { scale } = earthRenderQuality(quality, 3840, 2160, 2)
      expect(3840 * 2160 * scale ** 2).toBeLessThanOrEqual(budget + 1)
    }
  })
  it('does not supersample a standard-DPI screen or break on a hidden host', () => {
    expect(earthRenderQuality('sharp', 1440, 900, 1).scale).toBe(1)
    expect(earthRenderQuality('balanced', 0, 0, 2).scale).toBe(1)
  })
})
