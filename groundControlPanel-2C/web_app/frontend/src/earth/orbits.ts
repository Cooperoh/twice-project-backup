// Decorative circular orbits in Earth-fixed coordinates, not satellite ephemerides.
export const DEMO_ORBITS = [
  { radius: 7_800_000, inclination: 0.6, node: 0.3, phase: 0.7, period: 110, color: '#8bdcff' },
  { radius: 8_050_000, inclination: 1.15, node: 2.1, phase: 2.8, period: 145, color: '#e7bf86' },
  { radius: 7_650_000, inclination: -0.8, node: 1.3, phase: 4.8, period: 125, color: '#aaa9ff' },
] as const

export function orbitPoint(orbit: typeof DEMO_ORBITS[number], angle: number) {
  const x = orbit.radius * Math.cos(angle)
  const y = orbit.radius * Math.sin(angle) * Math.cos(orbit.inclination)
  return {
    x: x * Math.cos(orbit.node) - y * Math.sin(orbit.node),
    y: x * Math.sin(orbit.node) + y * Math.cos(orbit.node),
    z: orbit.radius * Math.sin(angle) * Math.sin(orbit.inclination),
  }
}

export function effectOpacity(height: number): number {
  return Math.max(0, Math.min(1, (height - 600_000) / 1_400_000))
}

export function orbitNormal(orbit: typeof DEMO_ORBITS[number]) {
  return {
    x: Math.sin(orbit.inclination) * Math.sin(orbit.node),
    y: -Math.sin(orbit.inclination) * Math.cos(orbit.node),
    z: Math.cos(orbit.inclination),
  }
}
