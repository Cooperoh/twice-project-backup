import type { GeoPoint, TrackUpdate } from '../types'

export interface TrackAppend {
  id: number
  epoch: number
  seq: number
  lat: number
  lon: number
  breakBefore: boolean
  previousLat?: number
  previousLon?: number
  oldestSeq: number
}

export class DroneTrackBuffer {
  readonly coordinates: Float64Array
  readonly breaks: Uint8Array
  readonly sequences: Float64Array
  head = 0
  count = 0
  epoch = 0
  lastSeq = 0

  constructor(readonly capacity: number) {
    this.coordinates = new Float64Array(capacity * 2)
    this.breaks = new Uint8Array(capacity)
    this.sequences = new Float64Array(capacity)
  }

  clear(epoch = this.epoch): void {
    this.head = 0
    this.count = 0
    this.epoch = epoch
    this.lastSeq = 0
    this.breaks.fill(0)
  }

  append(update: TrackUpdate): TrackAppend | null {
    if (update.epoch < this.epoch || update.seq <= this.lastSeq) return null
    const epochChanged = update.epoch !== this.epoch
    if (epochChanged) this.clear(update.epoch)

    const previous = this.count > 0 ? this.pointAt(this.count - 1) : null
    const breakBefore = previous === null || epochChanged || update.seq !== this.lastSeq + 1
    const tail = this.count < this.capacity
      ? (this.head + this.count) % this.capacity
      : this.head
    if (this.count < this.capacity) {
      this.count += 1
    } else {
      this.head = (this.head + 1) % this.capacity
    }
    this.coordinates[tail * 2] = update.point.lat
    this.coordinates[tail * 2 + 1] = update.point.lon
    this.breaks[tail] = breakBefore ? 1 : 0
    this.sequences[tail] = update.seq
    this.lastSeq = update.seq
    return {
      id: 0,
      epoch: update.epoch,
      seq: update.seq,
      lat: update.point.lat,
      lon: update.point.lon,
      breakBefore,
      previousLat: previous?.lat,
      previousLon: previous?.lon,
      oldestSeq: this.sequenceAt(0),
    }
  }

  pointAt(index: number): GeoPoint {
    const slot = (this.head + index) % this.capacity
    return {
      lat: this.coordinates[slot * 2]!,
      lon: this.coordinates[slot * 2 + 1]!,
    }
  }

  breakAt(index: number): boolean {
    return this.breaks[(this.head + index) % this.capacity] === 1
  }

  sequenceAt(index: number): number {
    return this.sequences[(this.head + index) % this.capacity]!
  }
}

export class TrackSession {
  readonly tracks = new Map<number, DroneTrackBuffer>()
  epoch = 0

  constructor(readonly capacity: number, readonly maxDroneId = 24) {}

  apply(updates: Record<string, TrackUpdate> | undefined): TrackAppend[] {
    if (!updates) return []
    const candidates = Object.entries(updates).flatMap(([rawId, update]) => {
      const id = Number(rawId)
      if (!Number.isInteger(id) || id < 1 || id > this.maxDroneId) return []
      if (!update || !Number.isFinite(update.epoch) || !Number.isFinite(update.seq)) return []
      if (!Number.isInteger(update.epoch) || update.epoch < 0) return []
      if (!Number.isInteger(update.seq) || update.seq < 1) return []
      if (!Number.isFinite(update.point?.lat) || !Number.isFinite(update.point?.lon)) return []
      return [{ id, update }]
    })
    const newestEpoch = candidates.reduce(
      (current, candidate) => Math.max(current, candidate.update.epoch),
      this.epoch,
    )
    if (newestEpoch > this.epoch) this.clear(newestEpoch)

    const applied: TrackAppend[] = []
    for (const { id, update } of candidates) {
      if (update.epoch !== this.epoch) continue
      let buffer = this.tracks.get(id)
      if (!buffer) {
        buffer = new DroneTrackBuffer(this.capacity)
        buffer.epoch = this.epoch
        this.tracks.set(id, buffer)
      }
      const append = buffer.append(update)
      if (append) {
        append.id = id
        applied.push(append)
      }
    }
    return applied
  }

  clear(epoch = this.epoch + 1): void {
    if (epoch < this.epoch) return
    this.epoch = epoch
    for (const buffer of this.tracks.values()) buffer.clear(epoch)
  }
}
