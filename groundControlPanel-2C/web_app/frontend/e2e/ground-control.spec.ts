import dgram from 'node:dgram'

import { expect, test, type APIRequestContext, type Page } from '@playwright/test'


async function sendTelemetry(id: number, lat = 38.3094, lon = 117.68, heading = 0): Promise<void> {
  await sendUdp({ type: 'telemetry', id, lat, lon, heading, tag: `DRONE${id}` })
}

async function sendUdp(payload: Record<string, unknown>): Promise<void> {
  const socket = dgram.createSocket('udp4')
  const data = Buffer.from(JSON.stringify(payload), 'utf8')
  await new Promise<void>((resolve, reject) => {
    socket.send(data, 56998, '127.0.0.1', (error) => {
      socket.close()
      if (error) reject(error)
      else resolve()
    })
  })
}


async function retainedTrajectoryCount(
  request: APIRequestContext,
  id: number,
): Promise<number> {
  const response = await request.get('/api/bootstrap')
  const snapshot = await response.json() as { trajectories?: Record<string, unknown[]> }
  return snapshot.trajectories?.[String(id)]?.length ?? 0
}


async function webglCanvasStats(page: Page): Promise<{
  checksum: number
  glError: number
  height: number
  paintedPixels: number
  webgl2: boolean
  width: number
}> {
  return page.evaluate(() => {
    const canvas = document.querySelector<HTMLCanvasElement & { __gcsTrackDraw?: () => void }>(
      'canvas.gcs-webgl-tracks',
    )
    if (!canvas) return { checksum: 0, glError: -1, height: 0, paintedPixels: 0, webgl2: false, width: 0 }
    const gl = canvas.getContext('webgl2')
    if (!gl || canvas.width < 1 || canvas.height < 1) {
      return {
        checksum: 0,
        glError: -1,
        height: canvas.height,
        paintedPixels: 0,
        webgl2: false,
        width: canvas.width,
      }
    }
    const pixels = new Uint8Array(canvas.width * canvas.height * 4)
    canvas.__gcsTrackDraw?.()
    gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels)
    let checksum = 0
    let paintedPixels = 0
    for (let offset = 0; offset < pixels.length; offset += 4) {
      if (pixels[offset + 3]! === 0) continue
      paintedPixels += 1
      checksum = (
        checksum * 33
        + pixels[offset]!
        + pixels[offset + 1]! * 3
        + pixels[offset + 2]! * 7
        + offset
      ) >>> 0
    }
    return {
      checksum,
      glError: gl.getError(),
      height: canvas.height,
      paintedPixels,
      webgl2: true,
      width: canvas.width,
    }
  })
}


async function webglContainsApproximateColors(
  page: Page,
  targets: Array<[number, number, number]>,
  tolerance = 12,
): Promise<boolean[]> {
  return page.evaluate(({ targets: expected, tolerance: allowed }) => {
    const found = expected.map(() => false)
    const canvas = document.querySelector<HTMLCanvasElement & { __gcsTrackDraw?: () => void }>(
      'canvas.gcs-webgl-tracks',
    )
    const gl = canvas?.getContext('webgl2')
    if (!canvas || !gl || canvas.width < 1 || canvas.height < 1) return found
    const pixels = new Uint8Array(canvas.width * canvas.height * 4)
    canvas.__gcsTrackDraw?.()
    gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels)
    const limit = allowed * allowed
    for (let offset = 0; offset < pixels.length; offset += 4) {
      if (pixels[offset + 3]! < 80) continue
      expected.forEach(([red, green, blue], index) => {
        if (found[index]) return
        const alphaScale = 255 / pixels[offset + 3]!
        const redDelta = pixels[offset]! * alphaScale - red
        const greenDelta = pixels[offset + 1]! * alphaScale - green
        const blueDelta = pixels[offset + 2]! * alphaScale - blue
        if (redDelta * redDelta + greenDelta * greenDelta + blueDelta * blueDelta <= limit) {
          found[index] = true
        }
      })
    }
    return found
  }, { targets, tolerance })
}


