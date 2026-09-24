import type { EarthOptions, EarthRenderer } from './contracts'

// Neither Cesium nor its CSS may enter the initial app or the idle Earth page.
export async function loadEarthRenderer(): Promise<
  (host: HTMLElement, options: EarthOptions) => EarthRenderer
> {
  ;(window as Window & { CESIUM_BASE_URL?: string }).CESIUM_BASE_URL =
    new URL('cesium/', document.baseURI).href
  return (await import('./renderer')).createEarthRenderer
}
