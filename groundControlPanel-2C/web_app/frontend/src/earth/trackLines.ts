import { Color, Material, Polyline, PolylineCollection, type Scene } from 'cesium'
import type { EarthTrackSegment } from './trackMirror'
import { displayPolyline } from './geography'

type Region = 'head' | 'history' | 'tail'
interface Entry { region: Region; line: Polyline }

/**
 * The two changing edges have their own small buffers. Completed history does
 * not go through Entity's asynchronous, whole-color geometry batching.
 * A point-count change in PolylineCollection reallocates that collection's
 * buffer, so putting every line in ONE collection would repeat the same mistake.
 */
export class EarthTrackLines {
  private readonly groups: Record<Region, PolylineCollection>
  private readonly entries = new Map<number, Entry>()
  private visible = true
  private altitude: number | null = null

  constructor(private readonly scene: Scene, private readonly color: Color) {
    this.groups = {
      head: scene.primitives.add(new PolylineCollection()),
      history: scene.primitives.add(new PolylineCollection()),
      tail: scene.primitives.add(new PolylineCollection()),
    }
  }

  sync(segments: readonly EarthTrackSegment[], changed: readonly EarthTrackSegment[], removed: readonly number[], altitude: number | null = null): void {
    const altitudeChanged = this.altitude !== altitude
    this.altitude = altitude
    for (const key of removed) {
      const entry = this.entries.get(key)
      if (entry) this.groups[entry.region].remove(entry.line)
      this.entries.delete(key)
    }
    const dirty = new Set(changed.map((segment) => segment.key))
    const firstKey = segments[0]?.key
    const lastKey = segments.at(-1)?.key
    for (const segment of segments) {
      const region: Region = segment.key === lastKey ? 'tail' : segment.key === firstKey ? 'head' : 'history'
      let entry = this.entries.get(segment.key)
      if (entry && entry.region !== region) {
        this.groups[entry.region].remove(entry.line)
        this.entries.delete(segment.key)
        entry = undefined
      }
      if (!entry) {
        const line = this.groups[region].add({
          positions: displayPolyline(segment.points, altitude), width: 2, show: this.visible,
          // Polyline owns/destroys its material, so materials must not be shared.
          material: Material.fromType('Color', { color: this.color }),
        })
        this.entries.set(segment.key, { region, line })
      } else if (altitudeChanged || dirty.has(segment.key)) {
        entry.line.positions = displayPolyline(segment.points, altitude)
      }
    }
  }

  setVisible(visible: boolean): void {
    this.visible = visible
    for (const entry of this.entries.values()) entry.line.show = visible
  }

  destroy(): void {
    for (const group of Object.values(this.groups)) this.scene.primitives.remove(group)
    this.entries.clear()
  }
}