async function overlayCanvasStats(page: Page): Promise<{
  colors: string[]
  dataUrl: string
  paintedPixels: number
}> {
  return page.evaluate(() => {
    const canvases = Array.from(
      document.querySelectorAll<HTMLCanvasElement>('.leaflet-overlay-pane canvas'),
    )
    const counts = new Map<string, number>()
    let paintedPixels = 0
    for (const canvas of canvases) {
      if (canvas.width < 1 || canvas.height < 1) continue
      const context = canvas.getContext('2d')
      if (!context) continue
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data
      for (let index = 0; index < pixels.length; index += 4) {
        if (pixels[index + 3]! < 80) continue
        paintedPixels += 1
        const color = `${pixels[index]},${pixels[index + 1]},${pixels[index + 2]}`
        counts.set(color, (counts.get(color) ?? 0) + 1)
      }
    }
    return {
      colors: [...counts.entries()]
        .filter(([, count]) => count >= 4)
        .map(([color]) => color)
        .sort(),
      dataUrl: canvases.map((canvas) => canvas.toDataURL()).join('|'),
      paintedPixels,
    }
  })
}


async function overlayContainsApproximateColors(
  page: Page,
  targets: Array<[number, number, number]>,
  tolerance = 8,
): Promise<boolean[]> {
  return page.evaluate(({ targets: expected, tolerance: allowed }) => {
    const found = expected.map(() => false)
    const limit = allowed * allowed
    const canvases = document.querySelectorAll<HTMLCanvasElement>('.leaflet-overlay-pane canvas')
    for (const canvas of canvases) {
      if (canvas.width < 1 || canvas.height < 1) continue
      const context = canvas.getContext('2d')
      if (!context) continue
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data
      for (let offset = 0; offset < pixels.length; offset += 4) {
        if (pixels[offset + 3]! < 80) continue
        expected.forEach(([red, green, blue], index) => {
          if (found[index]) return
          const redDelta = pixels[offset]! - red
          const greenDelta = pixels[offset + 1]! - green
          const blueDelta = pixels[offset + 2]! - blue
          if (
            redDelta * redDelta
            + greenDelta * greenDelta
            + blueDelta * blueDelta <= limit
          ) found[index] = true
        })
      }
    }
    return found
  }, { targets, tolerance })
}


async function overlayHasGotoYellow(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const canvases = document.querySelectorAll<HTMLCanvasElement>('.leaflet-overlay-pane canvas')
    for (const canvas of canvases) {
      if (canvas.width < 1 || canvas.height < 1) continue
      const context = canvas.getContext('2d')
      if (!context) continue
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data
      for (let offset = 0; offset < pixels.length; offset += 4) {
        const red = pixels[offset]!
        const green = pixels[offset + 1]!
        const blue = pixels[offset + 2]!
        if (
          pixels[offset + 3]! >= 80
          && red >= 100
          && green >= 70
          && blue <= 25
          && red > green * 1.15
        ) return true
      }
    }
    return false
  })
}


async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
}


async function monitorLayout(page: Page): Promise<{
  controlTop: number
  logHeight: number
  pageHeight: number
}> {
  return page.evaluate(() => {
    const controlPanel = document.querySelector<HTMLElement>('.command-panel')
    const logPanel = document.querySelector<HTMLElement>('.log-panel')
    if (!controlPanel || !logPanel) throw new Error('Monitor panels are missing')
    return {
      controlTop: controlPanel.getBoundingClientRect().top,
      logHeight: logPanel.getBoundingClientRect().height,
      pageHeight: document.documentElement.scrollHeight,
    }
  })
}


test('three pages render without horizontal overflow', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Flight Map' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Flight Control' })).toBeVisible()
  await expectNoHorizontalOverflow(page)

  await page.getByRole('link', { name: '02 Formation' }).click()
  await expect(page.getByRole('heading', { name: '编队成员管理' })).toBeVisible()
  await expectNoHorizontalOverflow(page)

  await page.getByRole('link', { name: '03 Workbench' }).click()
  await expect(page.getByRole('heading', { name: '算法开发与验证' })).toBeVisible()
  await expectNoHorizontalOverflow(page)
})


test('Workbench opens directly, survives reload, and serves fresh HTML with immutable assets', async ({ page, request }) => {
  const index = await request.get('/')
  expect(index.headers()['cache-control']).toBe('no-store, no-cache, must-revalidate')
  const html = await index.text()
  const assetReference = html.match(/(?:src|href)="((?:\.\/|\/)?assets\/[^"?]+-[A-Za-z0-9_-]{8,}\.[^"?]+)"/)?.[1]
  expect(assetReference).toBeTruthy()
  const assetPath = `/${assetReference!.replace(/^\.\//, '')}`
  const asset = await request.get(assetPath)
  expect(asset.ok()).toBe(true)
  expect(asset.headers()['cache-control']).toBe('public, max-age=31536000, immutable')

  await page.goto('/#/workbench')
  await expect(page.getByRole('heading', { name: '算法开发与验证' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: '算法开发与验证' })).toBeVisible()
})


