import { expect, it, vi } from 'vitest'
import { releaseClosedContextIndexBuffer, type CachedIndices } from '../src/earth/cesiumCleanup'

it('releases only the closed viewer context, including buffers Cesium did not dispose', () => {
  const indices = new Uint16Array([0, 1, 2]) as CachedIndices
  const dispose = vi.fn()
  const otherDispose = vi.fn()
  indices.indexBuffers = {
    closed: { isDestroyed: () => false, destroy: dispose },
    active: { isDestroyed: () => false, destroy: otherDispose },
    otherClosed: { isDestroyed: () => true, destroy: otherDispose },
  }
  releaseClosedContextIndexBuffer(indices, 'closed')
  releaseClosedContextIndexBuffer(indices, 'closed')
  expect(dispose).toHaveBeenCalledOnce()
  expect(otherDispose).not.toHaveBeenCalled()
  expect(Object.keys(indices.indexBuffers)).toEqual(['active', 'otherClosed'])
  expect([...indices]).toEqual([0, 1, 2])
  expect(() => releaseClosedContextIndexBuffer(new Uint16Array(), 'missing')).not.toThrow()
})
