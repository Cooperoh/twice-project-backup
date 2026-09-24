import { defineConfig, devices } from '@playwright/test'

const pythonCommand = process.platform === 'win32' ? 'python' : 'python3'

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  outputDir: './test-results',
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  webServer: {
    command: `${pythonCommand} ../run.py --config ../tests/config.browser.toml --no-browser`,
    url: 'http://127.0.0.1:8766/api/health',
    reuseExistingServer: false,
    timeout: 30_000,
  },
  use: {
    baseURL: 'http://127.0.0.1:8766',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium-1440',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'firefox-1280',
      use: { ...devices['Desktop Firefox'], viewport: { width: 1280, height: 800 } },
    },
    {
      name: 'webkit-1024',
      use: { ...devices['Desktop Safari'], viewport: { width: 1024, height: 768 } },
    },
    {
      name: 'chromium-720',
      use: { ...devices['Desktop Chrome'], viewport: { width: 720, height: 900 } },
    },
  ],
})