test('actual tracks are WebGL-only session state, extend live, and clear on hard refresh', async ({ page, request }) => {
  await request.delete('/api/tracks')
  await request.delete('/api/goto-targets')
  const routes = [
    {
      id: 1,
      points: [
        [38.3065, 117.6740],
        [38.3075, 117.6760],
        [38.3085, 117.6780],
        [38.3095, 117.6800],
        [38.3105, 117.6820],
        [38.3115, 117.6840],
      ],
    },
    {
      id: 2,
      points: [
        [38.3125, 117.6740],
        [38.3115, 117.6760],
        [38.3105, 117.6780],
        [38.3095, 117.6810],
        [38.3085, 117.6830],
        [38.3075, 117.6850],
      ],
    },
    {
      id: 3,
      points: [
        [38.3055, 117.6840],
        [38.3070, 117.6835],
        [38.3085, 117.6830],
        [38.3100, 117.6825],
        [38.3115, 117.6820],
        [38.3130, 117.6815],
      ],
    },
  ] as const

  await page.goto('/?trackDiagnostics=1')
  const trackToggle = page.getByRole('checkbox', { name: '轨迹' })
  await trackToggle.check()
  const canvas = page.locator('canvas.gcs-webgl-tracks')
  await expect(canvas).toBeVisible()
  await expect.poll(async () => (await webglCanvasStats(page)).webgl2).toBe(true)
  expect((await webglCanvasStats(page)).paintedPixels).toBe(0)

  for (const pointIndex of [0, 1] as const) {
    for (const route of routes) {
      const [lat, lon] = route.points[pointIndex]
      await sendTelemetry(route.id, lat, lon, route.id * 30)
    }
    if (pointIndex === 0) {
      for (const route of routes) {
        await expect(
          page.locator('.drone-marker-shell .drone-label').filter({
            hasText: new RegExp(`^DRONE${route.id}$`),
          }),
        ).toHaveCount(1)
      }
    }
    await page.waitForTimeout(140)
  }

  const diagnostics = await canvas.evaluate((element) => {
    const diagnosticCanvas = element as HTMLCanvasElement & {
      __gcsTrackDiagnostics?: () => unknown
    }
    return diagnosticCanvas.__gcsTrackDiagnostics?.()
  })
  expect(diagnostics).toEqual(expect.objectContaining({
    contextLost: false,
    segmentCounts: { 1: 1, 2: 1, 3: 1 },
    sessionPointCounts: { 1: 2, 2: 2, 3: 2 },
    visible: true,
  }))
  const webglStats = await webglCanvasStats(page)
  expect(webglStats.glError).toBe(0)

  const expectedColors: Array<[number, number, number]> = [
    [230, 25, 75],
    [60, 180, 75],
    [67, 99, 216],
  ]
  await expect.poll(() => webglContainsApproximateColors(page, expectedColors)).toEqual(
    [true, true, true],
  )
  const beforeLiveDelta = (await webglCanvasStats(page)).checksum

  for (const route of routes) {
    const [lat, lon] = route.points[2]
    await sendTelemetry(route.id, lat, lon, route.id * 35)
  }
  await expect.poll(async () => (await webglCanvasStats(page)).checksum).not.toBe(beforeLiveDelta)

  await trackToggle.uncheck()
  await expect(canvas).toBeHidden()
  for (const route of routes) {
    const [lat, lon] = route.points[3]
    await sendTelemetry(route.id, lat, lon, route.id * 40)
  }
  await page.waitForTimeout(140)
  await trackToggle.check()
  await expect(canvas).toBeVisible()
  await expect.poll(() => webglContainsApproximateColors(page, expectedColors)).toEqual(
    [true, true, true],
  )

  await trackToggle.uncheck()
  await page.reload()
  await expect(trackToggle).not.toBeChecked()
  await trackToggle.check()
  await expect(canvas).toBeVisible()
  await expect.poll(async () => (await webglCanvasStats(page)).paintedPixels).toBe(0)

  for (const pointIndex of [4, 5] as const) {
    for (const route of routes) {
      const [lat, lon] = route.points[pointIndex]
      await sendTelemetry(route.id, lat, lon, route.id * 45)
    }
    await page.waitForTimeout(140)
  }
  await expect.poll(() => webglContainsApproximateColors(page, expectedColors)).toEqual(
    [true, true, true],
  )
})


