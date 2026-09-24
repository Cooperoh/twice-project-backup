import { execFile } from 'node:child_process'
import dgram from 'node:dgram'
import { promisify } from 'node:util'

import { expect, test, type Page } from '@playwright/test'

const execFileAsync = promisify(execFile)
const MIB = 1024 * 1024

async function sendFleet(step: number): Promise<void> {
  const socket = dgram.createSocket('udp4')
  try {
    await Promise.all(Array.from({ length: 24 }, (_, index) => {
      const id = index + 1
      const payload = Buffer.from(JSON.stringify({
        type: 'telemetry',
        id,
        lat: 38.304 + id * 0.00035 + step * 0.00001,
        lon: 117.674 + step * 0.00002,
        heading: (step * 5 + id * 15) % 360,
        tag: `DRONE${id}`,
      }), 'utf8')
      return new Promise<void>((resolve, reject) => socket.send(
        payload,
        56998,
        '127.0.0.1',
        (error) => error ? reject(error) : resolve(),
      ))
    }))
  } finally {
    socket.close()
  }
}

async function installSyntheticSocket(page: Page): Promise<void> {
  await page.addInitScript(() => {
    type TestWindow = Window & { __gcsEmit?: (message: unknown) => boolean }
    let active: EventTarget | null = null

    class SyntheticWebSocket extends EventTarget {
      static readonly CONNECTING = 0
      static readonly OPEN = 1
      static readonly CLOSING = 2
      static readonly CLOSED = 3

      readonly url: string
      readyState = SyntheticWebSocket.CONNECTING

      constructor(url: string | URL) {
        super()
        this.url = String(url)
        active = this
        queueMicrotask(() => {
          this.readyState = SyntheticWebSocket.OPEN
          this.dispatchEvent(new Event('open'))
        })
      }

      close(): void {
        if (this.readyState === SyntheticWebSocket.CLOSED) return
        this.readyState = SyntheticWebSocket.CLOSED
        if (active === this) active = null
        this.dispatchEvent(new Event('close'))
      }
    }

    Object.defineProperty(window, 'WebSocket', {
      configurable: true,
      value: SyntheticWebSocket,
      writable: true,
    })
    ;(window as TestWindow).__gcsEmit = (message: unknown): boolean => {
      if (!active) return false
      active.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(message) }))
      return true
    }
  })
}

async function loadTrackRange(
  page: Page,
  first: number,
  last: number,
): Promise<{ durationMs: number; pointCounts: Record<string, number> }> {
  return page.locator('canvas.gcs-webgl-tracks').evaluate((element, range) => {
    const canvas = element as HTMLCanvasElement & {
      __gcsTrackLoad?: (
        firstSequence: number,
        lastSequence: number,
      ) => { durationMs: number; pointCounts: Record<string, number> }
    }
    if (!canvas.__gcsTrackLoad) throw new Error('track diagnostics loader is unavailable')
    return canvas.__gcsTrackLoad(range.first, range.last)
  }, { first, last })
}

async function jsHeapUsed(page: Page): Promise<number> {
  const session = await page.context().newCDPSession(page)
  await session.send('HeapProfiler.enable')
  await session.send('HeapProfiler.collectGarbage')
  const result = await session.send('Performance.getMetrics') as {
    metrics: Array<{ name: string; value: number }>
  }
  await session.detach()
  return result.metrics.find((metric) => metric.name === 'JSHeapUsedSize')?.value ?? 0
}

async function paintedWebglPixels(page: Page): Promise<number> {
  return page.evaluate(() => {
    const canvas = document.querySelector<HTMLCanvasElement & { __gcsTrackDraw?: () => void }>(
      'canvas.gcs-webgl-tracks',
    )
    const gl = canvas?.getContext('webgl2')
    if (!canvas || !gl || canvas.width < 1 || canvas.height < 1) return 0
    const pixels = new Uint8Array(canvas.width * canvas.height * 4)
    canvas.__gcsTrackDraw?.()
    gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels)
    let count = 0
    for (let offset = 3; offset < pixels.length; offset += 4) {
      if (pixels[offset]! > 0) count += 1
    }
    return count
  })
}

