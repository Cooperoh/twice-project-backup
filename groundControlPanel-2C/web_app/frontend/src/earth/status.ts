import { readonly, ref } from 'vue'

export type EarthStatus = 'idle' | 'loading' | 'running' | 'error'
// Keep this module tiny: the navigation must never import the renderer.
const status = ref<EarthStatus>('idle')
export const earthStatus = readonly(status)
export function setEarthStatus(value: EarthStatus): void { status.value = value }
