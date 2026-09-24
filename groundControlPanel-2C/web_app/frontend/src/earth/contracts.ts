import type { DroneState, GeoPoint } from '../types'
import type { TrackSession } from '../utils/trackSession'
import type { ImagerySelection, ImageryState } from './imageryConfig'

export interface EarthInputs {
  drones: readonly (DroneState & { id: number })[]
  tracks: TrackSession
  trajectories: Readonly<Record<string, GeoPoint[]>>
  stale: boolean
}

export interface EarthCamera {
  longitude: number
  latitude: number
  height: number
  heading: number
  pitch: number
  roll: number
}

export interface EarthStats { drones: number; points: number; catchingUp: boolean }
export type EarthQuality = 'smooth' | 'balanced' | 'sharp'
export type EarthLabelDensity = 'sparse' | 'standard' | 'detailed'
export interface EarthEffects {
  clouds: boolean; satellites: boolean; animate: boolean
  labels?: boolean; labelDensity?: EarthLabelDensity; boundaries?: boolean
  cumulus?: boolean; cirrus?: boolean; haze?: boolean; atmosphere?: boolean
}
export interface EarthPresentation { tour: boolean; sunlight: boolean; sunLongitude: number }
export type EarthDestination = 'asia' | 'pacific' | 'polar' | 'himalaya'
export type EarthTerrainStatus = 'idle' | 'off' | 'loading' | 'ready' | 'error' | 'unconfigured'

export interface EarthRenderer {
  update(input: EarthInputs): void
  setAltitude(altitude: number | null): void
  setTracksVisible(visible: boolean): void
  follow(id: number | null): void
  locateAll(): void
  skyView(): void
  overview(): void
  setQuality(quality: EarthQuality): void
  setTerrainEnabled(enabled: boolean): void
  reloadTerrain(): void
  setImagery(selection: ImagerySelection): Promise<boolean>
  setEffects(effects: EarthEffects): void
  setPresentation(presentation: EarthPresentation): void
  visit(destination: EarthDestination): void
  resize(): void
  camera(): EarthCamera
  destroy(): void
}

export interface EarthOptions {
  camera?: EarthCamera
  imagery?: ImagerySelection
  onImageryState?(state: ImageryState): void
  onWarning(message: string): void
  onStats(stats: EarthStats): void
  onTourChange?(active: boolean): void
  onTerrainStatus?(status: EarthTerrainStatus): void
}
