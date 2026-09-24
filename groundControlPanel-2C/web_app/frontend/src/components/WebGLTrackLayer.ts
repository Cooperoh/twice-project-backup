import type { Map as LeafletMap } from 'leaflet'

import type { RuntimeConfig } from '../types'
import type { TrackAppend, TrackSession } from '../utils/trackSession'

const EARTH_RADIUS_M = 6_378_137
const EARTH_CIRCUMFERENCE_M = 2 * Math.PI * EARTH_RADIUS_M

const TRACK_COLORS = [
  '#E6194B', '#3CB44B', '#4363D8', '#F58231', '#911EB4', '#008080',
  '#F032E6', '#9A6324', '#800000', '#808000', '#000075', '#A9A9A9',
  '#FF4500', '#2E8B57', '#1E90FF', '#DAA520', '#6A5ACD', '#20B2AA',
  '#C71585', '#D2691E', '#DC143C', '#228B22', '#4169E1', '#8B008B',
] as const

interface ProgramState {
  program: WebGLProgram
  cornerBuffer: WebGLBuffer
  originLocation: WebGLUniformLocation
  viewportLocation: WebGLUniformLocation
  scaleLocation: WebGLUniformLocation
  halfWidthLocation: WebGLUniformLocation
  colorLocation: WebGLUniformLocation
}

interface TrackDiagnosticCanvas extends HTMLCanvasElement {
  __gcsTrackDraw?: () => void
  __gcsTrackLoad?: (firstSequence: number, lastSequence: number) => {
    durationMs: number
    pointCounts: Record<string, number>
  }
  __gcsTrackDiagnostics?: () => {
    contextLost: boolean
    framePending: boolean
    segmentCounts: Record<string, number>
    sessionPointCounts: Record<string, number>
    visible: boolean
  }
}

class DroneSegments {
  readonly data: Float32Array
  readonly endSequences: Float64Array
  head = 0
  count = 0
  gpu: WebGLBuffer | null = null

  constructor(readonly capacity: number, public epoch: number) {
    this.data = new Float32Array(capacity * 4)
    this.endSequences = new Float64Array(capacity)
  }

  clear(epoch = this.epoch): void {
    this.head = 0
    this.count = 0
    this.epoch = epoch
  }

  expire(oldestPointSequence: number): void {
    while (this.count > 0 && this.endSequences[this.head]! <= oldestPointSequence) {
      this.head = (this.head + 1) % this.capacity
      this.count -= 1
    }
  }

  append(values: readonly [number, number, number, number], endSequence: number): number {
    const slot = this.count < this.capacity
      ? (this.head + this.count) % this.capacity
      : this.head
    if (this.count < this.capacity) this.count += 1
    else this.head = (this.head + 1) % this.capacity
    this.data.set(values, slot * 4)
    this.endSequences[slot] = endSequence
    return slot
  }
}

export class WebGLTrackLayer {
  private readonly canvas: TrackDiagnosticCanvas
  private readonly segments = new Map<number, DroneSegments>()
  private gl: WebGL2RenderingContext | null = null
  private state: ProgramState | null = null
  private frame: number | null = null
  private visible = true
  private contextLost = false
  private disposed = false
  private epoch: number
  private readonly homeProjected: [number, number]