test('partial telemetry heartbeats retain the last speed and heading', async ({ page }) => {
  await page.goto('/')
  await sendUdp({
    type: 'telemetry',
    id: 4,
    tag: 'DRONE4',
    lat: 38.3094,
    lon: 117.68,
    speed: 42.5,
    heading: 137,
    phase: 'cruise',
  })

  const row = page.locator('.telemetry-table tbody tr').filter({
    has: page.locator('.id-cell', { hasText: '#4' }),
  })
  const marker = page.locator('.drone-marker-shell').filter({
    has: page.locator('.drone-label', { hasText: /^DRONE4$/ }),
  })
  await expect(row.locator('td').nth(2)).toHaveText('42.5')
  await expect(row.locator('td').nth(3)).toHaveText('137')
  await expect(marker.locator('.drone-arrow')).toHaveAttribute('style', /rotate\(137deg\)/)

  await sendUdp({ type: 'telemetry', id: 4, tag: 'DRONE4' })
  await page.waitForTimeout(140)
  await expect(row.locator('td').nth(2)).toHaveText('42.5')
  await expect(row.locator('td').nth(3)).toHaveText('137')
  await expect(marker.locator('.drone-arrow')).toHaveAttribute('style', /rotate\(137deg\)/)
})


test('Goto targets render independently and unsupported trajectory packets are ignored', async ({ page, request }) => {
  await request.delete('/api/tracks')
  await request.delete('/api/goto-targets')
  await sendUdp({
    type: 'telemetry',
    id: 21,
    lat: 38.3094,
    lon: 117.6800,
    heading: 20,
    tag: 'DRONE21',
    goto_lat: 38.3120,
    goto_lon: 117.6830,
  })
  await sendUdp({
    type: 'trajectory',
    id: 21,
    points: [
      { lat: 38.3060, lon: 117.6760 },
      { lat: 38.3080, lon: 117.6790 },
      { lat: 38.3100, lon: 117.6820 },
    ],
  })
  await expect.poll(async () => {
    const response = await request.get('/api/bootstrap')
    const bootstrap = await response.json() as { drones?: Record<string, unknown> }
    return Boolean(bootstrap.drones?.['21'])
  }).toBe(true)

  await page.goto('/')
  await expect(page.getByRole('checkbox', { name: '期望点' })).toBeChecked()
  await expect.poll(() => Promise.all([
    overlayHasGotoYellow(page),
    overlayContainsApproximateColors(page, [[23, 104, 229]]),
    overlayContainsApproximateColors(page, [[220, 20, 60]]),
  ])).toEqual([true, [false], [false]])

  const beforeGotoUpdate = (await overlayCanvasStats(page)).dataUrl
  await sendUdp({
    type: 'telemetry',
    id: 21,
    goto_lat: 38.3130,
    goto_lon: 117.6840,
  })
  await expect.poll(async () => (await overlayCanvasStats(page)).dataUrl).not.toBe(beforeGotoUpdate)

  await request.delete('/api/goto-targets')
  await expect.poll(() => Promise.all([
    overlayHasGotoYellow(page),
    overlayContainsApproximateColors(page, [[23, 104, 229]]),
  ])).toEqual([false, [false]])

  await sendUdp({ type: 'trajectory', id: 21, points: [] })
  await expect.poll(() => retainedTrajectoryCount(request, 21)).toBe(0)
})


test('event log scrolls internally without moving flight controls', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Flight Control' })).toBeVisible()

  await page.getByRole('button', { name: '清除', exact: true }).click()
  await expect(page.getByText('事件日志已清除。', { exact: true })).toBeVisible()
  await expect(page.locator('.log-line')).toHaveCount(0)
  const before = await monitorLayout(page)

  for (let index = 0; index < 100; index += 1) {
    await sendUdp({ type: 'log', text: `layout-log-${String(index).padStart(3, '0')}` })
  }
  await expect(page.getByText('layout-log-099', { exact: true })).toBeVisible()

  const longText = `layout-long-${'X'.repeat(320)}`
  await sendUdp({ type: 'log', text: longText })
  const latestLine = page.locator('.log-line').last()
  await expect(latestLine).toContainText('layout-long-')

  const logStream = page.locator('.log-stream')
  const streamSize = await logStream.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }))
  expect(streamSize.scrollHeight).toBeGreaterThan(streamSize.clientHeight)
  await expect.poll(async () => logStream.evaluate((element) => (
    element.scrollHeight - element.scrollTop - element.clientHeight
  ))).toBeLessThanOrEqual(2)

  const longMessage = latestLine.locator('span')
  await expect(longMessage).toHaveAttribute('title', longText)
  await expect(longMessage).toHaveCSS('overflow', 'hidden')
  await expect(longMessage).toHaveCSS('text-overflow', 'ellipsis')
  await expect(longMessage).toHaveCSS('white-space', 'nowrap')

  const after = await monitorLayout(page)
  expect(Math.abs(after.logHeight - before.logHeight)).toBeLessThanOrEqual(2)
  expect(Math.abs(after.controlTop - before.controlTop)).toBeLessThanOrEqual(2)
  expect(Math.abs(after.pageHeight - before.pageHeight)).toBeLessThanOrEqual(2)
})


