import { Cartesian3, Cartographic, Matrix3 } from 'cesium'
import { describe, expect, it } from 'vitest'
import { displayPosition, displayPolyline, modelOrientation } from '../src/earth/geography'
import { altitudeOverride, displayAltitude } from '../src/earth/altitude'

describe('Earth geographic display and configurable altitude', () => {
  it('uses the override, then telemetry, then 2000 metres, including zero and invalid values', () => {
    for (const value of ['', ' ', -1, '-50', null, undefined, NaN, Infinity, 'bad']) {
      expect(altitudeOverride(value)).toBeNull()
      expect(displayAltitude(350, altitudeOverride(value))).toBe(350)
    }
    for (const value of [undefined, null, NaN, Infinity, -1, '', '350']) {
      expect(displayAltitude(value)).toBe(2000)
    }
    expect(altitudeOverride('0')).toBe(0)
    expect(displayAltitude(0)).toBe(0)
    for (const alt of [0, 350, undefined]) {
      expect(Cartographic.fromCartesian(displayPosition({ lat: 38, lon: 117, alt }, 0)).height).toBeCloseTo(0, 5)
      expect(Cartographic.fromCartesian(displayPosition({ lat: 38, lon: 117, alt }, 1234.5)).height).toBeCloseTo(1234.5, 5)
    }
    expect(Cartographic.fromCartesian(displayPosition({ lat: 38, lon: 117, alt: 350 })).height).toBeCloseTo(350, 5)
  })
  it('keeps local points and subdivides long edges along the ellipsoid at the fallback height', () => {
    const local = [{ lat: 38, lon: 117 }, { lat: 38.001, lon: 117.001 }]
    expect(displayPolyline(local)).toEqual(local.map(point => displayPosition(point)))
    const acrossDateLine = displayPolyline([{lat: 30, lon: 179}, {lat: 30, lon: -179}])
    expect(acrossDateLine.length).toBeGreaterThan(10)
    for (const point of acrossDateLine) {
      expect(Cartographic.fromCartesian(point).height).toBeCloseTo(2000, 5)
    }
    for (let i = 1; i < acrossDateLine.length; i++) {
      expect(Cartesian3.distance(acrossDateLine[i - 1]!, acrossDateLine[i]!)).toBeLessThan(10010)
    }
  })
  it('interpolates altitude on long edges and overrides every interpolated point', () => {
    const points = [{ lat: 30, lon: 179, alt: 400 }, { lat: 30, lon: -179, alt: 1400 }]
    const heights = displayPolyline(points).map(point => Cartographic.fromCartesian(point).height)
    heights.forEach((height, i) => expect(height).toBeCloseTo(400 + 1000 * i / (heights.length - 1), 5))
    for (const point of displayPolyline(points, 750)) expect(Cartographic.fromCartesian(point).height).toBeCloseTo(750, 5)
  })
  it('places missing-altitude points exactly 2000 metres above the WGS84 ellipsoid', () => {
    for (const point of [{lat: 38.3094, lon: 117.68}, {lat: -45, lon: -120}, {lat: 0, lon: 90}]) {
      const world = displayPosition(point)
      const cartographic = Cartographic.fromCartesian(world)
      expect(cartographic.height).toBeCloseTo(2000, 5)
      expect(cartographic.latitude * 180 / Math.PI).toBeCloseTo(point.lat, 8)
      expect(cartographic.longitude * 180 / Math.PI).toBeCloseTo(point.lon, 8)
    }
  })
  it('points the fixed-wing model north/east/south in the local tangent plane', () => {
    const nose = (point: Cartesian3, heading: number) => Matrix3.multiplyByVector(
      Matrix3.fromQuaternion(modelOrientation(point, heading)), Cartesian3.UNIT_Y, new Cartesian3(),
    )
    const equator = displayPosition({lat: 0, lon: 0})
    expect(Cartesian3.dot(nose(equator, 0), Cartesian3.UNIT_Z)).toBeCloseTo(1, 8)
    expect(Cartesian3.dot(nose(equator, 90), Cartesian3.UNIT_Y)).toBeCloseTo(1, 8)
    expect(Cartesian3.dot(nose(equator, 180), Cartesian3.UNIT_Z)).toBeCloseTo(-1, 8)
    const point = displayPosition({lat: 38.3094, lon: 117.68})
    expect(Cartesian3.dot(nose(point, 0), nose(point, 90))).toBeCloseTo(0, 8)
    expect(Cartesian3.dot(nose(point, 0), nose(point, 360))).toBeCloseTo(1, 8)
  })
})