  constructor(
    private readonly map: LeafletMap,
    private readonly config: RuntimeConfig,
    private readonly session: TrackSession,
  ) {
    this.epoch = session.epoch
    this.homeProjected = projectMeters(config.home_lat, config.home_lon)
    this.canvas = document.createElement('canvas')
    this.canvas.className = 'gcs-webgl-tracks'
    Object.assign(this.canvas.style, {
      position: 'absolute',
      inset: '0',
      pointerEvents: 'none',
      zIndex: '450',
    })
    this.map.getContainer().appendChild(this.canvas)
    this.canvas.addEventListener('webglcontextlost', this.onContextLost)
    this.canvas.addEventListener('webglcontextrestored', this.onContextRestored)
    if (new URLSearchParams(window.location.search).get('trackDiagnostics') === '1') {
      this.canvas.__gcsTrackDraw = () => this.draw()
      this.canvas.__gcsTrackLoad = (firstSequence, lastSequence) => {
        const started = performance.now()
        for (let seq = firstSequence; seq <= lastSequence; seq += 1) {
          const updates: Record<string, {
            epoch: number
            seq: number
            point: { lat: number; lon: number }
          }> = {}
          for (let id = 1; id <= 24; id += 1) {
            updates[String(id)] = {
              epoch: 0,
              seq,
              point: {
                lat: 38.304 + id * 0.00035 + seq * 0.00000001,
                lon: 117.674 + seq * 0.000001,
              },
            }
          }
          this.session.apply(updates)
        }
        this.rebuild()
        return {
          durationMs: performance.now() - started,
          pointCounts: Object.fromEntries(
            [...this.session.tracks].map(([id, track]) => [String(id), track.count]),
          ),
        }
      }
      this.canvas.__gcsTrackDiagnostics = () => ({
        contextLost: this.contextLost,
        framePending: this.frame !== null,
        segmentCounts: Object.fromEntries(
          [...this.segments].map(([id, track]) => [String(id), track.count]),
        ),
        sessionPointCounts: Object.fromEntries(
          [...this.session.tracks].map(([id, track]) => [String(id), track.count]),
        ),
        visible: this.visible,
      })
    }
    this.map.on('move zoom resize', this.scheduleDraw, this)
    this.initializeContext()
    this.rebuild()
  }

  setVisible(visible: boolean): void {
    this.visible = visible
    this.canvas.style.display = visible ? '' : 'none'
    this.scheduleDraw()
  }

  apply(changes: readonly TrackAppend[]): void {
    const gl = this.gl
    const newestEpoch = changes.reduce(
      (current, change) => Math.max(current, change.epoch),
      this.epoch,
    )
    if (newestEpoch !== this.epoch) {
      this.epoch = newestEpoch
      for (const track of this.segments.values()) track.clear(newestEpoch)
    }
    for (const change of changes) {
      let track = this.segments.get(change.id)
      if (!track) {
        track = new DroneSegments(this.session.capacity, change.epoch)
        this.segments.set(change.id, track)
        if (gl) this.createGpuBuffer(track)
      } else if (track.epoch !== change.epoch) {
        track.clear(change.epoch)
      }
      track.expire(change.oldestSeq)
      if (
        change.breakBefore
        || change.previousLat === undefined
        || change.previousLon === undefined
      ) continue
      const start = this.localMeters(change.previousLat, change.previousLon)
      const end = this.localMeters(change.lat, change.lon)
      const slot = track.append([start[0], start[1], end[0], end[1]], change.seq)
      if (gl && track.gpu) {
        gl.bindBuffer(gl.ARRAY_BUFFER, track.gpu)
        gl.bufferSubData(gl.ARRAY_BUFFER, slot * 16, track.data.subarray(slot * 4, slot * 4 + 4))
      }
    }
    this.scheduleDraw()
  }

  clear(): void {
    this.epoch = this.session.epoch
    for (const track of this.segments.values()) track.clear(this.session.epoch)
    this.scheduleDraw()
  }

  dispose(): void {
    this.disposed = true
    if (this.frame !== null) cancelAnimationFrame(this.frame)
    this.frame = null
    this.map.off('move zoom resize', this.scheduleDraw, this)
    this.canvas.removeEventListener('webglcontextlost', this.onContextLost)
    this.canvas.removeEventListener('webglcontextrestored', this.onContextRestored)
    delete this.canvas.__gcsTrackDraw
    delete this.canvas.__gcsTrackLoad
    delete this.canvas.__gcsTrackDiagnostics
    this.canvas.remove()
    this.segments.clear()
    this.gl = null
    this.state = null
  }

