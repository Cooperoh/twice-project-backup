import type { GeoPoint } from '../types'
import type { DroneTrackBuffer } from '../utils/trackSession'

export interface EarthTrackSegment {
  key: number
  sequences: number[]
  points: GeoPoint[]
}

// Small immutable-to-Cesium chunks keep updates bounded; no full-history copy per packet.
export class TrackMirror {
  readonly segments: EarthTrackSegment[] = []
  private epoch = -1
  private lastSeq = 0
  private nextKey = 0

  sync(buffer: DroneTrackBuffer, budget = 2048): {
    changed: EarthTrackSegment[]; removed: number[]; pending: boolean; processed: number
  } {
    const dirty = new Set<EarthTrackSegment>()
    const removed: number[] = []
    if (buffer.epoch !== this.epoch || buffer.lastSeq < this.lastSeq || buffer.count === 0) {
      removed.push(...this.segments.map((segment) => segment.key))
      this.segments.length = 0
      this.lastSeq = 0
      this.epoch = buffer.epoch
    }
    const oldest = buffer.count ? buffer.sequenceAt(0) : Infinity
    while (this.segments.length && this.segments[0]!.sequences.at(-1)! < oldest) {
      removed.push(this.segments.shift()!.key)
    }
    const first = this.segments[0]
    if (first) {
      const trim = first.sequences.findIndex((sequence) => sequence >= oldest)
      if (trim > 0) {
        first.sequences.splice(0, trim)
        first.points.splice(0, trim)
        dirty.add(first)
      }
    }
    let low = 0
    let high = buffer.count
    while (low < high) {
      const middle = (low + high) >>> 1
      if (buffer.sequenceAt(middle) <= this.lastSeq) low = middle + 1
      else high = middle
    }
    let processed = 0
    while (low < buffer.count && processed < budget) {
      const sequence = buffer.sequenceAt(low)
      const point = buffer.pointAt(low)
      let tail = this.segments.at(-1)
      const breakBefore = buffer.breakAt(low) || sequence !== this.lastSeq + 1
      if (!tail || breakBefore || tail.points.length >= 128) {
        const previous = !breakBefore && tail ? tail.points.at(-1) : undefined
        tail = {
          key: this.nextKey++,
          sequences: previous ? [this.lastSeq] : [],
          points: previous ? [previous] : [],
        }
        this.segments.push(tail)
      }
      tail.points.push(point)
      tail.sequences.push(sequence)
      dirty.add(tail)
      this.lastSeq = sequence
      ++low
      ++processed
    }
    return { changed: [...dirty], removed, pending: low < buffer.count, processed }
  }

  get pointCount(): number {
    // Adjacent chunks share one endpoint. Gaps do not share endpoints.
    let count = 0
    let last = -1
    for (const segment of this.segments) {
      count += segment.points.length - (segment.sequences[0] === last ? 1 : 0)
      last = segment.sequences.at(-1) ?? -1
    }
    return count
  }
}
