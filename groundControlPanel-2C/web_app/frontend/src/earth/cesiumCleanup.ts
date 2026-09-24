import { TerrainProvider } from 'cesium'

interface CachedBuffer { isDestroyed(): boolean; destroy(): void }
export type CachedIndices = (Uint16Array | Uint32Array) & {
  indexBuffers?: Record<string, CachedBuffer>
}

// Caller must have destroyed the owning Viewer before handing over its context ID.
export function releaseClosedContextIndexBuffer(indices: CachedIndices, contextId: string): void {
  const buffer = indices.indexBuffers?.[contextId]
  if (!buffer) return
  if (!buffer.isDestroyed()) buffer.destroy()
  delete indices.indexBuffers![contextId]
}

/**
 * Version-specific workaround for Cesium 1.145 / engine 26.3.
 * EllipsoidTerrainProvider uses 16 x 16 grids. Their shared CPU index arrays
 * retain GPU buffers by context ID after Viewer.destroy (GlobeSurfaceTile ->
 * indexBuffers), including entries whose reference counts never reached zero.
 * These retain the WebGL context and detached canvas. Release ONLY this closed
 * viewer's entries, never another viewer's live resources.
 * Keep the repeated-close browser heap check when upgrading Cesium.
 */
export function releaseEllipsoidContextCache(contextId: string): void {
  releaseClosedContextIndexBuffer(TerrainProvider.getRegularGridIndices(16, 16), contextId)
  const provider = TerrainProvider as typeof TerrainProvider & {
    getRegularGridAndSkirtIndicesAndEdgeIndices?: (width: number, height: number) => { indices: CachedIndices }
  }
  const withSkirts = provider.getRegularGridAndSkirtIndicesAndEdgeIndices?.(16, 16)
  if (withSkirts) releaseClosedContextIndexBuffer(withSkirts.indices, contextId)
}