  private initializeContext(): void {
    const gl = this.canvas.getContext('webgl2', {
      alpha: true,
      antialias: true,
      depth: false,
      preserveDrawingBuffer: false,
    })
    if (!gl) throw new Error('WebGL2 is required for the high-capacity track layer')
    this.gl = gl
    this.state = createProgram(gl)
    gl.enable(gl.BLEND)
    gl.blendFuncSeparate(
      gl.SRC_ALPHA,
      gl.ONE_MINUS_SRC_ALPHA,
      gl.ONE,
      gl.ONE_MINUS_SRC_ALPHA,
    )
  }

  private rebuild(): void {
    this.epoch = this.session.epoch
    this.segments.clear()
    for (const [id, buffer] of this.session.tracks) {
      const track = new DroneSegments(this.session.capacity, buffer.epoch)
      this.segments.set(id, track)
      let previous = buffer.count > 0 ? buffer.pointAt(0) : null
      for (let index = 1; index < buffer.count; index += 1) {
        const point = buffer.pointAt(index)
        if (!buffer.breakAt(index) && previous) {
          const start = this.localMeters(previous.lat, previous.lon)
          const end = this.localMeters(point.lat, point.lon)
          const seq = buffer.sequenceAt(index)
          track.append([start[0], start[1], end[0], end[1]], seq)
        }
        previous = point
      }
      if (this.gl) this.createGpuBuffer(track)
    }
    this.scheduleDraw()
  }

  private createGpuBuffer(track: DroneSegments): void {
    const gl = this.gl
    if (!gl) return
    track.gpu = gl.createBuffer()
    if (!track.gpu) throw new Error('Unable to allocate WebGL track buffer')
    gl.bindBuffer(gl.ARRAY_BUFFER, track.gpu)
    gl.bufferData(gl.ARRAY_BUFFER, track.data, gl.DYNAMIC_DRAW)
  }

  private readonly scheduleDraw = (): void => {
    if (this.disposed || this.contextLost || this.frame !== null) return
    this.frame = requestAnimationFrame(() => {
      this.frame = null
      this.draw()
    })
  }

  private draw(): void {
    const gl = this.gl
    const state = this.state
    if (!gl || !state || !this.visible) return
    const size = this.map.getSize()
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const width = Math.max(1, Math.round(size.x * dpr))
    const height = Math.max(1, Math.round(size.y * dpr))
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width
      this.canvas.height = height
      this.canvas.style.width = `${size.x}px`
      this.canvas.style.height = `${size.y}px`
    }
    gl.viewport(0, 0, width, height)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.useProgram(state.program)
    const origin = this.map.latLngToContainerPoint([
      this.config.home_lat,
      this.config.home_lon,
    ])
    const pixelsPerMeter = (256 * (2 ** this.map.getZoom())) / EARTH_CIRCUMFERENCE_M
    gl.uniform2f(state.originLocation, origin.x * dpr, origin.y * dpr)
    gl.uniform2f(state.viewportLocation, width, height)
    gl.uniform1f(state.scaleLocation, pixelsPerMeter * dpr)
    gl.uniform1f(state.halfWidthLocation, 2 * dpr)

    gl.bindBuffer(gl.ARRAY_BUFFER, state.cornerBuffer)
    gl.enableVertexAttribArray(0)
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0)
    gl.vertexAttribDivisor(0, 0)
    for (const [id, track] of this.segments) {
      if (!track.count || !track.gpu) continue
      const color = colorFor(id)
      gl.uniform4f(state.colorLocation, color[0], color[1], color[2], 0.82)
      gl.bindBuffer(gl.ARRAY_BUFFER, track.gpu)
      gl.enableVertexAttribArray(1)
      gl.vertexAttribDivisor(1, 1)
      const firstCount = Math.min(track.count, track.capacity - track.head)
      gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 16, track.head * 16)
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, firstCount)
      const secondCount = track.count - firstCount
      if (secondCount > 0) {
        gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 16, 0)
        gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, secondCount)
      }
    }
  }

  private localMeters(lat: number, lon: number): [number, number] {
    const point = projectMeters(lat, lon)
    return [point[0] - this.homeProjected[0], point[1] - this.homeProjected[1]]
  }

  private readonly onContextLost = (event: Event): void => {
    event.preventDefault()
    this.contextLost = true
    this.gl = null
    this.state = null
  }

  private readonly onContextRestored = (): void => {
    this.contextLost = false
    this.initializeContext()
    this.rebuild()
  }
}

