import { expect, it } from 'vitest'
import { DEMO_ORBITS, effectOpacity, orbitNormal, orbitPoint } from '../src/earth/orbits'
import { Cartesian3, Matrix3, Quaternion } from 'cesium'

it('keeps the static trail tip attached to its satellite through a complete orbit', () => {
  for (const orbit of DEMO_ORBITS) {
    const normal = orbitNormal(orbit)
    const axis = new Cartesian3(normal.x, normal.y, normal.z)
    const start = orbitPoint(orbit, orbit.phase)
    for (let step = 0; step <= 24; step++) {
      const angle = step / 24 * Math.PI * 2
      const rotation = Matrix3.fromQuaternion(Quaternion.fromAxisAngle(axis, angle))
      const tip = Matrix3.multiplyByVector(rotation, new Cartesian3(start.x, start.y, start.z), new Cartesian3())
      const satellite = orbitPoint(orbit, orbit.phase + angle)
      expect(Cartesian3.distance(tip, new Cartesian3(satellite.x, satellite.y, satellite.z))).toBeLessThan(0.001)
    }
  }
})

it('keeps all demonstration satellites above Earth and closes each circular orbit', () => {
  for (const orbit of DEMO_ORBITS) {
    for (let step = 0; step <= 120; step++) {
      const point = orbitPoint(orbit, step / 120 * Math.PI * 2)
      expect(Math.hypot(point.x, point.y, point.z)).toBeCloseTo(orbit.radius, 5)
      expect(Math.hypot(point.x, point.y, point.z)).toBeGreaterThan(6_378_137)
    }
    const first = orbitPoint(orbit, 0), last = orbitPoint(orbit, Math.PI * 2)
    expect(Math.hypot(first.x - last.x, first.y - last.y, first.z - last.z)).toBeLessThan(0.001)
  }
})

it('hides decorative objects in local flight views and fades them in only at global scale', () => {
  expect(effectOpacity(1_000)).toBe(0)
  expect(effectOpacity(600_000)).toBe(0)
  expect(effectOpacity(1_300_000)).toBeCloseTo(0.5)
  expect(effectOpacity(2_000_000)).toBe(1)
  expect(effectOpacity(30_000_000)).toBe(1)
})