async function restoreWebglContext(page: Page): Promise<boolean> {
  return page.evaluate(async () => {
    const canvas = document.querySelector<HTMLCanvasElement>('canvas.gcs-webgl-tracks')
    const gl = canvas?.getContext('webgl2')
    const extension = gl?.getExtension('WEBGL_lose_context')
    if (!canvas || !gl || !extension) return false
    const lost = new Promise<void>((resolve) => canvas.addEventListener(
      'webglcontextlost',
      () => resolve(),
      { once: true },
    ))
    extension.loseContext()
    await lost
    const restored = new Promise<void>((resolve) => canvas.addEventListener(
      'webglcontextrestored',
      () => resolve(),
      { once: true },
    ))
    window.setTimeout(() => extension.restoreContext(), 50)
    const restoredInTime = await Promise.race([
      restored.then(() => true),
      new Promise<false>((resolve) => window.setTimeout(() => resolve(false), 10_000)),
    ])
    if (!restoredInTime) return false
    await new Promise(requestAnimationFrame)
    await new Promise(requestAnimationFrame)
    return !gl.isContextLost()
  })
}

async function processPrivateBytes(ids: number[]): Promise<number[]> {
  if (process.platform !== 'win32' || ids.length === 0) return []
  const idList = ids.join(',')
  const command = `Get-Process -Id ${idList} -ErrorAction SilentlyContinue | ForEach-Object { $_.PrivateMemorySize64 }`
  const { stdout } = await execFileAsync(
    'powershell.exe',
    ['-NoProfile', '-NonInteractive', '-Command', command],
    { windowsHide: true },
  )
  return stdout.split(/\r?\n/).map(Number).filter((value) => Number.isFinite(value) && value > 0)
}

async function backendPrivateBytes(): Promise<number | null> {
  if (process.platform !== 'win32') return null
  const command = [
    "$owner = (Get-NetTCPConnection -State Listen -LocalPort 8766 -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess",
    "if ($owner) { (Get-Process -Id $owner -ErrorAction Stop).PrivateMemorySize64 }",
  ].join('; ')
  const { stdout } = await execFileAsync(
    'powershell.exe',
    ['-NoProfile', '-NonInteractive', '-Command', command],
    { windowsHide: true },
  )
  const value = Number(stdout.trim())
  return Number.isFinite(value) && value > 0 ? value : null
}