test('emergency stop locks ordinary controls and resume unlocks them', async ({ page }) => {
  await page.goto('/')
  const abort = page.getByRole('button', { name: '急停' })
  await expect(abort).toBeEnabled()
  await abort.click()

  await expect(page.getByRole('alert')).toContainText('急停状态')
  await expect(page.getByRole('button', { name: '起飞' })).toBeDisabled()

  await page.getByRole('alert').getByRole('button', { name: '恢复发令' }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
})


test('an empty persisted target never selects formation zero', async ({ page }) => {
  await sendTelemetry(24)
  await page.addInitScript(() => localStorage.setItem('gcs.monitor.group', ''))
  await page.goto('/')

  await expect(page.locator('.panel-meta').filter({ hasText: '未选择目标' })).toBeVisible()
  await expect(page.getByRole('button', { name: '起飞' })).toBeDisabled()
})


test('map layers update in place and visible logs download as UTF-8 text', async ({ page }) => {
  await sendTelemetry(20, 38.31, 117.68, 10)
  await page.goto('/')

  const marker = page.locator('.drone-marker-shell').filter({ hasText: 'DRONE20' })
  await expect(marker).toBeVisible()
  await expect(marker).toHaveCSS('width', '44px')
  await expect(marker).toHaveCSS('height', '44px')
  const arrow = marker.locator('.drone-arrow')
  const label = marker.locator('.drone-label')
  await expect(arrow).toHaveCSS('width', '44px')
  await expect(arrow).toHaveCSS('height', '44px')
  await expect(arrow.locator('polygon')).toHaveAttribute('points', '50,4 85,80 50,58 15,80')
  await expect(arrow.locator('polygon')).toHaveAttribute('fill', '#E8232A')
  await expect(arrow.locator('polygon')).toHaveAttribute('stroke', '#8B0000')
  await expect(label).toHaveCSS('font-size', '11px')
  await expect(label).toHaveCSS('font-family', /Tahoma/)
  await expect(label).toHaveCSS('font-weight', '700')
  await expect(label).toHaveCSS('color', 'rgb(101, 42, 34)')
  await expect(label).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
  await expect(label).toHaveCSS('box-shadow', 'none')
  await expect(label).not.toHaveAttribute('style')
  await marker.evaluate((element) => element.setAttribute('data-e2e-marker', 'preserved'))
  await sendTelemetry(20, 38.311, 117.681, 90)
  await expect(arrow).toHaveAttribute('style', /rotate\(90deg\)/)
  await expect(label).not.toHaveAttribute('style')
  await expect(marker).toHaveAttribute('data-e2e-marker', 'preserved')

  await sendUdp({ type: 'log', text: 'e2e-log-下载' })
  await expect(page.getByText('e2e-log-下载').last()).toBeVisible()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出 TXT' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(/^ground-control-.*\.txt$/)
})


test('formation menu moves remain unique and ID-sorted', async ({ page }) => {
  await sendTelemetry(9)
  await sendTelemetry(4)
  await sendTelemetry(7)
  await page.goto('/#/formation')

  for (const id of [9, 4, 7]) {
    const card = page.locator(`.drone-card[data-drone-id="${id}"]`)
    await expect(card).toBeVisible()
    await card.locator('select.move-select').selectOption('1')
  }

  const ids = await page.locator('.drone-zone[data-group="1"] .drone-card').evaluateAll((cards) =>
    cards.map((card) => Number((card as HTMLElement).dataset.droneId)),
  )
  expect(ids.filter((id) => [4, 7, 9].includes(id))).toEqual([4, 7, 9])
  expect(new Set(ids).size).toBe(ids.length)

  const groupOne = page.locator('.drone-zone[data-group="1"]')
  await groupOne.locator('.drone-card[data-drone-id="9"] .drag-handle').dragTo(
    groupOne.locator('.drone-card[data-drone-id="4"] .drag-handle'),
  )
  await expect.poll(async () => groupOne.locator('.drone-card').evaluateAll((cards) =>
    cards
      .map((card) => Number((card as HTMLElement).dataset.droneId))
      .filter((id) => [4, 7, 9].includes(id)),
  )).toEqual([4, 7, 9])
})
