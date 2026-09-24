import { Cartesian3, Cartographic, EllipsoidGeodesic, HeadingPitchRoll, Math as CesiumMath, Quaternion, Transforms } from 'cesium'
import type { GeoPoint } from '../types'
import { displayAltitude } from './altitude'

export function displayPosition(point: GeoPoint & { alt?: unknown }, override: number | null = null): Cartesian3 {
  return Cartesian3.fromDegrees(point.lon, point.lat, displayAltitude(point.alt, override))
}

// Low-level polylines use Cartesian segments. Subdivide long edges so they
// follow the ellipsoid just as the original geographic Entity polylines did.
export function displayPolyline(points: readonly (GeoPoint & { alt?: unknown })[], override: number | null = null): Cartesian3[] {
  const positions: Cartesian3[] = []
  let previous: Cartesian3 | undefined
  for (const point of points) {
    const current = displayPosition(point, override)
    if (previous && Cartesian3.distance(previous, current) > 10000) {
      const start = Cartographic.fromCartesian(previous)
      const end = Cartographic.fromCartesian(current)
      const arc = new EllipsoidGeodesic(start, end)
      const steps = Math.ceil(arc.surfaceDistance / 10000)
      for (let step = 1; step < steps; step++) {
        const intermediate = arc.interpolateUsingFraction(step / steps)
        const height = start.height + (end.height - start.height) * step / steps
        positions.push(Cartesian3.fromRadians(intermediate.longitude, intermediate.latitude, height))
      }
    }
    positions.push(current)
    previous = current
  }
  return positions
}

// The model's local north axis follows telemetry heading on the Earth tangent plane.
export function modelOrientation(point: Cartesian3, headingDegrees: number): Quaternion {
  return Transforms.headingPitchRollQuaternion(
    point, new HeadingPitchRoll(CesiumMath.toRadians(headingDegrees), 0, 0),
  )
}