test('Chromium WebGL holds 24 x 10000 points with bounded rollover memory', async ({
  browser,
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-1440', 'capacity acceptance uses real Chromium WebGL2')
  test.setTimeout(120_000)
  await installSyntheticSocket(page)
  await page.goto('/?trackDiagnostics=1')
  await expect(page.locator('.status-chip.status-ok').filter({ hasText: 'WS' })).toBeVisible()
  await expect(page.locator('canvas.gcs-webgl-tracks')).toBeVisible()
  await expect(page.locator('.map-error')).toHaveCount(0)

  const fill = await loadTrackRange(page, 1, 10_000)
  expect(Object.values(fill.pointCounts)).toHaveLength(24)
  expect(Object.values(fill.pointCounts).every((count) => count === 10_000)).toBe(true)
  await page.setViewportSize({ width: 1439, height: 900 })
  await page.setViewportSize({ width: 1440, height: 900 })
  await expect.poll(() => paintedWebglPixels(page), { timeout: 15_000 }).toBeGreaterThan(1_000)
  const fullHeap = await jsHeapUsed(page)

  // 3,600 more points per drone equals another 30 minutes at 2 Hz and forces
  // continuous overwrite of every fixed 10,000-point ring.
  const rollover = await loadTrackRange(page, 10_001, 13_600)
  expect(Object.values(rollover.pointCounts)).toHaveLength(24)
  expect(Object.values(rollover.pointCounts).every((count) => count === 10_000)).toBe(true)
  const rolledHeap = await jsHeapUsed(page)
  expect(rolledHeap).toBeLessThan(200 * MIB)
  expect(rolledHeap - fullHeap).toBeLessThan(50 * MIB)
  const browserSession = await browser.newBrowserCDPSession()
  const processResult = await browserSession.send('SystemInfo.getProcessInfo') as {
    processInfo: Array<{ id: number; type: string }>
  }
  await browserSession.detach()
  const rendererIds = processResult.processInfo
    .filter((processInfo) => processInfo.type === 'renderer')
    .map((processInfo) => processInfo.id)
  const rendererPrivate = await processPrivateBytes(rendererIds)
  if (rendererPrivate.length) expect(Math.max(...rendererPrivate)).toBeLessThan(500 * MIB)
  const pythonPrivate = await backendPrivateBytes()
  if (pythonPrivate !== null) expect(pythonPrivate).toBeLessThan(200 * MIB)

  await testInfo.attach('webgl-capacity-metrics.json', {
    body: Buffer.from(JSON.stringify({
      fillDurationMs: fill.durationMs,
      fullHeap,
      pythonPrivate,
      rendererPrivate,
      rolledHeap,
      rolloverDurationMs: rollover.durationMs,
    }, null, 2)),
    contentType: 'application/json',
  })
})

test('Chromium rebuilds the WebGL track layer after context restoration', async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-1440', 'context acceptance uses Chromium WebGL2')
  test.setTimeout(30_000)
  await installSyntheticSocket(page)
  await page.goto('/?trackDiagnostics=1')
  await expect(page.locator('canvas.gcs-webgl-tracks')).toBeVisible()
  await loadTrackRange(page, 1, 20)
  await expect.poll(() => paintedWebglPixels(page)).toBeGreaterThan(50)
  expect(await restoreWebglContext(page)).toBe(true)
  await expect.poll(() => paintedWebglPixels(page), { timeout: 10_000 }).toBeGreaterThan(50)
})

test('four live Chromium tabs keep bounded WebSocket queues without dropped batches', async ({
  context,
  page,
  request,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-1440', 'multi-tab acceptance runs once in Chromium')
  test.setTimeout(60_000)
  await request.delete('/api/tracks')
  const pages = [page]
  for (let index = 1; index < 4; index += 1) pages.push(await context.newPage())
  try {
    await Promise.all(pages.map((item) => item.goto('/?trackDiagnostics=1')))
    await Promise.all(pages.map((item) => expect(
      item.locator('.status-chip.status-ok').filter({ hasText: 'WS' }),
    ).toBeVisible()))
    const baselineResponse = await request.get('/api/health')
    const baseline = await baselineResponse.json() as {
      websocket: { dropped_total: number }
    }
    await expect.poll(async () => {
      const response = await request.get('/api/health')
      const health = await response.json() as { websocket: { clients: number } }
      return health.websocket.clients
    }).toBe(4)

    for (let step = 1; step <= 8; step += 1) {
      await sendFleet(step)
      await page.waitForTimeout(130)
    }
    await Promise.all(pages.map((item) => expect(
      item.locator('.telemetry-table tbody tr'),
    ).toHaveCount(24)))
    await Promise.all(pages.map(async (item) => {
      await expect.poll(() => paintedWebglPixels(item), { timeout: 10_000 }).toBeGreaterThan(100)
    }))

    const response = await request.get('/api/health')
    const health = await response.json() as {
      receive_buffer: { log_dropped_total: number }
      websocket: {
        client_queues: Array<{ depth: number; dropped: number }>
        dropped_total: number
        queue_capacity: number
      }
    }
    expect(health.websocket.queue_capacity).toBe(8)
    expect(health.websocket.dropped_total).toBe(baseline.websocket.dropped_total)
    expect(health.websocket.client_queues).toHaveLength(4)
    expect(health.websocket.client_queues.every((queue) => queue.depth <= 8 && queue.dropped === 0)).toBe(true)
    expect(health.receive_buffer.log_dropped_total).toBe(0)
  } finally {
    await Promise.all(pages.slice(1).map((item) => item.close()))
  }
})
