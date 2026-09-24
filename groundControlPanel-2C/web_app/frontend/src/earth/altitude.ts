export const EARTH_DEFAULT_ALTITUDE = 2000

// Zero is a valid override. Empty/negative/non-finite values select telemetry.
export function altitudeOverride(value: unknown): number | null {
  if (typeof value === 'string') value = value.trim() === '' ? null : Number(value)
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
}

export function displayAltitude(alt: unknown, override: number | null = null): number {
  return altitudeOverride(override)
    ?? (typeof alt === 'number' ? altitudeOverride(alt) : null)
    ?? EARTH_DEFAULT_ALTITUDE
}
