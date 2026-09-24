import { describe, expect, it } from 'vitest'

import type { TrackUpdate } from '../src/types'
import { DroneTrackBuffer, TrackSession } from '../src/utils/trackSession'

function update(epoch: number, seq: number, lat = 38 + seq / 1000): TrackUpdate {
  return { epoch, seq, point: { lat, lon: 117 + seq / 1000 } }
}

describe('fixed-capacity track session', () => {
  it('uses TypedArray storage and overwrites the oldest point at capacity', () => {
    const buffer = new DroneTrackBuffer(3)
    for (let seq = 1; seq <= 4; seq += 1) buffer.append(update(0, seq))

    expect(buffer.coordinates).toBeInstanceOf(Float64Array)
    expect(buffer.breaks).toBeInstanceOf(Uint8Array)
    expect(buffer.sequences).toBeInstanceOf(Float64Array)
    expect(buffer.coordinates).toHaveLength(6)
    expect(buffer.breaks).toHaveLength(3)
    expect(buffer.count).toBe(3)
    expect(buffer.pointAt(0)).toEqual(update(0, 2).point)
    expect(buffer.sequenceAt(0)).toBe(2)
    expect(buffer.pointAt(2)).toEqual(update(0, 4).point)
  })

  it('marks sequence gaps as line breaks without discarding valid later points', () => {
    const session = new TrackSession(10)
    expect(session.apply({ 1: update(0, 1) })[0]?.breakBefore).toBe(true)
    expect(session.apply({ 1: update(0, 2) })[0]?.breakBefore).toBe(false)
    const gap = session.apply({ 1: update(0, 4) })[0]

    expect(gap).toEqual(expect.objectContaining({ id: 1, seq: 4, breakBefore: true }))
    expect(session.tracks.get(1)?.count).toBe(3)
    expect(session.tracks.get(1)?.breakAt(2)).toBe(true)
    expect(gap?.oldestSeq).toBe(1)
  })

  it('clears every drone on a new epoch and ignores stale-epoch updates', () => {
    const session = new TrackSession(10)
    session.apply({ 1: update(0, 1), 2: update(0, 1, 39) })
    const next = session.apply({ 2: update(1, 1, 40) })

    expect(session.epoch).toBe(1)
    expect(session.tracks.get(1)?.count).toBe(0)
    expect(session.tracks.get(2)?.count).toBe(1)
    expect(next[0]).toEqual(expect.objectContaining({ id: 2, epoch: 1, breakBefore: true }))
    expect(session.apply({ 1: update(0, 2) })).toEqual([])
  })

  it('accepts only finite updates for configured drone IDs 1 through 24', () => {
    const session = new TrackSession(10, 24)
    const result = session.apply({
      0: update(0, 1),
      1: update(0, 1),
      24: update(0, 1, 39),
      25: update(0, 1),
      bad: update(0, 1),
      2: { epoch: 0, seq: 1, point: { lat: Number.NaN, lon: 117 } },
    })

    expect(result.map((item) => item.id)).toEqual([1, 24])
    expect([...session.tracks.keys()]).toEqual([1, 24])
  })
})