function projectMeters(lat: number, lon: number): [number, number] {
  const clampedLat = Math.max(-85.05112878, Math.min(85.05112878, lat))
  const latitude = clampedLat * Math.PI / 180
  return [
    EARTH_RADIUS_M * lon * Math.PI / 180,
    EARTH_RADIUS_M * Math.log(Math.tan(Math.PI / 4 + latitude / 2)),
  ]
}

function colorFor(id: number): [number, number, number] {
  const hex = TRACK_COLORS[((id - 1) % TRACK_COLORS.length + TRACK_COLORS.length) % TRACK_COLORS.length]!
  return [
    Number.parseInt(hex.slice(1, 3), 16) / 255,
    Number.parseInt(hex.slice(3, 5), 16) / 255,
    Number.parseInt(hex.slice(5, 7), 16) / 255,
  ]
}

function createProgram(gl: WebGL2RenderingContext): ProgramState {
  const vertex = compile(gl, gl.VERTEX_SHADER, `#version 300 es
    layout(location=0) in vec2 a_corner;
    layout(location=1) in vec4 a_segment;
    uniform vec2 u_origin;
    uniform vec2 u_viewport;
    uniform float u_scale;
    uniform float u_half_width;
    void main() {
      vec2 start = u_origin + vec2(a_segment.x, -a_segment.y) * u_scale;
      vec2 end = u_origin + vec2(a_segment.z, -a_segment.w) * u_scale;
      vec2 delta = end - start;
      float length_px = max(length(delta), 0.001);
      vec2 normal = vec2(-delta.y, delta.x) / length_px;
      vec2 pixel = mix(start, end, a_corner.x) + normal * a_corner.y * u_half_width;
      vec2 clip = vec2(pixel.x / u_viewport.x * 2.0 - 1.0, 1.0 - pixel.y / u_viewport.y * 2.0);
      gl_Position = vec4(clip, 0.0, 1.0);
    }
  `)
  const fragment = compile(gl, gl.FRAGMENT_SHADER, `#version 300 es
    precision mediump float;
    uniform vec4 u_color;
    out vec4 outputColor;
    void main() { outputColor = u_color; }
  `)
  const program = gl.createProgram()
  if (!program) throw new Error('Unable to create WebGL track program')
  gl.attachShader(program, vertex)
  gl.attachShader(program, fragment)
  gl.linkProgram(program)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program) || 'Unable to link WebGL track program')
  }
  const cornerBuffer = gl.createBuffer()
  if (!cornerBuffer) throw new Error('Unable to create WebGL corner buffer')
  gl.bindBuffer(gl.ARRAY_BUFFER, cornerBuffer)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, -1, 0, 1, 1, -1, 1, 1]), gl.STATIC_DRAW)
  const uniform = (name: string): WebGLUniformLocation => {
    const location = gl.getUniformLocation(program, name)
    if (!location) throw new Error(`Missing WebGL uniform ${name}`)
    return location
  }
  return {
    program,
    cornerBuffer,
    originLocation: uniform('u_origin'),
    viewportLocation: uniform('u_viewport'),
    scaleLocation: uniform('u_scale'),
    halfWidthLocation: uniform('u_half_width'),
    colorLocation: uniform('u_color'),
  }
}

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type)
  if (!shader) throw new Error('Unable to create WebGL shader')
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader) || 'Unable to compile WebGL shader')
  }
  return shader
}
